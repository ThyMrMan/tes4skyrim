"""FO3/FNV package types Oblivion lacks: Patrol, Guard, Dialogue and Use Weapon.

FO3/FNV number its packages as Oblivion does up to 10, then add Sandbox 12,
Patrol 13, Guard 14, Dialogue 15 and Use Weapon 16. Each has a vanilla Skyrim
template doing the same thing; before these handlers every one of them
sandboxed at its location. Sandbox keeps the converter's own fallback.

See: docs/commentary/tes5_import_package.md#fallout-package-types
"""

import struct

from ..base.text_reader import PLAYER_REF_FID, get_formid, get_int
from .templates import GUARD_POST, PATROL, SAY, USE_WEAPON, Inputs

FNV_PATROL, FNV_GUARD, FNV_DIALOGUE, FNV_USE_WEAPON = 13, 14, 15, 16

#: PLDT type 0, "near reference": a patrol that names its first marker.
_NEAR_REFERENCE = 0

#: PTDA type 3, "linked reference": the actor's own XLKR, a patrol's start otherwise.
_LINKED_REF_TARGET = (3, 0, 0)

#: The TES4-lineage GREETING and HELLO topics, opened through the owning quest's own greeting instead.
_SHARED_TOPICS = frozenset({0xC8, 0xD2})

#: PKW3 flag bits (xEdit wbDefinitionsFNV): Always Hit, Do No Damage, Crouch To Reload, Hold Fire When Blocked.
_ALWAYS_HIT, _NO_DAMAGE, _CROUCH, _HOLD_FIRE = 1 << 0, 1 << 8, 1 << 16, 1 << 24

#: PKW3 FireRate 1 = Volley Fire; FireCount 0 = Number of Bursts (1 = Repeat Fire).
_VOLLEY, _NUMBER_OF_BURSTS = 1, 0


def _conv():
    """The converter, imported late: it imports this module for its handlers."""
    from . import converter
    return converter


def _patrol_start(p) -> tuple:
    """(PTDA, start at nearest) for a patrol: its named marker, else its linked ref."""
    ref = get_formid(p.rec, 'PLDT.Location')
    if get_int(p.rec, 'PLDT.Type', -1) != _NEAR_REFERENCE or not ref:
        return _LINKED_REF_TARGET, 1
    alias = p.ctx.alias_for(p.pack_fid, ref)
    return (_conv().build_alias_target(alias) if alias is not None
            else _conv().build_target(0, ref)), 0


def pick_patrol(p) -> Inputs:
    """Patrol: walk the marker chain (XLKR) from the package's start marker."""
    start, nearest = _patrol_start(p)
    i = Inputs(PATROL)
    i.set('target', start)
    i.set('start_at_nearest', nearest)
    i.set('repeatable', get_int(p.rec, 'PKPT.Repeatable', 1))
    if p.radius > 0:
        i.set('radius', float(p.radius))
    return i


def pick_guard(p) -> Inputs:
    """Guard: wait at the package location, never leaving its radius (500 when unset)."""
    ltype, value, radius = struct.unpack('<iIi', p.loc)
    i = Inputs(GUARD_POST)
    i.set('wait_location', p.loc)
    i.set('restricted_area', (ltype, value, radius or 500))
    return i


def dialogue_topic(rec: dict):
    """A Dialogue package's topic; 0 opens the quest's own greeting."""
    topic = get_formid(rec, 'PKDD.Topic')
    return 0 if (topic & 0xFFFFFF) in _SHARED_TOPICS else topic


def is_player_conversation(rec: dict) -> bool:
    """A Dialogue package that opens a conversation with the player: a force greet."""
    return (get_int(rec, 'PKDT.Type', -1) == FNV_DIALOGUE
            and rec.get('PKDD.Type') != 'SayTo'
            and get_formid(rec, 'PTDT.Target') == PLAYER_REF_FID)


def pick_dialogue(p) -> Inputs:
    """Dialogue: a force greet on the player, else Say the topic to the target."""
    if is_player_conversation(p.rec):
        return _conv().force_greet_inputs(dialogue_topic(p.rec),
                                       get_int(p.rec, 'PTDT.Count', 0))
    i = Inputs(SAY)
    i.set('topic', dialogue_topic(p.rec) or (1, struct.unpack('<I', b'HELO')[0]))
    i.set('target', p.tgt)
    if p.rec.get('PLDT.Type'):
        i.set('location', p.loc)
    return i


def _attack_target(p) -> bytes:
    """The PTDA of what a Use Weapon package shoots at: its second target (PTD2)."""
    second = {k: v for k, v in p.rec.items() if not k.startswith('PTDT.')}
    second.update({k.replace('PTD2.', 'PTDT.'): v
                   for k, v in p.rec.items() if k.startswith('PTD2.')})
    return _conv().resolve_target(second, p.ctx, p.pack_fid)


def pick_use_weapon(p) -> Inputs:
    """Use Weapon: stand at the location and shoot the second target as PKW3 sets."""
    flags = get_int(p.rec, 'PKW3.Flags', 0)
    target = _attack_target(p)
    i = Inputs(USE_WEAPON)
    i.set('location', p.loc)
    i.set('target', target)
    i.set('trigger_ref', target)
    if get_int(p.rec, 'PTDT.Type', -1) == 1:
        i.set('weapon_type', p.tgt)
    i.set('always_hit', int(bool(flags & _ALWAYS_HIT)))
    i.set('do_no_damage', int(bool(flags & _NO_DAMAGE)))
    i.set('crouch_to_reload', int(bool(flags & _CROUCH)))
    i.set('hold_when_blocked', int(bool(flags & _HOLD_FIRE)))
    _set_bursts(i, p.rec)
    return i


def _set_bursts(i: Inputs, rec: dict) -> None:
    """Carry PKW3's burst count and volley pauses onto the barrage inputs."""
    if get_int(rec, 'PKW3.FireCount', 1) == _NUMBER_OF_BURSTS:
        i.set('never_end', 0)
        i.set('end_after_barrages', get_int(rec, 'PKW3.Bursts', 0))
    if get_int(rec, 'PKW3.FireRate', 0) == _VOLLEY:
        i.set('pause_between', 1)
        i.set('min_pause', float(rec.get('PKW3.PauseMin') or 0.0))
        i.set('max_pause', float(rec.get('PKW3.PauseMax') or 0.0))
        i.set('min_attacks', get_int(rec, 'PKW3.ShotsMin', 0))
        i.set('max_attacks', get_int(rec, 'PKW3.ShotsMax', 0))


#: FO3/FNV PKDT.Type -> handler, merged into the converter's own table.
FALLOUT_PICK_BY_TYPE = {FNV_PATROL: pick_patrol, FNV_GUARD: pick_guard,
                        FNV_DIALOGUE: pick_dialogue, FNV_USE_WEAPON: pick_use_weapon}
