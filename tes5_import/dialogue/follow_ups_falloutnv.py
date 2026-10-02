"""FO3/FNV Follow Up links: the speaker goes on to the next line unasked.

A FO3/FNV INFO's Follow Up list (TCFU) names the INFOs its speaker continues
with, the first whose conditions pass. Skyrim links topics, not INFOs, so each
such INFO gets a hidden topic holding shared copies of exactly its follow-ups,
and continues into it with Invisible Continue and one TCLT, as vanilla does.

See: docs/commentary/tes5_import_dialogue.md#fallout-follow-ups
"""

import struct

from ..base.conditions import FUNC_GET_GLOBAL_VALUE, build_ctda
from ..base.writer import (pack_group, pack_record, pack_string_subrecord, pack_subrecord,
                           pack_uint32_subrecord)
from ..record_types.common import get_formid, get_int
from .arrest import info_records, shared_copy
from .converter import convert_DIAL, make_dlbr
from .follow_up_marks_falloutnv import FROM_GLOBAL, SAID_GLOBAL
from .quest import QUEST_PRIORITY_MAX

#: Skyrim ENAM Say Once; a copy drops it, the chain's marks say when it has run.
_SAY_ONCE = 0x04

#: EditorID of the quest owning the resume topics, so they outrank the speaker's own greetings.
RESUME_QUEST = 'TES4FollowUpResume'

#: Converted INFO FormID -> the FormID of its follow-up topic.
FOLLOW_UP_TOPICS: dict = {}

#: Follow-up topic FormID -> (source INFO FormID, [(source, converted) follow-up INFO FormIDs]).
_PLAN: dict = {}

#: Follow-up INFO FormID -> (owning quest FormID, packed converted INFO), captured as topics convert.
_CAPTURED: dict = {}

#: Converted FormIDs of every INFO some line follows up with.
_TARGETS: set = set()


def plan_follow_ups(infos: list, writer, skipped_topics: set) -> int:
    """Give every INFO with a follow-up in a kept topic its topic id; returns how many."""
    FOLLOW_UP_TOPICS.clear()
    _PLAN.clear()
    _CAPTURED.clear()
    _TARGETS.clear()
    parent = {get_formid(r, 'FormID'): get_formid(r, 'ParentDIAL') for r in infos}
    for rec in infos:
        targets = [(rec[f'FollowUp[{i}]'], get_formid(rec, f'FollowUp[{i}]'))
                   for i in range(get_int(rec, 'FollowUpCount'))]
        targets = [t for t in targets if t[1] in parent and parent[t[1]] not in skipped_topics]
        if targets:
            topic = writer.derive_formid('FOLLOWUP_DIAL', rec['FormID'])
            FOLLOW_UP_TOPICS[get_formid(rec, 'FormID')] = topic
            _PLAN[topic] = (rec['FormID'], targets)
            _TARGETS.update(fid for _src, fid in targets)
    return len(_PLAN)


def blocking_branch(writer, key, edid: str, quest: int, topic: int) -> tuple:
    """(DLBR FormID, DLBR bytes) of a Blocking branch starting at `topic`."""
    branch = writer.derive_formid('BLOCKING_DLBR', key)
    return branch, make_dlbr(branch, f'{edid}_Branch', quest, topic, top_level=False, blocking=True)


def capture_follow_up(info_fid: int, owner_qfid: int, packed: bytes) -> None:
    """Keep a converted INFO that some line follows up with."""
    if info_fid in _TARGETS:
        _CAPTURED[info_fid] = (owner_qfid, packed)


def _copies(writer, site: str, source: str, found: list, gate: bytes = b'') -> bytes:
    """A source's follow-ups as shared copies without Say Once, led by `gate`.

    See: docs/commentary/tes5_import_dialogue.md#fallout-follow-ups-resume
    """
    return b''.join(
        shared_copy(body, fid, writer.derive_formid(site, (source, src)), flags, gate, _SAY_ONCE)
        for src, (_quest, packed) in found for fid, flags, body in info_records(packed))


def _resume_quest(writer) -> int:
    """The start-enabled quest owning every resume topic, at the top dialogue priority; its FormID."""
    fid = writer.derive_formid('SYNTH_QUST', RESUME_QUEST)
    subs = (pack_string_subrecord('EDID', RESUME_QUEST)
            + pack_subrecord('DNAM', struct.pack('<HBBII', 0x0011, QUEST_PRIORITY_MAX, 0, 0, 0))
            + pack_subrecord('NEXT', b'') + pack_uint32_subrecord('ANAM', 0))
    writer.add_record('QUST', pack_record('QUST', fid, 0, subs))
    return fid


def _global_is(fid: int, value: float) -> bytes:
    """One packed `GetGlobalValue(fid) == value` CTDA."""
    return pack_subrecord('CTDA', build_ctda(FUNC_GET_GLOBAL_VALUE, param1=fid, comp_value=value))


def _resume_gate(source: str, targets: list, unlock_globals: dict) -> bytes:
    """From == 1 and every follow-up's Said == 0; b'' when the chain carries no marks.

    See: docs/commentary/tes5_import_dialogue.md#fallout-follow-ups-resume
    """
    from_fid = unlock_globals.get(FROM_GLOBAL.format(int(source, 16) & 0xFFFFFF))
    if not from_fid:
        return b''
    said = [unlock_globals.get(SAID_GLOBAL.format(int(src, 16) & 0xFFFFFF)) for src, _fid in targets]
    return _global_is(from_fid, 1.0) + b''.join(_global_is(fid, 0.0) for fid in said if fid)


def _topic(writer, topic: int, edid: str, quest: int, copies: bytes, count: int, blocking: bool) -> tuple:
    """(DIAL bytes, DLBR bytes) of one hidden CUST topic holding `copies`."""
    site, key = ('FOLLOWUP_RESUME_DLBR', edid) if blocking else ('FOLLOWUP_DLBR', edid[len('TES4FollowUp_'):])
    branch = writer.derive_formid(site, key)
    dlbr = make_dlbr(branch, f'{edid}_Branch', quest, topic, top_level=False, blocking=blocking)
    content = convert_DIAL({'EditorID': edid}, info_count=count, dlbr_fid=branch,
                           quest_fid=quest, category=0, subtype=0, snam=b'CUST',
                           formid_override=topic)
    return content + pack_group(7, struct.pack('<I', topic), copies), dlbr


def build_follow_up_topics(writer, unlock_globals: dict = None) -> tuple:
    """(DIAL bytes, DLBR bytes) of every follow-up topic, and each marked chain's resume topic."""
    content, branches, resume = b'', b'', 0
    for topic, (source, targets) in _PLAN.items():
        found = [(src, _CAPTURED[fid]) for src, fid in targets if fid in _CAPTURED]
        if not found:
            continue
        quest = found[0][1][0]
        parts = [_topic(writer, topic, f'TES4FollowUp_{source}', quest,
                        _copies(writer, 'FOLLOWUP_INFO', source, found), len(found), False)]
        gate = _resume_gate(source, targets, unlock_globals or {})
        if gate:
            resume = resume or _resume_quest(writer)
            parts.append(_topic(writer, writer.derive_formid('FOLLOWUP_RESUME_DIAL', source),
                                f'TES4FollowUpResume_{source}', resume,
                                _copies(writer, 'FOLLOWUP_RESUME_INFO', source, found, gate),
                                len(found), True))
        content += b''.join(c for c, _d in parts)
        branches += b''.join(d for _c, d in parts)
    _CAPTURED.clear()
    return content, branches
