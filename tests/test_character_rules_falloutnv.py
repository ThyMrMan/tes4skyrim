"""A Fallout game's character rules plugin (tools/release/character_rules_falloutnv.py).

These lock what nothing reports until the game runs: where the kill and lock
nodes sit, the quest pools they start, every number the rules script reads,
and the event converted `RewardXP` sends, which the script must listen for.

See: docs/commentary/character_rules.md#fallout
"""
import re
import struct
from pathlib import Path

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
from tes5_import.base.constants import map_lock_level
from tes5_import.base.tes5_reader import records
from tes5_import.record_types.world_falloutnv import FALLOUT_REQUIRES_KEY
from tests.test_character_rules_esp import _properties
from tools.release.character_rules_falloutnv import (CRIME_EVENT_NODE, EVENT_POOL, KILL_EVENT_LAST_CHILD,
                                                     KILL_EVENT_NODE, LOCK_EVENT_NODE, SPECIAL,
                                                     build_fallout_plugin, settings_table)
from tools.release.character_rules_standings import amount_table
from tools.release.character_rules_records import SHARES_EVENT
from tools.release.make_game_select_esp import PLAYER_ATTRIBUTE_GLOBALS

MASTERS = ['Skyrim.esm', 'FalloutNV.esm']
KARMA = 0x5ABCDE
RULES_SOURCE = Path(__file__).resolve().parent.parent / 'character_rules' / 'scripts' / 'source'


def _settings():
    """New Vegas's settings as the master and engine give them."""
    out = {'iXPBase': 200, 'iXPBumpBase': 150, 'iMaxCharacterLevel': 30, 'iLevelUpSkillPointsBase': 11,
           'iLevelUpSkillPointsInterval': 1, 'fAVDTagSkillBonus': 15.0, 'fAVDSkillPrimaryBonusMult': 2.0,
           'fAVDSkillLuckBonusMult': 0.5, 'fAVDHealthLevelMult': 5.0, 'fAVDSkillBarterBase': 2.0,
           'fAVDSkillSurvivalBase': 2.0}
    for i, tier in enumerate(('VeryEasy', 'Easy', 'Average', 'Hard', 'VeryHard')):
        for name in ('iXPLevelKillCreature', 'iXPLevelKillNPC', 'iXPLevelPickLock'):
            out[name + tier] = i
        for name in ('iXPRewardKillOpponent', 'iXPRewardKillNPC', 'iXPRewardPickLock'):
            out[name + tier] = 10 * (i + 1)
    return out


def _skill(edid, name, attribute, skyrim, playable=True):
    """A skill row as character_data_falloutnv writes it."""
    return {'id': edid, 'name': name, 'attribute': attribute, 'skyrim': skyrim, 'playable': playable}


def _doc():
    """A small New Vegas-like character data document."""
    special = dict.fromkeys(SPECIAL, 5) | {'Intelligence': 7}
    return {'plugin': 'FalloutNV.esm', 'game': 'falloutnv',
            'skills': [_skill('AVBarter', 'Barter', 'Charisma', ['Speechcraft']),
                       _skill('AVBigGuns', 'Big Guns - OBSOLETE', 'Endurance', ['Marksman'], playable=False),
                       _skill('AVSmallGuns', 'Guns', 'Agility', ['Marksman']),
                       _skill('AVSpeech', 'Speech', 'Charisma', ['Speechcraft']),
                       _skill('AVThrowing', 'Survival', 'Endurance', [])],
            'classes': [{'id': 'PlayerClass', 'form': ['FalloutNV.esm', 0x57E6A], 'tags': ['Survival'],
                         'special': special}],
            'player': {'class': ['FalloutNV.esm', 0x57E6A]},
            'settings': _settings()}


def _built():
    """{(signature, FormID): [(subrecord, bytes)]} and the rules quest, for the plugin built from _doc()."""
    data, _count, main = build_fallout_plugin(_doc(), MASTERS, 6, 'FalloutRulesFalloutNV', KARMA)
    recs = {(rec.sig.decode(), rec.form_id): [(t.decode(), d) for t, d in rec.subs()]
            for rec in records(data, span=(0, len(data)))}
    return recs, main


def _props():
    """The rules script's properties."""
    recs, main = _built()
    return _properties(dict(recs[('QUST', main)])['VMAD'])


