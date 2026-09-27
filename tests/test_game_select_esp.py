"""Structural tests for the TESGameSelect plugin (tools/release/make_game_select_esp.py).

They lock the contracts that are invisible in game until already broken: the
MESG button/condition layout (a wrong one starts the wrong game), the MQ101
fragment retargets, and the travel quest and scroll records.
See: docs/commentary/tesgameselect.md#records
"""
import os
import re
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.release.make_game_select_esp import (
    ALCA_IN_INVENTORY, ALIAS_PLAYER, ALIAS_QUEST_OBJECT, ALIAS_SCROLL, BUTTONS,
    FID_ELDER_SCROLL, FID_FLST_MENUS, FID_GLOB_PLAYER_ATTRIBUTES, FID_FLST_TRAVEL, FID_GAMEHOUR,
    FID_GLOB_CURRENT, FID_HOLDING_CELL_MARKER, FID_MESG, FID_MESG_TRAVEL,
    FID_MQ101, FID_PLAYER_REF, FID_QUST, FID_SCROLL, FID_STASH_CHEST,
    FID_TRAVEL_QUST, FUNC_GET_GLOBAL_VALUE, GLOBALS, MAX_MESG_BUTTONS,
    MESG_VARIANTS, MQ101_RETARGETS, MQ101_SCRIPT_NAME, MQ101_TAKEOVER_STAGE,
    MQ101_VANILLA_FRAGMENT_SCRIPT, MQ101_VANILLA_STAGE0_ENTRIES, OP_NOT_EQUAL, PLAYER_ATTRIBUTE_GLOBALS,
    PLAYER_SCRIPT_NAME, QUEST_TYPE_NONE, SCRIPT_NAME, SCROLL_SCRIPT_NAME,
    SGE_FLAGS, TRAVEL_SCRIPT_NAME, TRAVEL_STAY, TRAVEL_VARIANTS,
    _skip_script_entry, build_plugin, prologue_for, travel_label, travel_props,
    write_seq)
from tes5_import.base.tes5_reader import records

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PSC_DIR = os.path.join(ROOT, 'TESGameSelect', 'scripts', 'source')


def _parse(data):
    """{(type, formid): [(subtype, payload), ...]}, TES4 header included."""
    return {(rec.sig.decode('ascii'), rec.form_id):
            [(t.decode('ascii'), d) for t, d in rec.subs()]
            for rec in records(data, span=(0, len(data)))}


def _psc(name):
    """The text of one hand-written script source."""
    with open(os.path.join(PSC_DIR, name + '.psc'), encoding='utf-8') as fh:
        return fh.read()


@pytest.fixture(scope='module')
def skyrim_esm():
    """The installed Skyrim.esm, which the MQ101 override and the scroll copy from."""
    from convert import load_config
    from source_paths import find_game_path
    try:
        cfg = load_config()
    except (FileNotFoundError, OSError):
        cfg = {}
    data_path = find_game_path('skyrimse', cfg)
    if not data_path:
        pytest.skip('Skyrim SE install not found')
    path = os.path.join(data_path, 'Skyrim.esm')
    if not os.path.isfile(path):
        pytest.skip(f'Skyrim.esm not found at {path}')
    return path


@pytest.fixture(scope='module')
def built(skyrim_esm):
    """(plugin bytes, HEDR count, parsed records)."""
    data, count = build_plugin(skyrim_esm)
    return data, count, _parse(data)


@pytest.fixture(scope='module')
def vanilla(skyrim_esm):
    """{(type, formid): record} for vanilla MQ101 and DA04ElderScroll."""
    from tools.release.make_game_select_esp import vanilla_records
    return vanilla_records(skyrim_esm)


def _buttons(subs):
    """[(label, [(func, param1, comp, type byte)])] for one MESG, in index order."""
    out = []
    for stype, payload in subs:
        if stype == 'ITXT':
            out.append((payload.rstrip(b'\0').decode(), []))
        elif stype == 'CTDA':
            out[-1][1].append((struct.unpack_from('<H', payload, 8)[0],
                               struct.unpack_from('<I', payload, 12)[0],
                               struct.unpack_from('<f', payload, 4)[0],
                               payload[0]))
    return out


