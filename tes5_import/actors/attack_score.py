"""Oblivion's combat-action scores: the best attack an actor's flee score has to beat.

Oblivion.exe scores every action a fighting actor could take and runs the
highest; fleeing wins only above all of them. This reproduces the weapon,
natural or unarmed, and spell scores from the actor's record, inventory and
spells under the game settings in effect for the plugin, at full health,
fatigue and weapon condition.

See: docs/commentary/tes5_import_actors.md#attack-score
"""

import math

from ..base.text_reader import get_float, get_formid, get_int, get_str
from ..packages.aliases import master_records
from ..record_types.items import leveled_entries
from .combat_style import game_settings, prefers_ranged

#: Oblivion.exe compiled-in value of every game setting an attack score reads.
_EXE_SETTINGS = {
    'fAIMeleeWeaponMult': 2.0, 'fAIMeleeHandMult': 1.3, 'fAIMagicSpellMult': 3.0,
    'fDamageWeaponMult': 1.0, 'fDamageWeaponConditionBase': 0.0,
    'fDamageWeaponConditionMult': 1.0, 'fDamageSkillBase': 0.2, 'fDamageSkillMult': 1.8,
    'fDamageStrengthBase': 0.5, 'fDamageStrengthMult': 1.0, 'fFatigueBase': 1.25,
    'fActorLuckSkillMult': 0.4, 'iActorLuckSkillBase': -20.0,
    'fHandDamageSkillBase': 0.0, 'fHandDamageSkillMult': 1.0,
    'fHandDamageStrengthBase': 0.0, 'fHandDamageStrengthMult': 0.75,
    'fHandHealthMin': 1.0, 'fHandHealthMax': 20.0,
    'fMagicDurMagBaseCostMult': 0.1, 'fMagicCostScale': 1.25, 'fMagicAreaBaseCostMult': 0.15,
    'fMagicRangeTargetCostMult': 1.5, 'fMagicCasterSkillCostBase': 0.1,
    'fMagicCasterSkillCostMult': 1.2,
}

#: Record types an attack score reads, indexed by FormID.
_SOURCE_SIGS = ('WEAP', 'ENCH', 'SPEL', 'LVLI', 'LVSP', 'RACE', 'BOOK')

#: Leveled-list signatures, resolved to their leaves.
_LEVELED_SIGS = frozenset({'LVLI', 'LVSP'})

#: TES4 skill actor value -> its NPC_ DATA field.
_SKILL_FIELDS = {
    14: 'Blade', 16: 'Blunt', 17: 'HandToHand', 20: 'Alteration', 21: 'Conjuration',
    22: 'Destruction', 23: 'Illusion', 24: 'Mysticism', 25: 'Restoration', 28: 'Marksman',
}

#: Weapon DATA.Type -> skill actor value (Oblivion.exe table 0xb086a0): Blade, Blunt (staffs too), Marksman.
_WEAPON_SKILL = (14, 14, 16, 16, 16, 28)

#: Hand to Hand's actor value, and the first magic school's skill (Alteration = 20 + school 0).
_HAND_TO_HAND, _FIRST_SCHOOL_SKILL = 17, 20

#: ACBS flags: CREA Weapon & Shield, and PC Level Offset on both actor types.
_WEAPON_AND_SHIELD, _PC_LEVEL_OFFSET = 0x4, 0x80

#: LVLF flag: pick from every level at or below the actor's, not only the highest.
_ALL_LEVELS = 0x1

#: TES4 MGEF flags: Hostile, No Duration, No Magnitude, No Area, and summon/bound (Use Weapon/Armor/Creature).
_HOSTILE, _NO_DURATION, _NO_MAGNITUDE, _NO_AREA, _SUMMON = 0x1, 0x80, 0x100, 0x200, 0x70000

#: SPIT.Type Spell, and the Manual Spell Cost / No Autocalc Cost flag bit.
_SPELL, _MANUAL_COST = 0, 0x1

#: Guard against a cyclic leveled list.
_MAX_DEPTH = 8