def test_kill_and_lock_nodes_start_a_pool_of_their_event_quests():
    """The kill node follows Skyrim's kill quests, the lock node opens its event; both share the event."""
    recs, _main = _built()
    nodes = {struct.unpack('<I', dict(subs)['PNAM'])[0]: subs for key, subs in recs.items() if key[0] == 'SMQN'}
    for parent, previous, event in ((KILL_EVENT_NODE, KILL_EVENT_LAST_CHILD, b'KILL'),
                                    (LOCK_EVENT_NODE, 0, b'LOCK'), (CRIME_EVENT_NODE, 0, b'ADCR')):
        subs = nodes[parent]
        assert struct.unpack('<I', dict(subs)['SNAM'])[0] == previous
        assert struct.unpack('<I', dict(subs)['DNAM'])[0] == SHARES_EVENT
        quests = [struct.unpack('<I', data)[0] for sig, data in subs if sig == 'NNAM']
        assert len(quests) == EVENT_POOL == struct.unpack('<I', dict(subs)['QNAM'])[0]
        assert {dict(recs[('QUST', q)])['ENAM'] for q in quests} == {event}


def test_special_lives_in_the_selectors_player_globals():
    """Each stat's global is the one TESGameSelect.esp names after it, sharing TES4's where the names match."""
    _name, props = _props()
    names = {fid & 0xFFFFFF: edid for fid, edid in PLAYER_ATTRIBUTE_GLOBALS}
    assert [names[fid] for fid in props['SpecialGlobals']] == [f'TESGS_Player{stat}' for stat in SPECIAL]
    assert props['SpecialStart'] == [5, 5, 5, 5, 7, 5, 5]


def test_hidden_skill_is_left_out_and_skyrim_skills_carry_their_sources():
    """Big Guns is not shown; Marksman carries Guns, Speech carries Barter and Speech, tags name shown skills."""
    _name, props = _props()
    assert props['SkillNames'] == ['Barter', 'Guns', 'Speech', 'Survival']
    marksman, speech = 2, 11
    assert props['SkyrimSources'][marksman * 3:marksman * 3 + 3] == [1, -1, -1]
    assert props['SkyrimSources'][speech * 3:speech * 3 + 3] == [0, 2, -1]
    assert props['SkillAttribute'] == [3, 5, 3, 2] and props['TagSkills'] == [3]
    assert props['SkillBase'] == [2.0, 0.0, 0.0, 2.0], 'Survival finds its base by name'


def test_skill_points_per_level_follow_each_game():
    """New Vegas: FalloutNV.exe's fixed 10 + Intelligence (at most 10) / 2, a point more on even levels
    for an odd Intelligence; Fallout 3: its settings' 10 + Intelligence."""
    nv, fo3 = settings_table(_settings() | {'iLevelUpSkillPointsBase': 99}, 'falloutnv'), \
        settings_table(_settings(), 'fallout3')
    assert (nv['SkillPointsOffset'], nv['SkillPointsPerIntelligence']) == (10.0, 0.5)
    assert (nv['IntelligenceCap'], nv['EvenLevelPoint']) == (10, 1)
    assert (fo3['SkillPointsOffset'], fo3['SkillPointsPerIntelligence'], fo3['EvenLevelPoint']) == (10.0, 1.0, 0)
    assert nv['TeammateKills'] == 1 and fo3['TeammateKills'] == 0
    assert nv['LevelKillNPC'] == [0, 1, 2, 3, 4] and nv['RewardKillCreature'] == [10, 20, 30, 40, 50]


def test_the_skill_menu_pages_hold_every_shown_skill():
    """Skill and tag pages: the skills and More, then the rest and Back; S.P.E.C.I.A.L. in both modes."""
    recs, _main = _built()
    menus = [[d.rstrip(b'\0').decode() for sig, d in subs if sig == 'ITXT']
             for key, subs in sorted(recs.items()) if key[0] == 'MESG']
    first = ['Barter', 'Guns', 'Speech', 'Survival', 'More skills']
    assert menus == [first, ['Back'], [*SPECIAL, 'Lower a stat', 'Done'],
                     [*SPECIAL, 'Raise a stat', 'Done'], first, ['Back'], ['Take it', 'Back']]