def _script_props(vmad, pos):
    """({property: formid}, next pos) for the script entry at `pos`."""
    pos += 2 + struct.unpack_from('<H', vmad, pos)[0] + 1
    count = struct.unpack_from('<H', vmad, pos)[0]
    pos += 2
    props = {}
    for _ in range(count):
        plen = struct.unpack_from('<H', vmad, pos)[0]
        name = vmad[pos + 2:pos + 2 + plen].decode()
        pos += 2 + plen
        assert vmad[pos] == 1, 'all properties are Object-typed'
        _unused, alias, fid = struct.unpack_from('<HhI', vmad, pos + 2)
        assert alias == -1
        props[name] = fid
        pos += 10
    return props, pos


def _decode_quest_vmad(vmad):
    """(script names, fragments, alias count) from a QUST VMAD."""
    script_count = struct.unpack_from('<H', vmad, 4)[0]
    pos, names = 6, []
    for _ in range(script_count):
        nlen = struct.unpack_from('<H', vmad, pos)[0]
        names.append(vmad[pos + 2:pos + 2 + nlen].decode())
        pos = _skip_script_entry(vmad, pos)
    frag_count = struct.unpack_from('<H', vmad, pos + 1)[0]
    pos += 3
    pos += 2 + struct.unpack_from('<H', vmad, pos)[0]
    frags = []
    for _ in range(frag_count):
        stage, log = struct.unpack_from('<II', vmad, pos)
        pos += 9
        script_end = pos + 2 + struct.unpack_from('<H', vmad, pos)[0]
        frag_end = script_end + 2 + struct.unpack_from('<H', vmad, script_end)[0]
        frags.append((stage, log, vmad[pos + 2:script_end].decode(),
                      vmad[script_end + 2:frag_end].decode()))
        pos = frag_end
    return names, frags, struct.unpack_from('<h', vmad, pos)[0]


def _mq101_vmads(built, vanilla):
    """(our MQ101 VMAD, vanilla MQ101 VMAD)."""
    ours = dict(built[2][('QUST', FID_MQ101)])['VMAD']
    theirs = next(s.data for s in vanilla[('QUST', FID_MQ101)].subrecords
                  if s.type == 'VMAD')
    return ours, theirs


def test_prologue_names_only_installed_games():
    """A line shows exactly when some installed game uses it; Skyrim's always.

    See: docs/commentary/tesgameselect.md#menu-variants
    """
    gated = [i for i, b in enumerate(BUTTONS) if b[1] is not None]
    for mask in range(MESG_VARIANTS):
        text = prologue_for(mask)
        assert BUTTONS[0][2] in text
        for idx in gated:
            line = BUTTONS[idx][2]
            users = [g for g in gated if BUTTONS[g][2] == line]
            shown = any(mask & (1 << gated.index(u)) for u in users)
            assert (line in text) == shown, f'mask {mask}: {line!r}'


def test_game_order_is_the_published_one():
    """Skyrim, Cyrodiil, both Vvardenfells, Nehrim, Arktwend, Mojave, in index order."""
    assert [b[0] for b in BUTTONS] == ['Skyrim', 'Cyrodiil', 'Vvardenfell',
                                       'Vvardenfell', 'Nehrim', 'Arktwend',
                                       'Mojave']


def test_menu_lists_hold_every_variant_in_mask_order(built):
    """Entry N of each FLST is the MESG variant for mask N."""
    recs = built[2]
    for flst, first, count in ((FID_FLST_MENUS, FID_MESG, MESG_VARIANTS),
                               (FID_FLST_TRAVEL, FID_MESG_TRAVEL, TRAVEL_VARIANTS)):
        listed = [struct.unpack('<I', d)[0] for s, d in recs[('FLST', flst)]
                  if s == 'LNAM']
        assert listed == [first + m for m in range(count)]
        assert all(('MESG', first + m) in recs for m in range(count))


def test_header_declares_only_skyrim_master(built):
    """Mastering a converted game would stop the plugin loading without it."""
    masters = [p.rstrip(b'\0').decode() for t, p in built[2][('TES4', 0)]
               if t == 'MAST']
    assert masters == ['Skyrim.esm']


