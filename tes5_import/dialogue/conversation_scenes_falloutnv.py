"""FO3/FNV NPC-to-NPC conversation packages played as Skyrim scenes.

A Fallout Dialogue package (Conversation, aimed at a reference, with a topic)
walked its actor to the target and ran a conversation: the topic's line, then
each line's Choice topic, the speakers alternating per NextSpeaker. Its linear
chain is walked here from the source and played by a scene on the package's
quest: phase 0 walks the speaker to the target, one phase per line after. Each
line is a shared copy (voice and result fragment intact) in a scene topic.

See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
"""

import struct
from collections import Counter
from dataclasses import dataclass, field

from ..base.conditions import CTDA_OR, FUNC_GET_IS_ID, required_speaker_ids
from ..base.tes5_reader import subrecords
from ..base.text_reader import PLAYER_REF_FID, get_formid, get_int, get_str, remap_formid
from ..base.writer import pack_formid_subrecord, pack_subrecord
from ..packages.conversations_falloutnv import (CONVERSATION_CAST, CONVERSATION_COUNT, CONVERSATION_DONE,
                                                CONVERSATION_SCENE, LINE_SCENES)
from ..packages.force_greet_gates import stages_set
from ..packages.converter import SPEED_WALK, build_pkdt, build_target, sit_inputs
from ..packages.scripts_falloutnv import package_flags
from ..packages.templates import TRAVEL, Inputs
from ..packages.types_falloutnv import FNV_DIALOGUE, dialogue_topic
from script_convert.conversation_sequence import equality_gate
from .arrest import info_records, shared_copy
from .converter import SCENE_TOPIC
from .force_greets import template_package
from .greeting_choices import topic_record
from .scenes import FACE_TARGET, dialogue_action, pack_scene, package_action, target_near
from .talking_lists_falloutnv import scan_pairs

#: The package's actor, and the reference it talks to.
SPEAKER, TARGET = 0, 1

#: INFO DATA.NextSpeaker: the same speaker says the next line.
_NEXT_SELF = 1

#: A chain this long is a loop the walk cannot close.
_MAX_STEPS = 24

#: PKDT interrupt flags of vanilla's scene stand packages (FreeformKarthwastenAAtarStandScenePackage).
_ALL_INTERRUPTS = 0xFFFF

#: PLDT type Near Reference: the package's place is a placed reference.
_NEAR_REFERENCE = 0

#: Activate distance when PTDT.Count is unset: the GECK's iActivatePickLength.
_DEFAULT_REACH = 150

#: TES5 IsInList, the talking-as gate beside a GetIsID.
_FUNC_IS_IN_LIST = 372

#: CTDA run-on value for the target, whom a line is said to.
_RUN_ON_TARGET = 1


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

@dataclass
class Conversation:
    """One package's conversation: who, where, and its lines step by step."""

    pack: str
    edid: str
    quest: int
    speaker: int
    target: int
    reach: int
    scene: int
    talking: set = field(default_factory=set)
    steps: list = field(default_factory=list)
    place: int = 0
    seat: bool = False


#: Written PACK FormID -> its planned conversation.
_CONVERSATIONS: dict = {}

#: Written INFO FormID -> its converted INFO record, for the INFOs the scenes copy.
_CAPTURED: dict = {}

#: Written INFO FormIDs some planned scene copies.
_LINES: set = set()

#: The package plan whose aliases cast the scenes.
_PLAN: list = []


# ---------------------------------------------------------------------------
# Planning, before packages convert
# ---------------------------------------------------------------------------

def _candidate(rec: dict) -> bool:
    """A Conversation Dialogue package aimed at a reference other than the player, with its own topic."""
    target = get_formid(rec, 'PTDT.Target')
    return (get_int(rec, 'PKDT.Type', -1) == FNV_DIALOGUE and rec.get('PKDD.Type') == 'Conversation'
            and get_int(rec, 'PTDT.Type', -1) == 0 and target not in (0, PLAYER_REF_FID)
            and bool(dialogue_topic(rec)))


def _links(rec: dict, key: str) -> list:
    """The written FormIDs of `key[0]`, `key[1]`, ... on a record."""
    out, i = [], 0
    while f'{key}[{i}]' in rec:
        out.append(get_formid(rec, f'{key}[{i}]'))
        i += 1
    return out