#: Run state: effective settings, {FormID: record} of _SOURCE_SIGS, {MGEF code: record}.
_STATE = {'settings': dict(_EXE_SETTINGS), 'records': {}, 'effects': {}}


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_attack_sources(by_type: dict, master_export: dict) -> None:
    """Read the plugin's effective game settings and index what an attack score reads."""
    _STATE['settings'] = game_settings(by_type, master_export, _EXE_SETTINGS)[0]
    records = dict(master_records(master_export, *_SOURCE_SIGS))
    records.update((get_formid(r, 'FormID'), r) for sig in _SOURCE_SIGS for r in by_type.get(sig, []))
    effects = {get_str(r, 'EditorID'): r for _, r in master_records(master_export, 'MGEF')}
    effects.update((get_str(r, 'EditorID'), r) for r in by_type.get('MGEF', []))
    _STATE.update(records=records, effects=effects)


# ---------------------------------------------------------------------------
# The actor's stats
# ---------------------------------------------------------------------------

def _is_creature(rec: dict) -> bool:
    """True for a CREA record."""
    return rec.get('Signature') == 'CREA'


def _skill(rec: dict, av: int) -> int:
    """The skill actor value `av`; a creature answers from its Combat/Magic/Stealth skill (0x6253c0)."""
    if not _is_creature(rec):
        return get_int(rec, f'DATA.{_SKILL_FIELDS[av]}')
    group = 'Combat' if 12 <= av <= 18 or av == 28 else ('Magic' if 19 <= av <= 25 else 'Stealth')
    return get_int(rec, f'DATA.{group}Skill')


def _effective_skill(rec: dict, av: int) -> float:
    """Skill plus the Luck term, clamped to 0-100 (0x547b90)."""
    s = _STATE['settings']
    value = (_skill(rec, av) + get_int(rec, 'DATA.Luck') * s['fActorLuckSkillMult']
             + s['iActorLuckSkillBase'])
    return min(100.0, max(0.0, value))


def _strength(rec: dict) -> int:
    """Strength, capped at 100 as the damage formulas cap it."""
    return min(100, get_int(rec, 'DATA.Strength'))


def _actor_level(rec: dict) -> int:
    """The level a level-1 player meets the actor at: fixed, or 1 + offset within its calc range."""
    level = get_int(rec, 'ACBS.Level')
    if not get_int(rec, 'ACBS.Flags') & _PC_LEVEL_OFFSET:
        return max(1, level)
    level = max(1, 1 + level, get_int(rec, 'ACBS.CalcMin'))
    top = get_int(rec, 'ACBS.CalcMax')
    return min(level, top) if top > 0 else level


# ---------------------------------------------------------------------------
# What the actor carries and knows
# ---------------------------------------------------------------------------

def _leaves(fid: int, level: int, depth: int = 0) -> list:
    """The records `fid` gives an actor of `level`: itself, or a leveled list's eligible leaves."""
    rec = _STATE['records'].get(fid)
    if rec is None or depth > _MAX_DEPTH:
        return []
    if rec.get('Signature') not in _LEVELED_SIGS:
        return [rec]
    entries = [(lvl, sub) for lvl, sub, _ in leveled_entries(rec) if lvl <= level]
    if entries and not get_int(rec, 'LVLF.Flags') & _ALL_LEVELS:
        top = max(lvl for lvl, _ in entries)
        entries = [(lvl, sub) for lvl, sub in entries if lvl == top]
    return [leaf for _, sub in entries for leaf in _leaves(sub, level, depth + 1)]


def _listed(rec: dict, count_key: str, item_key: str, sig: str, level: int) -> list:
    """The `sig` records a counted FormID list names, at `level`."""
    fids = (get_formid(rec, item_key.format(i)) for i in range(get_int(rec, count_key)))
    return [leaf for fid in fids for leaf in _leaves(fid, level) if leaf.get('Signature') == sig]


def _carried(rec: dict, sig: str) -> list:
    """The `sig` records the actor carries."""
    return _listed(rec, 'ItemCount', 'Item[{}].FormID', sig, _actor_level(rec))


# ---------------------------------------------------------------------------
# Magic costs
# ---------------------------------------------------------------------------

