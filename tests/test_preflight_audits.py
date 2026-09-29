"""The preflight audits: quest progression, asset load, build drift and the review ledger.

See: docs/commentary/tools_preflight.md#overview
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.esm.tes5_esm_reader import Sub, TES5Record
from tools.validate.preflight import (asset_load, build_diff, dialogue_loss, findings, log_triage, package_ai,
                                      quest_progression, quest_start, script_health, world_links)
from tools.validate.preflight.plugin_index import PluginIndex, vmad_scripts
from tools.validate.preflight.quest_converted import Script, load_scripts, parse_script
from tools.validate.preflight.quest_source import SourceGame, find_setters, required_speakers
from tools.validate.vmad_property_typecheck import binding_problem, reference_problem


def rec(sig, fid, subs=(), parent_dial=0):
    """A built record with `subs` as (signature, bytes) pairs."""
    return TES5Record(sig, 0, 0, fid, 44, [Sub(t, d) for t, d in subs], parent_dial=parent_dial)


def zs(text):
    """A NUL-terminated subrecord string."""
    return text.encode('latin-1') + b'\0'


def vmad(script):
    """A VMAD attaching one propertyless script."""
    name = script.encode('latin-1')
    return struct.pack('<hhH', 5, 2, 1) + struct.pack('<H', len(name)) + name + b'\0' + struct.pack('<H', 0)


def export_file(folder, sig, records):
    """Write `records` (dicts) as the export's `sig`.txt."""
    blocks = ['---RECORD_BEGIN---\nSignature=%s\n%s\n---RECORD_END---\n'
              % (sig, '\n'.join(f'{k}={v}' for k, v in r.items())) for r in records]
    (folder / f'{sig}.txt').write_text('\n'.join(blocks), encoding='utf-8')


def greeting_game(tmp_path):
    """A source game where a GREETING offers a reply whose line sets TestQ stage 10."""
    export = tmp_path / 'export'
    export.mkdir()
    export_file(export, 'QUST', [{'FormID': '00001000', 'EditorID': 'TestQ', 'StageCount': 1,
                                  'Stage[0].Index': 10, 'Stage[0].LogCount': 1}])
    export_file(export, 'DIAL', [{'FormID': '00002000', 'EditorID': 'GREETING', 'DATA.Type': 0},
                                 {'FormID': '00002001', 'EditorID': 'TestReply', 'DATA.Type': 0}])
    export_file(export, 'INFO', [
        {'FormID': '00003000', 'ParentDIAL': '00002000', 'QSTI.Quest': '00001000', 'Choice[0]': '00002001'},
        {'FormID': '00003001', 'ParentDIAL': '00002001', 'QSTI.Quest': '00001000',
         'ResultScript': 'SetStage TestQ 10 ; the reply'}])
    scripts = tmp_path / 'scripts'
    (scripts / 'source').mkdir(parents=True)
    (scripts / 'source' / 'TEST_TIF__00003001.psc').write_text(
        'ScriptName TEST_TIF__00003001 extends TopicInfo Hidden\n'
        'Function Fragment_0(ObjectReference akSpeakerRef)\n'
        '  TEST_TestQScript.TES4SetStage(TestQ as TEST_TestQScript, 10)\nEndFunction\n')
    (scripts / 'TEST_TIF__00003001.pex').write_bytes(b'')
    return SourceGame(str(export)), load_scripts(scripts)


def built_greeting(open_branch):
    """The built plugin: a Hello greeting, or a Blocking branch when `open_branch`."""
    records = [rec('QUST', 0x01001000, [('EDID', zs('TestQ'))]),
               rec('DIAL', 0x01002000, [('SNAM', b'CUST' if open_branch else b'HELO')]),
               rec('DIAL', 0x01002001, [('EDID', zs('TestReply')), ('SNAM', b'CUST')]),
               rec('INFO', 0x01003000, [('TCLT', struct.pack('<I', 0x01002001))], 0x01002000),
               rec('INFO', 0x01003001, [('VMAD', vmad('TEST_TIF__00003001'))], 0x01002001)]
    if open_branch:
        records.append(rec('DLBR', 0x01004000, [('DNAM', struct.pack('<I', 2)),
                                                ('SNAM', struct.pack('<I', 0x01002000))]))
    return PluginIndex(records)


