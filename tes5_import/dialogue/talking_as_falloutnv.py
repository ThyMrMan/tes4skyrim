"""FO3/FNV talking activators on a line: who may say it, in which voice, with which Speaker.

Fallout's engine lets a talking activator pass the actor's GetIsID it speaks
as. Each such actor has a formlist holding its own base (built by
`talking_lists_falloutnv`), and each GetIsID of the actor on a line is OR'd with
`IsInList` of that list; `TES4Polyfill.SetTalkingActivatorActor` moves the
activator's base into it. Kept free of heavy imports: dialogue.converter reads it.

See: docs/commentary/tes5_import_dialogue.md#fallout-talking-activators
"""

import struct

from ..base.conditions import CTDA_OR, FUNC_GET_IS_ID

#: TES5 IsInList: the subject's base object is in the formlist.
_FUNC_IS_IN_LIST = 372

#: Written actor base FormID -> its talking-as FLST.
TALKING_LIST: dict = {}

#: Written actor base FormID -> the voice types of the activators that speak as it.
TALKING_VOICES: dict = {}

#: Written TACT FormID -> the unplaced voice NPC its own lines name as Speaker.
TALKER_VOICE: dict = {}


def talker_speaker(own) -> int:
    """Voice NPC for a line whose only speakers are talking activators, else 0."""
    own = set(own)
    return TALKER_VOICE[min(own)] if own and own <= TALKER_VOICE.keys() else 0


def talking_voices(npc_fids) -> set:
    """The voice types of the activators that may speak as any of `npc_fids`."""
    return set().union(*(TALKING_VOICES.get(f, set()) for f in npc_fids))


def _talking_list(ctda: bytes) -> int:
    """The talking-as FLST of a `GetIsID(actor) == 1` whose actor an activator speaks as, else 0."""
    func, _pad, actor = struct.unpack_from('<HHI', ctda, 8)
    value, = struct.unpack_from('<f', ctda, 4)
    if func != FUNC_GET_IS_ID or ctda[0] & 0xE0 or value != 1.0:
        return 0
    return TALKING_LIST.get(actor, 0)


def talking_as(pairs: list) -> list:
    """`pairs` of (CTDA, trailing subrecords), each talked-through GetIsID OR'd with `IsInList` of its list.

    The IsInList keeps the GetIsID's own run-on and OR flag, so the pair sits where the test did.
    """
    out = []
    for ctda, extra in pairs:
        flst = _talking_list(ctda)
        if not flst:
            out.append((ctda, extra))
            continue
        in_list = bytearray(ctda)
        struct.pack_into('<HHII', in_list, 8, _FUNC_IS_IN_LIST, 0, flst, 0)
        out += [(bytes([ctda[0] | CTDA_OR]) + ctda[1:], extra), (bytes(in_list), b'')]
    return out
