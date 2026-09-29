"""The span graph: which floors are kept, and which neighbours they join.

A span is one floor in one column.  Two spans in side-by-side columns are
LINKED when their heights differ by at most a step and no wall stands on
either one's arm between them; each span side links to at most one partner,
so the lattice built on the links is always manifold.  The pathgrid seeds the
graph: every column its lines pass through gets a span (a synthetic one where
collision has no floor), consecutive seeds are linked whatever stands between
them, and only spans within a walked distance of a seed are kept.
"""

import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from .. import params
from .columns import ARM_STEPS, Arms, explode, floors, headroom, raster

#: How far below a pathgrid sample a floor may sit and still carry it.
SEED_DOWN = 64.0
#: How far from a pathgrid line's straight height a seed following the floor may climb or sink.
STAIR_WINDOW = 96.0
#: Columns either side of a pathgrid line whose floor is protected like the line itself.
BAND_COLS = 2
#: Height change two band spans of one pathgrid line may link across (the line walks it).
LANE_STEP = 2.0 * params.MAX_CLIMB
#: Pathgrid nodes this near a teleport door vote on which side of it is inside.
DOOR_SIDE_REACH = 512.0
#: Least half-width of the wall closing a teleport door's far side.
DOOR_BARRIER_HALF = 64.0
#: Half-length of the seed line laid through every door along its facing.
DOOR_SEED_REACH = 32.0
#: Clear height a floor needs; a pathgrid seed is exempt.
MIN_HEADROOM = 112.0
#: Most columns in a gap filled over a low obstacle, its walled rim included (5x5 columns).
HOLE_MAX = 24
#: A gap this many columns or fewer is a crack in the collision, stepped over; filled floor or not.
CRACK_MAX = 2
#: Tallest obstacle, above the floor around it, that a small gap is filled over.
HOLE_OBSTACLE = 64.0


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------

class Spans:
    """Every floor candidate, real spans first and synthetic ones appended."""

    def __init__(self, grid, walkable, blocking):
        """Rasterize the floors and measure each one's headroom."""
        self.grid = grid
        self.col, self.z = floors(walkable, grid)
        wc, wz = raster(walkable, grid)
        bc, bz = raster(blocking, grid)
        self.head = headroom(self.col, self.z, np.concatenate([wc, bc]),
                             np.concatenate([wz, bz]))
        self.extra = []
        self.extra_by_col = {}

    def near(self, col, z, down, up, prev=None):
        """The span in `col` nearest height z within z-down..z+up, or -1.

        With `prev`, only spans within a step of that height count.  A span
        with too little headroom to stand in loses to one that has it.
        """
        lo = int(np.searchsorted(self.col, col, 'left'))
        hi = int(np.searchsorted(self.col, col, 'right'))
        cands = [(float(self.z[k]), k, self.head[k] < MIN_HEADROOM) for k in range(lo, hi)]
        cands += [(ez, k, False) for (k, ez) in self.extra_by_col.get(col, ())]
        if prev is not None:
            cands = [c for c in cands if abs(c[0] - prev) <= params.MAX_CLIMB]
        cands = [(covered, abs(cz - z), k) for (cz, k, covered) in cands if -down <= cz - z <= up]
        return min(cands)[2] if cands else -1

    def height(self, k):
        """The height of span k, real or synthetic."""
        return float(self.z[k]) if k < len(self.z) else self.extra[k - len(self.z)][1]

    def covered(self, k):
        """True when span k has too little headroom to stand in (synthetic spans never)."""
        return k < len(self.head) and self.head[k] < MIN_HEADROOM

    def col_of(self, k):
        """The column of span k, real or synthetic."""
        return int(self.col[k]) if k < len(self.col) else self.extra[k - len(self.col)][0]

    def synthesize(self, col, z):
        """A synthetic span at (col, z), reusing one already there."""
        for (k, ez) in self.extra_by_col.get(col, ()):
            if abs(ez - z) <= 2.0 * params.MAX_CLIMB:
                return k
        k = len(self.col) + len(self.extra)
        self.extra.append((col, z))
        self.extra_by_col.setdefault(col, []).append((k, z))
        return k

    def arrays(self):
        """(column, z, headroom) over real and synthetic spans alike."""
        ec = np.array([c for (c, _z) in self.extra], np.int64)
        ez = np.array([z for (_c, z) in self.extra], float)
        return (np.concatenate([self.col, ec]), np.concatenate([self.z, ez]),
                np.concatenate([self.head, np.full(len(ec), np.inf)]))


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

