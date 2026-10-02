"""Say Once lines that open a stage-setting reply tree stay until that stage is set.

A Say Once line is spent as soon as it plays, so a player who leaves the talk
during its replies meets the speaker's next greeting on return, and the stage
the replies set is lost (FO3 Stanley's Pip-Boy greeting: stage 23 sits two
choices deep). Such a line instead drops Say Once and asks `GetStageDone ==
0` for every stage its reply tree sets. Its own result script is not counted:
a line that sets its stage as it ends must outlive its own fragment. Only a
player dialogue topic's line qualifies, and only one whose own script is safe
to run again (variables, stages, objectives): a line paying caps, XP or items
stays Say Once.

See: docs/commentary/tes5_import_dialogue.md#say-once-reply-trees
"""

import re
import struct
from collections import defaultdict

from ..base.writer import pack_subrecord
from ..packages.force_greet_gates import stages_set
from ..record_types.common import get_formid, get_int

#: INFO DATA / ENAM flag Say Once.
SAY_ONCE = 0x04

#: TES5 GetStageDone.
_FUNC_GET_STAGE_DONE = 59

#: Reply depth followed below a line; FO3 trees seen so far are two deep.
_MAX_DEPTH = 8

#: Source INFO FormID -> {(quest FormID, stage)} its reply tree sets.
TREE_STAGES: dict = {}

#: DIAL DATA.Type of a player dialogue topic.
_PLAYER_TOPIC = 0

#: A result-script statement that is safe to run again: a variable, a branch, a stage or an objective.
_REPEATABLE = re.compile(r'(?i)^(set\s+\S+\s+to\b|if\b|elseif\b|else\b|endif\b|setstage\b|'
                         r'setobjective(displayed|completed)\b)')

#: A source INFO's result script fields.
_RESULT_SCRIPTS = ('ResultScript', 'ResultScriptEnd')


def _replays_safely(rec: dict) -> bool:
    """Whether every statement of the INFO's own result scripts is safe to run again."""
    lines = '\n'.join(rec.get(k) or '' for k in _RESULT_SCRIPTS).splitlines()
    return all(_REPEATABLE.match(s) for s in (line.split(';', 1)[0].strip() for line in lines) if s)


def choices(rec: dict) -> list:
    """The topic FormIDs an INFO's Choice links name."""
    return [get_formid(rec, f'Choice[{i}]') for i in range(max(get_int(rec, 'ChoiceCount'), 0))]


def _tree_stages(rec: dict, by_dial: dict, own: dict) -> set:
    """{(quest, stage)} the replies below `rec` set, breadth first to _MAX_DEPTH."""
    found, seen, level = set(), set(), choices(rec)
    for _depth in range(_MAX_DEPTH):
        nxt = []
        for dial in level:
            if dial in seen:
                continue
            seen.add(dial)
            for reply in by_dial.get(dial, ()):
                found |= own[get_formid(reply, 'FormID')]
                nxt += choices(reply)
        level = nxt
    return found


def plan_reply_trees(infos: list, dials: list, quest_fid_by_edid: dict) -> int:
    """Fill TREE_STAGES for the Say Once player-topic lines with choices; returns how many lines."""
    TREE_STAGES.clear()
    player_topics = {get_formid(d, 'FormID') for d in dials if get_int(d, 'DATA.Type') == _PLAYER_TOPIC}
    by_dial = defaultdict(list)
    for rec in infos:
        by_dial[get_formid(rec, 'ParentDIAL')].append(rec)
    own = {get_formid(r, 'FormID'): stages_set(r, quest_fid_by_edid) for r in infos}
    for rec in infos:
        if (get_int(rec, 'DATA.Flags') & SAY_ONCE and choices(rec) and _replays_safely(rec)
                and get_formid(rec, 'ParentDIAL') in player_topics):
            stages = _tree_stages(rec, by_dial, own)
            if stages:
                TREE_STAGES[get_formid(rec, 'FormID')] = frozenset(stages)
    return len(TREE_STAGES)


def say_once_flags(rec: dict, flags: int) -> int:
    """`flags` less Say Once for a line whose reply tree sets a stage."""
    return flags & ~SAY_ONCE if get_formid(rec, 'FormID') in TREE_STAGES else flags


def tree_gate(rec: dict) -> bytes:
    """`GetStageDone(quest, stage) == 0` for each stage the line's reply tree sets, else b''."""
    return b''.join(pack_subrecord('CTDA', struct.pack('<B3xfHHIIII I', 0, 0.0, _FUNC_GET_STAGE_DONE, 0,
                                                       quest, stage, 0, 0, 0xFFFFFFFF))
                    for quest, stage in sorted(TREE_STAGES.get(get_formid(rec, 'FormID'), ())))
