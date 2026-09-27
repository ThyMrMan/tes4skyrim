"""Build TESGameSelect.esp: the new-game game selector and the Elder Scroll travel item.

Records (all authored here; Skyrim.esm is the only master, and every converted
game's forms resolve at runtime through Game.GetFormFromFile):

  GLOB   one "installed" flag per game, plus TESGS_CurrentGame
  FLST   the new-game prompt variants, and the travel-menu variants
  MESG   the prompt, one per installed-game set; the travel menu, one per
         started-game set
  BOOK   the travel scroll, with vanilla DA04ElderScroll's model and art
  QUST   the selector, the travel quest (Start Game Enabled, holds the scroll),
         and the MQ101 override whose stage-0 and stage-10 fragments are retargeted

Usage:
  python tools/release/make_game_select_esp.py                    # -> output/TESGameSelect/
  python tools/release/make_game_select_esp.py --outdir some/dir
  python tools/release/make_game_select_esp.py --no-compile       # skip Papyrus compile

See: docs/commentary/tesgameselect.md#records
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.subprocess_flags import windows_cmd

from tes5_import.base.writer import (pack_record, pack_subrecord, pack_tes4_header,
                                pack_top_group, pack_string_subrecord,
                                pack_formid_subrecord, pack_uint32_subrecord,
                                count_records_and_groups)
from tes5_import.base.conditions import build_ctda
from tes5_import.base.constants import TES4_ATTRIBUTE_NAMES
from script_convert.pipeline import build_vmad_object_script, build_vmad_quest_fragments
from tools.esm.tes5_esm_reader import read_tes5_file

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_NAME = 'TESGameSelect.esp'
SCRIPT_NAME = 'TESGameSelectQuest'
MQ101_SCRIPT_NAME = 'TESGameSelectMQ101'
TRAVEL_SCRIPT_NAME = 'TESGameSelectTravel'
PLAYER_SCRIPT_NAME = 'TESGameSelectTravelPlayer'
SCROLL_SCRIPT_NAME = 'TESGameSelectScroll'
#: Every hand-written script the plugin ships, compiled and staged together.
SCRIPTS = (SCRIPT_NAME, MQ101_SCRIPT_NAME, TRAVEL_SCRIPT_NAME,
           PLAYER_SCRIPT_NAME, SCROLL_SCRIPT_NAME)

FID_GLOB_SKYRIM       = 0x01000800
FID_GLOB_OBLIVION     = 0x01000801
FID_GLOB_NEHRIM       = 0x01000802
FID_GLOB_MORROBLIVION = 0x01000803
FID_GLOB_FALLOUTNV    = 0x01000804
FID_GLOB_MORROWIND    = 0x01000805
FID_GLOB_ARKTWEND     = 0x01000806
#: The game the player is in; every travel button compares its own id against it.
FID_GLOB_CURRENT      = 0x01000807
#: The prompt variants in mask order, which the selector indexes by installed mask.
FID_FLST_MENUS        = 0x0100080F
#: 2**gated CONSECUTIVE ids from here, a block that GROWS with each gated game.
FID_MESG              = 0x01000810
FID_QUST              = 0x01000A00
FID_TRAVEL_QUST       = 0x01000A01
FID_SCROLL            = 0x01000A02
#: The travel-menu variants in started-mask order.
FID_FLST_TRAVEL       = 0x01000AFF
#: 2**games CONSECUTIVE ids from here, a block that GROWS with each game.
FID_MESG_TRAVEL       = 0x01000B00

FID_MQ101 = 0x0003372B
#: WIDeadBodyCleanupCellMarker: Skyrim's own empty holding cell, where the player waits.
FID_HOLDING_CELL_MARKER = 0x001037F2
FID_GAMEHOUR            = 0x00000038
#: DA04ElderScroll, whose bounds, model and inventory art the travel scroll copies.
FID_ELDER_SCROLL        = 0x0002D513
#: XMarkerHeading: the return point dropped where the player leaves a game.
FID_XMARKER_HEADING     = 0x00000034
#: TreasChestSmallEMPTYNoRespawn: holds the player's items while vanilla stage 10 strips them.
FID_STASH_CHEST         = 0x000F8478
FID_PLAYER_REF          = 0x00000014
#: Vanilla ElderScrollScript's reading pieces: the scroll held in hand, its idle, IdleStop.
FID_SCROLL_IN_HAND      = 0x000F71DF
FID_IDLE_READ_SCROLL    = 0x000EC9D0
FID_IDLE_STOP           = 0x000E4242
#: FXReadElderScrollEffect (RFCT), FXReadScrollsBlindImod (IMAD), OBJElderScrollBlindIn/Out2D (SOUN).
FID_READ_EFFECT         = 0x00044F20
FID_BLIND_IMOD          = 0x00044F3F
FID_BLIND_IN_SOUND      = 0x0010A95A
FID_BLIND_OUT_SOUND     = 0x0010A95B

#: (stage, log entry) -> (vanilla fragment, our replacement) in the MQ101 override.
MQ101_RETARGETS = {(0, 0): ('Fragment_2', 'RunTakeover'),
                   (10, 0): ('Fragment_4', 'RunOpening')}
MQ101_TAKEOVER_STAGE = 0
MQ101_VANILLA_STAGE0_ENTRIES = 5
MQ101_VANILLA_FRAGMENT_SCRIPT = 'QF_MQ101_0003372B'

#: QUST DNAM flags StartGameEnabled | StartsEnabled.
SGE_FLAGS = 0x0011
#: Journal-invisible quest type.
QUEST_TYPE_NONE = 0
#: MESG DNAM bit 0: a modal message box with buttons.
MESG_MESSAGE_BOX = 0x00000001
FUNC_GET_GLOBAL_VALUE = 74
OP_EQUAL = 0x00
OP_NOT_EQUAL = 0x20
#: Alias FNAM bit: Quest Object, so the scroll cannot be dropped, sold or stripped.
ALIAS_QUEST_OBJECT = 0x00000004
#: Alias FNAM the pipeline's own player-script quest writes for its PlayerRef alias.
ALIAS_PLAYER_FLAGS = 0x00000292
#: ALCA high bit: create the object IN the named alias's inventory.
ALCA_IN_INVENTORY = 0x80000000
ALIAS_PLAYER = 0
ALIAS_SCROLL = 1
#: Message.Show() returns 0-9, so a menu holds at most this many buttons.
MAX_MESG_BUTTONS = 10

PROLOGUE_OPEN = (
    "The threads of prophecy gather, but fate has not yet chosen its weave.")
PROLOGUE_CLOSE = "Where does fate bind you?"
TRAVEL_TITLE = "Elder Scroll of Prophecy"
TRAVEL_TEXT = ("The scroll unrolls, and other worlds glimmer through its "
               "script.\n\nWhere do the threads lead?")
TRAVEL_STAY = "Stay"
SCROLL_TEXT = ("<p align='center'>The script shifts as you read, weaving "
               "the threads of many worlds.</p><p align='center'>Close the "
               "scroll to choose where they lead.</p>")

#: (button text, gate global, prologue line). INDEX IS THE GAME ID.
BUTTONS = [
    ("Skyrim", None,
     "A cart of prisoners rolls toward death."),
    ("Cyrodiil", FID_GLOB_OBLIVION,
     "An Emperor dreams of a stranger in a cell."),
    ("Vvardenfell", FID_GLOB_MORROWIND,
     "A ship makes port in a land of ash."),
    ("Vvardenfell", FID_GLOB_MORROBLIVION,
     "A ship makes port in a land of ash."),
    ("Nehrim", FID_GLOB_NEHRIM,
     "A godless land waits for no one."),
    ("Arktwend", FID_GLOB_ARKTWEND,
     "A forgotten realm stirs behind monastery walls."),
    ("Mojave", FID_GLOB_FALLOUTNV,
     "A shallow grave stirs beneath a desert sky."),
]

#: One prompt MESG per subset of the gated games, so each prologue names only those.
MESG_VARIANTS = 1 << sum(1 for _t, gate, _l in BUTTONS if gate is not None)
#: One travel MESG per subset of started games, so each button reads Begin or Return.
TRAVEL_VARIANTS = 1 << len(BUTTONS)

GLOBALS = [
    (FID_GLOB_SKYRIM,       'TESGS_HasSkyrim'),
    (FID_GLOB_OBLIVION,     'TESGS_HasOblivion'),
    (FID_GLOB_NEHRIM,       'TESGS_HasNehrim'),
    (FID_GLOB_MORROBLIVION, 'TESGS_HasMorroblivion'),
    (FID_GLOB_FALLOUTNV,    'TESGS_HasFalloutNV'),
    (FID_GLOB_MORROWIND,    'TESGS_HasMorrowind'),
    (FID_GLOB_ARKTWEND,     'TESGS_HasArktwend'),
]

#: The player's TES4 attributes, one GLOB each from here (below the travel FLST): rules write, TES4Polyfill reads.
FID_GLOB_PLAYER_ATTRIBUTES = 0x01000AF0
PLAYER_ATTRIBUTE_GLOBALS = [(FID_GLOB_PLAYER_ATTRIBUTES + i, f'TESGS_Player{name}')
                            for i, name in enumerate(TES4_ATTRIBUTE_NAMES)]


def build_glob(fid: int, edid: str) -> bytes:
    """A short-typed global, value 0 (vanilla writes the value as a float)."""
    subs = pack_string_subrecord('EDID', edid)
    subs += pack_subrecord('FNAM', b's')
    subs += pack_subrecord('FLTV', struct.pack('<f', 0.0))
    return pack_record('GLOB', fid, 0, subs)


def prologue_for(mask: int) -> str:
    """The prompt text for one installed set, a bitmask over the GATED BUTTONS.

    Skyrim's line is unconditional; every other line appears only when its bit
    is set, and a line two games share (the two Vvardenfells) prints once.
    """
    lines = [PROLOGUE_OPEN, '']
    gated = 0
    for _text, gate, line in BUTTONS:
        shown = gate is None or mask & (1 << gated)
        gated += gate is not None
        if shown and line not in lines:
            lines.append(line)
    return '\n'.join(lines + ['', PROLOGUE_CLOSE])


def gate_ctda(fid: int, value: float, operator: int = OP_EQUAL) -> bytes:
    """One `GetGlobalValue(fid) <op> value` condition subrecord."""
    return pack_subrecord('CTDA', build_ctda(
        FUNC_GET_GLOBAL_VALUE, param1=fid, comp_value=value, operator=operator))


def build_mesg(fid: int, edid: str, title: str, text: str, buttons: list) -> bytes:
    """A message box; `buttons` is [(label, [CTDA subrecords])] in index order.

    INAM is the required, always-NULL "Icon (unused)"; DNAM Auto Display stays
    clear because a script shows the box and reads the pressed index back.
    See: docs/commentary/tesgameselect.md#menu-variants
    """
    subs = pack_string_subrecord('EDID', edid)
    subs += pack_string_subrecord('DESC', text)
    subs += pack_string_subrecord('FULL', title)
    subs += pack_formid_subrecord('INAM', 0)
    subs += pack_uint32_subrecord('DNAM', MESG_MESSAGE_BOX)
    for label, conditions in buttons:
        subs += pack_string_subrecord('ITXT', label) + b''.join(conditions)
    return pack_record('MESG', fid, 0, subs)


def build_prompt(mask: int) -> bytes:
    """The new-game prompt for one installed set; each button gated on its game."""
    buttons = [(text, [gate_ctda(gate, 1.0)] if gate else [])
               for text, gate, _line in BUTTONS]
    return build_mesg(FID_MESG + mask, f'TESGSGameSelectMSG{mask:02d}',
                      'The Threads of Prophecy', prologue_for(mask), buttons)


def travel_label(game: int, started_mask: int) -> str:
    """'Return to <world>' for a started game, else 'Begin <world>'."""
    name = BUTTONS[game][0]
    return f'Return to {name}' if started_mask >> game & 1 else f'Begin {name}'


def build_travel_menu(mask: int) -> bytes:
    """The travel menu for one started set: installed games but the current one, then Stay.

    See: docs/commentary/tesgameselect.md#menu-variants
    """
    buttons = []
    for game, (_text, gate, _line) in enumerate(BUTTONS):
        conditions = [gate_ctda(gate, 1.0)] if gate else []
        conditions.append(gate_ctda(FID_GLOB_CURRENT, float(game), OP_NOT_EQUAL))
        buttons.append((travel_label(game, mask), conditions))
    buttons.append((TRAVEL_STAY, []))
    return build_mesg(FID_MESG_TRAVEL + mask, f'TESGSTravelMSG{mask:03d}',
                      TRAVEL_TITLE, TRAVEL_TEXT, buttons)


def build_form_list(fid: int, edid: str, first: int, count: int) -> bytes:
    """An FLST of `count` consecutive FormIDs from `first`, entry N being `first + N`."""
    subs = pack_string_subrecord('EDID', edid)
    for index in range(count):
        subs += pack_formid_subrecord('LNAM', first + index)
    return pack_record('FLST', fid, 0, subs)


def quest_dnam(flags: int) -> bytes:
    """QUST DNAM: flags, priority 0, form version 0, journal-invisible type."""
    return pack_subrecord('DNAM', struct.pack('<HBBII', flags, 0, 0, 0,
                                              QUEST_TYPE_NONE))


def build_qust() -> bytes:
    """The selector quest: script-only, NOT Start Game Enabled (MQ101 drives it).

    See: docs/commentary/tesgameselect.md#mq101-takeover
    """
    props = {edid.replace('TESGS_', ''): fid for fid, edid in GLOBALS}
    props['Menus'] = FID_FLST_MENUS
    subs = pack_string_subrecord('EDID', 'TESGSGameSelect')
    subs += pack_subrecord('VMAD', build_vmad_object_script(SCRIPT_NAME,
                                                            object_props=props))
    subs += pack_string_subrecord('FULL', 'Threads of Prophecy')
    subs += quest_dnam(0)
    subs += pack_subrecord('NEXT', b'')
    subs += pack_uint32_subrecord('ANAM', 0)
    return pack_record('QUST', FID_QUST, 0, subs)


def travel_props() -> dict:
    """The travel quest script's Object properties."""
    return {'Selector': FID_QUST, 'MQ101': FID_MQ101, 'Menus': FID_FLST_TRAVEL,
            'CurrentGameGlobal': FID_GLOB_CURRENT,
            'ReturnMarker': FID_XMARKER_HEADING, 'ScrollInHand': FID_SCROLL_IN_HAND,
            'ReadIdle': FID_IDLE_READ_SCROLL, 'StopIdle': FID_IDLE_STOP,
            'ReadEffect': FID_READ_EFFECT, 'BlindImod': FID_BLIND_IMOD,
            'BlindIn': FID_BLIND_IN_SOUND, 'BlindOut': FID_BLIND_OUT_SOUND}