def walk_columns(grid, a, b):
    """[(column i, column j, t along a-b)] a segment passes, 4-connected."""
    fx, fy = (a[0] - grid.x0) / grid.cs, (a[1] - grid.y0) / grid.cs
    gx, gy = (b[0] - grid.x0) / grid.cs, (b[1] - grid.y0) / grid.cs
    i, j = int(math.floor(fx)), int(math.floor(fy))
    ie, je = int(math.floor(gx)), int(math.floor(gy))
    dx, dy = gx - fx, gy - fy
    si, sj = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    tdx = abs(1.0 / dx) if dx else math.inf
    tdy = abs(1.0 / dy) if dy else math.inf
    tmx = ((i + (si > 0)) - fx) / dx if dx else math.inf
    tmy = ((j + (sj > 0)) - fy) / dy if dy else math.inf
    out = [(i, j, 0.0)]
    steps = abs(ie - i) + abs(je - j) + 1
    while (i, j) != (ie, je) and len(out) <= steps:
        if tmx < tmy:
            t, i, tmx = tmx, i + si, tmx + tdx
        else:
            t, j, tmy = tmy, j + sj, tmy + tdy
        out.append((i, j, min(t, 1.0)))
    return out


def _seed_segment(spans, a, b, synth_at):
    """Span ids along a-b in walking order; -1 where nothing may stand.

    `synth_at(t)` says whether a floorless sample at t may be synthesized.
    """
    grid = spans.grid
    out, prev = [], None
    for (i, j, t) in walk_columns(grid, a, b):
        if not (0 <= i < grid.nx and 0 <= j < grid.ny):
            out.append(-1)
            continue
        col = j * grid.nx + i
        z = a[2] + (b[2] - a[2]) * t
        k = -1 if prev is None else spans.near(col, z, STAIR_WINDOW, STAIR_WINDOW, prev)
        if k >= 0 and spans.covered(k):
            k = spans.near(col, z, STAIR_WINDOW, STAIR_WINDOW)
        if k < 0:
            k = spans.near(col, z, SEED_DOWN, params.MAX_CLIMB)
        if k < 0 and synth_at(t):
            k = spans.synthesize(col, z)
        out.append(k)
        prev = spans.height(k) if k >= 0 else None
    return out


def snap_nodes(spans, nodes):
    """Pathgrid nodes with Z moved down onto the floor they stand on."""
    out = []
    for (x, y, z) in nodes:
        col = spans.grid.column_at(x, y)
        k = spans.near(col, z, SEED_DOWN, params.MAX_CLIMB) if col >= 0 else -1
        zz = float(spans.z[k]) if 0 <= k < len(spans.z) else z
        out.append((x, y, zz))
    return out


def seed_lines(spans, nodes, edges, doors):
    """(seed span ids, anchor lines, forced links) from pathgrid and doors.

    Anchor lines are the pathgrid seeds, one span list per line: kept floor
    must be reachable from one.  A door seeds its own doorway, inventing
    floor only in the threshold's own column, but anchors nothing, so a door
    with no walked floor near it makes no island.  A teleport door seeds only
    its inside half (see door_inside).
    """
    anchored = [_seed_segment(spans, nodes[i], nodes[j], lambda t: True) for (i, j) in edges]
    lines = list(anchored)
    for door in doors:
        x, y, z, rz = door[:4]
        fx, fy = math.cos(rz) * DOOR_SEED_REACH, -math.sin(rz) * DOOR_SEED_REACH
        side = door_inside(door, nodes)
        back = (_seed_segment(spans, (x, y, z), (x - fx, y - fy, z), lambda t: t == 0.0)
                if side <= 0 else [])
        ahead = (_seed_segment(spans, (x, y, z), (x + fx, y + fy, z), lambda t: t == 0.0)
                 if side >= 0 else [])
        lines.append(back[::-1] + ahead[1:] if back else ahead)
    seeds, forced = set(), []
    for line in lines:
        seeds.update(k for k in line if k >= 0)
        forced += [(p, q) for p, q in zip(line, line[1:]) if p >= 0 and q >= 0 and p != q]
    return seeds, [[k for k in line if k >= 0] for line in anchored], forced


def door_inside(door, nodes):
    """+1 or -1: the side of a teleport door along its facing that the pathgrid is on.

    0 for an interior door, or a teleport door with no pathgrid near it: both
    sides count.  The pathgrid is the authored record of which side of a
    load door is this cell.
    """
    x, y, z, rz, teleport = door[:5]
    if not teleport:
        return 0
    fx, fy = math.cos(rz), -math.sin(rz)
    votes = sum(1 if (nx - x) * fx + (ny - y) * fy > 0 else -1
                for (nx, ny, nz) in nodes
                if math.hypot(nx - x, ny - y) < DOOR_SIDE_REACH and abs(nz - z) < params.AGENT_HEIGHT)
    return (votes > 0) - (votes < 0)


