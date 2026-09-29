"""The launcher's install checks: Skyrim version, SKSE, Creation Kit, Address Library."""

import sys
from pathlib import Path

import pytest

from core import setup_check as sc


def _paths(game_dir):
    """Stub find_game_path: Skyrim SE at `game_dir`, VR nowhere."""
    return lambda game, config=None: str(game_dir / "Data") if game == "skyrimse" else ""


def _fake_skyrim(tmp_path, *, ck=True, loader=True, lib="versionlib-1-6-1170-0.bin"):
    """A Skyrim folder holding only the requested pieces; returns (game, data)."""
    game, data = tmp_path, tmp_path / "Data"
    (data / "SKSE" / "Plugins").mkdir(parents=True)
    for name, wanted in (("CreationKit.exe", ck), ("skse64_loader.exe", loader)):
        if wanted:
            (game / name).write_bytes(b"")
    if lib:
        (data / "SKSE" / "Plugins" / lib).write_bytes(b"")
    return game, data


@pytest.mark.parametrize("version, name", [
    ((1, 6, 1170, 0), "versionlib-1-6-1170-0.bin"),
    ((1, 7, 104, 0), "versionlib-1-7-104-0.bin"),
    ((1, 5, 97, 0), "version-1-5-97-0.bin"),
])
def test_address_library_file_follows_the_game_version(version, name):
    """1.6+ loads versionlib-*.bin, 1.5 loads version-*.bin."""
    assert sc.address_library_name(version) == name


@pytest.mark.skipif(sys.platform != "win32", reason="reads a Windows version resource")
def test_exe_version_reads_a_real_exe():
    """python.exe carries a version resource whose major is Python's."""
    assert sc.exe_version(sys.executable)[:1] == (sys.version_info.major,)
    assert sc.exe_version("no such file.exe") == ()


_DEPOT = Path(r"C:\Program Files (x86)\Steam\steamapps\content\app_489830\depot_489833")


@pytest.mark.skipif(not (_DEPOT / "SkyrimSE.1.5.97.unpacked.exe").is_file(),
                    reason="needs the unpacked 1.5.97 exe")
def test_pre_1_6_exe_reports_its_real_version():
    """1.5.97's numeric version field says 1.0.0.0; the string says 1.5.97.0."""
    assert sc.exe_version(_DEPOT / "SkyrimSE.1.5.97.unpacked.exe") == (1, 5, 97, 0)


def test_skyrim_vr_alone_is_refused(monkeypatch):
    """No Skyrim SE but a VR install: say VR is unsupported."""
    monkeypatch.setattr(sc, "find_game_path",
                        lambda game, config=None: "D:/SkyrimVR/Data" if game == "skyrimvr" else "")
    assert "VR is not supported" in sc.version_problem(None, {}, ())[0]


def test_no_skyrim_at_all_is_reported(monkeypatch):
    """Neither SE nor VR: tell the user to install Skyrim SE."""
    monkeypatch.setattr(sc, "find_game_path", lambda game, config=None: "")
    assert "was not found" in sc.version_problem(None, {}, ())[0]


@pytest.mark.parametrize("version, refused", [
    ((1, 5, 97, 0), True), ((1, 6, 1170, 0), False), ((1, 7, 104, 0), False), ((), False),
])
def test_versions_before_1_6_are_refused(tmp_path, version, refused):
    """1.5.x is unsupported; 1.6+ and an unreadable version pass."""
    assert (sc.version_problem(tmp_path, {}, version) is not None) == refused


def test_complete_install_reports_nothing(tmp_path, monkeypatch):
    """Creation Kit, SKSE with its scripts, and the right Address Library: silent."""
    game, data = _fake_skyrim(tmp_path)
    monkeypatch.setattr(sc, "find_skse_source_scripts", lambda config: "x")
    assert sc.missing_installs(game, data, {}, (1, 6, 1170, 0)) == []


def test_each_missing_install_brings_its_download_page(tmp_path, monkeypatch):
    """Nothing installed: three items, each with the page that fixes it."""
    game, data = _fake_skyrim(tmp_path, ck=False, loader=False, lib=None)
    monkeypatch.setattr(sc, "find_skse_source_scripts", lambda config: "")
    urls = [url for _text, url in sc.missing_installs(game, data, {}, (1, 6, 1170, 0))]
    assert urls == [sc.CK_URL, sc.SKSE_URL, sc.ADDRESS_LIBRARY_URL]


def test_address_library_for_another_version_does_not_count(tmp_path, monkeypatch):
    """Only the file for the installed version satisfies the check."""
    game, data = _fake_skyrim(tmp_path, lib="versionlib-1-6-659-0.bin")
    monkeypatch.setattr(sc, "find_skse_source_scripts", lambda config: "x")
    urls = [url for _text, url in sc.missing_installs(game, data, {}, (1, 6, 1170, 0))]
    assert urls == [sc.ADDRESS_LIBRARY_URL]


def test_unsupported_version_is_not_also_sent_for_an_address_library(tmp_path, monkeypatch):
    """On 1.5 the fix is updating Skyrim; a 1.5 Address Library would not help."""
    game, data = _fake_skyrim(tmp_path, lib=None)
    monkeypatch.setattr(sc, "find_skse_source_scripts", lambda config: "x")
    assert sc.missing_installs(game, data, {}, (1, 5, 97, 0)) == []


def test_skse_without_its_script_files_is_reported(tmp_path, monkeypatch):
    """The loader alone is not enough: the converter compiles against SKSE's scripts."""
    game, data = _fake_skyrim(tmp_path)
    monkeypatch.setattr(sc, "find_skse_source_scripts", lambda config: "")
    (item,) = sc.missing_installs(game, data, {}, (1, 6, 1170, 0))
    assert "script files" in item[0][0]


def test_later_runs_are_silent_when_nothing_is_missing(tmp_path, monkeypatch, capsys):
    """No notice and no prompt, so the converter opens straight away."""
    game, _data = _fake_skyrim(tmp_path)
    monkeypatch.setattr(sc, "load_config", dict)
    monkeypatch.setattr(sc, "find_game_path", _paths(game))
    monkeypatch.setattr(sc, "exe_version", lambda path: (1, 6, 1170, 0))
    monkeypatch.setattr(sc, "find_skse_source_scripts", lambda config: "x")
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("prompted"))
    assert sc.main([]) == 0
    assert capsys.readouterr().out == ""