def build_travel_quest() -> bytes:
    """The travel quest: Start Game Enabled, Player alias, and the scroll as a quest item.

    See: docs/commentary/tesgameselect.md#travel-scroll
    """
    vmad = build_vmad_quest_fragments(
        'TESGSTravel', [], attached_script=(TRAVEL_SCRIPT_NAME, travel_props()),
        alias_scripts=[(ALIAS_PLAYER, [(PLAYER_SCRIPT_NAME,
                                        {'Travel': FID_TRAVEL_QUST})])],
        quest_fid=FID_TRAVEL_QUST)
    subs = pack_string_subrecord('EDID', 'TESGSTravel')
    subs += pack_subrecord('VMAD', vmad)
    subs += pack_string_subrecord('FULL', 'Threads of Prophecy: Travel')
    subs += quest_dnam(SGE_FLAGS)
    subs += pack_subrecord('NEXT', b'')
    subs += pack_uint32_subrecord('ANAM', ALIAS_SCROLL + 1)
    subs += pack_uint32_subrecord('ALST', ALIAS_PLAYER)
    subs += pack_string_subrecord('ALID', 'Player')
    subs += pack_uint32_subrecord('FNAM', ALIAS_PLAYER_FLAGS)
    subs += pack_formid_subrecord('ALFR', FID_PLAYER_REF)
    subs += pack_formid_subrecord('VTCK', 0) + pack_subrecord('ALED', b'')
    subs += pack_uint32_subrecord('ALST', ALIAS_SCROLL)
    subs += pack_string_subrecord('ALID', 'Scroll')
    subs += pack_uint32_subrecord('FNAM', ALIAS_QUEST_OBJECT)
    subs += pack_formid_subrecord('ALCO', FID_SCROLL)
    subs += pack_uint32_subrecord('ALCA', ALCA_IN_INVENTORY | ALIAS_PLAYER)
    subs += pack_uint32_subrecord('ALCL', 0)
    subs += pack_formid_subrecord('VTCK', 0) + pack_subrecord('ALED', b'')
    return pack_record('QUST', FID_TRAVEL_QUST, 0, subs)


