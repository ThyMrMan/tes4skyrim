"""TES4 combat styles as Skyrim CSTY records.

Oblivion decides each melee and maneuver move by percentage rolls (Attack %,
Block %, Dodge %, Left/Right %); Skyrim reads per-style multipliers that
interpolate between a Min and a Max game setting (SkyrimSE 1.6.1170
0x1408dc070: min + (max - min) * mult). Each Oblivion probability is inverted
onto the multiplier that yields the same chance. An actor with no style fights
by Oblivion's iAIDefault/fAIDefault game settings, converted the same way into
one generated default style.

See: docs/commentary/tes5_import_actors.md#combat-styles
"""

import struct

from ..base.text_reader import get_float, get_formid, get_int, get_str
from ..base.writer import PluginWriter, pack_record, pack_string_subrecord, pack_subrecord
from ..packages.aliases import master_records

#: EditorID of the generated style for actors without an authored one.
DEFAULT_STYLE_EDID = 'TES4DefaultCombatStyle'

#: Oblivion.exe compiled-in value of every game setting the conversion reads.
_EXE_SETTINGS = {
    'iAIDefaultDodgeChance': 75, 'iAIDefaultDodgeLeftRightChance': 50,
    'iAIDefaultBlockChance': 30, 'iAIDefaultAttackChance': 40,
    'fAIDefaultAttackDuringRecoilStaggerBonus': 5.0, 'iAIDefaultPowerAttackChance': 25,
    'fAIDefaultPowerAttackRecoilStaggerBonus': 5.0, 'iAIDefaultFleeDisabled': 0,
    'iAIDefaultPrefersRangedAttacks': 0, 'fAIDefaultDodgeFatigueBase': 0.0,
    'fAIDefaultDodgeNoAttackMult': 0.75, 'fAIDefaultDodgeBackNoAttackMult': 0.7,
    'fAIDefaultDodgeForwardNotAttackingMult': 0.5, 'fAIDefaultBlockSkillBase': 0.0,
    'fAIDefaultBlockDuringAttackMult': 2.0, 'fAIDefaultAttackSkillBase': 0.0,
    'fAIDefaultAttackNoAttackMult': 1.0,
}

#: CSTD key -> the game setting an actor without a style uses in its place.
_CSTD_SETTINGS = {
    'DodgeChance': 'iAIDefaultDodgeChance', 'LeftRightChance': 'iAIDefaultDodgeLeftRightChance',
    'BlockChance': 'iAIDefaultBlockChance', 'AttackChance': 'iAIDefaultAttackChance',
    'RecoilStaggerBonusToAttack': 'fAIDefaultAttackDuringRecoilStaggerBonus',
    'PowerAttackChance': 'iAIDefaultPowerAttackChance',
    'RecoilStaggerBonusToPowerAttack': 'fAIDefaultPowerAttackRecoilStaggerBonus',
}

#: CSAD key -> the game setting used when the style is not Advanced.
_CSAD_SETTINGS = {
    'DodgeFatigueModBase': 'fAIDefaultDodgeFatigueBase',
    'DodgeNotUnderAttackMult': 'fAIDefaultDodgeNoAttackMult',
    'DodgeBackNotUnderAttackMult': 'fAIDefaultDodgeBackNoAttackMult',
    'DodgeForwardNotAttackingMult': 'fAIDefaultDodgeForwardNotAttackingMult',
    'BlockSkillModifierBase': 'fAIDefaultBlockSkillBase',
    'BlockWhileUnderAttackMult': 'fAIDefaultBlockDuringAttackMult',
    'AttackSkillModifierBase': 'fAIDefaultAttackSkillBase',
    'AttackNotUnderAttackMult': 'fAIDefaultAttackNoAttackMult',
}

#: TES4 CSTD flag bits.
_ADVANCED, _FLEEING_DISABLED, _PREFERS_RANGED = 0x01, 0x20, 0x40

#: SkyrimSE 1.6.1170 defaults of the Min/Max settings each multiplier interpolates.
_ATTACK_CHANCE = (0.05, 1.0)
_BLOCK_CHANCE = (0.0, 1.0)
_CIRCLE_CHANCE = (0.0, 0.75)
_FALLBACK_CHANCE = (0.0, 0.5)