def test_a_reply_behind_a_hello_greeting_leaves_its_stage_unreachable(tmp_path):
    """The Amata case: Skyrim drops a Hello line's replies, so the stage they set is lost."""
    source, scripts = greeting_game(tmp_path)
    ctx = quest_progression.QuestContext('Test.esm', source, scripts, built_greeting(False))
    [finding] = quest_progression.audit(ctx)
    assert finding.key == 'quest|Test.esm|TestQ|10' and finding.severity == 'error'
    assert 'TestReply' in finding.detail[0] and 'not reachable' in finding.detail[0]


def test_a_blocking_greeting_keeps_the_reply_reachable(tmp_path):
    """The fix: a greeting that opens a Blocking branch keeps its replies."""
    source, scripts = greeting_game(tmp_path)
    ctx = quest_progression.QuestContext('Test.esm', source, scripts, built_greeting(True))
    assert quest_progression.audit(ctx) == []


def test_a_setter_in_a_dropped_menumode_block_is_named_as_such():
    """A SetStage kept only as a comment under a dead block header is inert, with the block named."""
    script = parse_script('X', 'Event OnUpdate()\nEndEvent\n'
                               '; --- TES4 `begin MenuMode 1` - no Skyrim equivalent ---\n'
                               ';  X.TES4SetStage(Tut as X, 52)\n', True)
    [(call, why)] = script.inert
    assert (call.quest_expr, call.stage) == ('tut', 52) and 'MenuMode 1' in why
    assert script.calls == []


def test_source_setters_skip_comments_and_keep_computed_stages():
    """A commented SetStage is skipped; a computed stage is kept as None."""
    quests = {'testq': 'TestQ'}
    text = '; setstage TestQ 5\\r\\nsetstage TestQ 10\\r\\nSetStage TestQ myStage'
    assert [(q, s) for q, s, _r, _b in find_setters(text, quests)] == [('TestQ', 10), ('TestQ', None)]


def test_the_ledger_hides_decided_findings_and_patterns_match():
    """`ok` hides, a pattern decides every key it matches, and `bug` forces an error."""
    fs = [findings.Finding('quest', 'quest|G|A|10', 'review', 'a'),
          findings.Finding('assets', 'assets|G|outside|meshes\\markers', 'review', 'b'),
          findings.Finding('quest', 'quest|G|B|20', 'review', 'c')]
    ledger = findings.mark({}, 'quest|G|A|10', 'ok', 'fine')
    ledger = findings.mark(ledger, 'assets|*|outside|*', 'skip', '')
    ledger = findings.mark(ledger, 'quest|G|B|*', 'bug', 'broken')
    out = findings.triage(fs, ledger, previous={'quest|G|B|20'})
    assert [f.key for f, _t in out['hidden']] == ['quest|G|A|10', 'assets|G|outside|meshes\\markers']
    assert [(f.key, t) for f, t in out['error']] == [('quest|G|B|20', 'bug: broken')]


def test_build_drift_separates_moved_removed_and_retyped():
    """An EditorID on a new FormID is moved, a vanished one removed, a changed signature retyped."""
    before = {'01000001': 'NPC_|Andy', '01000002': 'MISC|Cake', '01000003': 'STAT|Wall'}
    after = {'01000009': 'NPC_|Andy', '01000003': 'ACTI|Wall', '01000004': 'MISC|New'}
    keys = {f.key for f in build_diff.audit('G', before, after)}
    assert keys == {'build|G|moved|NPC_', 'build|G|removed|MISC', 'build|G|retyped|STAT'}
    assert build_diff.audit('G', None, after) == []