def build_scroll(vanilla) -> bytes:
    """The travel scroll: vanilla DA04ElderScroll's OBND/MODL/MODT/INAM, weightless.

    BOOK DATA is flags, type, 2 unused, teaches, value, weight; value and
    weight are written as 0.
    See: docs/commentary/tesgameselect.md#travel-scroll
    """
    kept = {s.type: s.data for s in vanilla.subrecords}
    data = kept['DATA']
    if len(data) != 16:
        raise SystemExit(f'DA04ElderScroll DATA is {len(data)} bytes, expected 16')
    subs = pack_string_subrecord('EDID', 'TESGSElderScroll')
    subs += pack_subrecord('VMAD', build_vmad_object_script(
        SCROLL_SCRIPT_NAME, object_props={'Travel': FID_TRAVEL_QUST}))
    subs += pack_subrecord('OBND', kept['OBND'])
    subs += pack_string_subrecord('FULL', TRAVEL_TITLE)
    subs += pack_subrecord('MODL', kept['MODL']) + pack_subrecord('MODT', kept['MODT'])
    subs += pack_string_subrecord('DESC', SCROLL_TEXT)
    subs += pack_subrecord('DATA', data[:8] + struct.pack('<If', 0, 0.0))
    subs += pack_subrecord('INAM', kept['INAM']) + pack_subrecord('CNAM', kept['CNAM'])
    return pack_record('BOOK', FID_SCROLL, 0, subs)