#: CSGD equipment mults (melee, magic, ranged, shout, unarmed, staff) with no preference.
_EQUIP_NEUTRAL = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

#: Prefers Ranged: vanilla csHumanMissile's ranged and melee mults, ranged applied to spells too.
_EQUIP_RANGED = (0.83, 3.2, 3.2, 1.0, 0.83, 3.2)

#: TESCombatStyle constructor values for fields Oblivion has no counterpart for.
_GROUP_OFFENSIVE, _AVOID_THREAT, _POWER_ATTACK_BLOCKING, _SPECIAL_ATTACK = 1.0, 0.2, 1.0, 0.1
_FLANK_DISTANCE, _STALK_TIME = 0.2, 0.2
_FLIGHT = (0.5, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.75)

#: CSTY DATA flag: Dueling close-range behavior (circle and fall back, no flanking).
_DUELING = 0x1

#: Run state: styles converted?, game settings, {style FormID: CSTD flags}, default style.
_STATE = {'active': False, 'settings': dict(_EXE_SETTINGS), 'styles': {}, 'default': 0}


def _clamp01(value: float) -> float:
    """`value` limited to 0..1."""
    return min(1.0, max(0.0, value))


def _mult(chance: float, span: tuple) -> float:
    """The multiplier that makes Skyrim's min + (max - min) * mult equal `chance`."""
    lo, hi = span
    return (chance - lo) / (hi - lo)


def _style_values(rec: dict) -> dict:
    """The Oblivion fields a style converts from, game settings filling what it lacks.

    `rec` is a CSTY export record, or {} for the no-style default.
    """
    settings = _STATE['settings']
    flags = get_int(rec, 'CSTD.Flags') if rec else (
        _FLEEING_DISABLED * bool(settings['iAIDefaultFleeDisabled'])
        | _PREFERS_RANGED * bool(settings['iAIDefaultPrefersRangedAttacks']))
    out = {key: get_float(rec, f'CSTD.{key}', settings[gmst]) if rec else settings[gmst]
           for key, gmst in _CSTD_SETTINGS.items()}
    advanced = bool(rec) and flags & _ADVANCED and any(k.startswith('CSAD.') for k in rec)
    out.update({key: get_float(rec, f'CSAD.{key}', settings[gmst]) if advanced else settings[gmst]
                for key, gmst in _CSAD_SETTINGS.items()})
    out['Flags'] = flags
    return out


def _probabilities(v: dict) -> dict:
    """Oblivion's per-decision chances of attacking, blocking, circling and backing off."""
    attack = _clamp01((v['AttackChance'] + v['AttackSkillModifierBase']) / 100.0
                      * v['AttackNotUnderAttackMult'])
    staggered = _clamp01((v['AttackChance'] + v['AttackSkillModifierBase']
                          + v['RecoilStaggerBonusToAttack']) / 100.0 * v['AttackNotUnderAttackMult'])
    dodge = _clamp01((v['DodgeChance'] + v['DodgeFatigueModBase']) / 100.0
                     * v['DodgeNotUnderAttackMult'])
    side = v['LeftRightChance'] / 100.0
    back, forward = v['DodgeBackNotUnderAttackMult'], v['DodgeForwardNotAttackingMult']
    back_share = back / (back + forward) if back + forward > 0 else 0.5
    power = v['PowerAttackChance']
    return {
        'attack': attack,
        'staggered': staggered / attack if attack > 0 else 1.0,
        'power_staggered': (power + v['RecoilStaggerBonusToPowerAttack']) / power if power > 0 else 1.0,
        'block': _clamp01((v['BlockChance'] + v['BlockSkillModifierBase']) / 100.0
                          * v['BlockWhileUnderAttackMult']),
        'circle': dodge * side,
        'fallback': dodge * (1.0 - side) * back_share,
    }


