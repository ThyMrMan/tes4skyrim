"""FO3/FNV CTDA fields that TES4's 24-byte layout does not carry.

A Fallout CTDA is 28 bytes: TES4's 20 shared bytes, then an explicit Run On
u32 and a Reference u32 in place of TES4's unused tail.  Its function indices
and its actor-value parameters follow Fallout's own tables, so both are
rewritten to Skyrim's before any index-keyed lookup.

See: docs/commentary/tes5_import_conditions.md#fallout-ctda
"""

import struct

from ..generated.ctda_fnv_remap import FNV_FUNC_ABSENT, FNV_FUNC_REMAP
from ..record_types.world_falloutnv import is_fallout_source

#: A CTDA at least this long carries Fallout's Run On / Reference tail.
FALLOUT_CTDA_SIZE = 28

#: GetDisposition: absent in Skyrim, but evaluated at a fixed tier by convert_ctda.
_GET_DISPOSITION = 76

#: The player's reference, the one whose karma the mirror global holds.
PLAYER_REF = 0x14

#: FO3/FNV actor value -> TES5; any other drops. See: docs/commentary/tes5_import_conditions.md#fallout-actor-values
FALLOUT_AV_TO_TES5 = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4,   # Aggression, Confidence, Energy, Responsibility, Mood
    13: 32,   # Carry Weight
    14: 33,   # Critical Chance
    15: 27,   # Heal Rate
    16: 24,   # Health
    17: 34,   # Melee Damage
    18: 39,   # Damage Resistance
    19: 40,   # Poison Resistance
    21: 30,   # Speed Multiplier
    32: 17,   # Barter           -> Speech
    33: 8,    # Big Guns         -> Archery (guns convert to crossbows)
    34: 8,    # Energy Weapons   -> Archery
    36: 14,   # Lockpick         -> Lockpicking
    37: 22,   # Medicine         -> Restoration
    38: 6,    # Melee Weapons    -> OneHanded (and TwoHanded, split_skill_conditions)
    39: 10,   # Repair           -> Smithing
    41: 8,    # Guns             -> Archery
    42: 15,   # Sneak
    43: 17,   # Speech
    45: 6,    # Unarmed          -> OneHanded
    46: 31,   # Inventory Weight
    47: 53,   # Paralysis
    48: 54,   # Invisibility
    49: 54,   # Chameleon        -> Invisibility
    50: 55,   # Night Eye
    52: 41,   # Fire Resistance
    53: 57,   # Water Breathing
    56: 35,   # Unarmed Damage
    57: 5,    # Assistance
    58: 42,   # Electric Resistance -> ResistShock
    59: 43,   # Frost Resistance
    62: 68, 63: 69, 64: 70, 65: 71, 66: 72,   # Variable01-05
    67: 73, 68: 74, 69: 75, 70: 76, 71: 77,   # Variable06-10
}

#: Variable01, 02, 05 and 10: free on NPCs (the dialogue helpers write the first three on the player only).
_KEPT_VARIABLES = frozenset({62, 63, 66, 71})

#: Fallout values the fork's conditions leave unread. See: docs/fork/character.md#condition-actor-values
FORK_DROPPED_ACTOR_VALUES = frozenset({15, 18, 33, 34, 37, 38, 41, 45, *range(62, 72)}) - _KEPT_VARIABLES

#: FALLOUT_AV_TO_TES5 without the fork's dropped values: what converted conditions read.
FORK_FALLOUT_AV = {av: tes5 for av, tes5 in FALLOUT_AV_TO_TES5.items() if av not in FORK_DROPPED_ACTOR_VALUES}

#: Fallout Run On values: Subject, Target, Reference, Combat Target, Linked Ref.
_RUN_ON_TARGET = 1
_RUN_ON_REFERENCE = 2

#: FO3/FNV GetObjectiveCompleted / GetObjectiveDisplayed -> the objective state each reads.
OBJECTIVE_FUNCS = {420: 'Done', 421: 'Shown'}

#: (source quest FormID low 24, objective index, state) -> the GLOB mirroring it; see objectives_falloutnv.
OBJECTIVE_GLOBALS: dict = {}

#: REPU FormID low 24 -> its [infamy, fame, mixed, good, bad, maximum] GLOB FormIDs; see reputation_falloutnv.
REPUTATION_GLOBALS: dict = {}

