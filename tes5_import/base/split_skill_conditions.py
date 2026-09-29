"""Source skills Skyrim split in two: a condition on one tests both halves.

Oblivion's Blade and Blunt and FNV's Melee Weapons covered one- and two-handed
weapons alike, so a skill gate on the CURRENT value reads the higher of
One-Handed and Two-Handed:
`>=`/`>` becomes an OR of the two tests, `<`/`<=` outside an OR group an AND.
A BASE read gates a trainer whose result script writes One-Handed, so it stays
One-Handed, as does any other shape.
See: docs/plans/character_sheet.md#bug-blade-blunt
"""

import struct

#: TES4 GetActorValue; the index is the same in TES5.
_AV_FUNCS = frozenset({14})

#: CTDA size -> the split skills' source actor values: TES4 Blade and Blunt, FO3/FNV Melee Weapons.
_SPLIT_SKILLS = {24: frozenset({14, 16}), 28: frozenset({38})}

#: TES5 Two-Handed actor-value index; the tables map every split skill to One-Handed.
_TWO_HANDED = 7

#: CTDA type-byte OR flag, and the comparison operators in its top three bits.
_OR = 0x01
_AT_LEAST = frozenset({2, 3})
_BELOW = frozenset({4, 5})


def _with_param1(ctda: bytes, param1: int, or_flag: bool) -> bytes:
    """`ctda` with its first parameter replaced and its OR flag set as given."""
    type_byte = (ctda[0] & ~_OR) | (_OR if or_flag else 0)
    return bytes([type_byte]) + ctda[1:12] + struct.pack('<I', param1) + ctda[16:]


def split_skill_ctdas(raw: bytes, ctda: 'bytes | None') -> list:
    """The TES5 CTDAs one TES4 condition becomes: [], [ctda], or a One/Two-Handed pair."""
    if ctda is None:
        return []
    func, av = struct.unpack_from('<H2xI', raw, 8)
    op, in_or = raw[0] >> 5, bool(raw[0] & _OR)
    if func not in _AV_FUNCS or av not in _SPLIT_SKILLS.get(len(raw), ()):
        return [ctda]
    one_handed = struct.unpack_from('<I', ctda, 12)[0]
    if op in _AT_LEAST:
        return [_with_param1(ctda, one_handed, True), _with_param1(ctda, _TWO_HANDED, in_or)]
    if op in _BELOW and not in_or:
        return [ctda, _with_param1(ctda, _TWO_HANDED, False)]
    return [ctda]
