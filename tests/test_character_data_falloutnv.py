"""FO3/FNV character records: their export, and the character data built from it.

See: docs/commentary/tes4_export_falloutnv.md#character-records
"""
import struct

from tes4_export.record_types.character_falloutnv import (emit_class_deltas, export_ACTORVALUE,
                                                          export_PERK, export_REPUTATION)
from tes4_export.record_types.actors import export_FACT
from tes4_export.tes4_reader import Record, Subrecord
from tes5_import.character_data_falloutnv import actor_value_index, character_data, game_of


def _record(sig, *subs):
    """A parsed record from (signature, bytes) pairs."""
    return Record(sig, 0, 0, 0x1234, [Subrecord(t, d) for t, d in subs])


def _z(text):
    """A zero-terminated string subrecord body."""
    return text.encode() + b'\0'


CTDA = bytes(range(28))


def test_perk_requirements_data_and_effects_in_order():
    """Conditions before DATA are the perk's; after a PRKE they belong to that effect's open tab."""
    rec = _record('PERK', ('EDID', _z('Toughness')), ('FULL', _z('Toughness')),
                  ('CTDA', CTDA), ('DATA', bytes([0, 4, 2, 1, 0])),
                  ('PRKE', bytes([2, 1, 0])), ('DATA', bytes([43, 3, 1])),
                  ('PRKC', b'\xff'), ('CTDA', CTDA),
                  ('EPFT', b'\x01'), ('EPFD', struct.pack('<f', 1.5)), ('PRKF', b''),
                  ('PRKE', bytes([0, 0, 0])), ('DATA', struct.pack('<IH2x', 0x0101, 20)), ('PRKF', b''),
                  ('PRKE', bytes([1, 0, 1])), ('DATA', struct.pack('<I', 0x0202)), ('PRKF', b''))
    lines = export_PERK(rec)
    assert f'Condition[0].Raw={CTDA.hex()}' in lines
    assert ['DATA.Trait=0', 'DATA.MinLevel=4', 'DATA.Ranks=2', 'DATA.Playable=1', 'DATA.Hidden=0'] == \
        [line for line in lines if line.startswith('DATA.')]
    assert 'Effect[0].Type=EntryPoint' in lines and 'Effect[0].EntryPoint=43' in lines
    assert 'Effect[0].Tab[0].RunOn=-1' in lines
    assert f'Effect[0].Tab[0].Condition[0].Raw={CTDA.hex()}' in lines
    assert 'Effect[0].ValueType=1' in lines and f"Effect[0].Value={struct.pack('<f', 1.5).hex()}" in lines
    assert 'Effect[1].Quest=00000101' in lines and 'Effect[1].Stage=20' in lines
    assert 'Effect[2].Ability=00000202' in lines and 'Effect[2].Priority=1' in lines
    assert lines[-1] == 'EffectCount=3'


def test_a_fallout3_perk_stops_before_hidden():
    """Fallout 3's DATA may be four bytes; Hidden is simply absent."""
    lines = export_PERK(_record('PERK', ('EDID', _z('Lady Killer')), ('DATA', bytes([0, 2, 1, 1]))))
    assert 'DATA.Playable=1' in lines and not [line for line in lines if line.startswith('DATA.Hidden')]
    assert lines[-1] == 'EffectCount=0'


def test_class_tag_skills_and_special():
    """A Fallout CLAS: four tag skills (-1 for none), flags, and the seven ATTR bytes."""
    data = struct.pack('<4iIIbB2x', 38, 41, 45, -1, 1, 0, -1, 0)
    lines = []
    emit_class_deltas(lines, _record('CLAS', ('DATA', data), ('ATTR', bytes([9, 8, 8, 7, 6, 7, 7]))))
    assert lines[:4] == ['DATA.TagSkill[0]=38', 'DATA.TagSkill[1]=41', 'DATA.TagSkill[2]=45', 'DATA.TagSkill[3]=-1']
    assert 'DATA.Flags=1' in lines and 'DATA.Teaches=-1' in lines
    assert 'ATTR.Strength=9' in lines and 'ATTR.Luck=7' in lines


def test_actor_value_and_reputation():
    """AVIF keeps its short name; REPU its float value."""
    avif = export_ACTORVALUE(_record('AVIF', ('EDID', _z('AVBarter')), ('FULL', _z('Barter')),
                                     ('ANAM', _z('Barter'))))
    assert 'FULL=Barter' in avif and 'ANAM=Barter' in avif
    repu = export_REPUTATION(_record('REPU', ('EDID', _z('RepNVFreeside')), ('DATA', struct.pack('<f', 30.0))))
    assert 'DATA.Value=30.0' in repu


