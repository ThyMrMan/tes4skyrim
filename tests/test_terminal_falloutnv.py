"""FO3/FNV terminals: exported item by item, and planned as message pages the importer and scripts share.

See: docs/commentary/script_convert.md#terminals
"""
import struct

from script_convert.terminal_plan import MAX_BUTTONS, menu_pages, plan_items, reachable_menus, sub_menus
from tes4_export.record_types.falloutnv import export_deltas, export_TERMINAL
from tes4_export.tes4_reader import Record, Subrecord
from tes5_import.base.object_scripts import holds_vmad
from tes5_import.base.text_reader import set_formid_index_offset
from tes5_import.record_types.world_falloutnv import activate_parent_subrecords


def _overseer():
    """export_TERMINAL over a trimmed CG04 Overseer's terminal: a note item, then a scripted one with conditions."""
    subs = [('EDID', b'CG04OverseersTerminal\0'), ('DESC', b'Welcome, Overseer.\0'),
            ('PNAM', struct.pack('<I', 0x29859)), ('DNAM', b'\x00\x00\x05\x00'),
            ('ITXT', b'View External Contact Report\0'), ('RNAM', b'\0\0\0\0'), ('ANAM', b'\x01'),
            ('INAM', struct.pack('<I', 0xC2F1B)), ('SCHR', bytes(20)),
            ('ITXT', b"Open Overseer's Tunnel\0"), ('RNAM', b'Opening...\0'), ('ANAM', b'\x00'),
            ('SCHR', bytes(20)), ('SCTX', b'setstage CG04 120'), ('SCRO', struct.pack('<I', 0x57AE8)),
            ('SCRO', struct.pack('<I', 0x8AA2F)), ('CTDA', bytes(28)), ('CTDA', b'\x01' + bytes(27))]
    return export_TERMINAL(Record('TERM', 0, 0, 0x29853, [Subrecord(t, d) for t, d in subs]))


def test_each_menu_item_exports_its_fields_in_order():
    """Items split on ITXT; each keeps its note, script, numbered SCROs and conditions."""
    lines = _overseer()
    for line in ('DESC=Welcome, Overseer.', 'PNAM=00029859', 'DNAM.Difficulty=0', 'DNAM.Flags=0', 'ItemCount=2',
                 'Item[0].Text=View External Contact Report', 'Item[0].Flags=1', 'Item[0].Note=000C2F1B',
                 'Item[1].Result=Opening...', 'Item[1].Script=setstage CG04 120', 'Item[1].SCRO[1]=0008AA2F',
                 'Item[1].Condition[1].Raw=01' + '00' * 27):
        assert line in lines, line
    assert not any(line.startswith('Item[0].Script') for line in lines)


def _term(fid, count, subs=()):
    """A TERM record dict with `count` items; `subs` maps an item to the TERM it opens."""
    rec = {'FormID': fid, 'EditorID': f'T{fid}', 'ItemCount': str(count)}
    rec.update({f'Item[{i}].SubMenu': target for i, target in dict(subs).items()})
    return rec


def test_a_long_menu_pages_by_eight_with_more():
    """Nine items fit one page; seventeen take pages of eight, eight, one."""
    assert [p.items for p in menu_pages(_term('A', MAX_BUTTONS - 1))] == [tuple(range(9))]
    pages = menu_pages(_term('A', 17))
    assert [len(p.items) for p in pages] == [8, 8, 1] and [p.more for p in pages] == [True, True, False]


def test_sub_menus_are_reached_once_and_numbered_after_the_root():
    """A sub-menu that links back to its parent is listed once; items number across menus."""
    root, sub = _term('0000000A', 2, {1: '0000000B'}), _term('0000000B', 1, {0: '0000000A'})
    menus = reachable_menus(root, {'0000000A': root, '0000000B': sub})
    assert menus == [root, sub]
    assert [(m['FormID'], i) for m, i in plan_items(menus)] == [('0000000A', 0), ('0000000A', 1), ('0000000B', 0)]
    assert sub_menus([root, sub]) == {'0000000A', '0000000B'}


def test_a_terminal_carries_its_object_script_as_an_activator():
    """TERM becomes an ACTI, which holds a VMAD; a Fallout static does not."""
    assert holds_vmad('TERM', {}) and not holds_vmad('MSTT', {})


def test_activate_parents_round_trip_from_export_to_skyrim():
    """CG04's wall panel keeps its switch as activate parent, delay and all."""
    subs = [('XAPD', b'\x00'), ('XAPR', struct.pack('<If', 0x57AE9, 0.5))]
    lines = export_deltas(Record('REFR', 0, 0, 0x521A3, [Subrecord(t, d) for t, d in subs]))
    assert lines == ['XAPD.ParentActivateOnly=0', 'XAPR[0].Ref=00057AE9', 'XAPR[0].Delay=0.5']
    set_formid_index_offset(1)
    try:
        packed = activate_parent_subrecords(dict(line.split('=', 1) for line in lines))
    finally:
        set_formid_index_offset(0)
    assert packed == b'XAPD\x01\x00\x00' + b'XAPR\x08\x00' + struct.pack('<If', 0x01057AE9, 0.5)