def build_mq101_override(src) -> bytes:
    """Vanilla MQ101 verbatim, but for the VMAD retargets in MQ101_RETARGETS.

    Refuses when stage 0 no longer has its five vanilla log entries: the
    layout drifted, and the takeover would replace the wrong one.
    See: docs/commentary/tesgameselect.md#mq101-takeover
    """
    out = b''
    stage_index = None
    stage0_entries = 0
    for sub in src.subrecords:
        data = sub.data
        if sub.type == 'VMAD':
            data = _splice_mq101_vmad(data)
        elif sub.type == 'INDX':
            stage_index = struct.unpack_from('<H', data, 0)[0]
        elif sub.type == 'QSDT' and stage_index == MQ101_TAKEOVER_STAGE:
            stage0_entries += 1
        out += pack_subrecord(sub.type, data)
    if stage0_entries != MQ101_VANILLA_STAGE0_ENTRIES:
        raise SystemExit(
            f'MQ101 stage 0 has {stage0_entries} log entries, expected '
            f'{MQ101_VANILLA_STAGE0_ENTRIES}; re-check the real new-game path '
            f'against the installed Skyrim.esm.')
    return pack_record('QUST', FID_MQ101, src.flags, out)


def _retarget_fragment(vmad: bytes, pos: int):
    """(entry bytes, next pos, retargeted key or None) for one fragment at `pos`."""
    stage, log, unknown = struct.unpack_from('<IIB', vmad, pos)
    name_at = pos + 9
    name_end = _skip_wstring(vmad, name_at)
    script = vmad[name_at + 2:name_end].decode('utf-8')
    frag_end = _skip_wstring(vmad, name_end)
    fragment = vmad[name_end + 2:frag_end].decode('utf-8')
    target = MQ101_RETARGETS.get((stage, log))
    if target is None:
        return vmad[pos:frag_end], frag_end, None
    if (script, fragment) != (MQ101_VANILLA_FRAGMENT_SCRIPT, target[0]):
        raise SystemExit(
            f'MQ101 stage {stage} / log {log} runs {script}.{fragment}, expected '
            f'{MQ101_VANILLA_FRAGMENT_SCRIPT}.{target[0]}; another mod or a game '
            f'update changed the record, refusing to retarget.')
    entry = (struct.pack('<IIB', stage, log, unknown)
             + _pack_wstring(MQ101_SCRIPT_NAME) + _pack_wstring(target[1]))
    return entry, frag_end, (stage, log)


