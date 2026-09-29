"""Coarsen a lattice mesh by edge collapses, flips and smoothing that keep its surface.

A collapse folds one vertex into a neighbour that stays where it is; a flip
swaps the diagonal of two triangles; smoothing slides an inner vertex along
the lattice surface.  A change is refused if a triangle would flip or pinch in
plan, grow a sharper corner than the worse of MIN_ANGLE and what was there, or
run an edge past MAX_EDGE.  The outline is simplified once, to OUTLINE_TOL,
and never moves at a pinned vertex.  Each triangle carries the points it
covers: original lattice vertices, which must stay within Z_TOL of the
surface, and MUST points, which must stay covered at all.
"""

import heapq
import math

import numpy as np

#: Longest plan edge a collapse may create (units).
MAX_EDGE = 256.0
#: Vertical distance the surface may drift from any original lattice vertex.
Z_TOL = 16.0
#: How far the simplified outline may stray from the lattice outline (units).
OUTLINE_TOL = 14.0
#: Longest outline edge the simplified outline keeps (the corridor's densify step).
OUTLINE_EDGE = 128.0
#: Smallest plan corner (degrees) a change may create unless one was already smaller.
MIN_ANGLE = 22.0
#: The same floor for a collapse on the outline; flips and smoothing fatten what it leaves.
MIN_ANGLE_RIM = 15.0
#: Collapse, flip and smooth rounds; the loop stops early once nothing changes.
ROUNDS = 8


# ---------------------------------------------------------------------------
# Plan geometry
# ---------------------------------------------------------------------------

def _area2(p, q, r):
    """Twice the signed plan area of p, q, r."""
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _sharpness(p, q, r):
    """Cosine of the smallest plan corner of triangle p, q, r; 1.0 when degenerate."""
    out = -1.0
    for a, b, c in ((p, q, r), (q, r, p), (r, p, q)):
        ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], c[0] - a[0], c[1] - a[1]
        nn = math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
        if nn < 1e-9:
            return 1.0
        out = max(out, (ux * vx + uy * vy) / nn)
    return out


#: The sharpness of a MIN_ANGLE corner, and of a MIN_ANGLE_RIM one.
_SHARP, _SHARP_RIM = math.cos(math.radians(MIN_ANGLE)), math.cos(math.radians(MIN_ANGLE_RIM))


def _corner(p, q, r):
    """Plan angle at p of triangle p, q, r, in radians."""
    ux, uy, vx, vy = q[0] - p[0], q[1] - p[1], r[0] - p[0], r[1] - p[1]
    return abs(math.atan2(ux * vy - uy * vx, ux * vx + uy * vy))


def _overlap(a, b):
    """True when two plan triangles share interior area, not just an edge or corner."""
    for t, u in ((a, b), (b, a)):
        s = 1.0 if _area2(*t) > 0 else -1.0
        for k in range(3):
            p, q = t[k], t[(k + 1) % 3]
            nx, ny = s * (q[1] - p[1]), s * (p[0] - q[0])
            norm = math.hypot(nx, ny) or 1.0
            if min(((w[0] - p[0]) * nx + (w[1] - p[1]) * ny) / norm for w in u) >= -1e-6:
                return False
    return True


