# The launcher: TES Auto-Convert.cmd and core/setup_check.py

**Code:** `TES Auto-Convert.cmd`, `core/setup_check.py`, `preflight.py` (`_skse_headers`)

## Contents

- [What each start does](#each-start)
- [Why a .venv that reuses the user's packages](#system-site-packages)
- [Package versions do not change the navmesh](#versions-and-navmesh)
- [What the install check looks for](#install-check)
- [Batch-file traps](#batch-traps)

## <a id="each-start"></a>What each start does

1. `cd` to the launcher's own folder, and stop with "move this folder" if that
   fails or the folder can't be written to.
2. Rebuild `.venv` if its `python.exe` no longer starts (its base Python was
   uninstalled or moved).
3. First run only: find Python 3.14 (`py -3.14`, then the usual install
   folders), install it with `winget --scope user` if missing, and create
   `.venv`.
4. `pip install -r requirements.txt` into `.venv`, output to
   `logs\launcher.log`. On failure the last 15 log lines are shown.
5. While `external\xwmaencode\xWMAEncode.exe` is missing, offer to download
   `DXSDK_Jun10.exe` (599,455,936 bytes) from Microsoft and extract only
   `DXSDK\Utilities\bin\x86\xWMAEncode.exe` with the bundled 7-Zip (about 2 s).
6. `python -m core.setup_check` (see [below](#install-check)), then start
   `gui.py` under `.venv\Scripts\pythonw.exe`.

A later run with nothing missing takes about 1 s before the GUI opens.

## <a id="system-site-packages"></a>Why a .venv that reuses the user's packages

`.venv` is created with `--system-site-packages`: a package already installed
in the user's Python at the pinned version is reused, and anything missing or
at another version goes into `.venv` only. The user's own Python is never
changed. Measured on the development machine: 4 of 10 packages were reused and
6 (numpy 2.3.5 → 2.5.3, scipy 1.17.1 → 1.18.1, Pillow, mapbox_earcut,
setuptools, tkinterdnd2) went into `.venv`; the global `pip freeze` was
identical before and after.

Side effect: pip may log a conflict for a global package that pins an older
dependency (seen: `numba 0.66.0 requires numpy<2.5`). The converter never
imports such packages, so it is harmless; pip still exits 0.

## <a id="versions-and-navmesh"></a>Package versions do not change the navmesh

The navmesh cache tag hashes the navmesh sources and the native module, not the
numpy/scipy versions. Measured: 20 evenly spaced Oblivion.esm cells generated
with the cache off were byte-identical under numpy 2.3.5 / scipy 1.17.1 and
numpy 2.5.3 / scipy 1.18.1. A future version that changes results would not be
caught by the tag.

## <a id="install-check"></a>What the install check looks for

`core/setup_check.py` is silent when everything is in place; otherwise it lists
only what is missing, offers to open those pages, and waits for Enter.

- **Skyrim:** the Skyrim Special Edition registry key. With only the `Skyrim VR`
  key, it says VR is unsupported. `SkyrimSE.exe`'s file version below 1.6 is
  refused (the exe's version resource is readable despite the Steam DRM).
  The version comes from the `FileVersion` string: in 1.5.97 and VR 1.4.15 the
  numeric `VS_FIXEDFILEINFO` field is 1.0.0.0 while the string says 1.5.97.0 /
  1.4.15.0; from 1.6 both agree (checked on 1.6.659, 1.6.1170, 1.7.104).
- **Creation Kit:** `CreationKit.exe` in the game folder. Its page is the Steam
  store page for app 1946180 ("Skyrim Special Edition: Creation Kit"), which has
  an Install button. `steam://install/1946180` was tried first and opened
  nothing in testing, so a plain web page is used.
- **SKSE:** `skse64_loader.exe`, and its script files through
  `papyrus_compile.find_skse_source_scripts`, the compiler's own lookup.
  `preflight.py` checks the same files for the Scripts step.
- **Address Library:** `Data\SKSE\Plugins\versionlib-<a>-<b>-<c>-<d>.bin` for
  the installed version (`version-*.bin` before 1.6). Not checked on an
  unsupported version, where updating Skyrim is the fix. A copy installed only
  inside Mod Organizer 2's virtual folder is not visible here.

The first run also offers a desktop shortcut, made through PowerShell's
`WScript.Shell` with paths passed in environment variables so an apostrophe in
a folder name can't break the command.

## <a id="batch-traps"></a>Batch-file traps

- **A failed `cd` must stop the script.** With `cd /d "%~dp0"` failing, the
  script ran on in the caller's folder; in testing that was the repo root, where
  it used the developer's `.venv` and opened the GUI.
- **`type nul > file || ...` does not catch a denied write.** The check writes a
  file and tests `if exist`.
- **Links are marked explicitly.** Windows Terminal auto-detects plain URLs,
  but a URL wrapped in color codes stopped being clickable, so each link is
  also an OSC 8 hyperlink (`ESC ]8;;<url> ESC \` … `ESC ]8;; ESC \`).
- **The file must be CRLF.** cmd.exe misreads labels in LF-only batch files, and
  GitHub's source zip keeps stored line endings, so `.gitattributes` has
  `*.cmd text eol=crlf`.
