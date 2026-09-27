"""The character data file: a TES4 plugin's skills, leveling settings,
classes, races and birthsigns, as `SKSE/Plugins/TESRuntime/<plugin>.character.json`.

Every form is `[owning plugin, local id]`, so a plugin that overrides a class
or adds a birthsign extends its master's data in load order. A masterless
plugin also carries the engine's attributes, standings and leveling defaults
under its own GMSTs. FO3/FNV and TES3 sources write none yet.

See: docs/commentary/tes5_import_character_data.md#the-character-data-file
"""

import json
import os

from core.plugin_masters import masters_from_export_header

from .base.constants import (TES4_ATTRIBUTE_NAMES, TES4_AV_NAMES,
                             TES4_SKILL_AV_BASE)
from .base.text_reader import get_float, get_int, get_str
from .dialogue.morrowind_sidecar import is_tes3_export
from .record_types.crime import SIDECAR_DIR
from .record_types.world_falloutnv import is_fallout_source

#: Schema version; the runtime rejects files it does not understand.
VERSION = 1

#: Oblivion.exe's own tables, with every setting's engine default under `settings`.
ENGINE_TABLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'tes4_export', 'oblivion_engine_tables.json')

#: The settings the skill-use rules read.
LEVELING_SETTINGS = (
    'iLevelUpSkillCount', *(f'iLevelUp{n:02d}Mult' for n in range(1, 11)),
    'fSkillUseExp', 'fSkillUseFactor', 'fSkillUseMajorMult',
    'fSkillUseMinorMult', 'fSkillUseSpecMult', 'fPCBaseHealthMult',
    'fPCBaseMagickaMult', 'iTrainingSkills')

#: CLAS and SKIL DATA.Specialization.
SPECIALIZATIONS = ('Combat', 'Magic', 'Stealth')

#: TES4 skill -> the Skyrim skills whose increases can be credited to it; absent means none.
SKYRIM_SKILLS = {
    'Armorer': ('Smithing',), 'Blade': ('OneHanded', 'TwoHanded'),
    'Block': ('Block',), 'Blunt': ('OneHanded', 'TwoHanded'),
    'HeavyArmor': ('HeavyArmor',), 'Alchemy': ('Alchemy',),
    'Alteration': ('Alteration',), 'Conjuration': ('Conjuration',),
    'Destruction': ('Destruction',), 'Illusion': ('Illusion',),
    'Mysticism': ('Alteration', 'Conjuration'), 'Restoration': ('Restoration',),
    'LightArmor': ('LightArmor',), 'Marksman': ('Marksman',),
    'Mercantile': ('Speechcraft',), 'Security': ('Lockpicking',),
    'Sneak': ('Sneak',), 'Speechcraft': ('Speechcraft',),
}

#: TES4 standings, each with the Skyrim actor value that already carries it.
STANDINGS = ({'name': 'Fame', 'skyrim': 'Fame'},
             {'name': 'Infamy', 'skyrim': 'Infamy'})

#: CLAS and RACE DATA.Flags bit 0: offered at character creation.
_PLAYABLE = 0x1

#: A class names seven major skills; a race boosts up to seven.
_MAJOR_SKILLS = _SKILL_BOOSTS = 7


def _form(formid: str, masters: list, plugin: str) -> list:
    """`[owning plugin, local id]` for an export FormID in this plugin's master space."""
    value = int(formid, 16)
    index = value >> 24
    return [masters[index] if index < len(masters) else plugin, value & 0xFFFFFF]


def _spells(rec: dict, masters: list, plugin: str) -> list:
    """Each `Spell[i]` a race or birthsign grants, as a form."""
    return [_form(rec[f'Spell[{i}]'], masters, plugin)
            for i in range(get_int(rec, 'SpellCount')) if rec.get(f'Spell[{i}]')]


def _specialization(rec: dict):
    """A CLAS or SKIL record's specialization name, or None when out of range."""
    index = get_int(rec, 'DATA.Specialization', -1)
    return SPECIALIZATIONS[index] if 0 <= index < len(SPECIALIZATIONS) else None


def _skill_name(av: int):
    """A TES4 skill actor value's name, or None outside 12-32."""
    return TES4_AV_NAMES.get(av) if av >= TES4_SKILL_AV_BASE else None


def _skills(records: list, masters: list, plugin: str) -> list:
    """Each SKIL: its actor value, governing attribute, specialization, use values."""
    rows = []
    for rec in records:
        name = _skill_name(get_int(rec, 'INDX.Skill', -1))
        attribute = get_int(rec, 'DATA.Attribute', -1)
        if not name or not 0 <= attribute < len(TES4_ATTRIBUTE_NAMES):
            continue
        rows.append({'name': name, 'av': get_int(rec, 'INDX.Skill'),
                     'form': _form(rec['FormID'], masters, plugin),
                     'attribute': TES4_ATTRIBUTE_NAMES[attribute],
                     'specialization': _specialization(rec),
                     'use': [round(get_float(rec, f'DATA.UseValue{i}'), 6) for i in (1, 2)],
                     'skyrim': list(SKYRIM_SKILLS.get(name, ()))})
    return rows


