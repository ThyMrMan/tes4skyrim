"""The hand-corrected navmesh ops model: replay, index stability, staleness."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.navmesh import meshedit
from tools.navmesh.meshedit import (
    free_cell_name, is_stale, make_entry, mesh_hash, replay,
)

VERTS = [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [20, 0, 0]]
TRIS = [[0, 1, 2], [0, 2, 3], [1, 4, 2]]


def test_delete_keeps_later_ops_addressable():
    """A door set on tri 2 survives tri 1 being deleted in the same batch."""
    _v, tris, doors, _l = replay(VERTS, TRIS,
                                 [{'op': 'del_tri', 'tri': 1},
                                  {'op': 'set_door', 'tri': 2}])
    assert tris == [[0, 1, 2], [1, 4, 2]]
    assert doors == [1]


def test_door_on_deleted_triangle_is_dropped():
    """Marking then deleting the same triangle leaves no dangling door."""
    _v, _t, doors, _l = replay(VERTS, TRIS,
                               [{'op': 'set_door', 'tri': 0},
                                {'op': 'del_tri', 'tri': 0}])
    assert doors == []


def test_move_vert_takes_an_absolute():
    """move_vert places one vertex, touching nothing else."""
    verts, tris, _d, _l = replay(VERTS, TRIS,
                                 [{'op': 'move_vert', 'v': 0,
                                   'to': [1, 2, 3]}])
    assert verts[0] == [1.0, 2.0, 3.0]
    assert tris == TRIS


def test_weld_rewrites_the_index_everywhere():
    """A crack closes only when both triangles SHARE the vertex index.

    Triangle 2 is `[1, 4, 2]`; welding 4 into 0 must leave it `[1, 0, 2]`,
    with index 4 referenced nowhere.
    """
    verts, tris, _d, _l = replay(VERTS, TRIS,
                                 [{'op': 'snap_vert', 'v': 4, 'to_v': 0}])
    assert verts[4] == [0, 0, 0]
    assert tris[-1] == [1, 0, 2]
    assert all(4 not in t for t in tris)


def test_weld_drops_triangles_it_degenerates():
    """Welding two corners of one triangle together leaves no sliver."""
    verts = [[0, 0, 0], [10, 0, 0], [10, 10, 0], [10.5, 0.2, 0]]
    tris = [[0, 1, 2], [3, 1, 2]]
    _v, out, _d, _l = replay(verts, tris, [{'op': 'snap_vert', 'v': 3,
                                            'to_v': 1}])
    assert out == [[0, 1, 2]]


def test_add_tri():
    """add_tri appends over existing vertices."""
    _v, tris, _d, _l = replay(VERTS, TRIS,
                              [{'op': 'add_tri', 'verts': [0, 3, 4]}])
    assert tris[-1] == [0, 3, 4]


def test_unknown_op_is_ignored():
    """An op we do not understand changes nothing, rather than guessing."""
    _v, tris, _d, _l = replay(VERTS, TRIS, [{'op': 'rotate_everything'}])
    assert tris == TRIS


def test_add_vert_extends_the_mesh():
    """A triangle can reach into open floor, not only fill an existing hole."""
    verts, tris, _d, _l = replay(VERTS, TRIS,
                                 [{'op': 'add_vert', 'to': [30, 10, 5]},
                                  {'op': 'add_tri', 'verts': [4, 5, 2]}])
    assert verts[5] == [30.0, 10.0, 5.0]
    assert tris[-1] == [4, 5, 2]


def test_links_are_editable():
    """add_link/del_link edit the drop-down links production returns."""
    _v, _t, _d, links = replay(VERTS, TRIS, [{'op': 'add_link',
                                              'up': 0, 'down': 2}])
    assert links == [(0, 2)]
    _v, _t, _d, links = replay(VERTS, TRIS,
                               [{'op': 'del_link', 'up': 0, 'down': 2}],
                               links=[(0, 2)])
    assert links == []


def test_link_to_deleted_triangle_is_dropped():
    """A link is meaningless once one of its triangles is gone."""
    _v, _t, _d, links = replay(VERTS, TRIS, [{'op': 'del_tri', 'tri': 2}],
                               links=[(0, 2)])
    assert links == []


def test_links_remap_with_deletions():
    """Surviving links follow their triangles' new indices."""
    _v, _t, _d, links = replay(VERTS, TRIS, [{'op': 'del_tri', 'tri': 0}],
                               links=[(1, 2)])
    assert links == [(0, 1)]