def nif(types):
    """A minimal 20.2.0.7 NIF header with one block of each type."""
    head = b'Gamebryo File Format, Version 20.2.0.7\n' + struct.pack('<IBII', 0x14020007, 1, 12, len(types))
    head += struct.pack('<I', 83) + b'\0\0\0' + struct.pack('<H', len(types))
    for t in types:
        head += struct.pack('<I', len(t)) + t.encode()
    head += b''.join(struct.pack('<H', i) for i in range(len(types)))
    return head + b''.join(struct.pack('<I', 0) for _ in types) + struct.pack('<III', 0, 0, 0)


def test_a_block_skyrim_cannot_build_is_a_red_marker():
    """A mesh holding a block type with no RTTI in the exe is an error naming the block."""
    [f] = asset_load.nif_findings('G', 'meshes\\x.nif', nif(['NiNode', 'bhkConvexListShape']),
                                    {'NiNode'}, [('STAT X 01000001', 3)])
    assert f.severity == 'error' and 'bhkConvexListShape' in f.summary
    assert asset_load.nif_findings('G', 'meshes\\x.nif', nif(['NiNode']), {'NiNode'}, []) == []


def test_an_embedded_weapon_without_its_node_is_reported():
    """Embedded flag 0x20 with no NNAM means the actor drops the weapon."""
    dnam = bytearray(100)
    struct.pack_into('<I', dnam, 12, 0x20)
    index = PluginIndex([rec('WEAP', 0x01000001, [('EDID', zs('ClawGun')), ('DNAM', bytes(dnam))]),
                         rec('WEAP', 0x01000002, [('EDID', zs('Kept')), ('DNAM', bytes(dnam)),
                                                  ('NNAM', zs('Weapon'))])])
    assert [f.key for f in asset_load.embedded_findings('G', index)] == ['assets|G|embedded|ClawGun']


def test_vmad_properties_resolve_to_their_formids():
    """A script's object properties are read so a SetStage on a property finds its quest."""
    name, prop = b'S', b'MyQuest'
    data = (struct.pack('<hhH', 5, 2, 1) + struct.pack('<H', 1) + name + b'\0' + struct.pack('<H', 1)
            + struct.pack('<H', len(prop)) + prop + bytes([1, 1]) + struct.pack('<hhI', 0, -1, 0x01001000))
    assert vmad_scripts(data) == [('s', {'myquest': 0x01001000})]


def trigger_game(tmp_path, converted_body):
    """A source game whose only StartQuest of TestQ sits in an activator script, and its build."""
    export = tmp_path / 'export'
    export.mkdir(parents=True)
    export_file(export, 'QUST', [{'FormID': '00001000', 'EditorID': 'TestQ', 'DATA.Flags': 0}])
    export_file(export, 'SCPT', [{'FormID': '00005000', 'EditorID': 'TrigScript',
                                  'SCTX': 'Begin OnActivate\\r\\nStartQuest TestQ\\r\\nEnd'}])
    export_file(export, 'ACTI', [{'FormID': '00006000', 'EditorID': 'Trig', 'SCRI': '00005000'}])
    scripts = tmp_path / 'scripts'
    (scripts / 'source').mkdir(parents=True)
    (scripts / 'source' / 'TEST_TrigScript.psc').write_text(
        'ScriptName TEST_TrigScript extends ObjectReference\nEvent OnActivate(ObjectReference a)\n'
        f'{converted_body}\nEndEvent\n')
    (scripts / 'TEST_TrigScript.pex').write_bytes(b'')
    index = PluginIndex([rec('QUST', 0x01001000, [('EDID', zs('TestQ')), ('DNAM', struct.pack('<HBBII', 0, 0, 0, 0, 0))]),
                         rec('ACTI', 0x01006000, [('VMAD', vmad('TEST_TrigScript'))])])
    return quest_progression.QuestContext('Test.esm', SourceGame(str(export)), load_scripts(scripts), index)


def test_a_startquest_the_converter_dropped_leaves_the_quest_unstarted(tmp_path):
    """A StartQuest that converted to nothing means the quest never runs; `Start()` keeps it."""
    [finding] = quest_start.start_findings(trigger_game(tmp_path / 'a', '  ; nothing'))
    assert finding.key == 'start|Test.esm|TestQ' and finding.severity == 'error'
    assert 'Begin OnActivate' in finding.detail[0]
    assert quest_start.start_findings(trigger_game(tmp_path / 'b', '  TestQ.Start()')) == []