#: FO3/FNV actor value index -> the GLOB mirroring it (Karma).
ACTOR_VALUE_GLOBALS: dict = {}

#: FO3/FNV GetActorValue, GetReputation and GetReputationThreshold.
_GET_ACTOR_VALUE, _GET_REPUTATION, _GET_REPUTATION_THRESHOLD = 14, 573, 575

#: Skyrim GetGlobalValue, and the CTDA type bits a global read keeps (operator and OR).
_GET_GLOBAL_VALUE, _OPERATOR_AND_OR = 74, 0xE1

#: TES4/FO3/FNV CTDA type bit: the comparison value is a GLOB.
_USE_GLOBAL = 0x04

def fallout_ctda(raw: bytes) -> bytes:
    """`raw`, padded to the full 28 bytes when it is a Fallout CTDA.

    Length alone cannot tell: FO3/FNV masters also store the older 20- and
    24-byte forms, which omit Reference (24) or Run On and Reference (20), so
    a short CTDA is Fallout's whenever the source plugin is. Zero padding
    reads as Run On = Subject, the omitted fields' meaning. A TES4 CTDA is
    returned unchanged.
    See: docs/commentary/tes5_import_conditions.md#fallout-short-ctda
    """
    if len(raw) < FALLOUT_CTDA_SIZE and is_fallout_source():
        return raw.ljust(FALLOUT_CTDA_SIZE, b'\0')
    return raw


def fallout_function(func_idx: int) -> 'int | None':
    """The Skyrim index for a Fallout condition function, or None if it has none."""
    if func_idx in FNV_FUNC_ABSENT and func_idx != _GET_DISPOSITION:
        return None
    return FNV_FUNC_REMAP.get(func_idx, func_idx)


def _mirror_global(func_idx: int, param1: int, param2: int, on_player: bool) -> int:
    """The GLOB a FO3/FNV objective, reputation or player-karma test reads, or 0."""
    state = OBJECTIVE_FUNCS.get(func_idx)
    if state:
        return OBJECTIVE_GLOBALS.get((param1 & 0xFFFFFF, param2, state), 0)
    if func_idx == _GET_ACTOR_VALUE:
        return ACTOR_VALUE_GLOBALS.get(param1, 0) if on_player else 0
    rep = REPUTATION_GLOBALS.get(param1 & 0xFFFFFF)
    if rep and func_idx == _GET_REPUTATION and param2 in (0, 1):
        return rep[param2]
    if rep and func_idx == _GET_REPUTATION_THRESHOLD and param2 in (0, 1, 2):
        return rep[2 + param2]
    return 0


def mirrored_ctda(type_byte: int, comp_raw: int, func_idx: int, param1: int,
                  param2: int, on_player: bool = False) -> 'bytes | None':
    """A FO3/FNV test of state kept in a global, as GetGlobalValue(it), same comparison; else None.

    Objectives (Skyrim's functions are script-only), reputation and karma
    (Skyrim has none) are mirrored in globals the converted scripts set.
    See: docs/commentary/tes5_import_conditions.md#fallout-objective-conditions
    See: docs/commentary/tes5_import_character_data.md#fallout-reputation
    """
    glob = _mirror_global(func_idx, param1, param2, on_player)
    if not glob or type_byte & _USE_GLOBAL:
        return None
    return struct.pack('<B3xIHHIIII I', type_byte & _OPERATOR_AND_OR, comp_raw,
                       _GET_GLOBAL_VALUE, 0, glob, 0, 0, 0, 0xFFFFFFFF)


def fallout_actor_value(av: int) -> 'int | None':
    """The Skyrim actor value a Fallout one maps to, or None when it has none.

    See: docs/commentary/tes5_import_conditions.md#fallout-actor-values
    """
    return FORK_FALLOUT_AV.get(av)


def fallout_run_on(raw: bytes, remap) -> tuple:
    """(is_target, run_on, reference) from the Fallout tail.

    Run On = Target is reported as `is_target` so the caller applies the
    same Say-topic retargeting it gives TES4's run-on-target flag; every
    other Run On passes through with its reference load-order remapped.
    """
    run_on, reference = struct.unpack_from('<II', raw, 20)
    if run_on == _RUN_ON_TARGET:
        return True, 0, 0
    if run_on == _RUN_ON_REFERENCE:
        reference = remap(reference)
    return False, run_on, reference