def test_entry_carries_ops_and_result():
    """A correction stores the changelist AND the finished mesh."""
    entry = make_entry('Oblivion.esm', 'X', VERTS, TRIS,
                       [{'op': 'del_tri', 'tri': 0}])
    assert entry['ops'] == [{'op': 'del_tri', 'tri': 0}]
    assert len(entry['result']['tris']) == 2
    assert entry['base_hash'] == mesh_hash(VERTS, TRIS)


def test_staleness_tracks_the_generator():
    """The hash matches its own mesh and changes when the mesh does."""
    entry = make_entry('Oblivion.esm', 'X', VERTS, TRIS, [])
    assert not is_stale(entry, VERTS, TRIS)
    assert is_stale(entry, VERTS, TRIS + [[0, 1, 3]])


def test_float_jitter_is_not_a_change():
    """Sub-0.01u movement must not invalidate a correction."""
    jittered = [[c + 1e-5 for c in p] for p in VERTS]
    assert mesh_hash(jittered, TRIS) == mesh_hash(VERTS, TRIS)


def test_free_name_is_the_cell_when_unused(tmp_path, monkeypatch):
    """A cell with no correction saves under its own name."""
    monkeypatch.setattr(meshedit, 'FIXES', str(tmp_path))
    assert free_cell_name('Oblivion.esm', 'SomeCell') == 'SomeCell'


def test_free_name_never_reuses_an_existing_file(tmp_path, monkeypatch):
    """A second reading of one cell must not overwrite the first.

    A stale correction's `result` is the only record of what the mesh should
    have looked like, so saving again numbers the file instead.
    """
    monkeypatch.setattr(meshedit, 'FIXES', str(tmp_path))
    entry = make_entry('Oblivion.esm', 'C', VERTS, TRIS, [])
    meshedit.save_fix('Oblivion.esm', 'C', entry)
    assert free_cell_name('Oblivion.esm', 'C') == 'C.2'
    meshedit.save_fix('Oblivion.esm', 'C.2', entry)
    assert free_cell_name('Oblivion.esm', 'C') == 'C.3'


#: A saved edit: tri 0 deleted, a new tri added -- so result indices differ from base ones.
SAVED_OPS = [{'op': 'del_tri', 'tri': 0}, {'op': 'add_tri', 'verts': [0, 1, 4]}]

#: Edits made over that saved RESULT: a new vertex and tri, a door on it, a delete.
SESSION_OPS = [{'op': 'add_vert', 'to': [30, 10, 0]},
               {'op': 'add_tri', 'verts': [4, 5, 2]},
               {'op': 'set_door', 'tri': 3},
               {'op': 'del_tri', 'tri': 0}]


def test_rebased_edits_replay_to_what_the_page_showed():
    """Replaying saved + rebased ops over the base equals the session's ops over the result.

    See: docs/commentary/tes5_import_navmesh.md#editing-a-saved-result
    """
    rv, rt, rd, rl = replay(VERTS, TRIS, SAVED_OPS)
    want = replay(rv, rt, SESSION_OPS, rd, rl)
    combined = meshedit.rebase_ops(VERTS, TRIS, SAVED_OPS, SESSION_OPS)
    assert replay(VERTS, TRIS, combined) == want


def test_result_marks_replay_back_into_the_saved_doors_and_links():
    """Base doors and links rebuilt from a result reproduce that result's own."""
    entry = make_entry('Oblivion.esm', 'X', VERTS, TRIS, SAVED_OPS,
                       doors=[2], links=[(1, 2)])
    doors, links = meshedit.result_marks(VERTS, TRIS, SAVED_OPS, entry['result'])
    _v, _t, rd, rl = replay(VERTS, TRIS, SAVED_OPS, doors, links)
    assert rd == entry['result']['doors'] and [list(l) for l in rl] == entry['result']['links']