def test_a_required_alias_on_a_deleted_reference_blocks_its_quest():
    """A non-optional forced-reference alias whose reference is deleted keeps the quest from starting."""
    alias = [('ALST', struct.pack('<I', 0)), ('ALID', zs('Boss')), ('FNAM', struct.pack('<I', 0)),
             ('ALFR', struct.pack('<I', 0x800)), ('ALED', b'')]
    ref = TES5Record('REFR', 0, 0x20, 0x800, 44, [])
    index = PluginIndex([rec('QUST', 0x100, [('EDID', zs('Q'))] + alias), ref])
    [f] = quest_start.alias_findings('G', index)
    assert f.severity == 'error' and 'cannot start' in f.summary and 'deleted' in f.detail[0]


def test_inert_findings_group_only_quest_moving_commands(tmp_path):
    """A `;NE:` KillActor is reported by command; a `;NE:` SetCombatStyle is not."""
    (tmp_path / 'A.psc').write_text('  ;NE: TODO: bossRef.KillActor\n  ;NE: SetCombatStyle x\n')
    [f] = script_health.inert_findings('G', tmp_path, lambda script: 'SomeQuest')
    assert f.key == 'scripts|G|inert|killactor' and 'SomeQuest' in f.detail[0]


def test_an_unbound_property_counts_only_when_code_uses_it(tmp_path):
    """A property used only inside a comment is harmless; one used in code reads None."""
    (tmp_path / 's.psc').write_text('Actor Property Foo Auto\nActor Property Bar Auto\n'
                                    'Foo.Kill()\n;NE: Bar.Kill()\n')
    index = PluginIndex([rec('ACTI', 1, [('VMAD', vmad('s'))]),
                         rec('NPC_', 2, [('EDID', zs('Foo'))]), rec('NPC_', 3, [('EDID', zs('Bar'))])])
    declared = {('s', 'Foo'): ('Actor', True), ('s', 'Bar'): ('Actor', True)}
    [f] = script_health.unbound_findings('G', index, declared, tmp_path)
    assert f.key == 'scripts|G|unbound|Actor|NPC_' and f.detail == ('s.Foo',)


def test_compile_failures_group_by_cause(tmp_path):
    """Two scripts failing the same way are one finding; an unlogged missing .pex is its own cause."""
    (tmp_path / 'compile_errors.log').write_text('X_A.psc(3,4): variable Foo is undefined\n'
                                                  'X_B.psc(9,1): variable Bar is undefined\n')
    scripts = {'x_a': Script('X_A', False), 'x_b': Script('X_B', False), 'x_c': Script('X_C', False)}
    causes = sorted(f.summary for f in script_health.compile_findings('G', tmp_path, scripts))
    assert causes == ['1 scripts failed to compile: no .pex and no logged error',
                      '2 scripts failed to compile: variable # is undefined']


def test_a_binding_fits_when_any_record_under_the_id_does():
    """Records sharing a local id bind when any type fits, else all are named."""
    assert binding_problem([('REFR', 'A'), ('QUST', 'Q')], {'QUST'}) is None
    assert binding_problem([('REFR', 'A'), ('STAT', 'B')], {'QUST'}) == ('REFR/STAT', 'A')
    assert binding_problem([], {'QUST'}) == ('<no such record>', None)


def ctda(func, param, flags=0):
    """A decoded `func(param) == 1` condition, OR'd with the next when flags has 0x01."""
    return (flags, 1.0, func, param, 0)


def test_only_an_all_getisid_or_chain_binds_the_speaker():
    """GetIsID OR'd with a faction test lets anyone in; two GetIsID chains intersect."""
    assert required_speakers([ctda(72, 5, 1), ctda(71, 9)]) is None
    assert required_speakers([ctda(72, 5, 1), ctda(72, 6)]) == [5, 6]
    assert required_speakers([ctda(72, 5), ctda(72, 6)]) == []