def door_barriers(doors, nodes):
    """(N, 3, 3) blocking triangles closing every teleport door one column past its threshold.

    A door panel's own collision is left out of the cell so interior doors
    stay open; a teleport door leads to another cell, so the far side of its
    threshold is walled off here.
    """
    out = []
    for door in doors:
        side = door_inside(door, nodes)
        if not side:
            continue
        x, y, z, rz, _tp, width = door[:6]
        fx, fy = -side * math.cos(rz), side * math.sin(rz)
        tx, ty = -fy, fx
        half = max(0.5 * width, DOOR_BARRIER_HALF)
        cx, cy = x + fx * params.CS, y + fy * params.CS
        a, b = (cx - tx * half, cy - ty * half), (cx + tx * half, cy + ty * half)
        lo, hi = z - params.MAX_CLIMB, z + 2.0 * params.AGENT_HEIGHT
        out += [[(a[0], a[1], lo), (b[0], b[1], lo), (b[0], b[1], hi)],
                [(a[0], a[1], lo), (b[0], b[1], hi), (a[0], a[1], hi)]]
    return np.asarray(out, float).reshape(-1, 3, 3)


def band(spans, arms, lines, radius):
    """{span: pathgrid lines it serves} for floor within `radius` columns of each line.

    The band grows only across arms no wall crosses, so a line hugging a wall
    does not carry floor into it; a wall the line itself passes through (a
    closed secret door) leaves both sides banded by the line's own columns.
    """
    out = {}
    for li, line in enumerate(lines):
        for s in line:
            out.setdefault(s, set()).add(li)
        front = list(line)
        for _ in range(radius):
            front = [t for s in front for t in _band_step(spans, arms, s, li, out)]
    return out


def _band_step(spans, arms, s, li, out):
    """Spans one unwalled column from span s that join line li's band, recorded in `out`."""
    grid, zs, c = spans.grid, spans.height(s), spans.col_of(s)
    got = []
    for arm, (di, dj) in enumerate(ARM_STEPS):
        i, j = c % grid.nx + di, c // grid.nx + dj
        if not (0 <= i < grid.nx and 0 <= j < grid.ny):
            continue
        n = j * grid.nx + i
        t = spans.near(n, zs, params.MAX_CLIMB, params.MAX_CLIMB)
        if t < 0 or spans.covered(t) or li in out.get(t, ()) or _arm_blocked(arms, c, n, arm, zs):
            continue
        out.setdefault(t, set()).add(li)
        got.append(t)
    return got


def _arm_blocked(arms, c, n, arm, z):
    """True when a wall crosses the step from column c to its neighbour n at height z."""
    lo, hi = z + params.MAX_CLIMB, z + params.AGENT_HEIGHT
    return bool(arms.hit([c, n], [arm, arm ^ 1], [lo, lo], [hi, hi]).any())


# ---------------------------------------------------------------------------
# Links and reach
# ---------------------------------------------------------------------------

def walled(arms, col, z):
    """True where a wall crosses one of the span's own arms in the actor band."""
    n = len(col)
    hit = arms.hit(np.repeat(col, 4), np.tile(np.arange(4), n),
                   np.repeat(z + params.MAX_CLIMB, 4), np.repeat(z + params.AGENT_HEIGHT, 4))
    return hit.reshape(n, 4).any(1)


def _side_candidates(col, z, alive, grid, arms, arm, lanes):
    """(a, b, |dz|) for alive spans a and b one column apart across `arm`.

    A wall on the arms, or a height change past a step, parts them unless
    both serve one pathgrid line, which may climb up to LANE_STEP there.
    """
    order = np.argsort(col, kind='stable')
    sc = col[order]
    di, dj = ARM_STEPS[arm]
    ci, cj = col % grid.nx + di, col // grid.nx + dj
    inside = (ci >= 0) & (ci < grid.nx) & (cj >= 0) & (cj < grid.ny) & alive
    nb = np.where(inside, cj * grid.nx + ci, -1)
    lo = np.searchsorted(sc, nb, 'left')
    hi = np.where(inside, np.searchsorted(sc, nb, 'right'), lo)
    a, k = explode(hi - lo)
    b = order[lo[a] + k]
    dz = np.abs(z[a] - z[b])
    ok = alive[b] & (dz <= LANE_STEP)
    a, b, dz = a[ok], b[ok], dz[ok]
    band = params.AGENT_HEIGHT
    free = (dz <= params.MAX_CLIMB) & ~(
        arms.hit(col[a], arm, z[a] + params.MAX_CLIMB, z[a] + band)
        | arms.hit(col[b], arm ^ 1, z[b] + params.MAX_CLIMB, z[b] + band))
    for k in np.flatnonzero(~free).tolist():
        free[k] = bool(lanes.get(int(a[k]), set()) & lanes.get(int(b[k]), set()))
    return a[free], b[free], dz[free]


