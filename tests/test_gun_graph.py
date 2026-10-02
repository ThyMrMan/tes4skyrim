"""The gun state machines and the humanoid graph patch, offline.

Everything here runs on synthetic packfile XML: the vanilla SSE graphs are
only needed by the real build (gun_patch_falloutnv), where hkxconv
round-trips them."""

import xml.etree.ElementTree as ET

import pytest

from asset_convert.havok.gun_anim_falloutnv import (classify_stem,
                                                    gun_layout)
from asset_convert.havok.gun_graph_falloutnv import (
    GUN_EVENTS, GUN_HAND_TYPE, GUN_VARIABLES, GunClips, GunGraphBuilder,
    class_selector, clip_speed, fire_machine, has_gait, loco_machine,
    moving_gen, ready_machine, equip_gen)
from asset_convert.havok.humanoid_graph import HumanoidGraph, param_text
from tes5_import.record_types.equipment_falloutnv import gun_profile

BASE_EVENTS = ['crossbowAttackStart', 'attackRelease', 'attackStop',
               'arrowAttach', 'bowDrawn', 'BowRelease', 'arrowRelease',
               'moveStart', 'moveStop', 'turnLeft', 'turnRight', 'turnStop',
               'SneakStart', 'SneakStop', 'WeapEquip_Out',
               'WeapEquip_OutMoving', 'weaponDraw', 'BeginWeaponDraw',
               'AttackWinStart', 'AttackWinEnd']
BASE_VARS = ['iRightHandType', 'iLeftHandType', 'AimPitchCurrent', 'bBowDrawn',
             'weaponSpeedMult',
             'iIsInSneak', 'iSyncTurnState', 'iSyncIdleLocomotion',
             'Direction', 'SpeedSampled']


def _entry(stem, duration=1.0, hits=(), motion=None, keys=None):
    """A manifest clip entry with the fields the builders read."""
    return {'stem': stem, 'anim': f'Animations\\TES4Guns\\{stem}.hkx',
            'duration': duration, 'frames': 30, 'tracks': 60, 'sounds': [],
            'feet': [], 'hits': list(hits), 'keys': keys or {},
            'motion': motion}


def _manifest():
    """A rifle-only manifest covering every machine's clip roles."""
    stems = {
        '2hraim': _entry('2hraim'), '2hraimup': _entry('2hraimup'),
        '2hraimdown': _entry('2hraimdown'),
        'sneak2hraim': _entry('sneak2hraim'),
        '2hrattackleft': _entry('2hrattackleft', 0.6, hits=[0.033]),
        '2hrattack3': _entry('2hrattack3', 0.5, hits=[0.05]),
        '2hrreloada': _entry('2hrreloada', 2.0),
        '2hrreloadx': _entry('2hrreloadx', 1.0),
        '2hrreloadxstart': _entry('2hrreloadxstart', 0.9),
        '2hrequip': _entry('2hrequip', 0.5, keys={'attach': 0.2}),
        '2hrunequip': _entry('2hrunequip', 0.5, keys={'detach': 0.2}),
        '2hrturnleft': _entry('2hrturnleft'),
        '2hrforward': _entry('2hrforward', 1.2, motion={
            'bone': 'x', 'times': [0, 1.2], 'translations': [[0, 0, 0], [0, 120, 0]],
            'rotations': None}),
        '2hrfastforward': _entry('2hrfastforward', 0.8, motion={
            'bone': 'x', 'times': [0, 0.8], 'translations': [[0, 0, 0], [0, 240, 0]],
            'rotations': None}),
        '2hrfastleft': _entry('2hrfastleft', 0.8),
    }
    return {'clips': list(stems.values()),
            'anim_dir': gun_layout('OUT')['anim_dir'],
            'classes': {s: classify_stem(s) for s in stems}}


def _builder(clips, events=BASE_EVENTS, variables=BASE_VARS):
    """A builder over the base tables plus the gun events and variables."""
    return GunGraphBuilder(events + list(GUN_EVENTS),
                           variables + list(GUN_VARIABLES), 100, clips)


