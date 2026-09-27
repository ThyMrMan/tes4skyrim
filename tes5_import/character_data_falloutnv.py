"""The character data file for an FO3/FNV plugin: S.P.E.C.I.A.L., skills,
classes, races, perks, traits, reputations and the XP rules' settings.

Same shape as the TES4 file ([character_data](character_data.py)), with
`rules: 'xp'`. Every form is `[owning plugin, local id]`.

See: docs/commentary/tes5_import_character_data.md#fallout
"""

import json
import os

from .base.text_reader import get_float, get_int, get_str

#: The engine's setting defaults, read from each game's GECK.
_EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tes4_export')
ENGINE_SETTINGS = {'falloutnv': os.path.join(_EXPORT_DIR, 'falloutnv_engine_settings.json'),
                   'fallout3': os.path.join(_EXPORT_DIR, 'fallout3_engine_settings.json')}

#: A plugin header version from this one on is New Vegas's (1.34); Fallout 3 writes 0.94.
_NEW_VEGAS_HEDR = 1.3

#: An AVIF's category is its FormID block; its actor value index is the block's first plus the offset.
AV_BLOCKS = ((0x3E8, 7, 5), (0x44C, 20, 12), (0x4B0, 14, 32), (0x514, 5, 0), (0x5DC, 30, 46))

#: The S.P.E.C.I.A.L. block and the skill block, as (first FormID, count).
SPECIAL_BLOCK, SKILL_BLOCK = (0x3E8, 7), (0x4B0, 14)

#: Skill AVIF EditorID -> governing S.P.E.C.I.A.L.; in no record, read from Fallout3.exe (docs: fallout-governing-stats).
GOVERNING = {'AVBarter': 'Charisma', 'AVBigGuns': 'Endurance', 'AVEnergyWeapons': 'Perception',
             'AVExplosives': 'Perception', 'AVLockpick': 'Perception', 'AVMedicine': 'Intelligence',
             'AVMeleeWeapons': 'Strength', 'AVRepair': 'Intelligence', 'AVScience': 'Intelligence',
             'AVSmallGuns': 'Agility', 'AVSneak': 'Agility', 'AVSpeech': 'Charisma',
             'AVUnarmed': 'Endurance'}

#: New Vegas reuses Throwing's actor value for Survival; Fallout 3's cut Throwing keeps Intelligence.
_SURVIVAL = {'falloutnv': 'Endurance', 'fallout3': 'Intelligence'}

#: The skill each game's engine hides, leaving 13: New Vegas's Big Guns, Fallout 3's Throwing.
_CUT_SKILL = {'falloutnv': 'AVBigGuns', 'fallout3': 'AVThrowing'}

#: Skill AVIF EditorID -> the Skyrim skills the converted content exercises with it.
SKYRIM_SKILLS = {'AVBarter': ('Speechcraft',), 'AVSpeech': ('Speechcraft',),
                 'AVLockpick': ('Lockpicking',), 'AVSneak': ('Sneak',), 'AVRepair': ('Smithing',),
                 'AVMeleeWeapons': ('OneHanded', 'TwoHanded'), 'AVSmallGuns': ('Marksman',),
                 'AVEnergyWeapons': ('Marksman',), 'AVBigGuns': ('Marksman',)}

#: The settings the XP rules read by name; every iXPReward*, iXPLevel* and fAVDSkill* setting is kept too.
XP_SETTINGS = (
    'iXPBase', 'iXPBumpBase', 'iMaxCharacterLevel', 'iLevelsPerPerk',
    'iLevelUpSkillPointsBase', 'iLevelUpSkillPointsInterval', 'fAVDTagSkillBonus',
    'fAVDSkillPrimaryBonusMult', 'fAVDSkillLuckBonusMult', 'fBookPerkBonus',
    'iTraitMenuMaxNumTraits', 'fAVDHealthEnduranceMult', 'fAVDHealthEnduranceOffset',
    'fAVDHealthLevelMult', 'fAVDCarryWeightsBase', 'fAVDCarryWeightMult',
    'fAVDActionPointsBase', 'fAVDActionPointsMult', 'fAlignEvilMaxKarma',
    'fAlignGoodMinKarma')
_XP_PREFIXES = ('iXPReward', 'iXPLevel', 'fAVDSkill')

#: The player's NPC_ record, whose class carries the S.P.E.C.I.A.L. a new character starts with.
_PLAYER = 0x000007

#: CLAS and RACE DATA.Flags bit 0: offered at character creation.
_PLAYABLE = 0x1

#: RACE DATA.SkillBoost entries, 255 for an empty one.
_SKILL_BOOSTS, _NO_SKILL = 7, 255