def _splice_mq101_vmad(vmad: bytes) -> bytes:
    """Append our script and retarget each MQ101_RETARGETS fragment; the rest verbatim.

    A QUST VMAD is version, objectFormat, scripts[], then the fragment struct
    (bind version, count, file name, fragments[]), then the aliases array.
    """
    version, obj_format, script_count = struct.unpack_from('<HHH', vmad, 0)
    pos = 6
    for _ in range(script_count):
        pos = _skip_script_entry(vmad, pos)
    scripts_end = pos
    frag_count = struct.unpack_from('<H', vmad, pos + 1)[0]
    pos = _skip_wstring(vmad, pos + 3)
    header = vmad[scripts_end:pos]
    frags, done = b'', set()
    for _ in range(frag_count):
        entry, pos, key = _retarget_fragment(vmad, pos)
        frags += entry
        done.add(key)
    missing = set(MQ101_RETARGETS) - done
    if missing:
        raise SystemExit(f'MQ101 fragments {sorted(missing)} not found; cannot '
                         f'install the takeover')
    our_script = _pack_script_entry(MQ101_SCRIPT_NAME, {
        'Selector': FID_QUST, 'HoldingCellMarker': FID_HOLDING_CELL_MARKER,
        'GameHour': FID_GAMEHOUR, 'StashChest': FID_STASH_CHEST,
        'Travel': FID_TRAVEL_QUST})
    return (struct.pack('<HHH', version, obj_format, script_count + 1)
            + vmad[6:scripts_end] + our_script + header + frags + vmad[pos:])


