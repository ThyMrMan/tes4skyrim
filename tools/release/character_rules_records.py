"""The records every character rules plugin shares: FormIDs, VMAD, globals,
form lists, the rules quest, Story Manager event quests and nodes, and the
Papyrus compile. The game halves (make_character_rules_esp.py for TES4,
character_rules_falloutnv.py for FO3/FNV) build their tables on these.

See: docs/commentary/character_rules.md#the-rules-plugin
"""
import os
import shutil
import struct
import subprocess

from convert import load_config
from core.subprocess_flags import windows_cmd
from papyrus_compile import find_skse_source_scripts, find_skyrim_source_scripts
from tes5_import.base.conditions import build_ctda
from tes5_import.base.writer import (pack_formid_subrecord, pack_record, pack_string_subrecord,
                                     pack_subrecord, pack_uint32_subrecord)
from tes5_import.pipeline_finalize import write_seq_file

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DIR = os.path.join(ROOT, 'character_rules', 'scripts', 'source')
SELECTOR_SOURCE_DIR = os.path.join(ROOT, 'TESGameSelect', 'scripts', 'source')
#: The scripts every converted game ships, which the rules call into (TES4_Reputation).
STATIC_SOURCE_DIR = os.path.join(ROOT, 'script_convert', 'static_scripts')

#: SMQN DNAM: Shares event, so the vanilla quests on the same event still run.
SHARES_EVENT = 0x00020000

#: QUST DNAM flags: Start Game Enabled and Starts Enabled; the player alias's FNAM.
SGE_FLAGS, PLAYER_ALIAS_FLAGS, PLAYER_REF = 0x0011, 0x00000292, 0x00000014

#: CTDA function 74, GetGlobalValue.
FUNC_GET_GLOBAL_VALUE = 74

#: A rules plugin's own local ids, from here up.
OWN_BASE = 0x800

#: VMAD property type by Python value kind; arrays are the scalar type + 10.
_OBJECT, _STRING, _INT, _FLOAT = 1, 2, 3, 4
_ARRAY = 10


# ---------------------------------------------------------------------------
# FormIDs
# ---------------------------------------------------------------------------

class Forms:
    """Local ids for this plugin's records, and form conversion into its master space."""

    def __init__(self, masters: list):
        """Records numbered from OWN_BASE, in the index after the masters."""
        self.masters = [name.lower() for name in masters]
        self.index = len(masters) << 24
        self.next = OWN_BASE

    def new(self) -> int:
        """The next unused own FormID."""
        fid = self.index | self.next
        self.next += 1
        return fid

    def of(self, form: list) -> int:
        """An `[owning plugin, local id]` form as a FormID in this plugin."""
        return (self.masters.index(form[0].lower()) << 24) | form[1]


# ---------------------------------------------------------------------------
# VMAD
# ---------------------------------------------------------------------------

def _wstring(text: str) -> bytes:
    """A u16-length string, as VMAD stores names and string values."""
    data = text.encode('utf-8')
    return struct.pack('<H', len(data)) + data


def _scalar(kind: int, value) -> bytes:
    """One VMAD value of `kind`: an object is (unused, alias -1, FormID)."""
    if kind == _OBJECT:
        return struct.pack('<HhI', 0, -1, value)
    if kind == _STRING:
        return _wstring(value)
    return struct.pack('<i' if kind == _INT else '<f', value)


def _kind(value) -> int:
    """The VMAD type for a property value: Obj(fid) is an object, a list an array."""
    sample = value[0] if isinstance(value, list) and value else value
    if isinstance(sample, Obj):
        kind = _OBJECT
    elif isinstance(sample, str):
        kind = _STRING
    else:
        kind = _FLOAT if isinstance(sample, float) else _INT
    return kind + _ARRAY if isinstance(value, list) else kind


class Obj(int):
    """A FormID a VMAD property binds as an object."""


def pack_script(name: str, props: dict) -> bytes:
    """One VMAD script entry with typed properties (objects, strings, ints, floats, arrays).

    An empty list is left unset: the game refuses a zero-length array property.
    See: docs/commentary/character_rules.md#the-rules-plugin
    """
    props = {pname: value for pname, value in props.items() if value != []}
    out = _wstring(name) + struct.pack('<BH', 0, len(props))
    for pname, value in props.items():
        kind = _kind(value)
        out += _wstring(pname) + struct.pack('<BB', kind, 1)
        if kind > _ARRAY:
            out += struct.pack('<I', len(value))
            out += b''.join(_scalar(kind - _ARRAY, item) for item in value)
        else:
            out += _scalar(kind, value)
    return out


def pack_quest_vmad(script: bytes, quest_fid: int, alias_scripts: tuple = ()) -> bytes:
    """A QUST VMAD: one script, no fragments, and scripts on alias 0."""
    out = struct.pack('<HHH', 5, 2, 1) + script + struct.pack('<bH', 2, 0) + _wstring('')
    out += struct.pack('<h', 1 if alias_scripts else 0)
    if alias_scripts:
        out += struct.pack('<HhI', 0, 0, quest_fid) + struct.pack('<hhh', 5, 2, len(alias_scripts))
        out += b''.join(alias_scripts)
    return out


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def build_glob(fid: int, edid: str) -> bytes:
    """A short global, 0."""
    subs = pack_string_subrecord('EDID', edid) + pack_subrecord('FNAM', b's')
    return pack_record('GLOB', fid, 0, subs + pack_subrecord('FLTV', struct.pack('<f', 0.0)))