def _avif(formid, edid, name):
    """An exported AVIF row."""
    return {'Signature': 'AVIF', 'FormID': f'{formid:08X}', 'EditorID': edid, 'FULL': name}


AVIFS = [_avif(0x3E8 + i, f'AV{n}', n) for i, n in enumerate(
    ('Strength', 'Perception', 'Endurance', 'Charisma', 'Intelligence', 'Agility', 'Luck'))] + [
    _avif(0x4B0, 'AVBarter', 'Barter'), _avif(0x4B9, 'AVSmallGuns', 'Guns'),
    _avif(0x4BC, 'AVThrowing', 'Survival'), _avif(0x457, 'AVKarma', 'Karma')]


def test_actor_values_follow_their_formid_blocks():
    """S.P.E.C.I.A.L. from 0x3E8 is 5-11, skills from 0x4B0 are 32 on, AI values from 0x514 are 0-4."""
    assert actor_value_index(0x3E8) == 5 and actor_value_index(0x3EE) == 11
    assert actor_value_index(0x4B0) == 32 and actor_value_index(0x4BD) == 45
    assert actor_value_index(0x514) == 0 and actor_value_index(0x457) == 23
    assert actor_value_index(0x400) is None


def test_new_vegas_skills_classes_and_settings():
    """Skills from the skill block only; Survival reuses Throwing's value; tags are named by actor value."""
    by_type = {'AVIF': AVIFS,
               'CLAS': [{'FormID': '00001234', 'EditorID': 'Courier', 'FULL': 'Courier', 'DATA.Flags': '1',
                         'DATA.TagSkill[0]': '32', 'DATA.TagSkill[1]': '44', 'DATA.TagSkill[2]': '-1',
                         'ATTR.Strength': '5', 'ATTR.Luck': '6'}],
               'GMST': [{'EditorID': 'iLevelUpSkillPointsBase', 'DATA.Value': '11'},
                        {'EditorID': 'iXPRewardPickLockEasy', 'DATA.Value': '10'},
                        {'EditorID': 'fUnrelated', 'DATA.Value': '2'}]}
    doc = character_data(by_type, [], 'FalloutNV.esm', 'falloutnv')
    assert doc['rules'] == 'xp' and doc['game'] == 'falloutnv'
    assert doc['attributes'][0] == 'Strength' and len(doc['attributes']) == 7
    assert [(s['name'], s['av'], s['attribute']) for s in doc['skills']] == [
        ('Barter', 32, 'Charisma'), ('Guns', 41, 'Agility'), ('Survival', 44, 'Endurance')]
    cls = doc['classes'][0]
    assert cls['tags'] == ['Barter', 'Survival'] and cls['playable'] and cls['special']['Luck'] == 6
    settings = doc['settings']
    assert settings['iLevelUpSkillPointsBase'] == 11 and settings['iXPRewardPickLockEasy'] == 10
    assert settings['iLevelsPerPerk'] == 2 and 'fUnrelated' not in settings
    assert doc['standings'] == [{'name': 'Karma', 'skyrim': None}]


def _actor(formid, karma, template=0, flags=0):
    """An exported NPC_ row with its karma and trait template."""
    row = {'FormID': f'{formid:08X}', 'ACBS.Karma': str(karma), 'ACBS.TemplateFlags': str(flags)}
    return row | ({'TPLT.Template': f'{template:08X}'} if template else {})


def test_factions_and_the_alignment_each_actors_karma_gives():
    """FACT's crime flag and reputation link; karma sorts by fAlign*, through trait templates and agreeing lists."""
    lines = export_FACT(_record('FACT', ('EDID', _z('NCR')), ('DATA', bytes([0, 1, 0, 0])),
                                ('WMI1', struct.pack('<I', 0xF43DD))))
    assert 'DATA.Flags=0' in lines and 'DATA.Flags2=1' in lines and 'WMI1.Reputation=000F43DD' in lines
    facts = [{'FormID': '00000010', 'DATA.Flags2': '1', 'WMI1.Reputation': '000F43DD'},
             {'FormID': '00000011', 'DATA.Flags2': '0'}]
    npcs = [_actor(0x100, -900), _actor(0x101, -500), _actor(0x102, 0, template=0x300, flags=1),
            _actor(0x103, 900, template=0x100), _actor(0x104, 0, template=0x301, flags=1)]
    lists = [{'FormID': '00000300', 'EntryCount': '2', 'Entry[0].FormID': '00000100', 'Entry[1].FormID': '00000100'},
             {'FormID': '00000301', 'EntryCount': '2', 'Entry[0].FormID': '00000100', 'Entry[1].FormID': '00000101'}]
    doc = character_data({'AVIF': AVIFS, 'FACT': facts, 'NPC_': npcs, 'LVLN': lists}, [], 'FalloutNV.esm',
                         'falloutnv')
    assert doc['factions'] == [{'form': ['FalloutNV.esm', 0x10], 'crime': True, 'evil': False,
                                'reputation': ['FalloutNV.esm', 0xF43DD]}]
    assert doc['alignments'] == {'very_evil': [['FalloutNV.esm', 0x100], ['FalloutNV.esm', 0x102]],
                                 'evil': [['FalloutNV.esm', 0x101]], 'very_good': [['FalloutNV.esm', 0x103]]}


