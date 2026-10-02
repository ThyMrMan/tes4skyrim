"""FO3/FNV PACK: the OnBegin/OnEnd/OnChange scripts and the Dialogue data TES4 lacks.

Each of the three sections is a marker (POBA, POEA, POCA), then an idle
(INAM), an embedded script (SCHR SCDA SCTX, locals, SCRO/SCRV) and a topic
(TNAM), in that order (xEdit wbDefinitionsFNV PACK). They are emitted as
`<Section>.Idle`, `<Section>.Script`, `<Section>.SCRO[i]` and `<Section>.Topic`.

See: docs/commentary/tes4_export_falloutnv.md#package-scripts
"""

import struct

from ..tes4_reader import Record, get_formid_str, get_string, get_subrecord
from .common import escape_value

#: Section marker subrecord -> the key prefix its fields are written under.
PACKAGE_SECTIONS = {'POBA': 'OnBegin', 'POEA': 'OnEnd', 'POCA': 'OnChange'}

#: A patrol point's section marker (XPPA, "Patrol Script Marker") and its key prefix.
_PATROL_SECTION = {'XPPA': 'Patrol'}

#: A section's FormID subrecords -> field name; SCRO is numbered in order instead.
_FORMID_FIELDS = {'INAM': 'Idle', 'TNAM': 'Topic', 'SCRO': ''}

#: Location types whose value is a FormID: near reference, in cell, object ID.
_REFERENCE_LOCATIONS = (0, 1, 4)

#: PKDD Dialogue Type values (Conversation 0, Say To 1).
_DIALOGUE_TYPES = {0: 'Conversation', 1: 'SayTo'}


def _formid(data: bytes) -> str:
    """The FormID in a 4-byte subrecord, as the export writes FormIDs."""
    return get_formid_str(struct.unpack_from('<I', data, 0)[0])


def _section_lines(rec: Record, sections: dict = None) -> list:
    """Each marked section's Idle/Script/SCRO/Topic lines, walked in stream order."""
    sections = sections or PACKAGE_SECTIONS
    lines, prefix, scro = [], None, 0
    for sub in rec.subrecords:
        if sub.type in sections:
            prefix, scro = sections[sub.type], 0
        elif prefix and sub.type == 'SCTX':
            lines.append(f'{prefix}.Script={escape_value(get_string(sub))}')
        elif prefix and sub.type in _FORMID_FIELDS and sub.data[:4].strip(b'\0'):
            name = _FORMID_FIELDS[sub.type] or f'SCRO[{scro}]'
            scro += sub.type == 'SCRO'
            lines.append(f'{prefix}.{name}={_formid(sub.data)}')
    return lines


def _use_weapon_lines(data: bytes) -> list:
    """PKW3, a Use Weapon package's fire settings (xEdit wbDefinitionsFNV PKW3)."""
    flags, rate, count, bursts, shots_min, shots_max = struct.unpack_from('<IBBHHH', data, 0)
    pause_min, pause_max = struct.unpack_from('<ff', data, 12)
    return [f'PKW3.Flags={flags}', f'PKW3.FireRate={rate}', f'PKW3.FireCount={count}',
            f'PKW3.Bursts={bursts}', f'PKW3.ShotsMin={shots_min}', f'PKW3.ShotsMax={shots_max}',
            f'PKW3.PauseMin={pause_min}', f'PKW3.PauseMax={pause_max}']


def _second_target_lines(data: bytes) -> list:
    """PTD2, the second target: what a Use Weapon package shoots at."""
    ttype, target, count = struct.unpack_from('<iIi', data, 0)
    value = get_formid_str(target) if ttype in (0, 1) else str(target)
    return [f'PTD2.Type={ttype}', f'PTD2.Target={value}', f'PTD2.Count={count}']


def _trigger_location_lines(data: bytes) -> list:
    """PLD2, a Dialogue package Trigger Location, laid out as PLDT."""
    ltype, value, radius = struct.unpack_from('<iIi', data, 0)
    shown = get_formid_str(value) if ltype in _REFERENCE_LOCATIONS else str(value)
    return [f'PLD2.Type={ltype}', f'PLD2.Location={shown}', f'PLD2.Radius={radius}']


def emit_patrol_data(lines: list, rec: Record) -> None:
    """A patrol point's idle time, then its idle, embedded script and topic.

    The same shape as a package section, opened by XPPA: `Patrol.IdleTime`,
    `Patrol.Idle`, `Patrol.Script`, `Patrol.SCRO[i]`, `Patrol.Topic`.
    See: docs/commentary/tes4_export_falloutnv.md#patrol-points
    """
    xprd = get_subrecord(rec, 'XPRD')
    if xprd and len(xprd.data) >= 4:
        lines.append(f'Patrol.IdleTime={struct.unpack_from("<f", xprd.data, 0)[0]}')
    lines += _section_lines(rec, _PATROL_SECTION)


def emit_package_deltas(lines: list, rec: Record) -> None:
    """FO3/FNV PACK: the section scripts, the patrol, weapon, trigger-location
    and second-target data, then PKDD's topic and dialogue type."""
    lines += _section_lines(rec)
    pkpt = get_subrecord(rec, 'PKPT')
    if pkpt and pkpt.data:
        lines.append(f'PKPT.Repeatable={pkpt.data[0]}')
    pkw3 = get_subrecord(rec, 'PKW3')
    if pkw3 and len(pkw3.data) >= 20:
        lines += _use_weapon_lines(pkw3.data)
    pld2 = get_subrecord(rec, 'PLD2')
    if pld2 and len(pld2.data) >= 12:
        lines += _trigger_location_lines(pld2.data)
    ptd2 = get_subrecord(rec, 'PTD2')
    if ptd2 and len(ptd2.data) >= 12:
        lines += _second_target_lines(ptd2.data)
    pkdd = get_subrecord(rec, 'PKDD')
    if pkdd and len(pkdd.data) >= 8:
        lines.append(f'PKDD.FOV={struct.unpack_from("<f", pkdd.data, 0)[0]}')
        lines.append(f'PKDD.Topic={_formid(pkdd.data[4:8])}')
    if pkdd and len(pkdd.data) >= 20:
        kind = struct.unpack_from('<I', pkdd.data, 16)[0]
        lines.append(f'PKDD.Type={_DIALOGUE_TYPES.get(kind, kind)}')