def build_flst(fid: int, edid: str, entries: list) -> bytes:
    """A form list of `entries`."""
    subs = pack_string_subrecord('EDID', edid)
    subs += b''.join(pack_formid_subrecord('LNAM', entry) for entry in entries)
    return pack_record('FLST', fid, 0, subs)


def global_is(glob: int, value: float) -> bytes:
    """A CTDA: GetGlobalValue(glob) == value."""
    return pack_subrecord('CTDA', build_ctda(FUNC_GET_GLOBAL_VALUE, param1=glob,
                                             comp_value=value, operator=0x00))


def build_main_quest(fid: int, edid: str, script: bytes, player_script: str) -> bytes:
    """The rules quest: Start Game Enabled, the rules script, and the player alias with `player_script`."""
    player = pack_script(player_script, {'Rules': Obj(fid)})
    subs = pack_string_subrecord('EDID', edid)
    subs += pack_subrecord('VMAD', pack_quest_vmad(script, fid, (player,)))
    subs += pack_subrecord('DNAM', struct.pack('<HBBII', SGE_FLAGS, 0, 0, 0, 0))
    subs += pack_subrecord('NEXT', b'') + pack_uint32_subrecord('ANAM', 1)
    subs += pack_uint32_subrecord('ALST', 0) + pack_string_subrecord('ALID', 'Player')
    subs += pack_uint32_subrecord('FNAM', PLAYER_ALIAS_FLAGS)
    subs += pack_formid_subrecord('ALFR', PLAYER_REF) + pack_formid_subrecord('VTCK', 0)
    return pack_record('QUST', fid, 0, subs + pack_subrecord('ALED', b''))


def build_event_quest(fid: int, edid: str, event: bytes, script: str, main_fid: int) -> bytes:
    """A quest the Story Manager starts on `event`, whose `script` hands it to the rules quest."""
    subs = pack_string_subrecord('EDID', edid)
    subs += pack_subrecord('VMAD', pack_quest_vmad(pack_script(script, {'Rules': Obj(main_fid)}), fid))
    subs += pack_subrecord('DNAM', struct.pack('<HBBII', 0, 0, 0, 0, 0))
    subs += pack_subrecord('ENAM', event) + pack_subrecord('NEXT', b'')
    return pack_record('QUST', fid, 0, subs + pack_uint32_subrecord('ANAM', 0))


def build_node(fid: int, edid: str, place: tuple, quests: list, active_fid: int) -> bytes:
    """A Story Manager quest node at `place` (parent event node, previous sibling or 0), sharing
    the event and starting the first of `quests` not already running, while the rules are on."""
    subs = pack_string_subrecord('EDID', edid)
    subs += pack_formid_subrecord('PNAM', place[0]) + pack_formid_subrecord('SNAM', place[1])
    subs += pack_uint32_subrecord('CITC', 1) + global_is(active_fid, 1.0)
    subs += pack_uint32_subrecord('DNAM', SHARES_EVENT) + pack_uint32_subrecord('XNAM', 0)
    subs += pack_uint32_subrecord('QNAM', len(quests))
    subs += b''.join(pack_formid_subrecord('NNAM', quest) for quest in quests)
    return pack_record('SMQN', fid, 0, subs)


# ---------------------------------------------------------------------------
# Compile and the Data folder
# ---------------------------------------------------------------------------

def compile_scripts(outdir: str, scripts: tuple) -> bool:
    """Compile `scripts` against Skyrim's, SKSE's, TESGameSelect's and the converted games' headers."""
    try:
        cfg = load_config()
    except (FileNotFoundError, OSError):
        cfg = {}
    headers = [find_skyrim_source_scripts(cfg), find_skse_source_scripts(cfg),
               SELECTOR_SOURCE_DIR, STATIC_SOURCE_DIR, SOURCE_DIR]
    compiler = os.path.join(ROOT, 'external', 'papyrus-compiler', 'papyrus.exe')
    out_dir = os.path.join(outdir, 'scripts')
    ok = True
    for name in scripts:
        cmd = [compiler, 'compile', '-nocache', '-i', os.path.join(SOURCE_DIR, name + '.psc'),
               '-o', out_dir]
        for header in filter(None, headers):
            cmd += ['-h', header]
        run = subprocess.run(windows_cmd(cmd), capture_output=True, text=True, timeout=90, cwd=ROOT)
        built = os.path.isfile(os.path.join(out_dir, name + '.pex'))
        print(f'  {"compiled" if run.returncode == 0 and built else "COMPILE FAILED"} {name}')
        if run.returncode != 0 or not built:
            print('   ', ((run.stdout or '') + (run.stderr or '')).strip().replace('\n', '\n    '))
            ok = False
    return ok


def write_data_folder(outdir: str, esp_name: str, plugin: tuple, scripts: tuple,
                      compile_psc: bool) -> bool:
    """Write `plugin` (bytes, record count, rules quest) as `esp_name`, its .seq and `scripts`' sources,
    compiled unless told not to; True when it is shippable."""
    data, count, main = plugin
    esp = os.path.join(outdir, esp_name)
    os.makedirs(os.path.join(outdir, 'scripts', 'source'), exist_ok=True)
    with open(esp, 'wb') as handle:
        handle.write(data)
    print(f'Wrote {esp} ({len(data)} bytes, {count} records and groups)')
    write_seq_file(esp, {main})
    for name in scripts:
        shutil.copyfile(os.path.join(SOURCE_DIR, name + '.psc'),
                        os.path.join(outdir, 'scripts', 'source', name + '.psc'))
    return compile_scripts(outdir, scripts) if compile_psc else True