def _skip_wstring(data: bytes, pos: int) -> int:
    """The offset just past the U16-length string at `pos`."""
    return pos + 2 + struct.unpack_from('<H', data, pos)[0]


def _skip_script_entry(data: bytes, pos: int) -> int:
    """The offset just past one objectFormat-2 script entry (name, flags, properties)."""
    pos = _skip_wstring(data, pos) + 1
    prop_count = struct.unpack_from('<H', data, pos)[0]
    pos += 2
    for _ in range(prop_count):
        pos = _skip_wstring(data, pos)
        prop_type = data[pos]
        pos = _skip_property_value(data, pos + 2, prop_type)
    return pos


def _skip_property_value(data: bytes, pos: int, prop_type: int) -> int:
    """The offset just past one VMAD property value of `prop_type`."""
    fixed = {1: 8, 3: 4, 4: 4, 5: 1}
    if prop_type in fixed:
        return pos + fixed[prop_type]
    if prop_type == 2:
        return _skip_wstring(data, pos)
    if prop_type >= 11:
        count = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        for _ in range(count):
            pos = _skip_property_value(data, pos, prop_type - 10)
        return pos
    raise ValueError(f'unhandled VMAD property type {prop_type}')


def _pack_wstring(text: str) -> bytes:
    """A U16-length UTF-8 string."""
    raw = text.encode('utf-8')
    return struct.pack('<H', len(raw)) + raw


def _pack_script_entry(name: str, object_props: dict) -> bytes:
    """One attached-script entry: name, flags 0, Object-typed Edited properties."""
    out = _pack_wstring(name) + struct.pack('<BH', 0, len(object_props))
    for prop_name, fid in object_props.items():
        out += _pack_wstring(prop_name) + struct.pack('<BBHhI', 1, 1, 0, -1, fid)
    return out