def _effects(item: dict) -> list:
    """(MGEF record, magnitude, area, duration, range) per effect of a SPEL or ENCH."""
    out = []
    for i in range(get_int(item, 'EffectCount')):
        mgef = _STATE['effects'].get(get_str(item, f'Effect[{i}].EFID'))
        if mgef is not None:
            out.append((mgef, get_int(item, f'Effect[{i}].Magnitude'),
                        get_int(item, f'Effect[{i}].Area'), get_int(item, f'Effect[{i}].Duration'),
                        get_str(item, f'Effect[{i}].Type')))
    return out


def _effect_cost(effect: tuple, caster_factor: float = 1.0) -> float:
    """One effect's cost: max(1, floor(base cost x the caster's factor)) (0x413890, 0x548b50)."""
    s = _STATE['settings']
    mgef, magnitude, area, duration, rng = effect
    flags = get_int(mgef, 'DATA.Flags')
    magnitude = 0 if flags & _NO_MAGNITUDE else magnitude
    duration = 0 if flags & _NO_DURATION else duration
    area = 0 if flags & _NO_AREA or rng == 'Self' else area
    cost = (s['fMagicDurMagBaseCostMult'] * get_float(mgef, 'DATA.BaseCost') * max(1, duration)
            * (magnitude ** s['fMagicCostScale'] if magnitude > 0 else 1.0)
            * max(1.0, area * s['fMagicAreaBaseCostMult'])
            * (s['fMagicRangeTargetCostMult'] if rng == 'Target' else 1.0))
    return max(1.0, math.floor(cost * caster_factor))


def _caster_factor(rec: dict, mgef: dict) -> float:
    """The caster's cost factor for the school of `mgef` (0x548c00)."""
    s = _STATE['settings']
    skill = _effective_skill(rec, _FIRST_SCHOOL_SKILL + get_int(mgef, 'DATA.School'))
    return s['fMagicCasterSkillCostBase'] + s['fMagicCasterSkillCostMult'] * (1.0 - skill / 100.0)


def _spell_cost(rec: dict, spell: dict) -> float:
    """What the actor pays for `spell`: manual cost by its costliest school, else each effect's (0x41d320)."""
    effects = _effects(spell)
    if not effects:
        return float(get_int(spell, 'SPIT.Cost'))
    if get_int(spell, 'SPIT.Flags') & _MANUAL_COST:
        costliest = max(effects, key=_effect_cost)[0]
        return get_int(spell, 'SPIT.Cost') * _caster_factor(rec, costliest)
    return sum(_effect_cost(e, _caster_factor(rec, e[0])) for e in effects)


def _enchantment_cost(ench: dict) -> float:
    """An enchantment's cost: ENIT cost when No Autocalc, else its effects' (0x4190a0)."""
    if get_int(ench, 'ENIT.Flags') & _MANUAL_COST:
        return float(get_int(ench, 'ENIT.Cost'))
    return sum(_effect_cost(e) for e in _effects(ench))


def _is_hostile(item: dict) -> bool:
    """True when any of the item's effects is Hostile (0x4149f0)."""
    return any(get_int(e[0], 'DATA.Flags') & _HOSTILE for e in _effects(item))


def _spell_kind(item: dict) -> str:
    """'target' or 'touch' for a hostile, non-summoning spell by its ranges; '' otherwise (0x616db0)."""
    effects = _effects(item)
    if not _is_hostile(item) or any(get_int(e[0], 'DATA.Flags') & _SUMMON for e in effects):
        return ''
    ranges = {e[4] for e in effects}
    return 'target' if 'Target' in ranges else ('touch' if 'Touch' in ranges else '')


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

def _weapon_skill(weap: dict) -> int:
    """The skill actor value a weapon swings with."""
    kind = get_int(weap, 'DATA.Type')
    return _WEAPON_SKILL[kind] if 0 <= kind < len(_WEAPON_SKILL) else _WEAPON_SKILL[0]