def _index(by_type: dict) -> dict:
    """What the walk reads: placed bases, talking-as actors per TACT base, topics and their lines."""
    tacts = {get_str(r, 'EditorID').lower(): get_formid(r, 'FormID') for r in by_type.get('TACT', [])}
    talking = {}
    for tact, actor_hex in scan_pairs(by_type):
        talking.setdefault(tacts.get(tact), set()).add(remap_formid(int(actor_hex, 16)))
    lines = {}
    for rec in by_type.get('INFO', []):
        lines.setdefault(get_formid(rec, 'ParentDIAL'), []).append(rec)
    return {'base': {get_formid(r, 'FormID'): get_formid(r, 'NAME')
                     for s in ('REFR', 'ACHR', 'ACRE') for r in by_type.get(s, [])},
            'talking': talking, 'lines': lines,
            'dials': {get_formid(d, 'FormID'): d for d in by_type.get('DIAL', [])},
            'seats': {get_formid(r, 'FormID') for r in by_type.get('FURN', [])}}


def _speaks(info: dict, ids: set) -> bool:
    """Whether one of `ids` may say the line by its speaker GetIsID chains."""
    required = required_speaker_ids(info)
    return required is None or bool({remap_formid(r) for r in required} & ids)


def _follows(info: dict, prev: int) -> bool:
    """Whether the line may come after topic `prev` (None: the opening line)."""
    links = _links(info, 'LinkFrom')
    return prev in links if links else True


def _counter(info: dict):
    """(quest, variable, value) of the line's `GetQuestVariable == n` test, else None."""
    i = 0
    while f'Condition[{i}].Raw' in info:
        gate = equality_gate(info[f'Condition[{i}].Raw'])
        if gate:
            return gate
        i += 1
    return None


def _on_count(lines: list, count, again: bool) -> tuple:
    """(counter, the lines it selects) for a topic that links to itself: each repeat steps the counter by one.

    `count` is (quest, variable, value) or None. The first step of a counted
    topic starts at its lowest gated value.
    """
    gates = [g for g in map(_counter, lines) if g]
    if not gates:
        return count, lines
    key = gates[0][:2]
    if count is None or count[:2] != key:
        value = min(g[2] for g in gates if g[:2] == key)
    else:
        value = count[2] + (1 if again else 0)
    picked = [i for i in lines if (_counter(i) or (key + (value,)))[:3] == key + (value,)]
    return key + (value,), picked


def _walk(index: dict, start: int, roles: tuple, counted: bool = False) -> list:
    """[(DIAL rec, role, [INFO recs], previous DIAL FormID, counter key part)] of the chain from `start`; [] if it branches or loops.

    A step keeps the lines linked from the previous topic when it has any (GECK: a Goodbye info names the
    topic it follows in Link From), else every line its speaker may say. `counted`: a topic that links
    to itself steps a quest-variable counter, for a chain the plain walk cannot close.
    See: docs/commentary/tes5_import_dialogue.md#counted-loops
    """
    steps, topic, role, prev, count = [], start, SPEAKER, None, None
    while topic in index['dials'] and len(steps) < _MAX_STEPS:
        lines = [i for i in index['lines'].get(topic, []) if _speaks(i, roles[role]) and _follows(i, prev)]
        lines = [i for i in lines if prev in _links(i, 'LinkFrom')] or lines
        if counted and any(topic in _links(i, 'Choice') for i in lines):
            count, lines = _on_count(lines, count, topic == prev)
        if not lines:
            break
        steps.append((index['dials'][topic], role, lines, prev or 0, f'|{count[2]}' if count else ''))
        nexts = list(dict.fromkeys(c for i in lines for c in _links(i, 'Choice')))
        if len(nexts) > 1:
            return []
        if not all(get_int(i, 'DATA.NextSpeaker') == _NEXT_SELF for i in lines):
            role = TARGET - role
        prev, topic = topic, (nexts[0] if nexts else 0)
    return steps if len(steps) < _MAX_STEPS else []