def test_lines_lost_behind_a_hello_greeting_are_ranked_by_quest(tmp_path):
    """The Amata case as dialogue loss: the reply anyone may say counts against its quest."""
    source, scripts = greeting_game(tmp_path)
    ctx = quest_progression.QuestContext('Test.esm', source, scripts, built_greeting(False))
    [f] = dialogue_loss.speaker_findings(ctx, dialogue_loss.lost_lines(ctx))
    assert f.key == 'dialogue|Test.esm|anyone|TestQ' and 'lost 1 dialogue lines' in f.summary


def test_two_hello_topics_in_one_quest_are_flagged():
    """Skyrim honors one topic per bark subtype per quest."""
    quest = struct.pack('<I', 0x100)
    index = PluginIndex([rec('QUST', 0x100, [('EDID', zs('Q'))]),
                         rec('DIAL', 0x200, [('EDID', zs('A')), ('SNAM', b'HELO'), ('QNAM', quest)]),
                         rec('DIAL', 0x201, [('EDID', zs('B')), ('SNAM', b'HELO'), ('QNAM', quest)]),
                         rec('DIAL', 0x202, [('EDID', zs('C')), ('SNAM', b'CUST'), ('QNAM', quest)])])
    [f] = dialogue_loss.bark_findings('G', index)
    assert f.key == 'dialogue|G|bark|Q|HELO' and f.detail == ('A', 'B')


def pldt(kind, value):
    """A 12-byte package location or target entry."""
    return struct.pack('<IIi', kind, value, 0)


def test_package_records_schedules_and_navmesh():
    """A missing target is an error, a date of 40 is out of range, a cell without navmesh is reviewed."""
    sched = struct.pack('<bbBbbxxxi', -1, -1, 40, 8, 0, 60)
    index = PluginIndex([rec('PACK', 0x300, [('EDID', zs('P')), ('PSDT', sched), ('PLDT', pldt(0, 0x999)),
                                             ('PTDA', pldt(0, 0x400))]),
                         rec('CELL', 0x500, [('EDID', zs('Room')), ('DATA', b'\x01\x00')]),
                         TES5Record('REFR', 0, 0, 0x400, 44, [Sub('EDID', zs('Spot'))], parent_cell=0x500)])
    keys = {(f.key, f.severity) for f in package_ai.audit('G', index)}
    assert keys == {('packages|G|record|P', 'error'), ('packages|G|schedule|P', 'error'),
                    ('packages|G|navmesh|Room', 'review')}


def test_an_npc_runs_its_templates_packages_when_flagged():
    """ACBS template flag 0x20 hands an NPC its template's PKID list."""
    acbs = bytearray(24)
    struct.pack_into('<H', acbs, 18, 0x20)
    base = rec('NPC_', 0x10, [('PKID', struct.pack('<I', 0x300))])
    child = rec('NPC_', 0x11, [('ACBS', bytes(acbs)), ('TPLT', struct.pack('<I', 0x10))])
    index = PluginIndex([base, child])
    assert package_ai.package_source(index, child) is base
    assert package_ai.users(index)[0][0x300] == {0x10, 0x11}


def door(fid, target, cell):
    """A teleport door REFR in `cell` leading to `target`."""
    return TES5Record('REFR', 0, 0, fid, 44, [Sub('XTEL', struct.pack('<I', target) + bytes(28))], parent_cell=cell)


def test_world_links_flag_broken_doors_traps_targets_and_markers():
    """A one-way door into an interior traps the player; a missing door, bad target and nameless marker too."""
    index = PluginIndex([
        rec('CELL', 0x50, [('EDID', zs('Out')), ('DATA', b'\x00\x00')]),
        rec('CELL', 0x51, [('EDID', zs('In')), ('DATA', b'\x01\x00')]),
        door(0x60, 0x61, 0x50), TES5Record('REFR', 0, 0, 0x61, 44, [], parent_cell=0x51),
        door(0x62, 0x999, 0x50),
        rec('QUST', 0x70, [('EDID', zs('Q')), ('ALST', struct.pack('<I', 0)), ('ALED', b''),
                           ('QSTA', struct.pack('<iI', 3, 0))]),
        rec('REFR', 0x80, [('XMRK', b'')])])
    keys = {(f.key, f.severity) for f in world_links.audit('G', index)}
    assert keys == {('world|G|door|00000060', 'error'), ('world|G|door|00000062', 'error'),
                    ('world|G|trapped|In', 'review'), ('world|G|target|Q', 'error'),
                    ('world|G|marker|nameless', 'review')}


