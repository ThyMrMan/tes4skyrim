"""The character data file TESRuntime's leveling rules read.

See: docs/commentary/tes5_import_character_data.md#the-character-data-file
"""

import json
import os

from tes4_export.record_types.actors import export_SKIL
from tes4_export.tes4_reader import Record, Subrecord
from tes5_import.character_data import (LEVELING_SETTINGS, character_data,
                                        engine_defaults, write_character_sidecar)

#: SkillAthletics (Oblivion.esm SKIL 0000003E), INDX and DATA verbatim.
ATHLETICS_INDX = bytes.fromhex('0d000000')
ATHLETICS_DATA = bytes.fromhex('0d00000004000000000000008fc2f53c0ad7233d')


def _skill(formid='0000003E', index='13', attribute='4', spec='0'):
    """A SKIL export record, Athletics by default."""
    return {'FormID': formid, 'EditorID': 'SkillAthletics', 'INDX.Skill': index,
            'DATA.Attribute': attribute, 'DATA.Specialization': spec,
            'DATA.UseValue1': '0.029999999329447746',
            'DATA.UseValue2': '0.03999999910593033'}


def _class(formid='0001C3AA'):
    """A playable CLAS export record: Strength and Endurance, Combat, two majors."""
    return {'FormID': formid, 'EditorID': 'Knight', 'FULL': 'Knight',
            'DATA.PrimaryAttribute1': '0', 'DATA.PrimaryAttribute2': '5',
            'DATA.Specialization': '0', 'DATA.MajorSkill[0]': '14',
            'DATA.MajorSkill[1]': '15', 'DATA.Flags': '1'}


def _race():
    """A RACE export record with two skill bonuses, one unused slot and a spell."""
    rec = {'FormID': '00000907', 'EditorID': 'Imperial', 'FULL': 'Imperial',
           'DATA.SkillBoost[0].Skill': '16', 'DATA.SkillBoost[0].Bonus': '5',
           'DATA.SkillBoost[1].Skill': '32', 'DATA.SkillBoost[1].Bonus': '10',
           'DATA.SkillBoost[2].Skill': '255', 'DATA.SkillBoost[2].Bonus': '0',
           'DATA.Flags': '1', 'SpellCount': '1', 'Spell[0]': '00047ADE'}
    for sex in ('Male', 'Female'):
        rec.update({f'ATTR.{sex}.{a}': '40' for a in ('Strength', 'Luck')})
    return rec


def _gmst(name, value):
    """A GMST export record."""
    return {'FormID': '00012345', 'EditorID': name, 'DATA.Value': value}


def test_the_exporter_reads_every_skil_field_at_its_offset():
    """INDX is the skill; DATA is action, attribute, specialization, two use values."""
    rec = Record(type='SKIL', data_size=0, flags=0, form_id=0x3E,
                 subrecords=[Subrecord('INDX', ATHLETICS_INDX),
                             Subrecord('DATA', ATHLETICS_DATA)])
    lines = dict(line.split('=', 1) for line in export_SKIL(rec))
    assert lines['INDX.Skill'] == '13'
    assert lines['DATA.Action'] == '13'
    assert lines['DATA.Attribute'] == '4'
    assert lines['DATA.Specialization'] == '0'
    assert round(float(lines['DATA.UseValue1']), 6) == 0.03
    assert round(float(lines['DATA.UseValue2']), 6) == 0.04


def test_a_masterless_plugin_carries_its_records_and_the_engine_defaults():
    """Skills, classes, races and signs are named and owned; settings merge GMSTs over defaults."""
    by_type = {'SKIL': [_skill()], 'CLAS': [_class()], 'RACE': [_race()],
               'BSGN': [{'FormID': '0001FD9D', 'EditorID': 'BirthSignWarrior',
                         'FULL': 'The Warrior', 'SpellCount': '1', 'Spell[0]': '00022A6E'}],
               'GMST': [_gmst('fSkillUseExp', '1.5'), _gmst('fDialogSpeachDelay', '0.15')]}
    doc = character_data(by_type, [], 'Oblivion.esm')
    assert doc['rules'] == 'skill-use'
    assert doc['skills'] == [{'name': 'Athletics', 'av': 13, 'form': ['Oblivion.esm', 0x3E],
                              'attribute': 'Speed', 'specialization': 'Combat',
                              'use': [0.03, 0.04], 'skyrim': []}]
    knight = doc['classes'][0]
    assert knight['attributes'] == ['Strength', 'Endurance']
    assert knight['major'] == ['Blade', 'Block'] and knight['playable']
    race = doc['races'][0]
    assert race['skills'] == {'Blunt': 5, 'Speechcraft': 10}
    assert race['male']['Strength'] == 40 and race['female']['Luck'] == 40
    assert race['spells'] == [['Oblivion.esm', 0x47ADE]]
    assert doc['signs'][0]['spells'] == [['Oblivion.esm', 0x22A6E]]
    assert doc['settings']['fSkillUseExp'] == 1.5
    assert doc['settings']['iLevelUp01Mult'] == 2
    assert 'fDialogSpeachDelay' not in doc['settings']
    assert doc['attributes'][0] == 'Strength' and doc['standings'][0]['skyrim'] == 'Fame'


