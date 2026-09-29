"""Merge flat, fully linked squares of the lattice into larger quads before simplify.

Aligned 2x2 blocks of quads merge level by level, up to MAX_SIDE, while every
vertex of the block lies within FLAT_TOL of one plane and every quad linked
across its sides is at most one level smaller.  A merged quad is two
triangles, or a fan from its center vertex when a side keeps a vertex another
quad uses.  The vertices it drops come back as probes, so simplify still holds
the surface to them.
"""

import numpy as np

from .mesh import split_quad
from .simplify import locate

#: Farthest a merged block's vertex may lie from the block's best-fit plane (units).
FLAT_TOL = 4.0
#: Longest side a merged quad may have (units): the outline's longest edge.
MAX_SIDE = 128.0


def _partners(n, links):
    """[east, north, west, south] partner of every span, -1 where unlinked."""
    nb = np.full((4, n), -1, np.int64)
    if links:
        a, b, arm = np.array(links, np.int64).T
        east = arm == 1
        nb[0, a[east]], nb[2, b[east]] = b[east], a[east]
        nb[1, a[~east]], nb[3, b[~east]] = b[~east], a[~east]
    return nb


def _block(leaves, nb, a):
    """The 2x2 block of same-level leaves anchored at leaf a, as one span array, or None."""
    A = leaves[a]
    B, C = leaves.get(int(nb[0, A[-1, 0]])), leaves.get(int(nb[1, A[0, -1]]))
    if B is None or C is None:
        return None
    D = leaves.get(int(nb[0, C[-1, 0]]))
    if D is None or nb[1, B[0, -1]] != D[0, 0]:
        return None
    if not ((nb[0, A[-1]] == B[0]).all() and (nb[0, C[-1]] == D[0]).all()
            and (nb[1, A[:, -1]] == C[:, 0]).all() and (nb[1, B[:, -1]] == D[:, 0]).all()):
        return None
    return np.block([[A, C], [B, D]])


def _sheet_verts(corner, S):
    """Vertex ids over span sheet S (indexed [x, y]), or None where quads do not share corners."""
    V = np.empty((S.shape[0] + 1, S.shape[1] + 1), np.int64)
    V[:-1, :-1] = corner[S, 0]
    V[-1, :-1] = corner[S[-1], 1]
    V[:-1, -1] = corner[S[:, -1], 2]
    V[-1, -1] = corner[S[-1, -1], 3]
    shared = ((corner[S, 1] == V[1:, :-1]).all() and (corner[S, 2] == V[:-1, 1:]).all()
              and (corner[S, 3] == V[1:, 1:]).all())
    return V if shared else None


def _flat(p, V):
    """True when every vertex of V lies within FLAT_TOL of their best-fit plane."""
    q = p[V.ravel()]
    a = np.c_[q[:, 0] - q[:, 0].mean(), q[:, 1] - q[:, 1].mean(), np.ones(len(q))]
    coef = np.linalg.lstsq(a, q[:, 2], rcond=None)[0]
    return float(np.abs(a @ coef - q[:, 2]).max()) <= FLAT_TOL


def _balanced(nb, level, S, lv):
    """True when every span linked across the sheet's sides is at level lv or more."""
    out = np.concatenate([nb[0, S[-1]], nb[1, S[:, -1]], nb[2, S[0]], nb[3, S[:, 0]]])
    return bool((level[out[out >= 0]] >= lv).all())


def _merge_level(leaves, nb, col, grid, lv, ctx):
    """Merge the aligned blocks of level-lv leaves; (merged {anchor: (S, V)}, leaves left)."""
    corner, p, pin, level = ctx
    size = 2 << lv
    spans = {a: S for a, (S, _V) in leaves.items()}
    up, gone = {}, set()
    for a in sorted(leaves):
        c = int(col[a])
        if (c % grid.nx) % size or (c // grid.nx) % size:
            continue
        S = _block(spans, nb, a)
        V = None if S is None else _sheet_verts(corner, S)
        if V is None or pin[V[1:-1, 1:-1]].any() or not _balanced(nb, level, S, lv) \
                or not _flat(p, V):
            continue
        level[S] = lv + 1
        up[a] = (S, V)
        gone |= {a, int(S[size // 2, 0]), int(S[0, size // 2]), int(S[size // 2, size // 2])}
    return up, {a: leaf for a, leaf in leaves.items() if a not in gone}


def _leaf_tris(V, used, p):
    """Triangles over one leaf: two for a plain quad, else a fan from its center."""
    n = V.shape[0] - 1
    ring = ([V[x, 0] for x in range(n)] + [V[n, y] for y in range(n)]
            + [V[x, n] for x in range(n, 0, -1)] + [V[0, y] for y in range(n, 0, -1)])
    ring = [int(v) for v in ring if used[v]]
    if len(ring) == 4:
        return split_quad(p, [int(V[0, 0]), int(V[-1, 0]), int(V[0, -1]), int(V[-1, -1])])
    c = int(V[n // 2, n // 2])
    return [(c, ring[k], ring[(k + 1) % len(ring)]) for k in range(len(ring))]


def merge_flat(grid, col, kept, links, verts, corner, pinned):
    """(tris, triangles of each kept span, probes) with flat lattice areas merged.

    corner: [span, 4] vertex ids from `lattice`; pinned vertices are never dropped.
    probes: [(x, y, z, triangle)] for every lattice vertex no longer used.
    """
    n = len(col)
    nb = _partners(n, links)
    p = np.asarray(verts, float)
    pin = np.zeros(len(p), bool)
    pin[sorted(pinned)] = True
    ctx = (corner, p, pin, np.zeros(n, np.int64))
    leaves = {s: (np.array([[s]]), corner[s][[0, 2, 1, 3]].reshape(2, 2))
              for s in np.flatnonzero(kept).tolist()}
    final = {}
    for lv in range(int(round(np.log2(MAX_SIDE / grid.cs)))):
        leaves, left = _merge_level(leaves, nb, col, grid, lv, ctx)
        final.update(left)
    final.update(leaves)
    return _triangulate(final, p, pin)


def _triangulate(final, p, pin):
    """(tris, span triangles, probes) for the final leaves."""
    used = pin.copy()
    for (_S, V) in final.values():
        used[V[[0, 0, -1, -1], [0, -1, 0, -1]]] = True
    tris, span_tris, probes, seen = [], {}, [], set()
    for a in sorted(final):
        S, V = final[a]
        new = _leaf_tris(V, used, p)
        ids = list(range(len(tris), len(tris) + len(new)))
        tris += new
        for s in S.ravel().tolist():
            span_tris[s] = ids
        drop = sorted(set(V.ravel().tolist()) - {k for t in new for k in t} - seen)
        seen.update(drop)
        if drop:
            which, _z = locate(p[drop], p[np.array(new)])
            probes += [(*p[k], ids[w]) for k, w in zip(drop, which.tolist()) if w >= 0]
    return tris, span_tris, probes
