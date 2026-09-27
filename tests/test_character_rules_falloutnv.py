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
from tools.release.character_rules_falloutnv import (EVENT_POOL, KILL_EVENT_LAST_CHILD, KILL_EVENT_NODE,
                                                     LOCK_EVENT_NODE, SPECIAL, build_fallout_plugin,
                                                     settings_table)
from tools.release.character_rules_records import SHARES_EVENT
from tools.release.make_game_select_esp import PLAYER_ATTRIBUTE_GLOBALS

MASTERS = ['Skyrim.esm', 'FalloutNV.esm']
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
    data, _count, main = build_fallout_plugin(_doc(), MASTERS, 6, 'FalloutRulesFalloutNV')
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
                                    (LOCK_EVENT_NODE, 0, b'LOCK')):
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
    """New Vegas: 10 + Intelligence / 2 from the master's 11 and 1; Fallout 3: 10 + Intelligence."""
    nv, fo3 = settings_table(_settings(), 'falloutnv'), settings_table(_settings(), 'fallout3')
    assert (nv['SkillPointsOffset'], nv['SkillPointsPerIntelligence']) == (10.0, 0.5)
    assert (fo3['SkillPointsOffset'], fo3['SkillPointsPerIntelligence']) == (10.0, 1.0)
    assert nv['TeammateKills'] == 1 and fo3['TeammateKills'] == 0
    assert nv['LevelKillNPC'] == [0, 1, 2, 3, 4] and nv['RewardKillCreature'] == [10, 20, 30, 40, 50]


def test_the_skill_menu_pages_hold_every_shown_skill():
    """Page one's buttons are its skills and More; page two's the rest and Back."""
    recs, _main = _built()
    menus = [[d.rstrip(b'\0').decode() for sig, d in subs if sig == 'ITXT']
             for key, subs in sorted(recs.items()) if key[0] == 'MESG']
    assert menus == [['Barter', 'Guns', 'Speech', 'Survival', 'More skills'], ['Back']]


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
