"""Which creatures the player can talk to: the authored dialogue that names them.

A generated creature race carries RACE DATA 'Allow PC Dialogue' only when a
creature sharing it is named as the speaker of a line the player can reach.
See: docs/commentary/tes5_import_actors.md#creature-talk-prompt
"""

import os

from ..base.conditions import read_getisid_fids
from ..base.text_reader import get_formid, get_int, get_str
from ..dialogue.converter import DIAL_TYPE_CONVERSATION, classify_topic
from ..dialogue.morrowind_sidecar import export_records

#: TES3 MWIN line kinds said to the player in the dialogue menu.
_MWIN_TALK_TYPES = frozenset({'Topic', 'Greeting', 'Persuasion'})


def _is_talk_topic(dial: dict) -> bool:
    """True for a topic the player hears in the dialogue menu: GREETING or a non-bark topic."""
    edid = get_str(dial, 'EditorID', '')
    dtype = get_int(dial, 'DATA.Type')
    return edid == 'GREETING' or (dtype != DIAL_TYPE_CONVERSATION
                                  and not classify_topic(edid, dtype)[3])


def _info_speakers(records: list) -> set:
    """FormIDs a GetIsID names on INFOs under talk topics, among `records`."""
    talk = {get_formid(d, 'FormID') for d in records
            if d.get('Signature') == 'DIAL' and _is_talk_topic(d)}
    out = set()
    for rec in records:
        if rec.get('Signature') == 'INFO' and get_formid(rec, 'ParentDIAL') in talk:
            out |= read_getisid_fids(rec)
    return out


def _mwin_speakers(export_dir: str) -> set:
    """Lower-cased TES3 actor ids a TES3 export's talk lines are filtered to."""
    path = os.path.join(export_dir, 'MWIN.txt')
    return {rec['Actor'].lower() for rec in export_records(path, ('Actor', 'InfoType'))
            if rec.get('Actor') and rec.get('InfoType') in _MWIN_TALK_TYPES}


def talking_creatures(creatures: list, by_type: dict, master_export: dict,
                      export_dir: str) -> set:
    """FormIDs of the CREA records in `creatures` that are named as a talk-line speaker.

    Reads this plugin's and its masters' INFO GetIsID conditions and this
    plugin's TES3 MWIN `Actor` ids.
    """
    records = list((master_export or {}).values())
    records += by_type.get('DIAL', []) + by_type.get('INFO', [])
    fids = _info_speakers(records)
    ids = _mwin_speakers(export_dir)
    return {get_formid(rec, 'FormID') for rec in creatures
            if get_formid(rec, 'FormID') in fids
            or get_str(rec, 'EditorID', '').lower() in ids}