def _seg_dist(p, a, b):
    """Plan distance from p to segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d2 = dx * dx + dy * dy
    t = 0.0 if d2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d2))
    return math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t)


def _plan_len(p, q):
    """Plan distance between two points."""
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _douglas_peucker(pts, tol):
    """Indices of an open polyline kept so every dropped point is within tol."""
    keep, stack = {0, len(pts) - 1}, [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        far, k = max((_seg_dist(pts[k], pts[i], pts[j]), k) for k in range(i + 1, j))
        if far > tol:
            keep.add(k)
            stack += [(i, k), (k, j)]
    return keep


def outline_loops(tris):
    """Closed outline loops as vertex lists, plus vertices where loops touch."""
    out = {}
    have = {(t[k], t[(k + 1) % 3]) for t in tris for k in range(3)}
    for (a, b) in have:
        if (b, a) not in have:
            out.setdefault(a, []).append(b)
    pinch = {a for a, nx in out.items() if len(nx) > 1}
    unused = {(a, b) for a, nx in out.items() for b in nx}
    loops = []
    while unused:
        a, b = min(unused)
        unused.discard((a, b))
        loop = [a]
        while b != a:
            loop.append(b)
            step = next(((b, c) for c in out.get(b, ()) if (b, c) in unused), None)
            if step is None:
                break
            unused.discard(step)
            b = step[1]
        loops.append(loop)
    return loops, pinch


def _removable_outline(p, tris, pinned):
    """Outline vertices the simplified outline drops; DP corners, pinches and pins stay.

    Kept corners are then topped up so no outline edge runs past OUTLINE_EDGE.
    """
    loops, keep = outline_loops(tris)
    keep |= set(pinned)
    for loop in loops:
        if len(loop) < 4:
            keep.update(loop)
            continue
        far = max(range(len(loop)), key=lambda k: _plan_len(p[loop[k]], p[loop[0]]))
        for part in (loop[:far + 1], loop[far:] + loop[:1]):
            keep.update(part[k] for k in _douglas_peucker([p[i] for i in part], OUTLINE_TOL))
        keep.update(_spaced(p, loop, keep))
    return {k for loop in loops for k in loop} - keep


def _spaced(p, loop, keep):
    """Extra loop vertices so consecutive kept ones are at most OUTLINE_EDGE apart."""
    out, last, run = [], None, 0.0
    for k in loop + loop[:1]:
        if last is not None:
            run += _plan_len(p[last], p[k])
        if k in keep or k in out:
            run = 0.0
        elif run > OUTLINE_EDGE:
            out.append(last)
            run = _plan_len(p[last], p[k])
        last = k
    return out


def locate(pts, tri_xyz):
    """(index of the triangle holding each point or -1, its height there)."""
    a, b, c = tri_xyz[:, 0], tri_xyz[:, 1], tri_xyz[:, 2]
    d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    px, py = pts[:, None, 0], pts[:, None, 1]
    l0 = ((b[:, 1] - c[:, 1]) * (px - c[:, 0]) + (c[:, 0] - b[:, 0]) * (py - c[:, 1])) / d
    l1 = ((c[:, 1] - a[:, 1]) * (px - c[:, 0]) + (a[:, 0] - c[:, 0]) * (py - c[:, 1])) / d
    l2 = 1.0 - l0 - l1
    inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
    z = l0 * a[:, 2] + l1 * b[:, 2] + l2 * c[:, 2]
    which = np.where(inside.any(1), inside.argmax(1), -1)
    return which, z[np.arange(len(pts)), np.maximum(which, 0)]


# ---------------------------------------------------------------------------
# Mesh state
# ---------------------------------------------------------------------------

class _Mesh:
    """Mutable triangles, per-vertex incidence, per-triangle sharpness and cover."""

    def __init__(self, verts, tris, pinned, must, probes, seam):
        """Index the mesh and hand every point to a triangle covering it.

        `probes` and `must` are [(x, y, z, triangle)]: lattice points no vertex
        carries any more, and points that must stay covered.  `seam` maps a
        border vertex to the set of border lines it lies on.
        """
        self.p = [[float(c) for c in v[:3]] for v in verts]
        self.tris = [tuple(t) for t in tris]
        self.alive = [True] * len(self.tris)
        self.sharp = [_sharpness(*self.corners(t)) for t in self.tris]
        self.inc = [set() for _ in self.p]
        for ti, t in enumerate(self.tris):
            for k in t:
                self.inc[k].add(ti)
        extra = list(probes) + list(must)
        self.pts = np.array(self.p + [list(q[:3]) for q in extra], float).reshape(-1, 3)
        self.must = np.arange(len(self.pts)) >= len(self.p) + len(probes)
        self.cover = [[] for _ in self.tris]
        for k in range(len(self.p)):
            if self.inc[k]:
                self.cover[min(self.inc[k])].append(k)
        for k, q in enumerate(extra):
            self.cover[q[3]].append(len(self.p) + k)
        self.pinned, self.seam = pinned, seam
        self.removable = _removable_outline(self.p, self.tris, pinned)
        self.stamp = [0] * len(self.p)

    def corners(self, t):
        """The three corner positions of triangle `t`."""
        return self.p[t[0]], self.p[t[1]], self.p[t[2]]

    def ring(self, v):
        """Vertices sharing a triangle with v."""
        return {k for ti in self.inc[v] for k in self.tris[ti]} - {v}

    def outline_nbrs(self, v):
        """(incoming, outgoing) outline neighbours of v, or None if v is inside."""
        into, out = [], []
        for ti in self.inc[v]:
            t = self.tris[ti]
            k = t.index(v)
            nxt, prv = t[(k + 1) % 3], t[(k + 2) % 3]
            if len(self.inc[v] & self.inc[nxt]) == 1:
                out.append(nxt)
            if len(self.inc[v] & self.inc[prv]) == 1:
                into.append(prv)
        if not into and not out:
            return None
        return (into, out)

    def outline_ok(self, drop, keep):
        """May `drop` leave the outline by folding into outline neighbour `keep`?

        A border vertex goes only between two neighbours on its own border line.
        """
        got = self.outline_nbrs(drop)
        if got is None:
            return True
        into, out = got
        if drop not in self.removable or len(into) != 1 or len(out) != 1:
            return False
        line = self.seam.get(drop, set())
        if not (line <= self.seam.get(into[0], set()) and line <= self.seam.get(out[0], set())):
            return False
        return keep in (into[0], out[0])

    def link_ok(self, drop, keep, shared):
        """The link condition: the two rings meet only at the shared triangles' apexes."""
        apex = {k for ti in shared for k in self.tris[ti]} - {drop, keep}
        return not ((self.ring(drop) & self.ring(keep)) - apex)

    def wraps(self, v):
        """True when v's fan does not close once around it: an outline or slit vertex."""
        total = sum(_corner(*[self.p[k] for k in self.tris[ti][self.tris[ti].index(v):]
                              + self.tris[ti][:self.tris[ti].index(v)]])
                    for ti in self.inc[v])
        return abs(total - 2.0 * math.pi) > 1e-6 or self.outline_nbrs(v) is not None

    def folds(self, new, old):
        """True when a new triangle overlaps, in plan, a live one it touches outside `old`."""
        near = {ti for t in new for k in t for ti in self.inc[k]} - set(old)
        return any(_overlap(self.corners(t), self.corners(self.tris[ti]))
                   for t in new for ti in near)

    def shape_ok(self, old, new, floor):
        """New triangles are CCW in plan and no sharper than `floor` or the old worst."""
        limit = max(floor, max(self.sharp[ti] for ti in old))
        for t in new:
            c = self.corners(t)
            if _area2(*c) <= 1e-6 or _sharpness(*c) > limit + 1e-9:
                return False
        return True

    def recover(self, old, new, lossy):
        """(ok, cover lists) re-homing old triangles' points onto `new` triangles.

        A lattice point must stay within Z_TOL; a MUST point must stay covered;
        other points may fall off the mesh only when `lossy`.
        """
        pts = [k for ti in old for k in self.cover[ti]]
        idx = np.array(pts, np.int64)
        which, z = locate(self.pts[idx], np.array([self.corners(t) for t in new]))
        inside = which >= 0
        lattice_pts = inside & ~self.must[idx]
        if np.any(np.abs(z[lattice_pts] - self.pts[idx[lattice_pts], 2]) > Z_TOL):
            return False, None
        if np.any(~inside & (self.must[idx] | (not lossy))):
            return False, None
        cover = [[] for _ in new]
        for k, w in zip(pts, which.tolist()):
            if w >= 0:
                cover[w].append(k)
        return True, cover

    def replace(self, old, new, cover):
        """Swap triangles `old` for `new` in place; extra old ones die."""
        for ti in old:
            for k in self.tris[ti]:
                self.inc[k].discard(ti)
            self.alive[ti] = False
            self.cover[ti] = []
        for ti, t, c in zip(old, new, cover):
            self.tris[ti] = t
            self.alive[ti] = True
            self.cover[ti] = c
            self.sharp[ti] = _sharpness(*self.corners(t))
            for k in t:
                self.inc[k].add(ti)