def _cast(rec: dict, pack_fid: int, plan):
    """(quest, speaker ref) of a quest package with one runner whose target gets an alias; else None."""
    quest = plan.owner_quest.get(pack_fid)
    runners = [ref for ref, packs in plan.quest_packages.get(quest, {}).items() if pack_fid in packs]
    needed = plan.needed_aliases.get(quest, set())
    if quest is None or len(runners) != 1 or not {runners[0], get_formid(rec, 'PTDT.Target')} <= needed:
        return None
    return quest, runners[0]


def _plan_one(rec: dict, index: dict, plan, writer):
    """The Conversation a candidate package plays, else why not: 'has scripts', 'no cast' or 'no chain'."""
    cast = _cast(rec, get_formid(rec, 'FormID'), plan)
    if package_flags(rec) or cast is None:
        return 'has scripts' if package_flags(rec) else 'no cast'
    quest, speaker = cast
    target = get_formid(rec, 'PTDT.Target')
    talking = index['talking'].get(index['base'].get(target), set())
    roles = ({index['base'].get(speaker, 0)}, {index['base'].get(target, 0)} | talking)
    steps = _walk(index, dialogue_topic(rec), roles) or _walk(index, dialogue_topic(rec), roles, counted=True)
    if not steps:
        return 'no chain'
    place = get_formid(rec, 'PLDT.Location') if get_int(rec, 'PLDT.Type', -1) == _NEAR_REFERENCE else 0
    return Conversation(rec['FormID'].upper(), get_str(rec, 'EditorID'), quest, speaker, target,
                        get_int(rec, 'PTDT.Count', 0) or _DEFAULT_REACH,
                        writer.derive_formid('CONV_SCENE', rec['FormID'].upper()), talking, steps,
                        place, index['base'].get(place) in index['seats'])


def plan_conversations(by_type: dict, writer, plan) -> dict:
    """Plan a scene for each candidate conversation package, filling CONVERSATION_SCENE; {outcome: count}.

    Runs after the package plan and before packages convert.
    See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
    """
    for table in (_CONVERSATIONS, _CAPTURED, _LINES, CONVERSATION_SCENE, LINE_SCENES, CONVERSATION_DONE,
                  CONVERSATION_CAST, CONVERSATION_COUNT):
        table.clear()
    _PLAN[:] = [plan]
    index, outcomes = _index(by_type), Counter()
    quests = {get_str(q, 'EditorID').lower(): get_formid(q, 'FormID') for q in by_type.get('QUST', [])}
    for rec in filter(_candidate, by_type.get('PACK', [])):
        conv = _plan_one(rec, index, plan, writer)
        outcomes[conv if isinstance(conv, str) else 'planned'] += 1
        if not isinstance(conv, str):
            _record(get_formid(rec, 'FormID'), conv, quests)
            cast = tuple((plan.alias_of(conv.quest, ref), ref) for ref in (conv.speaker, conv.target))
            if all(alias is not None for alias, _ref in cast):
                CONVERSATION_CAST[get_formid(rec, 'FormID')] = cast
    return dict(outcomes)


def _record(pack_fid: int, conv, quests: dict) -> None:
    """File a planned conversation: its scene, its lines, the stages its last stage-setting step sets, its counter's end."""
    _CONVERSATIONS[pack_fid] = conv
    CONVERSATION_SCENE[pack_fid] = conv.scene
    for _d, _r, lines, _p, _c in conv.steps:
        for line in lines:
            _LINES.add(get_formid(line, 'FormID'))
            LINE_SCENES.setdefault(get_formid(line, 'FormID'), set()).add(conv.scene)
        stages = set().union(*(stages_set(line, quests) for line in lines))
        if stages:
            CONVERSATION_DONE[pack_fid] = frozenset(stages)
    last = conv.steps[-1]
    gate = last[4] and next(filter(None, map(_counter, last[2])), None)
    if gate:
        CONVERSATION_COUNT[pack_fid] = gate[:2] + (gate[2] + 1,)


def capture_line(info_fid: int, packed: bytes) -> None:
    """Keep a converted INFO some conversation scene copies."""
    if info_fid in _LINES:
        _CAPTURED[info_fid] = packed


# ---------------------------------------------------------------------------
# Building, after the dialogue
# ---------------------------------------------------------------------------

