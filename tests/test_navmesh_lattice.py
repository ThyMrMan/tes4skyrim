"""The prototype lattice navmesh generator, on synthetic collision."""

import numpy as np

from tes5_import.navmesh import params
from tes5_import.navmesh.lattice.build import pathgrid_points, seam_roles
from tes5_import.navmesh.lattice.columns import Grid
from tes5_import.navmesh.lattice.graph import build_graph
from tes5_import.navmesh.lattice.merge import merge_flat
from tes5_import.navmesh.lattice.mesh import lattice, surface_sampler
from tes5_import.navmesh.lattice.simplify import simplify
from tools.navmesh.navmesh_cache_hook import feeds_tag


def _floor(x0, y0, x1, y1, z=0.0):
    """Two walkable triangles over a plan rectangle."""
    return [[(x0, y0, z), (x1, y0, z), (x1, y1, z)], [(x0, y0, z), (x1, y1, z), (x0, y1, z)]]


def _wall(x, y0, y1, height=256.0):
    """Two blocking triangles standing in the plane x = const."""
    return [[(x, y0, 0.0), (x, y1, 0.0), (x, y1, height)], [(x, y0, 0.0), (x, y1, height), (x, y0, height)]]


def _kept_x(gap):
    """Largest kept column center x with a thin wall at x=256 holding a `gap` opening."""
    grid = Grid.over((0.0, 0.0), (512.0, 256.0), params.CS)
    walk = np.array(_floor(0, 0, 512, 256), float)
    block = np.array(_wall(256.5, 0, 128 - gap / 2) + _wall(256.5, 128 + gap / 2, 256), float)
    nodes, edges = [(64.0, 64.0, 0.0), (64.0, 192.0, 0.0)], [(0, 1)]
    col, _z, kept, _seed, _links = build_graph(grid, walk, block, nodes, edges, [], 1024.0)
    return max(grid.x0 + (int(c) % grid.nx + 0.5) * grid.cs for c in col[kept])


def test_a_gap_narrower_than_an_actor_stops_the_flood():
    """An 8u slit in a wall leaves the room behind it unmeshed."""
    assert _kept_x(8.0) < 256.0


def test_a_doorway_lets_the_flood_through():
    """A 96u opening carries the floor into the next room."""
    assert _kept_x(96.0) > 400.0


def _open_floor(cs, reach=1024.0):
    """(grid, graph, lattice) for an open 512u square floor crossed by a pathgrid."""
    grid = Grid.over((0.0, 0.0), (512.0, 512.0), cs)
    walk = np.array(_floor(0, 0, 512, 512), float)
    nodes, edges = [(40.0, 40.0, 0.0), (470.0, 470.0, 0.0), (40.0, 470.0, 0.0)], [(0, 1), (1, 2)]
    graph = build_graph(grid, walk, np.zeros((0, 3, 3)), nodes, edges, [], reach)
    return grid, graph, lattice(grid, graph[0], graph[1], graph[2], graph[4]), nodes


def _plan_area(verts, tris):
    """Total plan area of a triangle list."""
    v = np.asarray(verts, float)
    a, b, c = (v[[t[k] for t in tris], :2] for k in range(3))
    u, w = b - a, c - a
    return float(np.abs(u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]).sum() / 2.0)


def test_flat_merge_keeps_the_floor_in_far_fewer_triangles():
    """An open flat floor merges into MAX_SIDE quads covering exactly the lattice's area."""
    grid, (col, _z, kept, _seed, links), (verts, tris, _owner, corner), _n = _open_floor(params.CS)
    merged, span_tris, _probes = merge_flat(grid, col, kept, links, verts, corner, set())
    assert len(merged) <= len(tris) / 10
    assert abs(_plan_area(verts, merged) - _plan_area(verts, tris)) < 1e-6
    assert set(span_tris) == set(np.flatnonzero(kept).tolist())


def test_exterior_border_keeps_the_seam_step_and_nothing_between():
    """A cell-edge run ends up with vertices on every SEAM_STEP multiple, all on the edge."""
    grid, (col, _z, kept, _seed, links), (verts, tris, _owner, corner), _n = \
        _open_floor(params.CS_EXTERIOR, 8192.0)
    pinned, seam = seam_roles(verts, tris, (0.0, 0.0, 4096.0, 4096.0))
    merged, _span_tris, probes = merge_flat(grid, col, kept, links, verts, corner, pinned)
    sv, _st = simplify(verts, merged, pinned, (), None, probes, seam)
    assert sorted(y for (x, y, _z) in sv if abs(x) < 0.5) == [0.0, 128.0, 256.0, 384.0, 512.0]


def test_simplified_mesh_covers_the_pathgrid_and_shrinks():
    """Every pathgrid node stays on the simplified mesh, which is far coarser than the lattice."""
    grid, (col, z, kept, seed, links), (verts, tris, owner, corner), nodes = _open_floor(params.CS)
    merged, span_tris, probes = merge_flat(grid, col, kept, links, verts, corner, set())
    sv, st = simplify(verts, merged, set(), pathgrid_points(grid, col, z, seed, span_tris, verts, merged),
                      surface_sampler(grid, col, verts, tris, owner), probes)
    assert len(st) < len(tris) / 10
    v = np.array(sv)
    for (x, y, _z) in nodes:
        inside = False
        for t in st:
            a, b, c = v[list(t), :2]
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            l0 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
            l1 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
            inside |= min(l0, l1, 1 - l0 - l1) >= -1e-6
        assert inside, (x, y)


def test_build_navmesh_runs_the_chosen_generator(monkeypatch):
    """The corridor unless TESCONV_NAVMESH_GENERATOR names the lattice."""
    from core.navmesh_options import NAVMESH_GENERATOR_ENV_VAR
    from tes5_import.navmesh import build as nb
    monkeypatch.setattr(nb, 'build_lattice', lambda *a, **k: ([(0, 0, 0)], [('lattice',)], []))
    monkeypatch.setattr(nb.corridor, 'build_corridors',
                        lambda *a, **k: ([(0, 0, 0)], [('corridor',)], []))
    run = lambda: nb.build_navmesh([], {}, None, [(0, 0, 0)], [], doors=[])[1][0][0]  # noqa: E731
    monkeypatch.delenv(NAVMESH_GENERATOR_ENV_VAR, raising=False)
    assert run() == 'corridor'
    monkeypatch.setenv(NAVMESH_GENERATOR_ENV_VAR, 'lattice')
    assert run() == 'lattice'


def test_the_lattice_package_does_not_gate_a_push():
    """The push gate watches top-level navmesh sources, never lattice/."""
    assert not feeds_tag('tes5_import/navmesh/lattice/graph.py')
    assert feeds_tag('tes5_import/navmesh/corridor.py')
    assert not feeds_tag('tes5_import/navmesh/pool.py')