# ---------------------------------------------------------------------------
# Collapses, flips and smoothing
# ---------------------------------------------------------------------------

def _collapse(m, drop, keep):
    """Fold drop into keep if every rule allows; True when it happened."""
    if drop in m.pinned or not m.inc[drop]:
        return False
    shared = m.inc[drop] & m.inc[keep]
    if not shared or not m.outline_ok(drop, keep) or not m.link_ok(drop, keep, shared):
        return False
    rest = sorted(m.inc[drop] - shared)
    new = [tuple(keep if k == drop else k for k in m.tris[ti]) for ti in rest]
    rim = m.outline_nbrs(drop) is not None
    if not new or not m.shape_ok(m.inc[drop], new, _SHARP_RIM if rim else _SHARP):
        return False
    kp = m.p[keep]
    if any(_plan_len(kp, m.p[k]) > MAX_EDGE for t in new for k in t):
        return False
    old = rest + sorted(shared)
    if (rim or m.wraps(drop) or m.wraps(keep)) and m.folds(new, old):
        return False
    ok, cover = m.recover(old, new, rim)
    if ok:
        m.replace(old, new, cover)
    return ok


def _push_edges(m, heap, verts):
    """Queue both half-edges of every edge at `verts`, stamped as they stand now."""
    for a in verts:
        for b in m.ring(a):
            d = _plan_len(m.p[a], m.p[b])
            heapq.heappush(heap, (d, a, b, m.stamp[a], m.stamp[b]))


