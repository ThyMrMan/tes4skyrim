"""The character rules plugin (tools/release/make_character_rules_esp.py).

These lock what nothing reports until the game runs: the Story Manager node's
place and condition, the quests' shape, and every property the rules script
reads, decoded back out of the VMAD.

See: docs/commentary/character_rules.md#the-rules-plugin
"""
import struct

from tes5_import.base.tes5_reader import records
from tools.release.make_character_rules_esp import (FUNC_GET_GLOBAL_VALUE, SHARES_EVENT,
                                                    SKILL_EVENT_LAST_CHILD, SKILL_EVENT_NODE,
                                                    build_plugin)

MASTERS = ['Skyrim.esm', 'Oblivion.esm']
CLASS_CHOICE = 0x01000A41


def _skill(name, attribute, spec, skyrim):
    """A skill row as character_data writes it."""
    return {'name': name, 'attribute': attribute, 'specialization': spec, 'skyrim': skyrim}


def _doc():
    """A small Oblivion-like character data document."""
    settings = {f'iLevelUp{n:02d}Mult': 2 + n // 5 for n in range(1, 11)}
    settings.update({f'sLevelUp{n}': f'Level {n}' for n in range(2, 21)})
    settings.update({'iLevelUpSkillCount': 10, 'sMeditate': 'Rest.',
                     'fAttributeClassPrimaryBonus': 5.0, 'fAttributeClassSecondaryBonus': 5.0,
                     'fPCBaseHealthMult': 2.0, 'fPCBaseMagickaMult': 1.0,
                     'fActorStrengthEncumbranceMult': 5.0, 'sAttributeNameStrength': 'Might'})
    return {
        'skills': [_skill('Blade', 'Strength', 'Combat', ['OneHanded', 'TwoHanded']),
                   _skill('Blunt', 'Strength', 'Combat', ['OneHanded', 'TwoHanded']),
                   _skill('Mercantile', 'Personality', 'Stealth', ['Speechcraft']),
                   _skill('Speechcraft', 'Personality', 'Stealth', ['Speechcraft']),
                   _skill('Athletics', 'Speed', 'Combat', [])],
        'classes': [{'id': 'Warrior', 'name': 'Warrior', 'playable': True,
                     'attributes': ['Strength', 'Endurance'], 'specialization': 'Combat',
                     'major': ['Blade', 'Athletics']},
                    {'id': 'Agent', 'name': 'agent', 'playable': True,
                     'attributes': ['Personality', 'Agility'], 'specialization': 'Stealth',
                     'major': ['Speechcraft']},
                    {'id': 'Guard', 'name': 'Guard', 'playable': False,
                     'attributes': [], 'specialization': 'Combat', 'major': []}],
        'races': [{'id': 'Imperial', 'playable': True, 'skills': {'Blade': 5},
                   'male': {'Strength': 40, 'Luck': 50}, 'female': {'Strength': 30}}],
        'folds': {'Blunt': [['Oblivion.esm', 0x1234]]},
        'books': {'Blade': [['Oblivion.esm', 0x5678]]},
        'settings': settings,
    }


def _built():
    """{(signature, FormID): [(subrecord, bytes)]} for the plugin built from _doc()."""
    data, count, main = build_plugin(_doc(), MASTERS, CLASS_CHOICE, 1, 'TES4RulesOblivion')
    recs = {(rec.sig.decode(), rec.form_id): [(t.decode(), d) for t, d in rec.subs()]
            for rec in records(data, span=(0, len(data)))}
    return recs, count, main


def _one(recs, sig):
    """The only record of `sig`, as (FormID, {subrecord: bytes})."""
    (fid, subs), = [(key[1], dict(subs)) for key, subs in recs.items() if key[0] == sig]
    return fid, subs


def _wstring(data, pos):
    """A u16-length string and the position after it."""
    size = struct.unpack_from('<H', data, pos)[0]
    return data[pos + 2:pos + 2 + size].decode(), pos + 2 + size


def _value(data, pos, kind):
    """One property value of `kind` and the position after it."""
    if kind == 1:
        return struct.unpack_from('<HhI', data, pos)[2], pos + 8
    if kind == 2:
        return _wstring(data, pos)
    return struct.unpack_from('<i' if kind == 3 else '<f', data, pos)[0], pos + 4


def _properties(vmad):
    """The first script's name and {property: value}, arrays as lists."""
    name, pos = _wstring(vmad, 6)
    count = struct.unpack_from('<H', vmad, pos + 1)[0]
    pos += 3
    props = {}
    for _ in range(count):
        pname, pos = _wstring(vmad, pos)
        kind = vmad[pos]
        pos += 2
        if kind > 10:
            items = []
            size = struct.unpack_from('<I', vmad, pos)[0]
            pos += 4
            for _ in range(size):
                item, pos = _value(vmad, pos, kind - 10)
                items.append(item)
            props[pname] = items
        else:
            props[pname], pos = _value(vmad, pos, kind)
    return name, props


def test_the_node_follows_skyrims_skill_quests_while_the_rules_are_on():
    """Parent is the SKIL event node, after its last child; it shares the event and needs RulesActive."""
    recs, _count, _main = _built()
    _fid, node = _one(recs, 'SMQN')
    active = [key[1] for key, subs in recs.items() if key[0] == 'GLOB'
              and dict(subs)['EDID'].startswith(b'TES4RulesOblivionRulesActive')]
    assert struct.unpack('<I', node['PNAM'])[0] == SKILL_EVENT_NODE
    assert struct.unpack('<I', node['SNAM'])[0] == SKILL_EVENT_LAST_CHILD
    assert struct.unpack('<I', node['DNAM'])[0] == SHARES_EVENT
    ctda = node['CTDA']
    assert struct.unpack_from('<H', ctda, 8)[0] == FUNC_GET_GLOBAL_VALUE
    assert struct.unpack_from('<I', ctda, 12)[0] == active[0]
    event = struct.unpack('<I', node['NNAM'])[0]
    assert dict(recs[('QUST', event)])['ENAM'] == b'SKIL'


def test_the_rules_quest_starts_with_the_game_on_the_player():
    """Start Game Enabled, one alias forced to the player, and listed in the .seq's quest."""
    recs, count, main = _built()
    subs = dict(recs[('QUST', main)])
    assert struct.unpack_from('<H', subs['DNAM'])[0] == 0x0011
    assert struct.unpack('<I', subs['ALFR'])[0] == 0x14
    hedr = dict(recs[('TES4', 0)])['HEDR']
    assert struct.unpack('<I', hedr[4:8])[0] == count
    assert main >> 24 == len(MASTERS)


def test_skyrim_skills_credit_their_source_skills():
    """One-Handed credits Blade, folding Blunt; Speech credits Speechcraft, folding Mercantile."""
    recs, _count, main = _built()
    name, props = _properties(dict(recs[('QUST', main)])['VMAD'])
    assert name == 'TES4Rules_Main'
    one_handed, speech = 0, 11
    assert props['SkyrimSkillNames'][one_handed] == 'OneHanded'
    assert props['SkyrimPrimary'][one_handed] == 0 and props['SkyrimFold'][one_handed] == 1
    assert props['SkyrimPrimary'][speech] == 3 and props['SkyrimFold'][speech] == 2
    assert props['SkyrimPrimary'][17] == -1, 'Enchanting credits nothing'
    assert props['SkillAttribute'] == [0, 0, 6, 6, 4]


def test_classes_follow_the_chargen_menu_order():
    """Playable classes only, sorted by name ignoring case, majors as a bit per skill."""
    recs, _count, main = _built()
    _name, props = _properties(dict(recs[('QUST', main)])['VMAD'])
    assert props['ClassIds'] == ['Agent', 'Warrior']
    assert props['ClassMajors'] == [1 << 3, (1 << 0) | (1 << 4)]
    assert props['ClassFavored1'] == [6, 0] and props['ClassFavored2'] == [3, 5]
    assert props['ClassChoice'] == CLASS_CHOICE


def test_races_bonuses_and_settings_reach_the_script():
    """Race arrays run eight attributes and seven bonus slots a race; texts and numbers come from the settings."""
    recs, _count, main = _built()
    _name, props = _properties(dict(recs[('QUST', main)])['VMAD'])
    assert props['RaceMale'] == [40, 0, 0, 0, 0, 0, 0, 50]
    assert props['RaceBonusSkill'] == [0, -1, -1, -1, -1, -1, -1]
    assert props['RaceBonusValue'][0] == 5
    assert props['LevelUpMults'][0] == 1 and len(props['LevelUpMults']) == 11
    assert props['LevelUpTexts'][0] == 'Level 2' and props['MeditateText'] == 'Rest.'
    assert props['SkillsPerLevel'] == 10 and props['HealthMult'] == 2.0


def test_the_level_up_menu_hides_a_picked_attribute():
    """A button per attribute, named by the game's texts, each gated on its Picked global being 0."""
    recs, _count, _main = _built()
    menu =[sub for key, subs in recs.items() if key[0] == 'MESG' for sub in subs]
    buttons = [data.rstrip(b'\0').decode() for sig, data in menu if sig == 'ITXT']
    assert buttons[0] == 'Might' and len(buttons) == 8
    assert sum(1 for sig, _d in menu if sig == 'CTDA') == 8