def _classes(records: list, masters: list, plugin: str) -> list:
    """Each CLAS: primary attributes, specialization, major skills, playable."""
    rows = []
    for rec in records:
        attributes = [TES4_ATTRIBUTE_NAMES[a] for a in
                      (get_int(rec, 'DATA.PrimaryAttribute1', -1),
                       get_int(rec, 'DATA.PrimaryAttribute2', -1))
                      if 0 <= a < len(TES4_ATTRIBUTE_NAMES)]
        major = [_skill_name(get_int(rec, f'DATA.MajorSkill[{i}]', -1))
                 for i in range(_MAJOR_SKILLS)]
        rows.append({'id': get_str(rec, 'EditorID'), 'name': get_str(rec, 'FULL'),
                     'form': _form(rec['FormID'], masters, plugin),
                     'attributes': attributes,
                     'specialization': _specialization(rec),
                     'major': [skill for skill in major if skill],
                     'playable': bool(get_int(rec, 'DATA.Flags') & _PLAYABLE)})
    return rows


def _races(records: list, masters: list, plugin: str) -> list:
    """Each RACE: skill bonuses, base attributes by sex, granted spells, playable."""
    rows = []
    for rec in records:
        boosts = ((_skill_name(get_int(rec, f'DATA.SkillBoost[{i}].Skill', -1)),
                   get_int(rec, f'DATA.SkillBoost[{i}].Bonus')) for i in range(_SKILL_BOOSTS))
        rows.append({'id': get_str(rec, 'EditorID'), 'name': get_str(rec, 'FULL'),
                     'form': _form(rec['FormID'], masters, plugin),
                     'skills': {skill: bonus for skill, bonus in boosts if skill and bonus},
                     'male': {a: get_int(rec, f'ATTR.Male.{a}') for a in TES4_ATTRIBUTE_NAMES},
                     'female': {a: get_int(rec, f'ATTR.Female.{a}') for a in TES4_ATTRIBUTE_NAMES},
                     'spells': _spells(rec, masters, plugin),
                     'playable': bool(get_int(rec, 'DATA.Flags') & _PLAYABLE)})
    return rows


def _signs(records: list, masters: list, plugin: str) -> list:
    """Each BSGN and the spells it grants."""
    return [{'id': get_str(rec, 'EditorID'), 'name': get_str(rec, 'FULL'),
             'form': _form(rec['FormID'], masters, plugin),
             'spells': _spells(rec, masters, plugin)} for rec in records]


def engine_defaults() -> dict:
    """The engine's defaults for LEVELING_SETTINGS, from ENGINE_TABLES."""
    with open(ENGINE_TABLES, encoding='utf-8') as handle:
        settings = json.load(handle).get('settings', {})
    return {name: settings[name] for name in LEVELING_SETTINGS if name in settings}


def _settings(records: list, masterless: bool) -> dict:
    """LEVELING_SETTINGS this plugin's GMSTs set, over the engine's when masterless."""
    out = engine_defaults() if masterless else {}
    for rec in records:
        name = get_str(rec, 'EditorID')
        if name in LEVELING_SETTINGS:
            value = get_float(rec, 'DATA.Value')
            out[name] = int(value) if name[0] == 'i' else round(value, 6)
    return out


def character_data(by_type: dict, masters: list, plugin: str) -> dict:
    """The character data document for one TES4 plugin's records, or {} when
    it defines none of them."""
    doc = {'skills': _skills(by_type.get('SKIL', []), masters, plugin),
           'classes': _classes(by_type.get('CLAS', []), masters, plugin),
           'races': _races(by_type.get('RACE', []), masters, plugin),
           'signs': _signs(by_type.get('BSGN', []), masters, plugin),
           'settings': _settings(by_type.get('GMST', []), not masters)}
    doc = {key: value for key, value in doc.items() if value}
    if not doc:
        return {}
    if not masters:
        doc['attributes'] = list(TES4_ATTRIBUTE_NAMES)
        doc['standings'] = list(STANDINGS)
    return {'version': VERSION, 'plugin': plugin, 'rules': 'skill-use', **doc}


def write_character_sidecar(by_type: dict, export_dir: str, output_path: str) -> int:
    """Write `<plugin>.character.json` beside the other TESRuntime sidecars.
    Returns files written: 0 for a TES3 or FO3/FNV source, or a plugin that
    defines no character data."""
    if is_tes3_export(export_dir) or is_fallout_source():
        return 0
    plugin = os.path.basename(output_path)
    doc = character_data(by_type, masters_from_export_header(export_dir), plugin)
    if not doc:
        return 0
    path = os.path.join(os.path.dirname(output_path), SIDECAR_DIR,
                        f'{os.path.splitext(plugin)[0]}.character.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(doc, handle, indent=1)
    return 1
