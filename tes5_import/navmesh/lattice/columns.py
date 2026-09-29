"""Collision rasterized onto a column grid: floors, headroom and wall arms.

A column is a CS-wide square.  Every walkable triangle over a column's center
gives it a FLOOR at that height; the next surface overhead bounds the floor's
HEADROOM.  Each column has four ARMS, the half-segments from its center to the
midpoints of its four sides; every blocking triangle crossing an arm is
recorded there with the height band it spans, so a wall is caught however thin
it is.
"""

import numpy as np

#: Floors closer than this in one column are one surface (double-sided or coplanar parts).
FLOOR_MERGE = 4.0

#: Arm directions: west, east, south, north, as (column step x, column step y).
ARM_STEPS = ((-1, 0), (1, 0), (0, -1), (0, 1))


# ---------------------------------------------------------------------------
# Floors and headroom
# ---------------------------------------------------------------------------

class Grid:
    """Column geometry: origin corner, column size and counts."""

    __slots__ = ('x0', 'y0', 'cs', 'nx', 'ny')

    def __init__(self, x0, y0, cs, nx, ny):
        """A grid of nx * ny columns of side cs whose low corner is (x0, y0)."""
        self.x0, self.y0, self.cs = float(x0), float(y0), float(cs)
        self.nx, self.ny = int(nx), int(ny)

    @classmethod
    def over(cls, lo, hi, cs):
        """The grid whose columns cover the plan box lo..hi."""
        nx = max(1, int(np.ceil((hi[0] - lo[0]) / cs)))
        ny = max(1, int(np.ceil((hi[1] - lo[1]) / cs)))
        return cls(lo[0], lo[1], cs, nx, ny)

    def column_at(self, x, y):
        """The column holding (x, y), or -1 outside the grid."""
        i = int(np.floor((x - self.x0) / self.cs))
        j = int(np.floor((y - self.y0) / self.cs))
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return j * self.nx + i
        return -1


def explode(counts):
    """(owner, k) for every k < counts[owner]: a ragged range, flattened."""
    counts = np.asarray(counts, dtype=np.int64)
    owner = np.repeat(np.arange(len(counts)), counts)
    starts = np.cumsum(counts) - counts
    return owner, np.arange(len(owner)) - starts[owner]


def _center_range(lo, hi, origin, cs, n):
    """First and last column index whose center lies in [lo, hi], clipped."""
    first = np.ceil((lo - origin) / cs - 0.5).astype(np.int64)
    last = np.floor((hi - origin) / cs - 0.5).astype(np.int64)
    return np.maximum(first, 0), np.minimum(last, n - 1)