def _form(formid: str, masters: list, plugin: str) -> list:
    """`[owning plugin, local id]` for an export FormID in this plugin's master space."""
    value = int(formid, 16)
    index = value >> 24
    return [masters[index] if index < len(masters) else plugin, value & 0xFFFFFF]


def actor_value_index(formid: int):
    """The actor value an AVIF stands for, from its FormID block, or None outside them."""
    local = formid & 0xFFFFFF
    for first, count, av in AV_BLOCKS:
        if first <= local < first + count:
            return av + local - first
    return None


def game_of(export_dir: str) -> str:
    """'falloutnv' or 'fallout3', from the plugin header's own version."""
    with open(os.path.join(export_dir, '_HEADER.txt'), encoding='utf-8') as handle:
        header = dict(line.rstrip('\n').split('=', 1) for line in handle if '=' in line)
    return 'falloutnv' if float(header.get('HEDR.Version', 0)) >= _NEW_VEGAS_HEDR else 'fallout3'


def _in_block(rec: dict, block: tuple) -> bool:
    """Whether an AVIF's FormID falls in (first, count)."""
    local = int(rec['FormID'], 16) & 0xFFFFFF
    return block[0] <= local < block[0] + block[1]


def _special(avifs: list) -> list:
    """The S.P.E.C.I.A.L. names, in actor value order."""
    rows = sorted((r for r in avifs if _in_block(r, SPECIAL_BLOCK)), key=lambda r: int(r['FormID'], 16))
    return [get_str(r, 'FULL') for r in rows]


def _skills(avifs: list, game: str, masters: list, plugin: str) -> list:
    """Each skill AVIF: its actor value, name, governing stat, the Skyrim skills it maps to, and
    whether the game shows it."""
    rows = []
    for rec in sorted(avifs, key=lambda r: int(r['FormID'], 16)):
        if not _in_block(rec, SKILL_BLOCK):
            continue
        edid = get_str(rec, 'EditorID')
        governing = _SURVIVAL[game] if edid == 'AVThrowing' else GOVERNING.get(edid)
        rows.append({'id': edid, 'name': get_str(rec, 'FULL'), 'av': actor_value_index(int(rec['FormID'], 16)),
                     'form': _form(rec['FormID'], masters, plugin), 'attribute': governing,
                     'skyrim': list(SKYRIM_SKILLS.get(edid, ())), 'playable': edid != _CUT_SKILL[game]})
    return rows


def _classes(records: list, skill_names: dict, special: list, masters: list, plugin: str) -> list:
    """Each CLAS: tag skills, S.P.E.C.I.A.L., playable."""
    rows = []
    for rec in records:
        tags = [skill_names.get(get_int(rec, f'DATA.TagSkill[{i}]', -1)) for i in range(4)]
        rows.append({'id': get_str(rec, 'EditorID'), 'name': get_str(rec, 'FULL'),
                     'form': _form(rec['FormID'], masters, plugin),
                     'tags': [tag for tag in tags if tag],
                     'special': {stat: get_int(rec, f'ATTR.{stat}') for stat in special},
                     'playable': bool(get_int(rec, 'DATA.Flags') & _PLAYABLE)})
    return rows


def _races(records: list, skill_names: dict, masters: list, plugin: str) -> list:
    """Each RACE: its skill bonuses and whether it is playable."""
    rows = []
    for rec in records:
        boosts = ((get_int(rec, f'DATA.SkillBoost[{i}].Skill', _NO_SKILL),
                   get_int(rec, f'DATA.SkillBoost[{i}].Bonus')) for i in range(_SKILL_BOOSTS))
        rows.append({'id': get_str(rec, 'EditorID'), 'name': get_str(rec, 'FULL'),
                     'form': _form(rec['FormID'], masters, plugin),
                     'skills': {skill_names[av]: bonus for av, bonus in boosts if av in skill_names and bonus},
                     'playable': bool(get_int(rec, 'DATA.Flags') & _PLAYABLE)})
    return rows