def _collapse_pass(m):
    """Every allowed collapse, shortest edge first; returns how many landed."""
    heap = []
    _push_edges(m, heap, [v for v in range(len(m.p)) if m.inc[v]])
    done = 0
    while heap:
        _d, drop, keep, sd, sk = heapq.heappop(heap)
        if sd == m.stamp[drop] and sk == m.stamp[keep] and _collapse(m, drop, keep):
            done += 1
            around = {keep} | m.ring(keep)
            for a in around:
                m.stamp[a] += 1
            _push_edges(m, heap, around)
    return done


def _flip(m, ti, k):
    """Swap the diagonal across edge k of triangle ti if that fattens both; True if done."""
    t = m.tris[ti]
    a, b, c = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
    other = (m.inc[a] & m.inc[b]) - {ti}
    if len(other) != 1:
        return False
    tj = other.pop()
    d = next(x for x in m.tris[tj] if x not in (a, b))
    if d in m.ring(c):
        return False
    new = [(a, d, c), (d, b, c)]
    before = max(m.sharp[ti], m.sharp[tj])
    for n in new:
        cn = m.corners(n)
        if _area2(*cn) <= 1e-6 or _sharpness(*cn) >= before - 1e-9:
            return False
    ok, cover = m.recover([ti, tj], new, False)
    if ok:
        m.replace([ti, tj], new, cover)
    return ok


def _flip_pass(m, sweeps=6):
    """Improving diagonal flips until none remain; how many landed."""
    total = 0
    for _ in range(sweeps):
        flipped = 0
        for ti in range(len(m.tris)):
            for k in range(3):
                if m.alive[ti] and _flip(m, ti, k):
                    flipped += 1
        total += flipped
        if not flipped:
            break
    return total


def _smooth(m, v, surface):
    """Move inner vertex v to its ring's plan center on the surface if that fattens its fan."""
    ring = m.ring(v)
    cx = sum(m.p[k][0] for k in ring) / len(ring)
    cy = sum(m.p[k][1] for k in ring) / len(ring)
    z = surface(cx, cy, m.p[v][2])
    if z is None:
        return False
    fan = sorted(m.inc[v])
    before = max(m.sharp[ti] for ti in fan)
    old = m.p[v]
    m.p[v] = [cx, cy, z]
    new = [m.tris[ti] for ti in fan]
    ok = all(_area2(*m.corners(t)) > 1e-6 for t in new)
    ok = ok and max(_sharpness(*m.corners(t)) for t in new) < before - 1e-6
    cover = None
    if ok:
        ok, cover = m.recover(fan, new, False)
    if not ok:
        m.p[v] = old
        return False
    m.replace(fan, new, cover)
    return True


def _smooth_pass(m, surface):
    """One sweep of improving moves over every live inner vertex; how many moved."""
    moved = 0
    for v in range(len(m.p)):
        if m.inc[v] and v not in m.pinned and not m.wraps(v):
            moved += _smooth(m, v, surface)
    return moved


def simplify(verts, tris, pinned=frozenset(), must=(), surface=None, probes=(), seam=None):
    """(verts, tris) coarsened by collapses, flips and, given `surface`, smoothing.

    `must` is [(x, y, z, triangle)] for points that must stay covered and
    `probes` the same for dropped lattice points held to Z_TOL; `seam` maps
    border vertices to their border lines; `surface(x, y, z hint)` is the
    height a moved vertex takes.
    """
    m = _Mesh(verts, tris, set(pinned), list(must), list(probes), seam or {})
    for _ in range(ROUNDS):
        done = _collapse_pass(m)
        done += _flip_pass(m)
        if surface is not None:
            done += _smooth_pass(m, surface)
        if not done:
            break
    live = [t for ti, t in enumerate(m.tris) if m.alive[ti]]
    used = sorted({k for t in live for k in t})
    remap = {k: i for i, k in enumerate(used)}
    return ([tuple(m.p[k]) for k in used], [tuple(remap[k] for k in t) for t in live])