def raster(tris, grid):
    """(column, z) where each triangle covers a column center, in plan."""
    t = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    if not len(t):
        return np.zeros(0, np.int64), np.zeros(0)
    i0, i1 = _center_range(t[:, :, 0].min(1), t[:, :, 0].max(1), grid.x0, grid.cs, grid.nx)
    j0, j1 = _center_range(t[:, :, 1].min(1), t[:, :, 1].max(1), grid.y0, grid.cs, grid.ny)
    ni, nj = np.maximum(i1 - i0 + 1, 0), np.maximum(j1 - j0 + 1, 0)
    ti, k = explode(ni * nj)
    ii, jj = i0[ti] + k % ni[ti], j0[ti] + k // ni[ti]
    px = grid.x0 + (ii + 0.5) * grid.cs
    py = grid.y0 + (jj + 0.5) * grid.cs
    a, b, c = t[ti, 0], t[ti, 1], t[ti, 2]
    d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok = np.abs(d) > 1e-9
    d = np.where(ok, d, 1.0)
    l0 = ((b[:, 1] - c[:, 1]) * (px - c[:, 0]) + (c[:, 0] - b[:, 0]) * (py - c[:, 1])) / d
    l1 = ((c[:, 1] - a[:, 1]) * (px - c[:, 0]) + (a[:, 0] - c[:, 0]) * (py - c[:, 1])) / d
    l2 = 1.0 - l0 - l1
    inside = ok & (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
    z = l0 * a[:, 2] + l1 * b[:, 2] + l2 * c[:, 2]
    return (jj * grid.nx + ii)[inside], z[inside]


def floors(walkable, grid):
    """Sorted (column, z) of every distinct floor, merged within FLOOR_MERGE."""
    col, z = raster(walkable, grid)
    order = np.lexsort((z, col))
    col, z = col[order], z[order]
    keep = np.ones(len(col), bool)
    keep[1:] = (col[1:] != col[:-1]) | (z[1:] - z[:-1] > FLOOR_MERGE)
    return col[keep], z[keep]


def headroom(span_col, span_z, over_col, over_z):
    """Clear height above each span: its column's next surface higher than FLOOR_MERGE."""
    order = np.lexsort((over_z, over_col))
    oc, oz = over_col[order], over_z[order]
    out = np.full(len(span_col), np.inf)
    if not len(oc):
        return out
    lo = np.searchsorted(oc, span_col, 'left')
    hi = np.searchsorted(oc, span_col, 'right')
    for k in range(int((hi - lo).max(initial=0))):
        at = np.minimum(lo + k, len(oz) - 1)
        above = (lo + k < hi) & (oz[at] > span_z + FLOOR_MERGE) & np.isinf(out)
        out[above] = oz[at][above] - span_z[above]
    return out


# ---------------------------------------------------------------------------
# Wall arms
# ---------------------------------------------------------------------------

def _plane_cuts(t, axis, lines, origin, cs, n):
    """Segments where triangles cross the grid center lines `axis` = const.

    Returns (line index, u0, z0, u1, z1) with u along the other plan axis.
    """
    lo, hi = _center_range(t[:, :, axis].min(1), t[:, :, axis].max(1), origin, cs, n)
    ti, k = explode(np.maximum(hi - lo + 1, 0))
    line = lo[ti] + k
    c = lines[line] + 1e-3
    u_ax = 1 - axis
    cross, us, zs = [], [], []
    for e0, e1 in ((0, 1), (1, 2), (2, 0)):
        p, q = t[ti, e0], t[ti, e1]
        sp, sq = p[:, axis] - c, q[:, axis] - c
        cut = (sp < 0) != (sq < 0)
        f = np.where(cut, sp / np.where(cut, sp - sq, 1.0), 0.0)
        cross.append(cut)
        us.append(p[:, u_ax] + (q[:, u_ax] - p[:, u_ax]) * f)
        zs.append(p[:, 2] + (q[:, 2] - p[:, 2]) * f)
    first = np.where(cross[0], 0, 1)
    second = np.where(cross[2], 2, 1)
    got = (cross[0].astype(int) + cross[1] + cross[2]) == 2
    u, z = np.stack(us, 1), np.stack(zs, 1)
    r = np.arange(len(line))
    return (line[got], u[r, first][got], z[r, first][got],
            u[r, second][got], z[r, second][got])


def _arm_bands(cut, origin, cs, n):
    """(line, arm slot, z low, z high) for every arm a cut crosses.

    Slot 2*i is the low-side arm of column i on that line, 2*i + 1 its
    high-side arm; a band is the cut's height range clipped to the arm.
    """
    line, u0, z0, u1, z1 = cut
    half = 0.5 * cs
    a = np.maximum(np.floor((np.minimum(u0, u1) - origin) / half).astype(np.int64), 0)
    b = np.minimum(np.floor((np.maximum(u0, u1) - origin) / half).astype(np.int64), 2 * n - 1)
    ci, k = explode(np.maximum(b - a + 1, 0))
    slot = a[ci] + k
    du = u1[ci] - u0[ci]
    flat = np.abs(du) <= 1e-9
    safe = np.where(flat, 1.0, du)
    fa = np.where(flat, 0.0, np.clip((origin + slot * half - u0[ci]) / safe, 0.0, 1.0))
    fb = np.where(flat, 1.0, np.clip((origin + (slot + 1) * half - u0[ci]) / safe, 0.0, 1.0))
    dz = z1[ci] - z0[ci]
    za, zb = z0[ci] + dz * fa, z0[ci] + dz * fb
    return line[ci], slot, np.minimum(za, zb), np.maximum(za, zb)


class Arms:
    """Blocking height bands on every column arm, sorted for lookup."""

    __slots__ = ('key', 'lo', 'hi')

    def __init__(self, blocking, grid):
        """Cut every blocking triangle along the row and column center lines."""
        t = np.asarray(blocking, dtype=np.float64).reshape(-1, 3, 3)
        keys, los, his = [np.zeros(0, np.int64)], [np.zeros(0)], [np.zeros(0)]
        if len(t):
            ys = grid.y0 + (np.arange(grid.ny) + 0.5) * grid.cs
            xs = grid.x0 + (np.arange(grid.nx) + 0.5) * grid.cs
            row, slot, lo, hi = _arm_bands(_plane_cuts(t, 1, ys, grid.y0, grid.cs, grid.ny),
                                           grid.x0, grid.cs, grid.nx)
            keys.append((row * grid.nx + slot // 2) * 4 + slot % 2)
            los.append(lo)
            his.append(hi)
            colx, slot, lo, hi = _arm_bands(_plane_cuts(t, 0, xs, grid.x0, grid.cs, grid.nx),
                                            grid.y0, grid.cs, grid.ny)
            keys.append(((slot // 2) * grid.nx + colx) * 4 + 2 + slot % 2)
            los.append(lo)
            his.append(hi)
        key = np.concatenate(keys)
        order = np.argsort(key, kind='stable')
        self.key = key[order]
        self.lo = np.concatenate(los)[order]
        self.hi = np.concatenate(his)[order]

    def hit(self, col, arm, zlo, zhi):
        """True where a blocking band on (col, arm) overlaps zlo..zhi."""
        q = np.asarray(col, np.int64) * 4 + np.asarray(arm, np.int64)
        start = np.searchsorted(self.key, q, 'left')
        end = np.searchsorted(self.key, q, 'right')
        qi, k = explode(end - start)
        ei = start[qi] + k
        over = ((self.lo[ei] <= np.asarray(zhi, float)[qi])
                & (self.hi[ei] >= np.asarray(zlo, float)[qi]))
        out = np.zeros(len(q), bool)
        out[qi[over]] = True
        return out