def _effect(rec: dict, i: int, masters: list, plugin: str) -> dict:
    """One perk effect: kind, rank, priority, what it does, and its condition tabs."""
    pfx = f'Effect[{i}]'
    row = {'type': get_str(rec, f'{pfx}.Type'), 'rank': get_int(rec, f'{pfx}.Rank'),
           'priority': get_int(rec, f'{pfx}.Priority')}
    if rec.get(f'{pfx}.Quest'):
        row.update(quest=_form(rec[f'{pfx}.Quest'], masters, plugin), stage=get_int(rec, f'{pfx}.Stage'))
    if rec.get(f'{pfx}.Ability'):
        row['ability'] = _form(rec[f'{pfx}.Ability'], masters, plugin)
    if rec.get(f'{pfx}.EntryPoint'):
        row.update(entry_point=get_int(rec, f'{pfx}.EntryPoint'), function=get_int(rec, f'{pfx}.Function'),
                   value_type=get_int(rec, f'{pfx}.ValueType'), value=get_str(rec, f'{pfx}.Value'))
    tabs = []
    while f'{pfx}.Tab[{len(tabs)}].RunOn' in rec:
        tab = f'{pfx}.Tab[{len(tabs)}]'
        conditions = []
        while f'{tab}.Condition[{len(conditions)}].Raw' in rec:
            conditions.append(rec[f'{tab}.Condition[{len(conditions)}].Raw'])
        tabs.append({'run_on': get_int(rec, f'{tab}.RunOn'), 'conditions': conditions})
    if tabs:
        row['tabs'] = tabs
    return row


def _perks(records: list, masters: list, plugin: str) -> list:
    """Each PERK: trait or perk, level, ranks, requirements and effects."""
    rows = []
    for rec in records:
        requirements = []
        while f'Condition[{len(requirements)}].Raw' in rec:
            requirements.append(rec[f'Condition[{len(requirements)}].Raw'])
        rows.append({'id': get_str(rec, 'EditorID'), 'name': get_str(rec, 'FULL'),
                     'form': _form(rec['FormID'], masters, plugin),
                     'trait': bool(get_int(rec, 'DATA.Trait')), 'level': get_int(rec, 'DATA.MinLevel'),
                     'ranks': get_int(rec, 'DATA.Ranks', 1), 'playable': bool(get_int(rec, 'DATA.Playable')),
                     'hidden': bool(get_int(rec, 'DATA.Hidden')), 'requirements': requirements,
                     'effects': [_effect(rec, i, masters, plugin) for i in range(get_int(rec, 'EffectCount'))]})
    return rows


def _reputations(records: list, masters: list, plugin: str) -> list:
    """Each REPU: a New Vegas faction reputation and its value."""
    return [{'id': get_str(rec, 'EditorID'), 'name': get_str(rec, 'FULL'),
             'form': _form(rec['FormID'], masters, plugin),
             'value': round(get_float(rec, 'DATA.Value'), 6)} for rec in records]


def _player(npcs: list, masters: list, plugin: str) -> dict:
    """The player record's class as a form, or {} when this plugin does not define the player."""
    for rec in npcs:
        if int(rec['FormID'], 16) & 0xFFFFFF == _PLAYER and rec.get('CNAM.Class'):
            return {'class': _form(rec['CNAM.Class'], masters, plugin)}
    return {}


def _wanted(name: str) -> bool:
    """Whether the XP rules read this setting."""
    return name in XP_SETTINGS or name.startswith(_XP_PREFIXES)


def _settings(records: list, game: str, masterless: bool) -> dict:
    """The XP rules' settings this plugin's GMSTs set, over the engine's when masterless."""
    out = {}
    if masterless:
        with open(ENGINE_SETTINGS[game], encoding='utf-8') as handle:
            out = {k: v for k, v in json.load(handle)['settings'].items() if _wanted(k)}
    for rec in records:
        name = get_str(rec, 'EditorID')
        if _wanted(name):
            value = get_float(rec, 'DATA.Value')
            out[name] = int(value) if name[0] == 'i' else round(value, 6)
    return out


def character_data(by_type: dict, masters: list, plugin: str, game: str,
                   master_export: dict = None) -> dict:
    """The character data document for one FO3/FNV plugin, or {} when it defines none.
    `master_export` supplies the masters' AVIFs, which name a dependent's skills."""
    avifs = by_type.get('AVIF', [])
    known = [*avifs, *(r for r in (master_export or {}).values() if r.get('Signature') == 'AVIF')]
    special = _special(known)
    skills = _skills(avifs, game, masters, plugin)
    skill_names = {row['av']: row['name'] for row in _skills(known, game, masters, plugin)}
    doc = {'skills': skills,
           'classes': _classes(by_type.get('CLAS', []), skill_names, special, masters, plugin),
           'races': _races(by_type.get('RACE', []), skill_names, masters, plugin),
           'perks': _perks(by_type.get('PERK', []), masters, plugin),
           'reputations': _reputations(by_type.get('REPU', []), masters, plugin),
           'settings': _settings(by_type.get('GMST', []), game, not masters),
           'player': _player(by_type.get('NPC_', []), masters, plugin)}
    doc = {key: value for key, value in doc.items() if value}
    if not doc:
        return {}
    if avifs and special:
        doc['attributes'] = special
    if not masters:
        doc['standings'] = [{'name': 'Karma', 'skyrim': None}]
    return {'version': 1, 'plugin': plugin, 'game': game, 'rules': 'xp', **doc}
