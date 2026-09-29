"""What `TES Auto-Convert.cmd` checks on every start, in plain words.

Finds Skyrim Special Edition, rejects Skyrim VR and versions before 1.6, and
looks for the Creation Kit, SKSE (loader and script files) and the Address
Library file for the installed game version. Silent when all is in place;
otherwise lists only what is missing, offers to open those download pages, and
waits for Enter. `--first-run` also says setup finished and offers a desktop
shortcut.

Usage: python -m core.setup_check [--first-run]
"""

import argparse
import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

from core.subprocess_flags import POPEN_FLAGS
from papyrus_compile import find_skse_source_scripts
from source_paths import find_game_path, load_config

#: The Skyrim Special Edition Creation Kit's Steam store page, which has an Install button.
CK_URL = "https://store.steampowered.com/app/1946180/"

SKSE_URL = "https://skse.silverlock.org/"

ADDRESS_LIBRARY_URL = "https://www.nexusmods.com/skyrimspecialedition/mods/32444"

#: The oldest Skyrim Special Edition the converter's SKSE plugins support.
MIN_VERSION = (1, 6)

REPO = Path(__file__).resolve().parent.parent

RULE = "=" * 76

#: Console color codes, matching the ones `TES Auto-Convert.cmd` uses.
COLORS = {"red": "\033[91m", "yellow": "\033[93m", "green": "\033[92m",
          "white": "\033[97m", "link": "\033[96m"}


def enable_colors() -> None:
    """Switch on color codes in the classic Windows console."""
    if sys.platform != "win32":
        return
    kernel = ctypes.windll.kernel32
    handle, mode = kernel.GetStdHandle(-11), ctypes.c_uint()
    if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel.SetConsoleMode(handle, mode.value | 0x0004)


def paint(text: str, color: str) -> str:
    """`text` in `color` on a console; plain when output is redirected."""
    return f"{COLORS[color]}{text}\033[0m" if sys.stdout.isatty() else text


def link(url: str) -> str:
    """`url` colored and marked as a clickable link (OSC 8) on a console.

    See: docs/commentary/core_setup_check.md#batch-traps
    """
    if not sys.stdout.isatty():
        return url
    return f"\033]8;;{url}\033\\{paint(url, 'link')}\033]8;;\033\\"


def query_version_block(api, buf, block: str):
    """(pointer, length) of `block` in a loaded version resource, or (None, 0)."""
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    if not api.VerQueryValueW(buf, block, ctypes.byref(ptr), ctypes.byref(length)):
        return None, 0
    return (ptr, length.value) if ptr.value else (None, 0)