def match_links(col, z, alive, grid, arms, forced, lanes):
    """[(a, b, arm)] with arm 1 (east) or 3 (north) from a to b, one per span side.

    Forced pathgrid links are taken first; the rest go by smallest height step.
    """
    cands = []
    for (p, q) in forced:
        arm = _arm_between(grid, col[p], col[q])
        if arm is not None:
            cands.append((-1.0, p, q, arm) if arm in (1, 3) else (-1.0, q, p, arm ^ 1))
    for arm in (1, 3):
        a, b, dz = _side_candidates(col, z, alive, grid, arms, arm, lanes)
        cands += zip(dz.tolist(), a.tolist(), b.tolist(), [arm] * len(a))
    cands.sort()
    used, out = set(), []
    for (_dz, a, b, arm) in cands:
        if (a, arm) in used or (b, arm ^ 1) in used:
            continue
        used.add((a, arm))
        used.add((b, arm ^ 1))
        out.append((a, b, arm))
    return out


def _arm_between(grid, ca, cb):
    """The arm of column ca that faces its 4-neighbour cb, else None."""
    di, dj = cb % grid.nx - ca % grid.nx, cb // grid.nx - ca // grid.nx
    return {(-1, 0): 0, (1, 0): 1, (0, -1): 2, (0, 1): 3}.get((int(di), int(dj)))


def reached(n, links, seeds, limit, core):
    """Spans within `limit` link steps of a seed through `core` spans, plus their rim.

    The flood crosses only core spans, whose four sides all link on; the
    spans on the edge of that floor are added back after.  A gap in the
    collision narrower than three columns therefore carries no flood.
    """
    if not seeds:
        return np.zeros(n, bool)
    a = np.array([p for (p, _q, _r) in links], np.int64)
    b = np.array([q for (_p, q, _r) in links], np.int64)
    inner = core[a] & core[b]
    g = coo_matrix((np.ones(int(inner.sum())), (a[inner], b[inner])), shape=(n, n)).tocsr()
    dist = dijkstra(g, directed=False, indices=sorted(seeds), min_only=True, limit=limit)
    kept = np.isfinite(dist)
    rim = np.zeros(n, bool)
    rim[b[kept[a]]] = True
    rim[a[kept[b]]] = True
    return kept | rim


def over_seeds(grid, col, z, seed):
    """Spans within BAND_COLS columns of a seed, more than a step above it but under headroom.

    The pathgrid asserts an actor walks its floor, so a surface that close
    over the walked line cannot be floor as well: it is something the actor
    passes (a moving wall's placed collision, a low grate).  A surface within
    a step of the line is a stair or a kerb and stays.  Seeds never drop.
    """
    by_col = {}
    for s, c in enumerate(col.tolist()):
        by_col.setdefault(c, []).append(s)
    out = np.zeros(len(col), bool)
    reach = range(-BAND_COLS, BAND_COLS + 1)
    for s in np.flatnonzero(seed).tolist():
        i, j = int(col[s]) % grid.nx, int(col[s]) // grid.nx
        for c in [(j + dj) * grid.nx + i + di for dj in reach for di in reach
                  if 0 <= i + di < grid.nx and 0 <= j + dj < grid.ny]:
            for t in by_col.get(c, ()):
                if params.MAX_CLIMB < z[t] - z[s] < MIN_HEADROOM and not seed[t]:
                    out[t] = True
    return out


def _kept_near(by_col, c, h):
    """True when column c keeps a span within a step of height h."""
    return any(abs(zz - h) <= params.MAX_CLIMB for zz in by_col.get(c, ()))


def _flood_hole(grid, by_col, start, h):
    """(columns, h) of the gap at height h holding `start`, or None.

    None past HOLE_MAX columns, and when a gap column already keeps floor
    within headroom of h: filling there would stack two floors.
    """
    hole, stack = {start}, [start]
    while stack:
        c = stack.pop()
        for di, dj in ARM_STEPS:
            i, j = c % grid.nx + di, c // grid.nx + dj
            if not (0 <= i < grid.nx and 0 <= j < grid.ny):
                return None
            n = j * grid.nx + i
            if n in hole or _kept_near(by_col, n, h):
                continue
            if any(abs(zz - h) < MIN_HEADROOM for zz in by_col.get(n, ())):
                return None
            hole.add(n)
            stack.append(n)
            if len(hole) > HOLE_MAX:
                return None
    return hole, h