def _weapon_score(rec: dict, weap: dict) -> float:
    """fAIMeleeWeaponMult x damage plus fAIMagicSpellMult x a hostile enchantment's cost (0x547140)."""
    s = _STATE['settings']
    damage = (s['fDamageWeaponMult'] * get_int(weap, 'DATA.Damage')
              * (s['fDamageWeaponConditionBase'] + s['fDamageWeaponConditionMult'])
              * (s['fDamageSkillBase'] + s['fDamageSkillMult'] * _effective_skill(rec, _weapon_skill(weap)) / 100.0)
              * (s['fDamageStrengthBase'] + s['fDamageStrengthMult'] * _strength(rec) / 100.0)
              * s['fFatigueBase'])
    score = s['fAIMeleeWeaponMult'] * damage
    ench = _STATE['records'].get(get_formid(weap, 'ENAM'))
    if ench is not None and _is_hostile(ench):
        score += s['fAIMagicSpellMult'] * _enchantment_cost(ench)
    return score


def _unarmed_score(rec: dict) -> float:
    """fAIMeleeHandMult x a creature's attack damage or an NPC's hand-to-hand damage (0x624f90, 0x60e270)."""
    s = _STATE['settings']
    if _is_creature(rec):
        return s['fAIMeleeHandMult'] * int(get_int(rec, 'DATA.AttackDamage') * s['fFatigueBase'])
    term = ((s['fHandDamageStrengthBase'] + s['fHandDamageStrengthMult'] * _strength(rec) / 100.0)
            * s['fFatigueBase']
            * (s['fHandDamageSkillBase']
               + s['fHandDamageSkillMult'] * _effective_skill(rec, _HAND_TO_HAND) / 100.0))
    damage = s['fHandHealthMin'] + (s['fHandHealthMax'] - s['fHandHealthMin']) * min(1.0, term)
    return s['fAIMeleeHandMult'] * int(damage)


def _spell_candidates(rec: dict) -> list:
    """(item, cost) for the actor's own and race Spells and its carried scrolls (0x61b1b0)."""
    level = _actor_level(rec)
    spells = _listed(rec, 'SpellCount', 'Spell[{}]', 'SPEL', level)
    race = None if _is_creature(rec) else _STATE['records'].get(get_formid(rec, 'RNAM.Race'))
    if race is not None:
        spells += _listed(race, 'SpellCount', 'Spell[{}]', 'SPEL', level)
    out = [(sp, _spell_cost(rec, sp)) for sp in spells if get_int(sp, 'SPIT.Type') == _SPELL]
    scrolls = (_STATE['records'].get(get_formid(b, 'ENAM')) for b in _carried(rec, 'BOOK'))
    return out + [(e, _enchantment_cost(e)) for e in scrolls if e is not None]


def _spell_scores(rec: dict, armed: bool) -> list:
    """fAIMagicSpellMult x the cheapest touch and ranged spell the actor would weigh (0x616980)."""
    costs = {'touch': [], 'target': []}
    for item, cost in _spell_candidates(rec):
        kind = _spell_kind(item)
        if kind:
            costs[kind].append(cost)
    used = {'touch': not armed, 'target': not armed or prefers_ranged(rec)}
    mult = _STATE['settings']['fAIMagicSpellMult']
    return [mult * min(c) for kind, c in costs.items() if c and used[kind]]


def attack_score(rec: dict) -> float:
    """The actor's best attack score at full health, fatigue and condition; 0 when it has none.

    See: docs/commentary/tes5_import_actors.md#attack-score
    """
    armed = not _is_creature(rec) or get_int(rec, 'ACBS.Flags') & _WEAPON_AND_SHIELD
    weapons = _carried(rec, 'WEAP') if armed else []
    weapon = max(weapons, key=lambda w: _weapon_score(rec, w), default=None)
    scores = _spell_scores(rec, weapon is not None)
    if weapon is not None:
        scores.append(_weapon_score(rec, weapon))
    if weapon is None or (not _is_creature(rec)
                          and _skill(rec, _HAND_TO_HAND) > _skill(rec, _weapon_skill(weapon))):
        scores.append(_unarmed_score(rec))
    return max(scores, default=0.0)