def test_a_dependent_names_skills_through_its_master():
    """A DLC class's tags resolve through the master's AVIFs, and the DLC lists no skills of its own."""
    master = {row['FormID']: row for row in AVIFS}
    by_type = {'CLAS': [{'FormID': '01000800', 'EditorID': 'DLCClass', 'DATA.TagSkill[0]': '41'}]}
    doc = character_data(by_type, ['FalloutNV.esm'], 'DeadMoney.esm', 'falloutnv', master)
    assert doc['classes'][0]['tags'] == ['Guns'] and doc['classes'][0]['form'] == ['DeadMoney.esm', 0x800]
    assert 'skills' not in doc and 'attributes' not in doc and 'standings' not in doc


def test_fallout3_hides_its_cut_throwing(tmp_path):
    """Fallout 3's cut Throwing keeps Fallout3.exe's Intelligence but is not shown; the header names the game."""
    (tmp_path / '_HEADER.txt').write_text('HEDR.Version=0.9399999976158142\n', encoding='utf-8')
    assert game_of(str(tmp_path)) == 'fallout3'
    doc = character_data({'AVIF': AVIFS}, [], 'Fallout3.esm', 'fallout3')
    throwing, = [s for s in doc['skills'] if s['id'] == 'AVThrowing']
    assert throwing['attribute'] == 'Intelligence' and not throwing['playable']
    assert 'iLevelsPerPerk' not in doc['settings']


def test_new_vegas_hides_big_guns_and_keeps_the_players_class():
    """Big Guns stays in New Vegas's data but is not shown; the player record names the starting class,
    and the skill bases and lock tiers are kept for the rules."""
    by_type = {'AVIF': AVIFS + [_avif(0x4B1, 'AVBigGuns', 'Big Guns - OBSOLETE')],
               'NPC_': [{'FormID': '00000007', 'EditorID': 'Player', 'CNAM.Class': '00057E6A'},
                        {'FormID': '00000900', 'EditorID': 'Other', 'CNAM.Class': '00000901'}]}
    doc = character_data(by_type, [], 'FalloutNV.esm', 'falloutnv')
    assert {s['id']: s['playable'] for s in doc['skills']} == {
        'AVBarter': True, 'AVBigGuns': False, 'AVSmallGuns': True, 'AVThrowing': True}
    assert doc['player'] == {'class': ['FalloutNV.esm', 0x57E6A]}
    settings = doc['settings']
    assert settings['fAVDSkillBarterBase'] == 3.0 and settings['iXPLevelPickLockHard'] == 3


def test_perk_rows_keep_requirements_effects_and_tabs():
    """A perk's requirements, ability and entry-point effects and their tabs survive as data."""
    perk = {'FormID': '00000900', 'EditorID': 'Toughness', 'FULL': 'Toughness', 'DATA.Trait': '0',
            'DATA.MinLevel': '4', 'DATA.Ranks': '2', 'DATA.Playable': '1', 'Condition[0].Raw': 'aa',
            'EffectCount': '2', 'Effect[0].Type': 'Ability', 'Effect[0].Ability': '00000901',
            'Effect[1].Type': 'EntryPoint', 'Effect[1].EntryPoint': '0', 'Effect[1].Function': '3',
            'Effect[1].ValueType': '1', 'Effect[1].Value': '0000803f',
            'Effect[1].Tab[0].RunOn': '1', 'Effect[1].Tab[0].Condition[0].Raw': 'bb'}
    row = character_data({'PERK': [perk]}, [], 'FalloutNV.esm', 'falloutnv')['perks'][0]
    assert row['level'] == 4 and row['ranks'] == 2 and row['playable'] and not row['trait']
    assert row['requirements'] == ['aa']
    assert row['effects'][0]['ability'] == ['FalloutNV.esm', 0x901]
    assert row['effects'][1]['entry_point'] == 0 and row['effects'][1]['tabs'] == [
        {'run_on': 1, 'conditions': ['bb']}]