def small_holes(spans, arms, col, z, kept):
    """[(column, height)] filling gaps of at most HOLE_MAX columns enclosed by kept floor.

    A gap is filled only over something low: nothing on its arms between
    HOLE_OBSTACLE and actor height (so a wall or pillar stays cut), and past a
    crack's size every column holding collision near the walking height (so
    a pit stays open).
    """
    grid, by_col, seen, out = spans.grid, {}, set(), []
    for s in np.flatnonzero(kept).tolist():
        by_col.setdefault(int(col[s]), []).append(float(z[s]))
    for s in np.flatnonzero(kept).tolist():
        for di, dj in ARM_STEPS:
            i, j = int(col[s]) % grid.nx + di, int(col[s]) // grid.nx + dj
            c = j * grid.nx + i
            if not (0 <= i < grid.nx and 0 <= j < grid.ny) or c in seen \
                    or _kept_near(by_col, c, float(z[s])):
                continue
            got = _flood_hole(grid, by_col, c, float(z[s]))
            seen.add(c)
            if got is not None and _low_fill(spans, arms, *got):
                seen |= got[0]
                out += [(hc, got[1]) for hc in sorted(got[0])]
    return out


def _low_fill(spans, arms, cols, h):
    """True when a gap has nothing tall on its arms and, past CRACK_MAX columns, collision near h."""
    for c in cols:
        if len(cols) > CRACK_MAX and spans.near(c, h, params.MAX_CLIMB, params.AGENT_HEIGHT) < 0:
            return False
        if arms.hit([c] * 4, range(4), [h + HOLE_OBSTACLE] * 4,
                    [h + params.AGENT_HEIGHT] * 4).any():
            return False
    return True


def _fill_span(spans, c, h):
    """A hole column's own floor within a step of h, a new span, or -1 beside other floor.

    A new span never goes within headroom of floor the column already has, and
    a covered floor is never filled: either would stack two floors in one place.
    """
    k = spans.near(c, h, params.MAX_CLIMB, params.MAX_CLIMB)
    if k >= 0:
        return -1 if spans.covered(k) else k
    if spans.near(c, h, MIN_HEADROOM, MIN_HEADROOM) >= 0:
        return -1
    return spans.synthesize(c, h)


def _solve(spans, arms, seeds, lanes, forced, reach):
    """(column, z, kept, seed, links) for the spans as they stand.

    `lanes` maps each span of the pathgrid band to the lines it serves: band
    spans are seeds, and two spans of one line link whatever stands between.
    """
    grid = spans.grid
    col, z, head = spans.arrays()
    seed = np.zeros(len(col), bool)
    seed[sorted(seeds | set(lanes))] = True
    walked = np.zeros(len(col), bool)
    walked[sorted(lanes)] = True
    alive = seed | ((head >= MIN_HEADROOM) & ~walled(arms, col, z)
                    & ~over_seeds(grid, col, z, walked))
    links = match_links(col, z, alive, grid, arms, forced, lanes)
    anchors = set(lanes)
    degree = np.bincount([s for (a, b, _r) in links for s in (a, b)], minlength=len(col))
    kept = reached(len(col), links, anchors, reach / grid.cs, seed | (degree == 4))
    links = [(a, b, r) for (a, b, r) in links if kept[a] and kept[b]]
    return col, z, kept, seed, links


def build_graph(grid, walkable, blocking, nodes, edges, doors, reach):
    """(column, z, kept mask, seed mask, links) for one cell's floors."""
    blocking = np.concatenate([np.asarray(blocking, float).reshape(-1, 3, 3),
                               door_barriers(doors, nodes)])
    spans = Spans(grid, walkable, blocking)
    snapped = snap_nodes(spans, nodes)
    seeds, lines, forced = seed_lines(spans, snapped, edges, doors)
    arms = Arms(blocking, grid)
    lanes = band(spans, arms, lines, BAND_COLS)
    col, z, kept, seed, links = _solve(spans, arms, seeds, lanes, forced, reach)
    holes = small_holes(spans, arms, col, z, kept)
    if not holes:
        return col, z, kept, seed, links
    seeds |= {_fill_span(spans, c, h) for (c, h) in holes} - {-1}
    return _solve(spans, arms, seeds, lanes, forced, reach)
