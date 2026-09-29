"""FO3/FNV speech challenges: a line rolls the player's Speech and can fail.

A challenge line (INFO flag 0x80) succeeds when a roll beats the chance
`Fallout3.exe` computes from Speech and the line's difficulty (DNAM). On a
failure the engine says the first passing line of its SpeechChallengeFailure
topic whose Link From is empty or names the challenged topic or ANY. Skyrim
says a topic's first passing INFO, so the challenge line requires Speech to
reach a rolled threshold global and shared copies of its failure lines follow
it; every challenge and failure line's End fragment rolls again.

See: docs/commentary/tes5_import_dialogue.md#fallout-speech-challenges
"""

import struct

from ..base.conditions import CTDA_OR, CTDA_USE_GLOBAL, required_speaker_ids
from ..base.conditions_falloutnv import fallout_actor_value
from ..base.tes5_reader import subrecords
from ..base.writer import pack_record, pack_string_subrecord, pack_subrecord
from ..record_types.common import get_formid, get_int, get_str
from ..record_types.world_falloutnv import is_fallout_source
from .arrest import info_records, shared_copy
from .speech_chance_falloutnv import (ANY_TOPIC, NEED_GLOBALS, chance_settings, difficulties, is_challenge,
                                      is_failure, raw_formid, rerolls, roll_point, speech_needed)

#: The roll a new game's thresholds start from, the middle of 0 to 99.
_FIRST_ROLL = 49

#: Fallout's Speech actor value, and the label its challenge prompts carry.
_SPEECH, _LABEL = 43, 'Speech'

#: Skyrim GetActorValue, the >= and < operators, and Run On Target (the player), as vanilla's persuades.
_GET_ACTOR_VALUE, _AT_LEAST, _BELOW, _RUN_ON_TARGET = 14, 0x60, 0x80, 1

#: 'needs': {global name: FormID}; 'failures': {challenge FormID: [(failure record, copy FormID)]}.
_PLAN: dict = {}


def _qualifies(failure: dict, topic: int, speakers) -> bool:
    """Whether a failure line answers a challenge in `topic` said by `speakers` (None: anyone)."""
    links = [raw_formid(failure, k) for k in failure if k.startswith('LinkFrom[')]
    if links and topic not in links and ANY_TOPIC not in links:
        return False
    theirs = required_speaker_ids(failure)
    return speakers is None or theirs is None or bool(speakers & theirs)


def _emit_need(writer, name: str, value: float) -> int:
    """Write one threshold global; its FormID."""
    fid = writer.derive_formid('GLOB', name)
    subs = (pack_string_subrecord('EDID', name) + pack_subrecord('FNAM', b'f')
            + pack_subrecord('FLTV', struct.pack('<f', value)))
    writer.add_record('GLOB', pack_record('GLOB', fid, 0, subs))
    return fid


def plan_speech_challenges(infos: list, gmsts: list, writer) -> int:
    """Write the threshold globals and pair each challenge with its failure copies; how many challenges fail.

    See: docs/commentary/tes5_import_dialogue.md#fallout-speech-challenges
    """
    _PLAN.clear()
    if not any(rerolls(r, is_fallout_source()) for r in infos):
        return 0
    settings = chance_settings(gmsts)
    point = roll_point(_FIRST_ROLL, settings)
    _PLAN['needs'] = {name: _emit_need(writer, name, speech_needed(point, d, settings))
                      for name, d in zip(NEED_GLOBALS, difficulties(settings))}
    failures = [r for r in infos if is_failure(r)]
    _PLAN['failures'] = {}
    for rec in filter(is_challenge, infos):
        topic, speakers = raw_formid(rec, 'ParentDIAL'), required_speaker_ids(rec)
        found = [f for f in failures if _qualifies(f, topic, speakers)]
        if found:
            _PLAN['failures'][get_formid(rec, 'FormID')] = [
                (f, writer.derive_formid('SPEECH_FAIL_INFO', (rec['FormID'], f['FormID']))) for f in found]
    return len(_PLAN['failures'])


def speech_props(rec: dict) -> dict:
    """The threshold globals a rolling line's fragment binds, by property name."""
    return dict(_PLAN['needs']) if _PLAN.get('needs') and (is_challenge(rec) or is_failure(rec)) else {}


def _speech_ctda(rec: dict, operator: int) -> bytes:
    """`GetActorValue Speech <operator> TES4SpeechNeed<level>` on the player, packed."""
    level = min(max(get_int(rec, 'DNAM.SpeechChallenge'), 0), len(NEED_GLOBALS) - 1)
    data = struct.pack('<B3xIHHIIIII', operator | CTDA_USE_GLOBAL, _PLAN['needs'][NEED_GLOBALS[level]],
                       _GET_ACTOR_VALUE, 0, fallout_actor_value(_SPEECH), 0, _RUN_ON_TARGET, 0, 0xFFFFFFFF)
    return pack_subrecord('CTDA', data)


def planned_failures(rec: dict) -> list:
    """A challenge line's [(failure record, copy FormID)], or [] when it cannot fail."""
    return _PLAN.get('failures', {}).get(get_formid(rec, 'FormID'), [])


def success_gate(rec: dict) -> bytes:
    """A failable challenge's Speech condition, passed on a won roll; else b''."""
    return _speech_ctda(rec, _AT_LEAST) if planned_failures(rec) else b''


def labelled(rec: dict, topic_text: str) -> dict:
    """A challenge line that can fail, its prompt led by the skill as Fallout shows it."""
    if not planned_failures(rec):
        return rec
    return {**rec, 'Prompt': f"[{_LABEL}] {get_str(rec, 'Prompt') or topic_text}"}


def _condition_block(body: bytes, exclude: bytes) -> bytes:
    """A converted INFO's conditions without `exclude`, its last OR flag cleared so more can follow."""
    pairs = []
    for tag, data in subrecords(body):
        if tag == b'CTDA':
            pairs.append([data, b''])
        elif tag in (b'CIS1', b'CIS2') and pairs:
            pairs[-1][1] += pack_subrecord(tag.decode('ascii'), data)
    pairs = [p for p in pairs if pack_subrecord('CTDA', p[0]) != exclude]
    if pairs:
        pairs[-1][0] = bytes([pairs[-1][0][0] & ~CTDA_OR]) + pairs[-1][0][1:]
    return b''.join(pack_subrecord('CTDA', ctda) + extra for ctda, extra in pairs)


def failure_copies(rec: dict, packed: bytes, convert) -> tuple:
    """(shared copies of a challenge line's failure lines, how many) to follow it; `convert` packs an INFO.

    Each copy passes only when the challenge line's own conditions pass and
    its roll lost, then on the failure line's conditions as this topic sees them.
    See: docs/commentary/tes5_import_dialogue.md#fallout-speech-challenges
    """
    plan = planned_failures(rec)
    if not plan:
        return b'', 0
    body = next(info_records(packed))[2]
    gate = _speech_ctda(rec, _BELOW) + _condition_block(body, success_gate(rec))
    out, count = b'', 0
    for failure, fid in plan:
        for _fid, flags, fbody in info_records(convert(failure)):
            out += shared_copy(fbody, get_formid(failure, 'FormID'), fid, flags, gate)
            count += 1
    return out, count