def test_hedr_count_matches_contents(built):
    """HEDR counts records + GRUPs; the engine walks the file by it.

    See: docs/commentary/tesgameselect.md#records
    """
    _data, count, recs = built
    hedr = dict(recs[('TES4', 0)])['HEDR']
    assert struct.unpack('<I', hedr[4:8])[0] == count
    assert count == (len(GLOBALS) + len(PLAYER_ATTRIBUTE_GLOBALS) + 1 + 1 + 2 + MESG_VARIANTS
                     + TRAVEL_VARIANTS + 3 + 5)


def test_selector_quest_is_not_start_game_enabled(built):
    """The MQ101 fragment drives the selector; SGE made OnInit show it twice."""
    dnam = dict(built[2][('QUST', FID_QUST)])['DNAM']
    flags, priority, _fv, _unknown, qtype = struct.unpack('<HBBII', dnam)
    assert flags & 0x01 == 0
    assert (qtype, priority) == (QUEST_TYPE_NONE, 0)


def test_seq_lists_only_the_travel_quest(tmp_path):
    """The travel quest is the plugin's one Start-Game-Enabled quest."""
    with open(write_seq(str(tmp_path)), 'rb') as fh:
        assert fh.read() == struct.pack('<I', FID_TRAVEL_QUST)


def test_prompt_buttons_are_the_game_ids_and_gated(built):
    """Show() returns the button's own index, so ITXT order IS the game id.

    Skyrim's button is unconditional so the prompt is never empty; every other
    button is gated on its own installed global.
    """
    buttons = _buttons(built[2][('MESG', FID_MESG)])
    assert [b[0] for b in buttons] == [b[0] for b in BUTTONS]
    for (label, conds), (_text, gate, _line) in zip(buttons, BUTTONS):
        expected = [] if gate is None else [(FUNC_GET_GLOBAL_VALUE, gate, 1.0, 0)]
        assert conds == expected, label
    assert dict(built[2][('MESG', FID_MESG)])['DNAM'] == b'\x01\x00\x00\x00'


def test_travel_menu_labels_follow_the_started_set(built):
    """Started games read "Return to", the rest "Begin"; Stay is last and ungated.

    See: docs/commentary/tesgameselect.md#menu-variants
    """
    for mask in (0, 1, 0b1010010, TRAVEL_VARIANTS - 1):
        buttons = _buttons(built[2][('MESG', FID_MESG_TRAVEL + mask)])
        assert len(buttons) == len(BUTTONS) + 1 <= MAX_MESG_BUTTONS
        assert buttons[-1] == (TRAVEL_STAY, [])
        for game, (label, _conds) in enumerate(buttons[:-1]):
            assert label == travel_label(game, mask)
            assert label.startswith('Return to' if mask >> game & 1 else 'Begin')


def test_travel_buttons_hide_absent_games_and_the_current_one(built):
    """Each game's button: its installed gate (not Skyrim's), and CurrentGame != id."""
    buttons = _buttons(built[2][('MESG', FID_MESG_TRAVEL)])
    for game, ((_label, conds), (_t, gate, _l)) in enumerate(zip(buttons, BUTTONS)):
        current = (FUNC_GET_GLOBAL_VALUE, FID_GLOB_CURRENT, float(game), OP_NOT_EQUAL)
        expected = ([] if gate is None else [(FUNC_GET_GLOBAL_VALUE, gate, 1.0, 0)])
        assert conds == expected + [current]


def test_travel_quest_starts_with_the_scroll_as_a_quest_item(built):
    """SGE, a forced Player alias, and the scroll created in its inventory as a Quest Object.

    See: docs/commentary/tesgameselect.md#travel-scroll
    """
    subs = built[2][('QUST', FID_TRAVEL_QUST)]
    flags = struct.unpack_from('<H', dict(subs)['DNAM'], 0)[0]
    assert flags == SGE_FLAGS
    fields = [(t, d) for t, d in subs if t in ('ALST', 'FNAM', 'ALFR', 'ALCO', 'ALCA')]
    as_int = [(t, struct.unpack('<I', d)[0]) for t, d in fields]
    assert as_int == [('ALST', ALIAS_PLAYER), ('FNAM', 0x292),
                      ('ALFR', FID_PLAYER_REF), ('ALST', ALIAS_SCROLL),
                      ('FNAM', ALIAS_QUEST_OBJECT), ('ALCO', FID_SCROLL),
                      ('ALCA', ALCA_IN_INVENTORY | ALIAS_PLAYER)]