def string_file_version(api, buf) -> tuple:
    """The numbers of the FileVersion string, or ()."""
    ptr, length = query_version_block(api, buf, "\\VarFileInfo\\Translation")
    if ptr is None or length < 4:
        return ()
    lang, codepage = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    ptr, _ = query_version_block(
        api, buf, f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileVersion")
    if ptr is None:
        return ()
    return tuple(int(n) for n in re.findall(r"\d+", ctypes.wstring_at(ptr))[:4])


def fixed_file_version(api, buf) -> tuple:
    """The numeric file version from VS_FIXEDFILEINFO, or ()."""
    ptr, _ = query_version_block(api, buf, "\\")
    if ptr is None:
        return ()
    fixed = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
    ms, ls = fixed[2], fixed[3]
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def exe_version(path) -> tuple:
    """`(major, minor, build, sub)` of an exe, or () when unreadable.

    The FileVersion string wins: Skyrim builds before 1.6 (and VR) leave the
    numeric field at 1.0.0.0.
    See: docs/commentary/core_setup_check.md#install-check
    """
    if sys.platform != "win32" or not os.path.isfile(path):
        return ()
    api = ctypes.windll.version
    size = api.GetFileVersionInfoSizeW(str(path), None)
    buf = ctypes.create_string_buffer(size)
    if not size or not api.GetFileVersionInfoW(str(path), 0, size, buf):
        return ()
    return string_file_version(api, buf) or fixed_file_version(api, buf)


def address_library_name(version: tuple) -> str:
    """The Address Library file SKSE plugins load for this game version."""
    prefix = "versionlib-" if version[:2] >= MIN_VERSION else "version-"
    return prefix + "-".join(str(n) for n in version) + ".bin"


def skyrim_folders(config: dict) -> tuple:
    """(game folder, Data folder) of Skyrim Special Edition, or (None, None)."""
    data = find_game_path("skyrimse", config)
    if not data:
        return None, None
    data = Path(data)
    if data.name.lower() != "data":
        return data, data / "Data"
    return data.parent, data


def version_problem(game, config: dict, version: tuple):
    """Why this Skyrim can't be used, or None when it can."""
    if game is None and find_game_path("skyrimvr", config):
        return ("Skyrim VR is not supported. The converter needs Skyrim Special",
                "Edition (or Anniversary Edition) version 1.6 or newer.")
    if game is None:
        return ("Skyrim Special Edition was not found. Install it from Steam",
                "and start it once, then run this again.")
    if version and version[:2] < MIN_VERSION:
        shown = ".".join(str(n) for n in version[:3])
        return (f"Your Skyrim is version {shown}, which is not supported.",
                "Update Skyrim to the latest version through Steam.")
    return None


def missing_installs(game: Path, data: Path, config: dict, version: tuple) -> list:
    """(text lines, download page) for each install this Skyrim lacks."""
    out = []
    if not (game / "CreationKit.exe").is_file():
        out.append((["The Skyrim Special Edition Creation Kit, free on Steam:",
                     link(CK_URL)], CK_URL))
    if not (game / "skse64_loader.exe").is_file():
        out.append(([f"SKSE, from {link(SKSE_URL)}",
                     "Copy its files straight into your Skyrim folder."], SKSE_URL))
    elif not find_skse_source_scripts(config):
        out.append((["SKSE's script files are missing. Copy ALL of SKSE's files,",
                     "the Data folder included, straight into your Skyrim folder."],
                    SKSE_URL))
    supported = version[:2] >= MIN_VERSION
    lib = data / "SKSE" / "Plugins" / address_library_name(version) if supported else None
    if lib is not None and not lib.is_file():
        out.append((["The Address Library for SKSE Plugins, with your mod manager:",
                     link(ADDRESS_LIBRARY_URL)], ADDRESS_LIBRARY_URL))
    return out


def notice_lines(blocker, missing: list) -> list:
    """The boxed notice for an unusable Skyrim and the missing installs."""
    lines = [RULE]
    if blocker:
        lines += [" " + paint(ln, "red") for ln in blocker]
    if blocker and missing:
        lines.append("")
    if missing:
        lines.append(" " + paint("Still to install:", "yellow"))
        lines.append("")
        for n, (text, _url) in enumerate(missing, 1):
            lines.append(f" {n}. {text[0]}")
            lines += ["    " + ln for ln in text[1:]]
        lines += ["", " Start the game through SKSE to play."]
    return lines + [RULE]


def read_line(prompt: str) -> str:
    """One line from the console, lower-cased; '' when input is closed."""
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return ""


def ask(question: str) -> bool:
    """Y/N from the console; only an explicit y/yes counts as yes."""
    return read_line(paint(f"{question} [Y/N]", "white") + " ") in ("y", "yes")


def create_shortcut() -> bool:
    """Put a TES Auto-Convert shortcut on the user's desktop."""
    script = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
              "(Join-Path $d 'TES Auto-Convert.lnk'));"
              "$s.TargetPath=$env:TAC_CMD;$s.WorkingDirectory=$env:TAC_DIR;"
              "$s.IconLocation=$env:TAC_ICON;$s.Save()")
    env = dict(os.environ, TAC_CMD=str(REPO / "TES Auto-Convert.cmd"),
               TAC_DIR=str(REPO), TAC_ICON=str(REPO / "docs" / "assets" / "favicon.ico"))
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          env=env, **POPEN_FLAGS)
    return done.returncode == 0


def main(argv=None) -> int:
    """Print what is missing, offer the pages and the shortcut, wait for Enter."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--first-run", action="store_true")
    first_run = ap.parse_args(argv).first_run
    config = load_config()
    game, data = skyrim_folders(config)
    version = exe_version(game / "SkyrimSE.exe") if game else ()
    blocker = version_problem(game, config, version)
    missing = missing_installs(game, data, config, version) if game else []
    if not (first_run or blocker or missing):
        return 0
    enable_colors()
    print()
    if first_run:
        print(paint("Setup is done.", "green"))
    if blocker or missing:
        print("\n".join(notice_lines(blocker, missing)))
    if missing and ask("Open these download pages now?"):
        for _text, url in missing:
            os.startfile(url)
    if first_run and ask("Put a TES Auto-Convert shortcut on your desktop?"):
        print("Shortcut created." if create_shortcut() else "Could not create the shortcut.")
    read_line(paint("Press Enter to open TES Auto-Convert ...", "white"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
