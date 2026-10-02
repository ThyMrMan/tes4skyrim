"""FO3/FNV conversation packages whose lines a scene plays: the package holds its speaker and starts the scene.

A Fallout Dialogue package held its actor through an NPC-to-NPC conversation.
Skyrim plays scripted conversations as scenes; the converted package keeps the
speaker where it stands and its OnBegin fragment (`TES4_ConversationStart`)
starts the scene the dialogue build made for it. The table is filled before
packages convert (`dialogue.conversation_scenes_falloutnv.plan_conversations`).

See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
"""

import struct

from ..base.writer import pack_subrecord
from .templates import HOLD_POSITION, Inputs

#: The static package fragment script that starts a conversation's scene (OnBegin).
START_SCRIPT = 'TES4_ConversationStart'

#: Written PACK FormID -> the SCEN playing its conversation.
CONVERSATION_SCENE: dict = {}

#: Written PACK FormID -> ((speaker alias, speaker ref), (target alias, target ref)) its scene casts.
CONVERSATION_CAST: dict = {}

#: Written PACK FormID -> (quest, variable index, end value) of its counted conversation's source counter.
CONVERSATION_COUNT: dict = {}

#: Source INFO FormID -> the SCENs that say a shared copy of it.
LINE_SCENES: dict = {}

#: Written PACK FormID -> {(quest FormID, stage)} its conversation's last stage-setting step sets.
CONVERSATION_DONE: dict = {}

#: TES5 GetStageDone; source GetQuestVariable; the CTDA "<" operator bits.
_FUNC_GET_STAGE_DONE = 59
_FUNC_GET_QUEST_VARIABLE, _OP_LESS = 79, 0x80

#: TES5 IsScenePlaying; the CTDA OR flag; run-on Target; the listener tests (GetIsID, IsInList).
_FUNC_IS_SCENE_PLAYING = 248
_CTDA_OR = 0x01
_RUN_ON_TARGET = 1
_LISTENER_FUNCS = (72, 372)

#: HoldPosition near the package's start location, radius 64: vanilla's DefaultHoldPositionCurrentLoc64.
_HOLD_HERE = (2, 0, 64)

#: VMAD fragment flags: OnBegin only.
_ON_BEGIN = 0x01


def conversation_inputs(pack_fid: int):
    """HoldPosition where the speaker stands, for a package a scene plays; None otherwise."""
    if pack_fid not in CONVERSATION_SCENE:
        return None
    inputs = Inputs(HOLD_POSITION)
    inputs.set('location', _HOLD_HERE)
    return inputs


def conversation_flags(pack_fid: int, flags: int, must_complete: int) -> int:
    """`flags` less Must Complete for a scene-played package; its scene holds it."""
    return flags & ~must_complete if pack_fid in CONVERSATION_SCENE else flags


def conversation_guard(pack_fid: int) -> bytes:
    """`GetStageDone == 0` per stage the conversation's end sets (no replay).

    See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
    """
    return b''.join(pack_subrecord('CTDA', struct.pack('<B3xfHHIIII I', 0, 0.0, _FUNC_GET_STAGE_DONE, 0,
                                                       quest, stage, 0, 0, 0xFFFFFFFF))
                    for quest, stage in sorted(CONVERSATION_DONE.get(pack_fid, ())))


def count_guard(pack_fid: int):
    """A source-format record asking a counted conversation's counter to be below its end, else None.

    See: docs/commentary/tes5_import_dialogue.md#counted-loops
    """
    count = CONVERSATION_COUNT.get(pack_fid)
    if not count:
        return None
    quest, var, end = count
    raw = struct.pack('<B3xfHHIIII', _OP_LESS, float(end), _FUNC_GET_QUEST_VARIABLE, 0, quest, var, 0, 0)
    return {'ConditionCount': '1', 'Condition[0].Raw': raw.hex()}


def _listens(ctda: bytes) -> bool:
    """Whether a CTDA tests who the line is said to (GetIsID or IsInList on Target)."""
    func, = struct.unpack_from('<H', ctda, 8)
    run_on, = struct.unpack_from('<I', ctda, 20)
    return func in _LISTENER_FUNCS and run_on == _RUN_ON_TARGET


def _scene_playing(scene: int, chained: bool) -> tuple:
    """(`IsScenePlaying(scene) == 1` CTDA, b''), OR-chained when `chained`."""
    return (struct.pack('<B3xfHHIIII I', _CTDA_OR if chained else 0, 1.0, _FUNC_IS_SCENE_PLAYING, 0,
                        scene, 0, 0, 0, 0xFFFFFFFF), b'')


def while_scene_plays(pairs: list, info_fid: int) -> list:
    """`pairs` of (CTDA, trailing subrecords), each listener OR group also passing while a scene copying the line plays.

    A shared copy plays only while its original passes, and a scene's line is
    not said to the actor the original names.
    See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
    """
    scenes = sorted(LINE_SCENES.get(info_fid, ()))
    if not scenes:
        return pairs
    out, group = [], []
    for ctda, extra in pairs:
        group.append((ctda, extra))
        if ctda[0] & _CTDA_OR:
            continue
        if any(_listens(c) for c, _x in group):
            last, tail = group[-1]
            group[-1] = (bytes([last[0] | _CTDA_OR]) + last[1:], tail)
            group += [_scene_playing(s, i < len(scenes) - 1) for i, s in enumerate(scenes)]
        out += group
        group = []
    return out + group


def conversation_vmad(pack_fid: int) -> bytes:
    """The OnBegin fragment VMAD starting the package's scene, with its cast to fill, or b''.

    script_convert is imported here: its converter imports tes5_import.dialogue,
    which imports this package's converter (the fragments_falloutnv cycle).
    """
    scene = CONVERSATION_SCENE.get(pack_fid)
    if not scene:
        return b''
    from script_convert.pipeline import build_vmad_package_fragment
    objects, values = {'ConversationScene': scene}, {}
    for role, (alias, ref) in zip(('Speaker', 'Target'), CONVERSATION_CAST.get(pack_fid, ())):
        objects[f'{role}Ref'] = ref
        values[f'{role}Alias'] = ('int', alias)
    return pack_subrecord('VMAD', build_vmad_package_fragment(
        START_SCRIPT, value_props=values, object_props=objects, flags=_ON_BEGIN))