class TestMachines:
    def test_clip_lookup_and_speed(self):
        """Clips resolve by (class, action, letter, pitch); speed from motion."""
        clips = GunClips(_manifest())
        assert clips.find('2hr', 'aim', pitch='up') == '2hraimup'
        assert clips.find('2hr', 'reload', letter='x', start=True) == '2hrreloadxstart'
        assert clips.present_classes() == ['2hr']
        assert clips.attacks_of('2hr') == ['attackleft', 'attack3']
        assert clip_speed(clips.entries['2hrforward']) == pytest.approx(100.0)

    def test_fire_machine_shape(self):
        """The fire machine raises the engine's shot events and reload/auto
        conditions, and every trigger time is non-negative."""
        gb = _builder(GunClips(_manifest()))
        sm = fire_machine(gb, '2hr')
        xml = gb.render(sm)
        root = ET.fromstring(xml)
        objs = {o.get('name'): o for o in root.find('hksection')}
        names = {o.get('class') for o in objs.values()}
        assert {'hkbManualSelectorGenerator', 'hkbExpressionCondition',
                'hkbClipTriggerArray'} <= names
        assert 'hkbEvaluateExpressionModifier' not in names
        fire_gens = [g for g in gb.generators if 'attack' in g['stem']]
        assert fire_gens
        events = {e for g in fire_gens for _t, e in g['events']}
        assert {'arrowRelease', 'attackStop', 'TES4GunFireEnd'} <= events
        assert not {'arrowAttach', 'bowDrawn', 'BowRelease'} & events
        shots = [t for g in fire_gens for t, e in g['events'] if e == 'arrowRelease']
        assert shots and all(t >= 0.0 for t in shots)
        conds = [(param_text(o, 'expression')) for o in objs.values()
                 if o.get('class') == 'hkbExpressionCondition']
        assert any('iGunShots >= iGunClipSize' in c for c in conds)
        assert any('iGunAuto == 1' in c for c in conds)

    def test_pitch_blend_raises_the_shot_once(self):
        """Only one clip of an attack's pitch blend carries the shot, kept running at zero weight."""
        m = _manifest()
        m['clips'] += [_entry('2hrattackleftup', 0.7, hits=[0.04]),
                       _entry('2hrattackleftdown', 0.5, hits=[0.03])]
        m['classes'] = {c['stem']: classify_stem(c['stem']) for c in m['clips']}
        gb = _builder(GunClips(m))
        xml = gb.render(fire_machine(gb, '2hr'))
        left = [g for g in gb.generators if g['stem'].startswith('2hrattackleft')]
        assert {g['stem'] for g in left} == {'2hrattackleft', '2hrattackleftup', '2hrattackleftdown'}
        carriers = {g['stem'] for g in left if any(e == 'arrowRelease' for _t, e in g['events'])}
        assert carriers == {'2hrattackleft'}
        root = ET.fromstring(xml)
        flags = {param_text(o, 'flags') for o in root.find('hksection')
                 if o.get('class') == 'hkbBlenderGenerator' and 'attackleft' in param_text(o, 'name')}
        assert flags == {'25'}

    def test_reload_chain_and_end_events(self):
        """A start clip chains into its loop; every reload ends with its event."""
        gb = _builder(GunClips(_manifest()))
        fire_machine(gb, '2hr')
        by_stem = {g['stem']: g for g in gb.generators}
        assert any(e == 'TES4GunReloadStart' for _t, e in by_stem['2hrreloadxstart']['events'])
        assert any(e == 'TES4GunReloadEnd' for _t, e in by_stem['2hrreloadx']['events'])
        assert by_stem['2hrreloada']['events'] == [(2.0, 'TES4GunReloadEnd')]

    def test_ready_locomotion_and_equip(self):
        """Ready, locomotion and equip nodes build; the draw fires weaponDraw
        at the clip's Attach key and the equip-out pair at its end."""
        gb = _builder(GunClips(_manifest()))
        ready_machine(gb, '2hr', '#0001', '#0002')
        loco_machine(gb, '2hr')
        eq = equip_gen(gb, '2hr')
        assert any(g['name'] == _text_name(eq) for g in gb.generators)
        eq_events = next(g for g in gb.generators if g['stem'] == '2hrequip')['events']
        assert (0.2, 'weaponDraw') in eq_events
        assert (0.5, 'WeapEquip_Out') in eq_events
        sel = class_selector(gb, 'MSG', lambda c: ready_machine(gb, c, '#0001', '#0002'))
        xml = gb.render(sel)
        assert xml.count('hkbManualSelectorGenerator') >= 1
        assert 'BSiStateTaggingGenerator' in xml

    def test_class_without_gaits_uses_the_vanilla_legs(self):
        """Fallout 3's third-person rifles have no walk/run clips: locomotion
        plays the vanilla slot, and moving wears the aim pose over it."""
        m = _manifest()
        m['clips'] = [c for c in m['clips'] if 'forward' not in c['stem']
                      and 'fastleft' not in c['stem']]
        clips = GunClips(m)
        gb = _builder(clips)
        assert not has_gait(clips, '2hr')
        assert loco_machine(gb, '2hr') is None
        sel = class_selector(gb, 'MSG', lambda c: loco_machine(gb, c), '#0777')
        assert '#0777' in gb.render(sel)
        moving = moving_gen(gb, '2hr', '#0001', '#0002')
        assert _text_name(moving) == 'TES4Gun_2hr_MovingBlend'