#: Papyrus log lines of each shape the triage groups, with their stack frames.
PAPYRUS = [
    'error: Property Door on script X_A attached to  (0F000001) cannot be bound because  (0F000002) is not the right type',
    'error: Property Gone on script X_A attached to  (0F000001) cannot be bound because <nullptr form> (0F000003) is not'
    ' the right type',
    'error: Unable to bind script X_B to  (0F000004) because their base types do not match',
    'Cannot open store for class "X_C", missing file?',
    'warning: Property Old on script X_A attached to  (0F000001) cannot be initialized because the script no longer '
    'contains that property',
    'error: Cannot call Enable() on a None object, aborting function call',
    'stack:',
    '\t[ (0F000001)].X_A.OnActivate() - "X_A.psc" Line 12',
    'error: Property Mine on script OtherMod attached to  (05000001) cannot be bound because  (05000002) is not the right'
    ' type',
]


def test_papyrus_lines_group_by_cause_and_fold_predicted_bindings():
    """Each shape is its own cause; another mod's line is dropped; a predicted binding folds into one review."""
    found = log_triage.papyrus_findings('G', 'X_', log_triage.classify(PAPYRUS), {('x_a', 'door')})
    keys = {(f.key, f.severity) for f in found}
    assert keys == {('logs|G|binding|predicted', 'review'), ('logs|G|binding|X_A|Gone', 'error'),
                    ('logs|G|bind-script|X_B', 'error'), ('logs|G|missing-class|X_C', 'error'),
                    ('logs|G|stale|X_A|Old', 'review'),
                    ('logs|G|runtime|Cannot call Enable() on a None object, aborting function call|X_A.OnActivate',
                     'error')}


def test_recorder_stages_map_to_this_plugins_quests():
    """The load-order byte is found from the events, and stages come back by quest EditorID."""
    index = PluginIndex([rec('QUST', 0x01001000, [('EDID', zs('TestQ'))])], masters=('Skyrim.esm',))
    events = [{'ev': 'quest_stage', 'quest': '0F001000', 'stage': 10},
              {'ev': 'quest_stage', 'quest': '0F001000', 'stage': 20},
              {'ev': 'quest_stage', 'quest': '00012345', 'stage': 5}]
    assert log_triage.stages_seen(index, events) == [('testq', 10), ('testq', 20)]


def test_an_actor_script_on_a_container_cannot_attach():
    """A script whose chain ends in Actor attaches only to an ACHR or NPC_."""
    index = PluginIndex([rec('CONT', 1, [('EDID', zs('Box')), ('VMAD', vmad('X_Loot'))]),
                         rec('NPC_', 2, [('VMAD', vmad('X_Loot'))])])
    extends = {'x_loot': 'x_base', 'x_base': 'actor'}
    [f] = script_health.attach_findings('G', index, extends)
    assert f.key == 'scripts|G|attach|actor|CONT' and f.detail == ('x_loot on Box',)


def test_a_reference_property_needs_a_persistent_placed_reference():
    """A script extending Actor cannot hold a base record or a reference that is not persistent."""
    index = PluginIndex([rec('NPC_', 1, [('EDID', zs('Base'))]),
                         TES5Record('REFR', 0, 0, 2, 44, []), TES5Record('REFR', 0, 0x400, 3, 44, [])])
    extends = {'x_spawn': 'actor'}
    assert reference_problem(index, 1, 'X_Spawn', extends)[0] == 'a NPC_ base, not a reference'
    assert reference_problem(index, 2, 'X_Spawn', extends)[0] == 'a reference that is not persistent'
    assert reference_problem(index, 3, 'X_Spawn', extends) is None
    assert reference_problem(index, 1, 'MiscObject', extends) is None