def test_engine_defaults_cover_every_leveling_setting():
    """Oblivion.exe registers every setting the rules read; the table is the leveling ladder."""
    defaults = engine_defaults()
    assert set(defaults) == set(LEVELING_SETTINGS)
    assert defaults['iLevelUpSkillCount'] == 10
    assert [defaults[f'iLevelUp{n:02d}Mult'] for n in range(1, 11)] == [2, 2, 2, 2, 3, 3, 3, 4, 4, 5]
    assert defaults['fSkillUseMajorMult'] == 0.75


def test_a_dependent_plugin_carries_only_what_it_defines():
    """A master's class overridden here stays the master's form; no engine defaults ride along."""
    doc = character_data({'CLAS': [_class('0001C3AA')],
                          'GMST': [_gmst('iLevelUpSkillCount', '12')]},
                         ['Oblivion.esm'], 'Knights.esp')
    assert doc['classes'][0]['form'] == ['Oblivion.esm', 0x1C3AA]
    assert doc['settings'] == {'iLevelUpSkillCount': 12}
    assert 'attributes' not in doc and 'standings' not in doc


def test_blunt_weapons_mysticism_spells_and_skill_books_are_listed():
    """Blunt is WEAP type 2 or 3; Mysticism a spell whose first effect's MGEF is school 4, the
    MGEF found in the master chain; a book lists under the skill it teaches."""
    by_type = {'WEAP': [{'FormID': '00000100', 'DATA.Type': '2'},
                        {'FormID': '00000101', 'DATA.Type': '0'}],
               'SPEL': [{'FormID': '00000200', 'Effect[0].EFID': 'TELE'},
                        {'FormID': '00000201', 'Effect[0].EFID': 'FIDG'}],
               'BOOK': [{'FormID': '00000300', 'DATA.Teaches': '2'},
                        {'FormID': '00000301', 'DATA.Teaches': '255'}]}
    masters_mgef = {'1': {'Signature': 'MGEF', 'EditorID': 'TELE', 'DATA.School': '4'},
                    '2': {'Signature': 'MGEF', 'EditorID': 'FIDG', 'DATA.School': '2'}}
    doc = character_data(by_type, ['Oblivion.esm'], 'Mod.esp', masters_mgef)
    assert doc['folds'] == {'Blunt': [['Oblivion.esm', 0x100]],
                            'Mysticism': [['Oblivion.esm', 0x200]]}
    assert doc['books'] == {'Blade': [['Oblivion.esm', 0x300]]}


def test_text_settings_keep_their_text():
    """An `s` setting is read as text, over the engine's default."""
    doc = character_data({'GMST': [_gmst('sMeditate', 'Sleep on it.')]}, [], 'Oblivion.esm')
    assert doc['settings']['sMeditate'] == 'Sleep on it.'
    assert doc['settings']['sAttributeNameLuck'] == 'Luck'


def test_a_plugin_defining_nothing_writes_nothing():
    """No character records and no leveling GMSTs: no document."""
    assert character_data({'GMST': [_gmst('fDialogSpeachDelay', '0.15')]},
                          ['Oblivion.esm'], 'Patch.esp') == {}


def _export(tmp_path, header=''):
    """An export folder whose `_HEADER.txt` holds `header`."""
    folder = tmp_path / 'export' / 'Plugin.esm'
    folder.mkdir(parents=True)
    (folder / '_HEADER.txt').write_text(header, encoding='utf-8')
    return str(folder)


def test_the_sidecar_lands_beside_the_other_tesruntime_sidecars(tmp_path):
    """`SKSE/Plugins/TESRuntime/<plugin>.character.json`, beside the output ESM."""
    output = str(tmp_path / 'output' / 'Plugin.esm' / 'Plugin.esm')
    assert write_character_sidecar({'SKIL': [_skill()]}, _export(tmp_path), output) == 1
    path = os.path.join(os.path.dirname(output), 'SKSE', 'Plugins', 'TESRuntime',
                        'Plugin.character.json')
    with open(path, encoding='utf-8') as handle:
        assert json.load(handle)['skills'][0]['name'] == 'Athletics'


def test_a_tes3_source_writes_no_sidecar(tmp_path):
    """Morrowind's rules come from its own records, in a later piece."""
    output = str(tmp_path / 'output' / 'Plugin.esm' / 'Plugin.esm')
    assert write_character_sidecar({'SKIL': [_skill()]},
                                   _export(tmp_path, 'Source=TES3\n'), output) == 0
