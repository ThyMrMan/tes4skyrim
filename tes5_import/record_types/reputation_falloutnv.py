"""FO3/FNV reputation and karma, kept in globals Skyrim conditions and scripts read.

Each REPU becomes a FormList at its own FormID listing its globals (infamy,
fame, the mixed, good and bad threshold, the maximum), which TES4_Reputation
keeps in step; karma is one global.

See: docs/commentary/tes5_import_character_data.md#fallout-reputation
"""

import struct

from ..base.conditions_falloutnv import ACTOR_VALUE_GLOBALS, REPUTATION_GLOBALS
from ..base.writer import pack_formid_subrecord, pack_record, pack_string_subrecord, pack_subrecord
from .common import get_float, get_formid
from .world_falloutnv import is_fallout_source

#: A reputation's globals in FormList order, with the value each starts at (None: its maximum).
_SLOTS = (('Infamy', 0.0), ('Fame', 0.0), ('Mixed', 1.0), ('Good', 1.0), ('Bad', 1.0), ('Max', None))

#: The karma global, and FO3/FNV's Karma actor value.
KARMA_GLOBAL, KARMA_AV = 'TES4Karma', 23


def _glob(writer, edid: str, value: float) -> int:
    """Write one float GLOB at a derived id; returns its FormID."""
    fid = writer.derive_formid('REPUTATION_GLOB', edid)
    subs = (pack_string_subrecord('EDID', edid) + pack_subrecord('FNAM', b'f')
            + pack_subrecord('FLTV', struct.pack('<f', value)))
    writer.add_record('GLOB', pack_record('GLOB', fid, 0, subs))
    return fid


def _reputation(writer, rec: dict) -> int:
    """Write one REPU's globals and its FormList; returns the list's FormID."""
    edid = rec['EditorID']
    fids = [_glob(writer, f'TES4Rep{slot}_{edid}',
                  get_float(rec, 'DATA.Value') if start is None else start)
            for slot, start in _SLOTS]
    rep = get_formid(rec, 'FormID')
    subs = pack_string_subrecord('EDID', edid) + b''.join(pack_formid_subrecord('LNAM', f) for f in fids)
    writer.add_record('FLST', pack_record('FLST', rep, 0, subs))
    REPUTATION_GLOBALS[int(rec['FormID'], 16) & 0xFFFFFF] = fids
    return rep


def create_reputation_records(by_type: dict, writer) -> dict:
    """Every REPU's FormList and globals, and the karma global; {EditorID: FormID}, {} for other games."""
    REPUTATION_GLOBALS.clear()
    ACTOR_VALUE_GLOBALS.clear()
    if not is_fallout_source():
        return {}
    out = {KARMA_GLOBAL: _glob(writer, KARMA_GLOBAL, 0.0)}
    ACTOR_VALUE_GLOBALS[KARMA_AV] = out[KARMA_GLOBAL]
    for rec in by_type.get('REPU', ()):
        if rec.get('EditorID') and rec.get('FormID'):
            out[rec['EditorID']] = _reputation(writer, rec)
    print(f"  Reputations: {len(REPUTATION_GLOBALS)} REPU lists, karma global")
    return out