def test_travel_quest_vmad_binds_both_scripts(built):
    """The quest script's properties, and the Player alias script bound to alias 0."""
    vmad = dict(built[2][('QUST', FID_TRAVEL_QUST)])['VMAD']
    assert struct.unpack_from('<HHH', vmad, 0) == (5, 2, 1)
    props, pos = _script_props(vmad, 6)
    assert props == travel_props()
    assert struct.unpack_from('<bH', vmad, pos) == (2, 0)
    pos += 3 + 2
    assert struct.unpack_from('<h', vmad, pos)[0] == 1
    assert struct.unpack_from('<HhI', vmad, pos + 2) == (0, ALIAS_PLAYER, FID_TRAVEL_QUST)
    name_at = pos + 2 + 8 + 6
    alias_props, end = _script_props(vmad, name_at)
    assert vmad[name_at + 2:name_at + 2 + len(PLAYER_SCRIPT_NAME)].decode() == PLAYER_SCRIPT_NAME
    assert alias_props == {'Travel': FID_TRAVEL_QUST}
    assert end == len(vmad)


def test_scroll_copies_the_vanilla_elder_scroll(built, vanilla):
    """Vanilla bounds, model and inventory art; weightless, valueless; our script bound."""
    ours = dict(built[2][('BOOK', FID_SCROLL)])
    theirs = {s.type: s.data for s in vanilla[('BOOK', FID_ELDER_SCROLL)].subrecords}
    for field in ('OBND', 'MODL', 'MODT', 'INAM'):
        assert ours[field] == theirs[field], field
    assert struct.unpack_from('<If', ours['DATA'], 8) == (0, 0.0)
    props, _end = _script_props(ours['VMAD'], 6)
    assert ours['VMAD'][8:8 + len(SCROLL_SCRIPT_NAME)].decode() == SCROLL_SCRIPT_NAME
    assert props == {'Travel': FID_TRAVEL_QUST}


def test_selector_vmad_binds_every_script_property(built):
    """The VMAD property names must match the .psc; a typo binds to nothing."""
    vmad = dict(built[2][('QUST', FID_QUST)])['VMAD']
    assert struct.unpack_from('<HHH', vmad, 0) == (5, 2, 1)
    assert vmad[8:8 + len(SCRIPT_NAME)].decode() == SCRIPT_NAME
    props, end = _script_props(vmad, 6)
    expected = {edid.replace('TESGS_', ''): fid for fid, edid in GLOBALS}
    expected['Menus'] = FID_FLST_MENUS
    assert props == expected
    assert end == len(vmad)


def test_globals_are_short_typed_and_zeroed(built):
    """A stale 1 from authoring would offer a game that is not installed."""
    for fid, edid in GLOBALS + [(FID_GLOB_CURRENT, 'TESGS_CurrentGame')]:
        subs = dict(built[2][('GLOB', fid)])
        assert subs['EDID'].rstrip(b'\0').decode() == edid
        assert subs['FNAM'] == b's'
        assert struct.unpack('<f', subs['FLTV'])[0] == 0.0


def test_mq101_override_retargets_only_its_two_fragments(built, vanilla):
    """Stage 0 / 0 runs RunTakeover and stage 10 / 0 RunOpening; the rest is vanilla.

    See: docs/commentary/tesgameselect.md#mq101-takeover
    """
    ours, theirs = _mq101_vmads(built, vanilla)
    v_names, v_frags, v_aliases = _decode_quest_vmad(theirs)
    o_names, o_frags, o_aliases = _decode_quest_vmad(ours)
    assert o_names == v_names + [MQ101_SCRIPT_NAME]
    assert o_aliases == v_aliases
    v_by_key = {(s, l): (sc, fn) for s, l, sc, fn in v_frags}
    o_by_key = {(s, l): (sc, fn) for s, l, sc, fn in o_frags}
    assert set(o_by_key) == set(v_by_key)
    for key, value in v_by_key.items():
        if key in MQ101_RETARGETS:
            vanilla_frag, ours_frag = MQ101_RETARGETS[key]
            assert value == (MQ101_VANILLA_FRAGMENT_SCRIPT, vanilla_frag)
            assert o_by_key[key] == (MQ101_SCRIPT_NAME, ours_frag)
        else:
            assert o_by_key[key] == value, key