def _text_name(obj):
    """The `name` param of a rendered builder object."""
    for name, body, _kind in obj.params:
        if name == 'name':
            return body
    return ''


SYNTH_GRAPH = '''<?xml version="1.0" encoding="ascii"?>
<hkpackfile classversion="8" contentsversion="hk_2010.2.0-r1" toplevelobject="#0050">
<hksection name="__data__">
<hkobject name="#0050" class="hkRootLevelContainer">
<hkparam name="namedVariants" numelements="1"><hkobject>
<hkparam name="name">hkbBehaviorGraph</hkparam><hkparam name="className">hkbBehaviorGraph</hkparam>
<hkparam name="variant">#0051</hkparam></hkobject></hkparam></hkobject>
<hkobject name="#0051" class="hkbBehaviorGraph">
<hkparam name="variableBindingSet">null</hkparam><hkparam name="userData">0</hkparam>
<hkparam name="name">g.hkb</hkparam><hkparam name="variableMode">VARIABLE_MODE_DISCARD_WHEN_INACTIVE</hkparam>
<hkparam name="rootGenerator">#0055</hkparam><hkparam name="data">#0052</hkparam></hkobject>
<hkobject name="#0052" class="hkbBehaviorGraphData">
<hkparam name="attributeDefaults" numelements="0"></hkparam>
<hkparam name="variableInfos" numelements="1"><hkobject><hkparam name="role"><hkobject>
<hkparam name="role">ROLE_DEFAULT</hkparam><hkparam name="flags">0</hkparam></hkobject></hkparam>
<hkparam name="type">VARIABLE_TYPE_INT32</hkparam></hkobject></hkparam>
<hkparam name="characterPropertyInfos" numelements="0"></hkparam>
<hkparam name="eventInfos" numelements="2"><hkobject><hkparam name="flags">0</hkparam></hkobject>
<hkobject><hkparam name="flags">0</hkparam></hkobject></hkparam>
<hkparam name="variableInitialValues">#0053</hkparam><hkparam name="stringData">#0054</hkparam></hkobject>
<hkobject name="#0053" class="hkbVariableValueSet">
<hkparam name="wordVariableValues" numelements="1"><hkobject><hkparam name="value">0</hkparam></hkobject></hkparam>
<hkparam name="quadVariableValues" numelements="0"></hkparam>
<hkparam name="variantVariableValues" numelements="0"></hkparam></hkobject>
<hkobject name="#0054" class="hkbBehaviorGraphStringData">
<hkparam name="eventNames" numelements="2"><hkcstring>attackStop</hkcstring><hkcstring>crossbowAttackStart</hkcstring></hkparam>
<hkparam name="attributeNames" numelements="0"></hkparam>
<hkparam name="variableNames" numelements="1"><hkcstring>iRightHandType</hkcstring></hkparam>
<hkparam name="characterPropertyNames" numelements="0"></hkparam></hkobject>
<hkobject name="#0055" class="hkbStateMachine">
<hkparam name="variableBindingSet">#0056</hkparam><hkparam name="userData">0</hkparam>
<hkparam name="name">TypeMachine</hkparam>
<hkparam name="startStateId">0</hkparam><hkparam name="states" numelements="3">#0057 #0058 #0064</hkparam>
<hkparam name="wildcardTransitions">null</hkparam></hkobject>
<hkobject name="#0064" class="hkbStateMachineStateInfo">
<hkparam name="variableBindingSet">null</hkparam><hkparam name="listeners" numelements="0"></hkparam>
<hkparam name="enterNotifyEvents">null</hkparam><hkparam name="exitNotifyEvents">null</hkparam>
<hkparam name="transitions">null</hkparam><hkparam name="generator">#0062</hkparam>
<hkparam name="name">State00</hkparam><hkparam name="stateId">13</hkparam>
<hkparam name="probability">1.000000</hkparam><hkparam name="enable">true</hkparam></hkobject>
<hkobject name="#0056" class="hkbVariableBindingSet">
<hkparam name="bindings" numelements="1"><hkobject><hkparam name="memberPath">startStateId</hkparam>
<hkparam name="variableIndex">0</hkparam><hkparam name="bitIndex">-1</hkparam>
<hkparam name="bindingType">BINDING_TYPE_VARIABLE</hkparam></hkobject></hkparam>
<hkparam name="indexOfBindingToEnable">-1</hkparam></hkobject>
<hkobject name="#0057" class="hkbStateMachineStateInfo">
<hkparam name="variableBindingSet">null</hkparam><hkparam name="listeners" numelements="0"></hkparam>
<hkparam name="enterNotifyEvents">null</hkparam><hkparam name="exitNotifyEvents">null</hkparam>
<hkparam name="transitions">#0059</hkparam><hkparam name="generator">#0061</hkparam>
<hkparam name="name">Zero</hkparam><hkparam name="stateId">0</hkparam>
<hkparam name="probability">1.000000</hkparam><hkparam name="enable">true</hkparam></hkobject>
<hkobject name="#0058" class="hkbStateMachineStateInfo">
<hkparam name="variableBindingSet">null</hkparam><hkparam name="listeners" numelements="0"></hkparam>
<hkparam name="enterNotifyEvents">null</hkparam><hkparam name="exitNotifyEvents">null</hkparam>
<hkparam name="transitions">null</hkparam><hkparam name="generator">#0062</hkparam>
<hkparam name="name">Crossbow</hkparam><hkparam name="stateId">12</hkparam>
<hkparam name="probability">1.000000</hkparam><hkparam name="enable">true</hkparam></hkobject>
<hkobject name="#0059" class="hkbStateMachineTransitionInfoArray">
<hkparam name="transitions" numelements="1"><hkobject>
<hkparam name="triggerInterval"><hkobject><hkparam name="enterEventId">-1</hkparam>
<hkparam name="exitEventId">-1</hkparam><hkparam name="enterTime">0.000000</hkparam>
<hkparam name="exitTime">0.000000</hkparam></hkobject></hkparam>
<hkparam name="initiateInterval"><hkobject><hkparam name="enterEventId">-1</hkparam>
<hkparam name="exitEventId">-1</hkparam><hkparam name="enterTime">0.000000</hkparam>
<hkparam name="exitTime">0.000000</hkparam></hkobject></hkparam>
<hkparam name="transition">null</hkparam><hkparam name="condition">#0060</hkparam>
<hkparam name="eventId">1</hkparam><hkparam name="toStateId">12</hkparam>
<hkparam name="fromNestedStateId">0</hkparam><hkparam name="toNestedStateId">0</hkparam>
<hkparam name="priority">0</hkparam><hkparam name="flags">0</hkparam></hkobject></hkparam></hkobject>
<hkobject name="#0060" class="hkbExpressionCondition">
<hkparam name="expression">(iRightHandType == 12)</hkparam></hkobject>
<hkobject name="#0063" class="hkbVariableBindingSet">
<hkparam name="bindings" numelements="1"><hkobject><hkparam name="memberPath">selectedGeneratorIndex</hkparam>
<hkparam name="variableIndex">0</hkparam><hkparam name="bitIndex">-1</hkparam>
<hkparam name="bindingType">BINDING_TYPE_VARIABLE</hkparam></hkobject></hkparam>
<hkparam name="indexOfBindingToEnable">-1</hkparam></hkobject>
<hkobject name="#0061" class="hkbManualSelectorGenerator">
<hkparam name="variableBindingSet">#0063</hkparam><hkparam name="userData">0</hkparam>
<hkparam name="name">TypeMSG</hkparam>
<hkparam name="generators" numelements="13">#0062 #0062 #0062 #0062 #0062 #0062 #0062 #0062 #0062 #0062 #0062 #0062 #0062</hkparam>
<hkparam name="selectedGeneratorIndex">0</hkparam><hkparam name="currentGeneratorIndex">0</hkparam></hkobject>
<hkobject name="#0062" class="hkbClipGenerator">
<hkparam name="variableBindingSet">null</hkparam><hkparam name="userData">0</hkparam>
<hkparam name="name">Idle</hkparam><hkparam name="animationName">Animations\\Idle.hkx</hkparam>
<hkparam name="triggers">null</hkparam><hkparam name="mode">MODE_LOOPING</hkparam></hkobject>
</hksection></hkpackfile>'''