def test_new_menus_leave_every_earlier_record_where_it_was():
    """The character creation menus come after the event quests, so no earlier FormID moves."""
    recs, main = _built()
    kills = sorted(fid for (sig, fid), subs in recs.items() if sig == 'QUST' and dict(subs).get('ENAM') == b'KILL')
    menus = sorted(fid for sig, fid in recs if sig == 'MESG')
    assert (main & 0xFFFFFF, menus[:2], kills[0] & 0xFFFFFF) == (0x801, [0x02000802, 0x02000803], 0x806)
    assert min(menus[2:]) > max(fid for (sig, fid), subs in recs.items()
                                if sig == 'QUST' and dict(subs).get('ENAM') != b'ADCR')


def _standing_doc():
    """_doc() with New Vegas's karma and crime settings, two alignments and three factions."""
    doc = _doc()
    doc['settings'] |= {'fKarmaModKillingEvilActor': 100.0, 'fKarmaModKillingVeryEvilActor': 2.0,
                        'fKarmaModMurderingNonEvilNPC': 0.0, 'fKarmaModMurderingGoodNPC': -50.0,
                        'fKarmaModMurderingVeryGoodNPC': -100.0, 'fKarmaModMurderingNonEvilCreature': 0.0,
                        'fKarmaModStealing': -5.0, 'fAlignMinKarma': -1000.0, 'fAlignMaxKarma': 1000.0,
                        'fReputationMajorCrimeNeg': 30.0, 'fReputationMinorCrimeNeg': 2.0}
    doc['alignments'] = {'very_evil': [['FalloutNV.esm', 0x100]], 'good': [['FalloutNV.esm', 0x200]]}
    rep = ['FalloutNV.esm', 0xF43DD]
    doc['factions'] = [{'form': ['FalloutNV.esm', 0x10], 'crime': True, 'evil': False, 'reputation': None},
                       {'form': ['FalloutNV.esm', 0x11], 'crime': False, 'evil': True, 'reputation': rep},
                       {'form': ['FalloutNV.esm', 0x12], 'crime': True, 'evil': False, 'reputation': rep}]
    return doc


def test_karma_and_infamy_read_the_converted_globals_and_the_games_amounts():
    """Karma is the converted plugin's global; a reputation lists its crime-tracking factions; kill karma by game."""
    data, _count, main = build_fallout_plugin(_standing_doc(), MASTERS, 6, 'FalloutRulesFalloutNV', KARMA)
    recs = {(rec.sig.decode(), rec.form_id): [(t.decode(), d) for t, d in rec.subs()]
            for rec in records(data, span=(0, len(data)))}
    props = _properties(dict(recs[('QUST', main)])['VMAD'])[1]

    def entries(fid):
        """A form list's entries."""
        return [struct.unpack('<I', d)[0] for sig, d in recs[('FLST', fid)] if sig == 'LNAM']
    assert props['Karma'] == 0x01000000 | KARMA and props['Reputations'] == [0x010F43DD]
    assert entries(props['VeryEvilActors']) == [0x01000100] and entries(props['GoodActors']) == [0x01000200]
    assert entries(props['EvilActors']) == [] and entries(props['CrimeFactions']) == [0x01000010, 0x01000012]
    assert entries(props['ReputationFactions'][0]) == [0x01000012] and entries(props['EvilFactions']) == [0x01000011]
    assert props['KillKarmaClaimed'] == [0.0, 100.0, 2.0, -50.0, -100.0] and props['KillMurders'] == [1, 0, 0, 0, 0]
    assert props['KillKarmaUnclaimed'] == [0.0] * 5
    assert (props['InfamyMajor'], props['InfamyMinor'], props['KarmaTheft']) == (30.0, 2.0, -5.0)
    fo3 = amount_table(_standing_doc()['settings'], 'fallout3')
    assert fo3['KillKarmaClaimed'][2] == fo3['KillKarmaUnclaimed'][2] == 100.0 and fo3['KillMurders'] == [1, 0, 0, 1, 1]
    crime = {fid for (sig, fid), subs in recs.items()
             if dict(subs).get('ENAM') == b'ADCR' or struct.unpack('<I', dict(subs).get('PNAM', bytes(4)))[0]
             == CRIME_EVENT_NODE}
    new = crime | {fid for sig, fid in recs if sig == 'FLST'}
    assert min(new) > max(fid for _sig, fid in recs if fid not in new), 'no earlier record moves'


