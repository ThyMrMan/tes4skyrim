"""Cellview's per-cell index rebases each master's FormIDs into the child's numbering."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.navmesh.cell_index import index_map, shift_fid


def _export(root, name, masters):
    """A fake export directory whose header lists `masters`."""
    d = root / name
    d.mkdir()
    lines = ['Master[%d]=%s' % (i, m) for i, m in enumerate(masters)]
    (d / '_HEADER.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(d)


def test_master_own_records_take_the_childs_slot(tmp_path):
    """Morrowind_ob's own 01xxxxxx is TR's 00xxxxxx; Oblivion's 00 is unaddressable."""
    _export(tmp_path, 'Oblivion.esm', [])
    mw = _export(tmp_path, 'Morrowind_ob.esm', ['Oblivion.esm'])
    _export(tmp_path, 'Patch.esp', ['Oblivion.esm', 'Morrowind_ob.esm'])
    tr = _export(tmp_path, 'TR.esm', ['Morrowind_ob.esm', 'Patch.esp'])
    imap = index_map(tr, mw)
    assert imap == {1: 0}
    assert shift_fid(0x010C084C, imap) == 0x000C084C
    assert shift_fid(0x000C084C, imap) is None


def test_shared_master_keeps_its_position(tmp_path):
    """A master both plugins declare maps by name, not by position."""
    _export(tmp_path, 'Oblivion.esm', [])
    _export(tmp_path, 'Morrowind_ob.esm', ['Oblivion.esm'])
    patch = _export(tmp_path, 'Patch.esp', ['Oblivion.esm', 'Morrowind_ob.esm'])
    tr = _export(tmp_path, 'TR.esm', ['Morrowind_ob.esm', 'Patch.esp'])
    assert index_map(tr, patch) == {1: 0, 2: 1}