class TestHumanoidGraphPatch:
    @pytest.fixture
    def graph(self, tmp_path):
        """The synthetic two-state graph, parsed."""
        p = tmp_path / 'g.xml'
        p.write_text(SYNTH_GRAPH, encoding='ascii')
        return HumanoidGraph(str(p))

    def test_vanilla_slot(self, graph):
        """The last vanilla type's generator in a selector or machine slot."""
        assert graph.vanilla_slot('TypeMSG') == '#0062'
        assert graph.vanilla_slot('TypeMachine') == '#0062'
        assert graph.vanilla_slot('NoSuchSlot') is None

    def test_tables_extend_in_place(self, graph):
        """Variables and events append once each and bump every count."""
        assert graph.add_variable('iGunClass') == 1
        assert graph.add_variable('iGunClass') == 1
        assert graph.add_event('TES4GunFireEnd') == 2
        assert graph.variables == ['iRightHandType', 'iGunClass']
        gdata = graph.of_class('hkbBehaviorGraphData')[0]
        assert gdata.find("hkparam[@name='variableInfos']").get('numelements') == '2'
        assert gdata.find("hkparam[@name='eventInfos']").get('numelements') == '3'

    def test_type_slots_gain_the_gun_entry(self, graph):
        """A selector gets a 14th generator; the vanilla leftover state 13
        (1HM_Readied_BehaviorGraph ships one) is overwritten, not skipped;
        a second pass leaves both alone."""
        names = graph.extend_type_slots(GUN_HAND_TYPE, {'TypeMachine': '#0061'})
        assert set(names) == {'TypeMSG', 'TypeMachine'}
        msg = graph.find('TypeMSG')
        assert len(graph.ref_list(msg, 'generators')) == 14
        sm = graph.find('TypeMachine')
        assert len(graph.ref_list(sm, 'states')) == 3
        st = graph.state_of(sm, GUN_HAND_TYPE)
        assert param_text(st, 'name') == 'TES4Type13_TypeMachine'
        assert param_text(st, 'generator') == '#0061'
        assert graph.extend_type_slots(GUN_HAND_TYPE, {}) == []
        assert param_text(st, 'generator') == '#0061'

    def test_leftover_state_clones_the_crossbow(self, graph):
        """Without a replacement the leftover takes the type-12 generator."""
        graph.extend_type_slots(GUN_HAND_TYPE, {})
        st = graph.state_of(graph.find('TypeMachine'), GUN_HAND_TYPE)
        assert param_text(st, 'generator') == '#0062'

    def test_conditions_widen_and_transitions_insert(self, graph):
        """`== 12` tests also accept 13; a conditioned transition lands first."""
        assert graph.widen_type_conditions(12, 13) == 1
        cond = graph.obj('#0060')
        assert param_text(cond, 'expression') == '((iRightHandType == 12) || (iRightHandType == 13))'
        st = graph.state_of(graph.find('TypeMachine'), 0)
        graph.add_transition(st, 'crossbowAttackStart', 99,
                             condition='iRightHandType == 13', priority=1, first=True)
        arr = graph.obj(param_text(st, 'transitions'))
        rows = arr.find("hkparam[@name='transitions']").findall('hkobject')
        assert len(rows) == 2 and param_text(rows[0], 'toStateId') == '99'
        assert param_text(rows[0], 'priority') == '1'
        assert param_text(graph.obj(param_text(rows[0], 'condition')), 'expression') == 'iRightHandType == 13'

    def test_splice_appends_builder_objects(self, graph):
        """Builder objects numbered from next_id() splice in without clashes."""
        for v in GUN_VARIABLES:
            graph.add_variable(v)
        for e in GUN_EVENTS:
            graph.add_event(e)
        gb = GunGraphBuilder(graph.events, graph.variables, graph.next_id(),
                             GunClips(_manifest()))
        eq = equip_gen(gb, '2hr')
        before = len(graph.objs)
        graph.splice(gb.render(eq))
        assert len(graph.objs) > before
        assert graph.obj(eq.ref) is not None


class TestGunProfile:
    def test_profile_from_the_authored_binding(self):
        """Class/reload/attack indices and clip size come off the WEAP DNAM."""
        rec ={'DNAM.FalloutAnimType': '5', 'DNAM.ReloadAnim': '2',
               'DNAM.AttackAnim': '38', 'DATA.ClipSize': '8',
               'DNAM.Flags1': '2'}
        p = gun_profile(rec)
        assert p == {'class': 1, 'reload': 2, 'attack': 2, 'clip_size': 8,
                     'auto': 1, 'dry_sound': '', 'sight_fov': 65.0, 'ammo': []}
        assert gun_profile({'DNAM.FalloutAnimType': '1'}) is None
        assert gun_profile({'DNAM.FalloutAnimType': '3'})['attack'] == -1