def vanilla_records(skyrim_esm: str) -> dict:
    """{(type, FormID): record} for the vanilla records the plugin copies from."""
    wanted = {('QUST', FID_MQ101), ('BOOK', FID_ELDER_SCROLL)}
    _hdr, recs, _loc = read_tes5_file(skyrim_esm)
    found = {(r.type, r.form_id): r for r in recs if (r.type, r.form_id) in wanted}
    missing = wanted - set(found)
    if missing:
        raise SystemExit(f'{sorted(missing)} not found in {skyrim_esm}')
    return found


def build_plugin(skyrim_esm: str):
    """(plugin bytes, HEDR record count).

    HEDR counts records + GRUPs, as vanilla does; the engine walks the file by
    it, so an undercount silently drops records.
    """
    vanilla = vanilla_records(skyrim_esm)
    globs = [build_glob(f, e) for f, e in GLOBALS]
    globs.append(build_glob(FID_GLOB_CURRENT, 'TESGS_CurrentGame'))
    globs += [build_glob(f, e) for f, e in PLAYER_ATTRIBUTE_GLOBALS]
    groups = [
        pack_top_group('GLOB', b''.join(globs)),
        pack_top_group('BOOK', build_scroll(vanilla[('BOOK', FID_ELDER_SCROLL)])),
        pack_top_group('FLST', build_form_list(
            FID_FLST_MENUS, 'TESGSGameSelectMenus', FID_MESG, MESG_VARIANTS)
            + build_form_list(FID_FLST_TRAVEL, 'TESGSTravelMenus',
                              FID_MESG_TRAVEL, TRAVEL_VARIANTS)),
        pack_top_group('MESG', b''.join(build_prompt(m) for m in range(MESG_VARIANTS))
                       + b''.join(build_travel_menu(m)
                                  for m in range(TRAVEL_VARIANTS))),
        pack_top_group('QUST', build_qust() + build_travel_quest()
                       + build_mq101_override(vanilla[('QUST', FID_MQ101)])),
    ]
    count = sum(count_records_and_groups(g) for g in groups)
    header = pack_tes4_header(
        ['Skyrim.esm'], num_records=count,
        next_object_id=(FID_MESG_TRAVEL + TRAVEL_VARIANTS) & 0xFFFFFF,
        author='TESConversion',
        description='Threads of Prophecy - choose which game to begin, and travel between them',
        is_esm=False)
    return header + b''.join(groups), count


def write_seq(outdir: str) -> str:
    """Write the .seq listing the one Start-Game-Enabled quest (travel); its path.

    The selector stays off it: an older build listed the selector, and its
    OnInit then showed the menu a second time.
    See: docs/commentary/tesgameselect.md#travel-scroll
    """
    seq_dir = os.path.join(outdir, 'seq')
    os.makedirs(seq_dir, exist_ok=True)
    path = os.path.join(seq_dir, os.path.splitext(PLUGIN_NAME)[0] + '.seq')
    with open(path, 'wb') as f:
        f.write(struct.pack('<I', FID_TRAVEL_QUST))
    return path


def compile_scripts(outdir: str) -> bool:
    """Compile every plugin script against the Skyrim SE headers; True when all built."""
    from convert import load_config
    from papyrus_compile import find_skyrim_source_scripts
    try:
        cfg = load_config()
    except (FileNotFoundError, OSError):
        cfg = {}
    headers = find_skyrim_source_scripts(cfg)
    compiler = os.path.join(ROOT, 'external', 'papyrus-compiler', 'papyrus.exe')
    if not headers or not os.path.isfile(compiler):
        print('  ERROR: Skyrim Papyrus source headers (<Skyrim SE>\\Data\\Source'
              f'\\Scripts) or the compiler ({compiler}) not found')
        return False
    src_dir = os.path.join(outdir, 'scripts', 'source')
    out_dir = os.path.join(outdir, 'scripts')
    os.makedirs(out_dir, exist_ok=True)
    return all([_compile_one(compiler, headers, src_dir, out_dir, name)
                for name in SCRIPTS])