def _csty_subrecords(v: dict) -> bytes:
    """CSGD CSME CSCR CSLR CSFL DATA for one style's Oblivion values."""
    p = _probabilities(v)
    equip = _EQUIP_RANGED if v['Flags'] & _PREFERS_RANGED else _EQUIP_NEUTRAL
    circle = _mult(p['circle'], _CIRCLE_CHANCE)
    subs = pack_subrecord('CSGD', struct.pack(
        '<10f', max(0.0, _mult(p['attack'], _ATTACK_CHANCE)), _mult(p['block'], _BLOCK_CHANCE),
        _GROUP_OFFENSIVE, *equip, _AVOID_THREAT))
    subs += pack_subrecord('CSME', struct.pack(
        '<8f', p['staggered'], p['power_staggered'], _POWER_ATTACK_BLOCKING,
        0.0, 0.0, 0.0, 0.0, _SPECIAL_ATTACK))
    subs += pack_subrecord('CSCR', struct.pack(
        '<4f', circle, _mult(p['fallback'], _FALLBACK_CHANCE), _FLANK_DISTANCE, _STALK_TIME))
    subs += pack_subrecord('CSLR', struct.pack('<f', circle))
    subs += pack_subrecord('CSFL', struct.pack('<8f', *_FLIGHT))
    return subs + pack_subrecord('DATA', struct.pack('<I', _DUELING))


def convert_CSTY(rec: dict) -> bytes:
    """A TES4 CSTY as a Skyrim CSTY; b'' for a source whose styles are not converted."""
    if not _STATE['active']:
        return b''
    subs = pack_string_subrecord('EDID', get_str(rec, 'EditorID'))
    subs += _csty_subrecords(_style_values(rec))
    return pack_record('CSTY', get_formid(rec, 'FormID'), 0, subs)


def game_settings(by_type: dict, master_export: dict, defaults: dict) -> tuple:
    """(effective settings, whether this plugin authors any): `defaults`, then masters, then own."""
    settings = dict(defaults)
    own = False
    sources = [(r, False) for _, r in master_records(master_export, 'GMST')]
    sources += [(r, True) for r in by_type.get('GMST', [])]
    for rec, is_own in sources:
        name = get_str(rec, 'EditorID')
        if name in settings:
            settings[name] = get_float(rec, 'DATA.Value', settings[name])
            own = own or is_own
    return settings, own


def _index_styles(by_type: dict, master_export: dict) -> dict:
    """{style FormID: CSTD flags} for the masters' styles and this plugin's own."""
    recs = list(master_records(master_export, 'CSTY'))
    recs += [(get_formid(r, 'FormID'), r) for r in by_type.get('CSTY', [])]
    return {fid: get_int(r, 'CSTD.Flags') for fid, r in recs}


def create_combat_styles(writer: PluginWriter, by_type: dict, master_export: dict,
                         master_index=None, wanted: bool = True) -> int:
    """Index the convertible styles and write the no-style default; returns its FormID.

    The default is adopted from a master that has it, and rewritten as an override
    only when this plugin authors one of the game settings it is built from.
    """
    _STATE.update(active=wanted, styles={}, default=0, settings=dict(_EXE_SETTINGS))
    if not wanted:
        return 0
    _STATE['settings'], own_settings = game_settings(by_type, master_export, _EXE_SETTINGS)
    _STATE['styles'] = _index_styles(by_type, master_export)
    fid = master_index.find_by_edid(b'CSTY', DEFAULT_STYLE_EDID) if master_index is not None else 0
    if not fid or own_settings:
        fid = fid or writer.derive_formid('CSTY', DEFAULT_STYLE_EDID)
        subs = pack_string_subrecord('EDID', DEFAULT_STYLE_EDID) + _csty_subrecords(_style_values({}))
        writer.add_record('CSTY', pack_record('CSTY', fid, 0, subs))
    _STATE['default'] = fid
    _STATE['styles'][fid] = _style_values({})['Flags']
    return fid


def actor_combat_style(rec: dict) -> int:
    """The actor's converted CSTY, else the default; 0 when styles are not converted."""
    fid = get_formid(rec, 'ZNAM.CombatStyle')
    return fid if fid in _STATE['styles'] else _STATE['default']


def fleeing_disabled(rec: dict) -> bool:
    """True when the actor's combat style has Oblivion's Fleeing Disabled flag."""
    return bool(_STATE['styles'].get(actor_combat_style(rec), 0) & _FLEEING_DISABLED)


def prefers_ranged(rec: dict) -> bool:
    """True when the actor's combat style has Oblivion's Prefers Ranged flag."""
    return bool(_STATE['styles'].get(actor_combat_style(rec), 0) & _PREFERS_RANGED)