def test_mq101_override_keeps_stage_log_entries_identical(built, vanilla):
    """No log entry is added or removed; stage 0 keeps its five vanilla entries."""
    def entry_counts(subs):
        """{stage: QSDT count}."""
        counts, current = {}, None
        for stype, payload in subs:
            if stype == 'INDX':
                current = struct.unpack_from('<H', payload, 0)[0]
                counts.setdefault(current, 0)
            elif stype == 'QSDT' and current is not None:
                counts[current] += 1
        return counts

    ours = entry_counts(built[2][('QUST', FID_MQ101)])
    theirs = entry_counts([(s.type, s.data)
                           for s in vanilla[('QUST', FID_MQ101)].subrecords])
    assert theirs[MQ101_TAKEOVER_STAGE] == MQ101_VANILLA_STAGE0_ENTRIES
    assert ours == theirs


def test_mq101_takeover_script_properties_bound(built, vanilla):
    """The takeover's selector, holding cell, GameHour, stash chest and travel quest."""
    ours, _theirs = _mq101_vmads(built, vanilla)
    pos = 6
    for _ in range(struct.unpack_from('<H', ours, 4)[0]):
        nlen = struct.unpack_from('<H', ours, pos)[0]
        if ours[pos + 2:pos + 2 + nlen].decode() == MQ101_SCRIPT_NAME:
            props, _end = _script_props(ours, pos)
            break
        pos = _skip_script_entry(ours, pos)
    assert props == {'Selector': FID_QUST,
                     'HoldingCellMarker': FID_HOLDING_CELL_MARKER,
                     'GameHour': FID_GAMEHOUR, 'StashChest': FID_STASH_CHEST,
                     'Travel': FID_TRAVEL_QUST}


def test_script_game_constants_match_the_button_order():
    """Each GAME_* constant equals its button's index; Show() returns that index."""
    text = _psc(SCRIPT_NAME)
    names = {fid: 'GAME_' + edid.replace('TESGS_Has', '').upper()
             for fid, edid in GLOBALS}
    names[None] = 'GAME_SKYRIM'
    for index, button in enumerate(BUTTONS):
        match = re.search(rf'Property {names[button[1]]}\s*=\s*(\d+)', text)
        assert match and int(match.group(1)) == index, names[button[1]]
    count = re.search(r'Property GAME_COUNT\s*=\s*(\d+)', text)
    assert count and int(count.group(1)) == len(BUTTONS)


def test_scripts_size_their_arrays_to_the_game_count():
    """Papyrus array sizes are literals; each must equal the number of games."""
    for name in (SCRIPT_NAME, TRAVEL_SCRIPT_NAME):
        sizes = re.findall(r'new \w+\[(\d+)\]', _psc(name))
        assert sizes and all(int(s) == len(BUTTONS) for s in sizes), name


def test_scripts_never_compare_an_array_to_none():
    """`array == None` compiles to a None->array cast the VM rejects, killing the call.

    See: docs/commentary/tesgameselect.md#travel-scroll
    """
    for name in (SCRIPT_NAME, MQ101_SCRIPT_NAME, TRAVEL_SCRIPT_NAME):
        text = _psc(name)
        arrays = re.findall(r'^\s*\w+\[\]\s+(\w+)', text, re.M)
        for var in arrays:
            assert not re.search(rf'\b{var}\s*[!=]=\s*None\b', text), (name, var)


def test_start_functions_never_clear_the_inventory():
    """Starting a game adds and equips its intro items; nothing strips the player.

    See: docs/commentary/tesgameselect.md#starting-equipment
    """
    text = _psc(SCRIPT_NAME)
    assert 'RemoveAllItems' not in text
    assert 'SetValue(1.0)' in text, 'a TES3 start sets CharGenState to 1'


def _function_body(text, name):
    """The source of one Papyrus function, signature through EndFunction."""
    match = re.search(rf'^\w*\s*Function {name}\(.*?^EndFunction', text, re.M | re.S)
    assert match, name
    return match.group(0)