def _listener_test(ctda: bytes) -> bool:
    """A GetIsID or talking-as IsInList run on whom the line is said to."""
    func, = struct.unpack_from('<H', ctda, 8)
    run_on, = struct.unpack_from('<I', ctda, 20)
    return run_on == _RUN_ON_TARGET and func in (FUNC_GET_IS_ID, _FUNC_IS_IN_LIST)


def _without_listener(body: bytes) -> list:
    """`body`'s subrecords less every OR group of listener tests alone: a scene line is said to no one."""
    out, group = [], []
    for tag, data in subrecords(body):
        if tag != b'CTDA':
            (group if group else out).append((tag, data))
            continue
        group.append((tag, data))
        if not data[0] & CTDA_OR:
            out += [] if all(_listener_test(d) for t, d in group if t == b'CTDA') else group
            group = []
    return out + group


def _line_body(line: dict, body: bytes, conv: Conversation, role: int) -> bytes:
    """The line's INFO body for the scene; a talking activator's line names the actor it speaks as."""
    subs = [(t, d) for t, d in _without_listener(body) if not (t == b'ANAM' and conv.talking and role == TARGET)]
    voices = {remap_formid(r) for r in required_speaker_ids(line) or ()} & conv.talking
    packed = b''.join(pack_subrecord(t.decode('ascii'), d) for t, d in subs)
    return packed + (pack_formid_subrecord('ANAM', min(voices)) if role == TARGET and voices else b'')


def _copies(writer, conv: Conversation, role: int, lines: list) -> list:
    """Shared copies of a step's captured lines, keyed on the package and the source INFO."""
    out = []
    for line in lines:
        for fid, flags, body in info_records(_CAPTURED.get(get_formid(line, 'FormID'), b'')):
            copy = writer.derive_formid('CONV_LINE', f'{conv.pack}|{line["FormID"].upper()}')
            out.append(shared_copy(_line_body(line, body, conv, role), fid, copy, flags))
    return out


def _stand_package(writer, conv: Conversation) -> int:
    """Add the scene's speaker package and return its FormID: sit at or go to the package's place, else walk to the target.

    See: docs/commentary/tes5_import_dialogue.md#conversation-place
    """
    fid = writer.derive_formid('CONV_STAND_PACK', conv.pack)
    if conv.seat:
        inputs = sit_inputs(build_target(0, conv.place))
    else:
        inputs = Inputs(TRAVEL)
        inputs.set('location', (0, conv.place, 0) if conv.place else (0, conv.target, conv.reach))
    writer.add_record('PACK', template_package(f'{conv.edid}Stand', fid, conv.quest, inputs,
                                               build_pkdt(0, SPEED_WALK, _ALL_INTERRUPTS)))
    return fid


def _build(writer, conv: Conversation) -> bytes:
    """Add one conversation's SCEN and stand PACK; return its scene topics (DIAL bytes), b'' without a cast."""
    plan = _PLAN[0]
    cast = (plan.alias_of(conv.quest, conv.speaker), plan.alias_of(conv.quest, conv.target))
    if None in cast:
        print(f'  Conversation scene {conv.edid}: no alias for its speaker or target, not built')
        return b''
    stand = _stand_package(writer, conv)
    last = len(conv.steps)
    actions = [package_action(1, cast[SPEAKER], 0, 0, stand), package_action(2, cast[SPEAKER], 1, last, stand)]
    content = b''
    for n, (dial, role, lines, prev, counted) in enumerate(conv.steps, 1):
        topic = writer.derive_formid('CONV_TOPIC', f'{conv.pack}|{prev:08X}|{dial["FormID"].upper()}|{role}{counted}')
        content += topic_record(dial, topic, f'{conv.edid}_{n}', conv.quest, SCENE_TOPIC,
                                _copies(writer, conv, role, lines))
        actions.append(dialogue_action(len(actions) + 1, cast[role], n, topic, cast[TARGET - role], FACE_TARGET))
    waits = {0: target_near(cast[SPEAKER], conv.target, conv.reach)} if conv.place else {}
    writer.add_record('SCEN', pack_scene(conv.scene, f'{conv.edid}Scene', conv.quest, list(cast), last + 1, actions,
                                         waits))
    return content


def build_conversation_scenes(writer) -> bytes:
    """The planned conversations' scene topics; SCEN and PACK go to `writer`.

    See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
    """
    return b''.join(_build(writer, conv) for conv in _CONVERSATIONS.values())
