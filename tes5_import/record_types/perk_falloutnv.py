"""FO3/FNV PERK: the same record in Skyrim, with Fallout's entry points
renumbered to Skyrim's where Skyrim has the same one.

Quest-stage and ability effects carry over. An entry point converts only when
Skyrim has it by name and every condition on it converts, since a dropped
condition would widen the effect to every weapon or target.

See: docs/commentary/tes5_import_character_data.md#fallout-perks
"""

import struct

from ..base.conditions import convert_ctda, convert_ctda_list
from ..base.text_reader import get_formid_index_offset
from .common import (get_formid, get_int, get_str, pack_record,
                     pack_string_subrecord, pack_subrecord)

#: FO3/FNV entry point -> Skyrim's of the same name (xEdit's lists; Fallout 3's is New Vegas's first 37).
SKYRIM_ENTRY_POINTS = {0: 0, 1: 1, 2: 2, 4: 3, 6: 4, 11: 5, 12: 6, 15: 7, 17: 8, 21: 9, 22: 10,
                       23: 11, 24: 12, 25: 13, 31: 15, 32: 16, 36: 17}

#: Entry point functions that change a number (Set Value to Negative Absolute Value), then Add Leveled List.
_VALUE_FUNCTIONS, _ADD_LEVELED_LIST = range(1, 8), 8

#: PRKE's effect kinds, as the export names them.
_KINDS = {'QuestStage': 0, 'Ability': 1, 'EntryPoint': 2}

#: EPFT: the entry point value is a leveled list's FormID.
_LEVELED_LIST_VALUE = 3


def _tabs(rec: dict, pfx: str) -> 'bytes | None':
    """Each condition tab as PRKC and its CTDAs, or None when any condition has no Skyrim form."""
    out, tab = b'', 0
    offset = get_formid_index_offset()
    while f'{pfx}.Tab[{tab}].RunOn' in rec:
        out += pack_subrecord('PRKC', struct.pack('<b', get_int(rec, f'{pfx}.Tab[{tab}].RunOn')))
        k = 0
        while f'{pfx}.Tab[{tab}].Condition[{k}].Raw' in rec:
            ctda = convert_ctda(bytes.fromhex(rec[f'{pfx}.Tab[{tab}].Condition[{k}].Raw']), offset)
            if ctda is None:
                return None
            out += pack_subrecord('CTDA', ctda)
            k += 1
        tab += 1
    return out


def _entry_point_value(rec: dict, pfx: str, function: int) -> 'bytes | None':
    """EPFT and EPFD for a value or leveled-list function, else None."""
    value_type = get_int(rec, f'{pfx}.ValueType')
    value = bytes.fromhex(get_str(rec, f'{pfx}.Value'))
    if function == _ADD_LEVELED_LIST and value_type == _LEVELED_LIST_VALUE and len(value) == 4:
        value = struct.pack('<I', get_formid({'Value': f'{struct.unpack("<I", value)[0]:08X}'}, 'Value'))
    elif function not in _VALUE_FUNCTIONS:
        return None
    return pack_subrecord('EPFT', bytes([value_type])) + (pack_subrecord('EPFD', value) if value else b'')


def _entry_point(rec: dict, pfx: str) -> 'bytes | None':
    """An entry point's DATA, tabs and value in Skyrim's numbering, or None when it does not convert."""
    skyrim = SKYRIM_ENTRY_POINTS.get(get_int(rec, f'{pfx}.EntryPoint'))
    function = get_int(rec, f'{pfx}.Function')
    tabs = _tabs(rec, pfx)
    value = _entry_point_value(rec, pfx, function)
    if skyrim is None or tabs is None or value is None:
        return None
    data = bytes([skyrim, function, get_int(rec, f'{pfx}.ConditionTabs')])
    return pack_subrecord('DATA', data) + tabs + value


def _effect(rec: dict, i: int) -> 'bytes | None':
    """One effect as PRKE, its DATA and parameters, then PRKF; None when it does not convert."""
    pfx = f'Effect[{i}]'
    kind = _KINDS.get(get_str(rec, f'{pfx}.Type'))
    if kind == 0:
        body = pack_subrecord('DATA', struct.pack('<IHH', get_formid(rec, f'{pfx}.Quest'),
                                                  get_int(rec, f'{pfx}.Stage'), 0))
    elif kind == 1:
        body = pack_subrecord('DATA', struct.pack('<I', get_formid(rec, f'{pfx}.Ability')))
    elif kind == 2:
        body = _entry_point(rec, pfx)
    else:
        body = None
    if body is None:
        return None
    head = bytes([kind, get_int(rec, f'{pfx}.Rank'), get_int(rec, f'{pfx}.Priority')])
    return pack_subrecord('PRKE', head) + body + pack_subrecord('PRKF', b'')


def perk_effects(rec: dict) -> tuple:
    """(the converted effects' bytes, how many effects did not convert)."""
    count = get_int(rec, 'EffectCount')
    effects = [_effect(rec, i) for i in range(count)]
    return b''.join(e for e in effects if e), sum(e is None for e in effects)


def convert_PERK(rec: dict) -> bytes:
    """PERK: EDID, FULL, DESC, requirements, DATA, then every effect that converts."""
    subs = pack_string_subrecord('EDID', get_str(rec, 'EditorID'))
    if get_str(rec, 'FULL'):
        subs += pack_string_subrecord('FULL', get_str(rec, 'FULL'))
    subs += pack_string_subrecord('DESC', get_str(rec, 'DESC'))
    subs += b''.join(pack_subrecord('CTDA', ctda) for ctda in convert_ctda_list(rec))
    data = [get_int(rec, f'DATA.{name}', default)
            for name, default in (('Trait', 0), ('MinLevel', 0), ('Ranks', 1), ('Playable', 0), ('Hidden', 0))]
    subs += pack_subrecord('DATA', bytes(data))
    subs += perk_effects(rec)[0]
    return pack_record('PERK', get_formid(rec, 'FormID'), 0, subs)