def test_mq101_is_run_once_so_the_takeover_never_stops_it(vanilla):
    """A stopped Run Once MQ101 never starts again, and "Begin Skyrim" dies with it.

    See: docs/commentary/tesgameselect.md#mq101-takeover
    """
    dnam = next(s.data for s in vanilla[('QUST', FID_MQ101)].subrecords
                if s.type == 'DNAM')
    assert struct.unpack_from('<H', dnam, 0)[0] & 0x0100
    code = re.sub(r';.*', '', _psc(MQ101_SCRIPT_NAME))
    assert not re.search(r'\bStop\(\)', code)


def test_takeover_strips_the_coc_items_after_the_menu():
    """Stripped before the load, what the player put on while loading survived.

    See: docs/commentary/tesgameselect.md#mq101-takeover
    """
    body = _function_body(_psc(MQ101_SCRIPT_NAME), 'RunTakeover')
    assert body.index('RunSelection()') < body.index('RemoveAllItems()')
    assert body.index('RemoveAllItems()') < body.index('BeginChosenGame()')


def test_travel_never_adopts_the_choice_while_the_prompt_is_up():
    """ChosenGame reads Skyrim during the prompt; adopting it offered "Return to Skyrim".

    See: docs/commentary/tesgameselect.md#mq101-takeover
    """
    sync = _function_body(_psc(TRAVEL_SCRIPT_NAME), 'Sync')
    assert '!Selector.Selecting' in sync
    takeover = _function_body(_psc(MQ101_SCRIPT_NAME), 'RunTakeover')
    assert takeover.index('Selecting = false') < takeover.index('Travel.Arrive')


def test_nehrim_main_quest_is_held_only_after_another_game_is_chosen():
    """Stopping MQ00 before the choice made it fail and restart when Nehrim was picked.

    See: docs/commentary/tesgameselect.md#opening-hold
    """
    text = _psc(SCRIPT_NAME)
    assert 'NehrimMainQuestID' not in _function_body(text, 'HoldOpeningMovers')
    hold_for = _function_body(text, 'HoldOpeningsFor')
    assert 'GAME_NEHRIM' in hold_for and 'HoldSelfStartingOpenings()' in hold_for


def test_scroll_reads_the_way_vanilla_elder_scrolls_do():
    """OnEquipped, first person, the hand scroll and idle; third person never played it.

    See: docs/commentary/tesgameselect.md#travel-scroll
    """
    assert 'Event OnEquipped(Actor akActor)' in _psc(SCROLL_SCRIPT_NAME)
    read = _function_body(_psc(TRAVEL_SCRIPT_NAME), 'ReadScroll')
    assert 'ForceFirstPerson()' in read and 'ForceThirdPerson' not in read
    order = ['PlayIdle(ReadIdle)', 'BlindIn.Play', 'ReadEffect.Play',
             'BlindImod.Apply', '.Show()', 'PlayIdle(StopIdle)', 'BlindOut.Play']
    positions = [read.index(step) for step in order]
    assert positions == sorted(positions)


def test_no_two_records_share_a_formid(built):
    """The growing MESG blocks must never run into another record."""
    ids = [fid for _sig, fid in built[2] if fid]
    assert len(ids) == len(set(ids))
    blocks = [range(FID_MESG, FID_MESG + MESG_VARIANTS),
              range(FID_MESG_TRAVEL, FID_MESG_TRAVEL + TRAVEL_VARIANTS)]
    others = [fid for sig, fid in built[2] if sig != 'MESG' and fid >> 24 == 1]
    for block in blocks:
        assert not [f for f in others if f in block]


def test_player_attribute_globals_sit_where_the_scripts_read_them(built):
    """TES4Polyfill and the character rules read the player's attributes at 0xAF0 on, Strength to Luck,
    then the two S.P.E.C.I.A.L. stats with no TES4 attribute of their name."""
    _data, _count, recs = built
    names = ['Strength', 'Intelligence', 'Willpower', 'Agility',
             'Speed', 'Endurance', 'Personality', 'Luck', 'Perception', 'Charisma']
    assert FID_GLOB_PLAYER_ATTRIBUTES & 0xFFFFFF == 0xAF0
    assert len(PLAYER_ATTRIBUTE_GLOBALS) == len(names)
    for i, name in enumerate(names):
        subs = dict(recs[('GLOB', FID_GLOB_PLAYER_ATTRIBUTES + i)])
        assert subs['EDID'].rstrip(b'\0').decode() == f'TESGS_Player{name}'
