"""A quest's greetings keep their source order across the Hello and Blocking topics.

FO3, FNV and Oblivion say the first valid GREETING line in topic order. Skyrim
says a valid Blocking line before any Hello line, so a leading line (said from
Blocking) would beat a plain line listed above it. FO3's Dad: after the
radroach dies (CG02 70), "Good work! That's one less Radroach" (`0001F9C6`,
`setstage CG02 80`) comes first, but "Something wrong? That Radroach is still
over there" (`0001F9C7`, valid from stage 55, with choices) won every time,
so stage 80 was never set. For each leading line, every plain line above it
that one speaker can say wins as it did:

- a Goodbye line is said from the Blocking topic, in its place: a Blocking
  line with no link ends the talk, which a Goodbye does anyway;
- any other plain line stays in Hello, and each line said from Blocking
  (leading or moved) below it asks that it fails (its conditions negated,
  one OR group per plain line).

A plain line that is Say Once or Random, or whose conditions hold an OR, has
no negation Skyrim can test; it is left as it was and counted.

See: docs/commentary/tes5_import_dialogue.md#greeting-order
"""

import struct

from ..base.conditions import read_getisid_fids
from ..base.writer import pack_subrecord

#: ENAM flags: Goodbye, Random, Say Once.
_GOODBYE, _RANDOM, _SAY_ONCE = 0x1, 0x2, 0x4

#: CTDA type byte: the OR flag, and each comparison's negation (operator in bits 5-7).
_OR = 0x01
_NEGATED = {0: 1, 1: 0, 2: 5, 5: 2, 3: 4, 4: 3}


def _subrecords(body: bytes):
    """Yield (signature, payload) for each subrecord of a record body."""
    pos = 0
    while pos + 6 <= len(body):
        size = struct.unpack_from('<H', body, pos + 4)[0]
        yield body[pos:pos + 4], body[pos + 6:pos + 6 + size]
        pos += 6 + size


def _ctdas(body: bytes) -> list:
    """The record's CTDA payloads, in order."""
    return [data for sig, data in _subrecords(body) if sig == b'CTDA']


def _enam(body: bytes) -> int:
    """The INFO's ENAM flags."""
    return next((struct.unpack_from('<H', d)[0] for s, d in _subrecords(body) if s == b'ENAM' and len(d) >= 2), 0)


def negated_gate(plain: bytes, lead: bytes):
    """CTDAs passing only when `plain` fails, given `lead` passes; None when Skyrim cannot test that.

    Conditions `lead` already asks are dropped: they hold whenever it is said.
    """
    if _enam(plain) & (_RANDOM | _SAY_ONCE):
        return None
    tests = _ctdas(plain)
    if any(t[0] & _OR for t in tests):
        return None
    asked = set(_ctdas(lead))
    rest = [t for t in tests if t not in asked]
    if not rest:
        return None
    out = b''
    for i, t in enumerate(rest):
        kind = (_NEGATED[t[0] >> 5] << 5) | (t[0] & 0x1E) | (_OR if i < len(rest) - 1 else 0)
        out += pack_subrecord('CTDA', bytes([kind]) + t[1:])
    return out


def _shared_speaker(a: set, b: set) -> bool:
    """Whether two lines' GetIsID speakers can be one actor (empty: anyone)."""
    return not a or not b or bool(a & b)


def _moved_goodbyes(lines: list) -> set:
    """Plain Goodbye lines above a leading line one speaker can also say: said from Blocking."""
    moved, plain = set(), []
    for fid, body, speakers, leads in lines:
        if not leads:
            plain.append((fid, body, speakers))
            continue
        moved |= {p for p, b, s in plain if _enam(b) & _GOODBYE and _shared_speaker(speakers, s)}
    return moved


def order_greetings(lines: list, offset: int) -> tuple:
    """({moved Goodbye FormIDs}, {Blocking FormID: gate CTDAs}, unordered count) for `lines` in topic order.

    `lines` is [(output FormID, packed body, source record, leads on)]. Each
    line said from Blocking (leading or moved) waits on the Hello lines above it.
    """
    lines = [(fid, body, read_getisid_fids(rec, offset=offset, positive_only=True), leads)
             for fid, body, rec, leads in lines]
    moved = _moved_goodbyes(lines)
    gates, unordered, hello = {}, 0, []
    for fid, body, speakers, leads in lines:
        if not (leads or fid in moved):
            hello.append((body, speakers))
            continue
        gate = b''
        for p_body, p_speakers in hello:
            if _shared_speaker(speakers, p_speakers):
                negated = negated_gate(p_body, body)
                unordered += negated is None
                gate += negated or b''
        if gate:
            gates[fid] = gate
    return moved, gates, unordered