def _compile_one(compiler: str, headers: str, src_dir: str, out_dir: str,
                 name: str) -> bool:
    """Compile one script with -nocache (the cache keys on content alone); True on success."""
    cmd = [compiler, 'compile', '-nocache', '-i',
           os.path.join(src_dir, name + '.psc'), '-o', out_dir,
           '-h', headers, '-h', src_dir]
    r = subprocess.run(windows_cmd(cmd), capture_output=True, text=True,
                       timeout=90, cwd=ROOT)
    pex = os.path.join(out_dir, name + '.pex')
    if r.returncode != 0 or not os.path.isfile(pex):
        out = (r.stdout or '') + (r.stderr or '')
        print(f'  COMPILE FAILED ({name}):')
        print('   ', out.strip().replace('\n', '\n    '))
        return False
    print(f'  compiled {name}.pex ({os.path.getsize(pex)} bytes)')
    return True


def resolve_skyrim_esm(explicit: str = None) -> str:
    """The Skyrim.esm whose MQ101 is overridden, or '' when none is found."""
    if not explicit:
        from convert import load_config
        from source_paths import find_game_path
        try:
            cfg = load_config()
        except (FileNotFoundError, OSError):
            cfg = {}
        data_path = find_game_path('skyrimse', cfg)
        if not data_path:
            print('  ERROR: Skyrim SE install not found; pass --skyrim-esm')
            return ''
        explicit = os.path.join(data_path, 'Skyrim.esm')
    if not os.path.isfile(explicit):
        print(f'  ERROR: Skyrim.esm not found at {explicit}')
        return ''
    return explicit


def stage_sources(outdir: str) -> None:
    """Copy the hand-written .psc sources into the shipped Data folder."""
    src_dir = os.path.join(outdir, 'scripts', 'source')
    os.makedirs(src_dir, exist_ok=True)
    for name in SCRIPTS:
        shutil.copyfile(
            os.path.join(ROOT, 'TESGameSelect', 'scripts', 'source', name + '.psc'),
            os.path.join(src_dir, name + '.psc'))


def build(outdir: str, skyrim_esm: str = None, compile_psc: bool = True) -> bool:
    """Build the whole Data folder into `outdir`; True when it is shippable.

    The one implementation behind both the CLI and the packager.
    """
    os.makedirs(outdir, exist_ok=True)
    esm = resolve_skyrim_esm(skyrim_esm)
    if not esm:
        return False
    stage_sources(outdir)
    print(f'Reading MQ101 and DA04ElderScroll from {esm} ...')
    data, count = build_plugin(esm)
    esp_path = os.path.join(outdir, PLUGIN_NAME)
    with open(esp_path, 'wb') as f:
        f.write(data)
    print(f'Wrote {esp_path} ({len(data)} bytes, HEDR numRecords={count})')
    print(f'Wrote {write_seq(outdir)} (the travel quest)')
    return compile_scripts(outdir) if compile_psc else True


def main() -> int:
    """CLI entry point; 0 when the Data folder was built."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--outdir', default='output/TESGameSelect',
                    help='Data-folder-style output root (default: output/TESGameSelect)')
    ap.add_argument('--no-compile', action='store_true',
                    help='Skip Papyrus compilation (plugin only)')
    ap.add_argument('--skyrim-esm', default=None,
                    help='Path to Skyrim.esm (default: the installed game)')
    args = ap.parse_args()
    outdir = args.outdir if os.path.isabs(args.outdir) else os.path.join(ROOT, args.outdir)
    if not build(outdir, skyrim_esm=args.skyrim_esm,
                 compile_psc=not args.no_compile):
        return 1
    print('\nShip the contents of this folder as a Data folder:')
    print(f'  {PLUGIN_NAME}')
    print(f'  seq\\{os.path.splitext(PLUGIN_NAME)[0]}.seq')
    for name in SCRIPTS:
        print(f'  scripts\\{name}.pex')
    return 0


if __name__ == '__main__':
    sys.exit(main())
