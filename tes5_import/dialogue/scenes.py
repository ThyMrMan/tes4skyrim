"""SCEN records in vanilla's layout: phases, actors, then dialogue and package actions.

Phase, actor and action subrecords follow DA11NamiraScene (one line) and
FreeformKarthwastenAScene (a two-actor conversation, one line per phase, each
actor's standing package spanning every phase).

See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
"""

import struct

from ..base.writer import (pack_float_subrecord, pack_formid_subrecord, pack_record, pack_string_subrecord,
                           pack_subrecord, pack_uint16_subrecord, pack_uint32_subrecord)

#: Actor behavior: Death End, Combat End, Dialogue Pause (DA11NamiraScene), so talking to one pauses the scene.
ACTOR_BEHAVIOR = 0x1A

#: Scene FNAM of DA11NamiraScene and FreeformKarthwastenAScene.
_SCENE_FLAGS = 4

#: Action types: a line of dialogue, a package.
_DIALOGUE, _PACKAGE = 0, 1

#: TES5 GetDistance; CTDA "<=" operator bits; run on Quest Alias.
_FUNC_GET_DISTANCE, _OP_AT_MOST, _RUN_ON_ALIAS = 1, 0xA0, 5

#: Dialogue action FNAM of FreeformKarthwastenAScene's lines: face the head-tracked actor.
FACE_TARGET = 0x8000


def _phase(done: bytes = b'') -> bytes:
    """One unnamed phase; `done` holds its packed completion CTDAs."""
    return (pack_subrecord('HNAM', b'') + pack_string_subrecord('NAM0', '')
            + pack_subrecord('NEXT', b'') + done + pack_subrecord('NEXT', b'')
            + pack_uint32_subrecord('WNAM', 200) + pack_subrecord('HNAM', b''))


def target_near(alias: int, target: int, reach: int) -> bytes:
    """`GetDistance(target) <= reach` on quest alias `alias` (id in the last field)."""
    return pack_subrecord('CTDA', struct.pack('<B3xfHHIIIIi', _OP_AT_MOST, float(reach), _FUNC_GET_DISTANCE, 0,
                                              target, 0, _RUN_ON_ALIAS, 0, alias))


def _head(kind: int, index: int, alias: int) -> bytes:
    """An action's leading ANAM NAM0 ALID INAM."""
    return (pack_uint16_subrecord('ANAM', kind) + pack_string_subrecord('NAM0', '')
            + pack_uint32_subrecord('ALID', alias) + pack_uint32_subrecord('INAM', index))


def dialogue_action(index: int, alias: int, phase: int, topic: int, headtrack: int = -1, flags=None) -> bytes:
    """`alias` says `topic` in `phase`, head-tracking alias `headtrack` (-1: none)."""
    out = _head(_DIALOGUE, index, alias)
    out += pack_uint32_subrecord('FNAM', flags) if flags is not None else b''
    return (out + pack_uint32_subrecord('SNAM', phase) + pack_uint32_subrecord('ENAM', phase)
            + pack_formid_subrecord('DATA', topic) + pack_subrecord('HTID', struct.pack('<i', headtrack))
            + pack_float_subrecord('DMAX', 10.0) + pack_float_subrecord('DMIN', 1.0)
            + pack_uint32_subrecord('DEMO', 0) + pack_uint32_subrecord('DEVA', 0) + pack_subrecord('ANAM', b''))


def package_action(index: int, alias: int, start: int, end: int, package: int) -> bytes:
    """`alias` runs `package` from phase `start` through `end`."""
    return (_head(_PACKAGE, index, alias) + pack_uint32_subrecord('SNAM', start)
            + pack_uint32_subrecord('ENAM', end) + pack_formid_subrecord('PNAM', package)
            + pack_subrecord('ANAM', b''))


def pack_scene(fid: int, edid: str, quest_fid: int, aliases: list, phases: int, actions: list,
               done: dict = None) -> bytes:
    """A scene of `phases` phases casting `aliases`; `actions` are packed actions numbered 1..n.

    `done` maps a phase to its packed completion conditions.
    """
    subs = pack_string_subrecord('EDID', edid) + pack_uint32_subrecord('FNAM', _SCENE_FLAGS)
    subs += b''.join(_phase((done or {}).get(n, b'')) for n in range(phases))
    subs += b''.join(pack_uint32_subrecord('ALID', a) + pack_uint32_subrecord('LNAM', 0)
                     + pack_uint32_subrecord('DNAM', ACTOR_BEHAVIOR) for a in aliases)
    subs += b''.join(actions) + pack_formid_subrecord('PNAM', quest_fid)
    subs += pack_uint32_subrecord('INAM', len(actions))
    subs += pack_subrecord('VNAM', struct.pack('<4I', 3, 3, 3, 3))
    return pack_record('SCEN', fid, 0, subs)