def test_the_rules_hear_the_converted_character_creation_menus():
    """SetSPECIALPoints, the Vigor Tester and SetTagSkills send the menu event the rules register for."""
    src = ('scn T\nbegin GameMode\n  SetSPECIALPoints 40\n  ShowLoveTesterMenuParams 40\n'
           '  SetTagSkills 3 1\n  ShowTraitMenu\nend\n')
    out = ScriptConverter(CrossRefGraph()).convert_standalone('T', src, 'Quest', 'T')
    sent = re.findall(r'SendModEvent\("(\w+)", "(\w+)", ([\w. ]+)\)', out)
    assert sent == [('TESCharacterMenu', 'special', '40 as Float'), ('TESCharacterMenu', 'special', '40 as Float'),
                    ('TESCharacterMenu', 'tags', '3 as Float'), ('TESCharacterMenu', 'traits', '0.0')]
    rules = (RULES_SOURCE / 'FalloutRules_Main.psc').read_text(encoding='utf-8')
    assert re.search(r'MENU_EVENT = "TESCharacterMenu" AutoReadOnly', rules)
    assert all(f'strArg == "{kind}"' in rules for kind in ('special', 'tags', 'traits'))


def test_converted_reward_xp_sends_the_event_the_rules_hear():
    """RewardXP becomes TESCharacterXP with the amount, the event FalloutRules_Main registers for."""
    src = 'scn T\nshort amt\nbegin GameMode\n  RewardXP amt\nend\n'
    out = ScriptConverter(CrossRefGraph()).convert_standalone('T', src, 'Quest', 'T')
    event, = re.findall(r'SendModEvent\("(\w+)", "", amt as Float\)', out)
    rules = (RULES_SOURCE / 'FalloutRules_Main.psc').read_text(encoding='utf-8')
    assert re.search(rf'XP_EVENT = "{event}" AutoReadOnly', rules)


def test_fallout_very_hard_locks_stay_pickable():
    """Fallout's 100 is a Very Hard lock and only 255 needs the key; TES4's 100 needs the key."""
    assert map_lock_level(100, requires_key=FALLOUT_REQUIRES_KEY) == 100
    assert map_lock_level(255, requires_key=FALLOUT_REQUIRES_KEY) == 255
    assert map_lock_level(0, requires_key=FALLOUT_REQUIRES_KEY) == 1
    assert map_lock_level(100) == 255


def test_a_class_without_tags_leaves_the_tag_list_unset():
    """The game refuses a zero-length array property, so no tags means no TagSkills at all."""
    doc = _doc()
    doc['classes'][0]['tags'] = []
    data, _count, main = build_fallout_plugin(doc, MASTERS, 6, 'FalloutRulesFalloutNV', KARMA)
    quest = next(rec for rec in records(data, span=(0, len(data))) if rec.form_id == main)
    _name, props = _properties(dict((t.decode(), d) for t, d in quest.subs())['VMAD'])
    assert 'TagSkills' not in props
    assert props['SpecialStart'] == [5, 5, 5, 5, 7, 5, 5]


def _requirement(function, param, value, op=3, or_next=False):
    """A Fallout requirement condition: function(param) <op> value, op 3 being >=."""
    return struct.pack('<B3xfHxxIIII', op << 5 | or_next, value, function, param, 0, 0, 0).hex()


def _perk(name, level, form, requirements=(), trait=False, playable=True):
    """A perk row as character_data_falloutnv writes it."""
    return {'id': name, 'name': name, 'text': f'{name} text', 'form': ['FalloutNV.esm', form], 'trait': trait,
            'level': level, 'ranks': 1, 'playable': playable, 'hidden': False,
            'requirements': list(requirements), 'effects': []}


def _perk_doc():
    """_doc() with skills' actor values and New Vegas-like perks, a hidden one and a trait."""
    doc = _doc()
    for skill, av in zip(doc['skills'], (32, 33, 41, 43, 44)):
        skill['av'] = av
    doc['settings'] |= {'iLevelsPerPerk': 2, 'iTraitMenuMaxNumTraits': 2}
    doc['perks'] = [_perk('Toughness', 6, 0x31DE0, [_requirement(495, 7, 5.0)]),
                    _perk('Run n Gun', 4, 0x14609D, [_requirement(495, 41, 45.0, or_next=True),
                                                     _requirement(495, 32, 45.0)]),
                    _perk('Lady Killer', 2, 0x94EB9, [_requirement(70, 0, 1.0, op=0)]),
                    _perk('Challenge', 0, 0x15EAD7),
                    _perk('Companion', 2, 0x100, playable=False),
                    _perk('Four Eyes', 1, 0x135EC4, [_requirement(495, 6, 1.0, op=2)], trait=True)]
    return doc


