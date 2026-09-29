"""Cellview's NavIndex opens a child worldspace cell on its PARENT's land.

See: docs/commentary/tes5_import_navmesh.md#child-worldspaces-walk-the-parents-land
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.navmesh.index import NavIndex

WRLD_TXT = ('---RECORD_BEGIN---\nSignature=WRLD\nFormID=00001000\n---RECORD_END---\n\n'
            '---RECORD_BEGIN---\nSignature=WRLD\nFormID=00001001\n'
            'WNAM.Parent=00001000\n---RECORD_END---\n')


def _cell(fid, wrld, x):
    return {'FormID': fid, 'ParentWRLD': wrld, 'XCLC.X': str(x), 'XCLC.Y': '0'}


PARENT_CELL = _cell('00002000', '00001000', -13)
CHILD_CELL = _cell('00002100', '00001001', -13)
LONE_CHILD_CELL = _cell('00002101', '00001001', 7)


class _FakeIndex(object):
    """Cells and per-cell LAND the way CellIndex serves them."""

    def __init__(self):
        """Three cells; only the parent's has LAND."""
        self.cells = [PARENT_CELL, CHILD_CELL, LONE_CHILD_CELL]
        self.lands = {'00002000': {'FormID': '00003000'}}

    def of_cell(self, fid):
        """`(refrs, pgrd, land)` for one cell."""
        return [], None, self.lands.get(fid)


def _index(tmp_path):
    """A NavIndex over the fake cells and a two-world WRLD.txt, no tables armed."""
    (tmp_path / 'WRLD.txt').write_text(WRLD_TXT)
    idx = object.__new__(NavIndex)
    idx.export, idx._idx, idx._land_at = str(tmp_path), _FakeIndex(), None
    return idx


def test_child_cell_walks_the_parents_land(tmp_path):
    """The child's own LAND loses to the parent's at the same square."""
    got = _index(tmp_path).land_for(CHILD_CELL, {'FormID': '00003100'})
    assert got['FormID'] == '00003000'


def test_child_keeps_own_land_where_parent_has_no_cell(tmp_path):
    """No parent cell at the square leaves the child's own LAND."""
    own = {'FormID': '00003101'}
    assert _index(tmp_path).land_for(LONE_CHILD_CELL, own) is own
