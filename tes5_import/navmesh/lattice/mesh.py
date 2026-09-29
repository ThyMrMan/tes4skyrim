"""The lattice mesh: one quad per kept span, corners shared across links.

A span's quad covers its column.  Two linked spans share the two corners on
their common side, so connectivity is structural: a crack, an overlap or a
T-junction cannot be built.  A corner's height is the mean of the spans that
share it, which turns a staircase's treads into one ramp.  Two spans of the
same column never share a corner, so storeys never fuse.
"""

import numpy as np

#: Corners a link joins, per arm: (corner of a, corner of b) pairs for east and north.
_JOIN = {1: ((1, 0), (3, 2)), 3: ((2, 0), (3, 1))}


class _Corners:
    """Union-find over (span, corner) with one span per column per class."""

    def __init__(self, col, kept):
        """Every kept span's four corners start as their own class."""
        self.parent = {}
        self.members = {}
        for s in np.flatnonzero(kept).tolist():
            for k in range(4):
                e = s * 4 + k
                self.parent[e] = e
                self.members[e] = {int(col[s]): s}

    def find(self, e):
        """The class root of element e, with path halving."""
        p = self.parent
        while p[e] != e:
            p[e] = p[p[e]]
            e = p[e]
        return e

    def join(self, e, f):
        """Merge two classes unless that would fuse two spans of one column."""
        a, b = self.find(e), self.find(f)
        if a == b:
            return True
        ma, mb = self.members[a], self.members[b]
        if any(c in ma and ma[c] != s for c, s in mb.items()):
            return False
        if len(ma) < len(mb):
            a, b, ma, mb = b, a, mb, ma
        self.parent[b] = a
        ma.update(mb)
        del self.members[b]
        return True


def lattice(grid, col, z, kept, links):
    """(verts, tris, span of each triangle, [span, 4] corner vertex ids) for the kept spans.

    Corners are ordered (00, 10, 01, 11); an unkept span's are -1.
    """
    uf = _Corners(col, kept)
    for (a, b, arm) in links:
        for ka, kb in _JOIN[arm]:
            uf.join(a * 4 + ka, b * 4 + kb)
    index, verts = {}, []
    for root, members in uf.members.items():
        s, k = divmod(root, 4)
        i, j = int(col[s]) % grid.nx + (k & 1), int(col[s]) // grid.nx + (k >> 1)
        index[root] = len(verts)
        verts.append([grid.x0 + i * grid.cs, grid.y0 + j * grid.cs,
                      float(np.mean([z[m] for m in members.values()]))])
    tris, owner = [], []
    corner = np.full((len(col), 4), -1, np.int64)
    for s in np.flatnonzero(kept).tolist():
        corner[s] = [index[uf.find(s * 4 + k)] for k in range(4)]
        tris += split_quad(verts, corner[s].tolist())
        owner += [s, s]
    return verts, tris, owner, corner


def surface_sampler(grid, col, verts, tris, owner):
    """f(x, y, z hint) -> the lattice height at (x, y) nearest the hint, or None."""
    by_col = {}
    for ti, s in enumerate(owner):
        by_col.setdefault(int(col[s]), []).append(ti)
    v = np.asarray(verts, float)

    def sample(x, y, hint):
        """Height of the lattice triangle over (x, y) closest to `hint`."""
        i = int(np.floor((x - grid.x0) / grid.cs))
        j = int(np.floor((y - grid.y0) / grid.cs))
        best = None
        for ti in by_col.get(j * grid.nx + i, ()):
            a, b, c = v[list(tris[ti])]
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            l0 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
            l1 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
            if min(l0, l1, 1.0 - l0 - l1) < -1e-6:
                continue
            z = l0 * a[2] + l1 * b[2] + (1.0 - l0 - l1) * c[2]
            if best is None or abs(z - hint) < abs(best - hint):
                best = z
        return best
    return sample


def split_quad(verts, v):
    """Two CCW triangles over corners (00, 10, 01, 11), cut on the flatter diagonal."""
    z = [verts[k][2] for k in v]
    if abs(z[0] - z[3]) <= abs(z[1] - z[2]):
        return [(v[0], v[1], v[3]), (v[0], v[3], v[2])]
    return [(v[0], v[1], v[2]), (v[1], v[3], v[2])]