def _perk_built():
    """The records and rules properties of the plugin built from _perk_doc()."""
    data, _count, main = build_fallout_plugin(_perk_doc(), MASTERS, 6, 'FalloutRulesFalloutNV', KARMA)
    recs = {(rec.sig.decode(), rec.form_id): [(t.decode(), d) for t, d in rec.subs()]
            for rec in records(data, span=(0, len(data)))}
    return recs, _properties(dict(recs[('QUST', main)])['VMAD'])[1]


def test_perks_by_level_then_traits_with_the_requirements_the_rules_read():
    """Level-0 and unplayable perks stay off; each requirement is (kind, index, op, value, OR)."""
    _recs, props = _perk_built()
    assert props['PerkNames'] == ['Lady Killer', 'Run n Gun', 'Toughness', 'Four Eyes']
    assert props['FirstTrait'] == 3 and props['LevelsPerPerk'] == 2 and props['MaxTraits'] == 2
    assert props['PerkForms'][0] == 0x01094EB9 and props['PerkTexts'][3] == 'Four Eyes text'
    assert (props['PerkReqStart'], props['PerkReqCount']) == ([0, 1, 3, 4], [1, 2, 1, 1])
    rows = list(zip(props['ReqKind'], props['ReqIndex'], props['ReqOp'], props['ReqValue'], props['ReqOr']))
    assert rows == [(3, 0, 0, 1.0, 0), (1, 1, 3, 45.0, 1), (1, 0, 3, 45.0, 0), (0, 2, 3, 5.0, 0),
                    (0, 1, 2, 1.0, 0)]


def test_a_perk_button_shows_while_its_slot_global_is_one():
    """Each perk's ITXT is followed by GetGlobalValue(its slot) == 1; More and Back by theirs."""
    recs, props = _perk_built()
    page = recs[('MESG', props['PerkPages'][0])]
    texts = [i for i, (sig, _d) in enumerate(page) if sig == 'ITXT']
    globs = [struct.unpack_from('<HxxI', page[i + 1][1], 8) for i in texts]
    slots = [*props['PickSlots'][:3], props['PickMore'], props['PickBack']]
    assert [page[i][1].rstrip(b'\0').decode() for i in texts] == ['Lady Killer', 'Run n Gun', 'Toughness',
                                                                  'More', 'Back']
    assert globs == [(74, slot) for slot in slots]
    trait_page = [d.rstrip(b'\0').decode() for sig, d in recs[('MESG', props['TraitPages'][0])] if sig == 'ITXT']
    assert trait_page == ['Four Eyes', 'More', 'Back', 'Done']


def test_converted_perk_commands_call_skyrims_perk_natives():
    """AddPerk, RemovePerk and HasPerk keep the perk and drop Fallout's teammate flag."""
    src = ('scn T\nshort x\nbegin GameMode\n  player.AddPerk Toughness 1\n  set x to player.HasPerk Toughness 1\n'
           '  player.RemovePerk Toughness\nend\n')
    out = ScriptConverter(CrossRefGraph()).convert_standalone('T', src, 'Quest', 'T')
    assert 'Game.GetPlayer().AddPerk(Toughness)' in out
    assert 'x = Game.GetPlayer().HasPerk(Toughness) as Int' in out
    assert 'Game.GetPlayer().RemovePerk(Toughness)' in out


def test_a_rank_read_from_add_perk_adds_then_reads_it_back():
    """Fallout's AddPerk returns the new rank; Papyrus's returns nothing, so the value is read after."""
    src = 'scn T\nshort rank\nbegin GameMode\n  set rank to (player.AddPerk Toughness)\nend\n'
    out = ScriptConverter(CrossRefGraph()).convert_standalone('T', src, 'Quest', 'T')
    lines = [line.strip() for line in out.splitlines()]
    add = lines.index('Game.GetPlayer().AddPerk(Toughness)')
    assert lines[add + 1] == 'rank = Game.GetPlayer().HasPerk(Toughness) as Int'
