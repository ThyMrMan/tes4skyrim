"""Read a hand-corrected navmesh the way a walker would, against the generator.

A correction in `tests/navmesh_fixed/<plugin>/<cell>.json` records a human
fixing a SMALL part of a cell.  Its `ops` are keystrokes and mean nothing;
only `result` is ground truth, and `base` is the generator mesh it was made
from.  This tool diffs `result` against `base`, finds the region the human
touched, and answers three questions INSIDE that region only -- cell-wide
percentages bury the edit -- for three meshes: the base the human saw, the
generator as it builds NOW, and the human's target:

  EXTENT   how much real walkable floor has mesh over it (floor the human
           ADDED mesh over = "the mesh did not reach far enough"; floor the
           human REMOVED mesh from = ground we should not have covered)
  SURFACE  how far the mesh sits off the collision floor under it -- floating,
           sunk into it, or hanging over nothing
  SHAPE    how the region is tiled: quads (a corridor should be a run of
           quads), slivers, and triangles per unit floor

It also writes a PNG of the region (base | now | corrected) with collision and
pathgrid so the change can be SEEN, which is how the human made it.

    python tools/navmesh/fix_analyze.py                       # every fix
    python tools/navmesh/fix_analyze.py --cell imperialdungeon02
    python tools/navmesh/fix_analyze.py --cell X --pad 160 --out temp/x.png
    python tools/navmesh/fix_analyze.py --cell X --list        # per-vertex diff

See: docs/commentary/tes5_import_navmesh.md#hand-corrected-navmesh-corpus
"""

import argparse
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
from PIL import Image

from tes5_import.navmesh import params
from tools.navmesh import draw
from tools.navmesh.index import NavIndex
from tools.navmesh.meshedit import fixed_cells, load_fix, mesh_hash

#: Region padding around the touched vertices, in world units.
DEFAULT_PAD = 96.0

#: A vertex that moved less than this is unchanged (the JSON rounds to 0.001).
MOVE_EPS = 0.01

#: Floor sampling step for the EXTENT measure.
FLOOR_STEP = 8.0

#: Mesh is "on" the floor when within this of the collision surface.
SURFACE_TOL = 8.0

#: A collision floor further than this below/above a mesh point is another storey.
SURFACE_WINDOW = 80.0

#: Two triangles are a quad when their union is convex with corners this near 90 deg.
QUAD_ANGLE_TOL = 25.0

#: A SURFACE probe also looks this far around itself for floor (tile edges).
EDGE_PROBE_RADIUS = 4.0

#: Sliver: a triangle whose smallest angle is under this.
SLIVER_DEG = 20.0


def _tri_key(t):
    """Sorted vertex triple, the winding-free identity of a triangle."""
    return tuple(sorted(int(i) for i in t[:3]))


def diff_meshes(base_v, base_t, fix_v, fix_t):
    """`(moved, added_v, removed_t, added_t)` between base and corrected.

    Indices are into the corrected mesh's vertex list for `moved`/`added_v`
    (the correction keeps the generator's numbering and appends), triangle
    keys are sorted index triples.
    """
    moved = [i for i in range(min(len(base_v), len(fix_v)))
             if math.dist(base_v[i], fix_v[i]) > MOVE_EPS]
    added_v = list(range(len(base_v), len(fix_v)))
    bk = {_tri_key(t) for t in base_t}
    fk = {_tri_key(t) for t in fix_t}
    return moved, added_v, sorted(bk - fk), sorted(fk - bk)


def touched_region(fix_v, base_v, moved, added_v, removed_t, added_t, pad):
    """`(bbox, zlo, zhi)` of everything the human touched, padded.

    An added vertex no triangle uses is editor debris and does not count.
    """
    used = {k for t in added_t for k in t}
    pts = [fix_v[i] for i in moved + [v for v in added_v if v in used]]
    pts += [base_v[i] for i in moved]
    pts += [fix_v[k] for t in added_t for k in t]
    pts += [base_v[k] for t in removed_t for k in t]
    xs, ys, zs = zip(*pts)
    bbox = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    return bbox, min(zs) - params.MAX_CLIMB, max(zs) + params.MAX_CLIMB


def _in_region(verts, tris, bbox, zlo, zhi):
    """Triangles whose centroid falls inside the region's XY box and Z slab."""
    out = []
    for t in tris:
        cx = sum(verts[k][0] for k in t) / 3.0
        cy = sum(verts[k][1] for k in t) / 3.0
        cz = sum(verts[k][2] for k in t) / 3.0
        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3] \
                and zlo <= cz <= zhi:
            out.append(tuple(int(k) for k in t[:3]))
    return out


class _Surface(object):
    """Height lookup over a triangle soup, vectorized with numpy.

    `heights_at(p)` returns every surface height under plan point p;
    `z_near` picks the one nearest a reference height within a window.
    """

    def __init__(self, tris):
        """Index a list of 3-point triangles (empty list allowed)."""
        a = np.array([[p for p in t] for t in tris], dtype=float) \
            if tris else np.zeros((0, 3, 3))
        self.a, self.b, self.c = a[:, 0], a[:, 1], a[:, 2]
        d = np.cross(self.b - self.a, self.c - self.a)
        self.n = d
        self.n_z = np.where(np.abs(d[:, 2]) < 1e-9, np.nan, d[:, 2])
        self.xy_min = a[:, :, :2].min(axis=1) - 0.5
        self.xy_max = a[:, :, :2].max(axis=1) + 0.5

    def _bary_inside(self, p):
        """Boolean (T,) mask of triangles containing point p in plan."""
        v0 = self.c[:, :2] - self.a[:, :2]
        v1 = self.b[:, :2] - self.a[:, :2]
        v2 = p[:2] - self.a[:, :2]
        d00 = (v0 * v0).sum(1)
        d01 = (v0 * v1).sum(1)
        d11 = (v1 * v1).sum(1)
        d20 = (v2 * v0).sum(1)
        d21 = (v2 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        den = np.where(np.abs(den) < 1e-12, np.nan, den)
        u = (d11 * d20 - d01 * d21) / den
        v = (d00 * d21 - d01 * d20) / den
        return (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)

    def heights_at(self, p):
        """Every surface height under plan point p (sorted ascending)."""
        if not len(self.a):
            return np.zeros(0)
        box = ((self.xy_min <= p[:2]) & (self.xy_max >= p[:2])).all(1)
        idx = np.nonzero(box)[0]
        if not len(idx):
            return np.zeros(0)
        sub = _Surface.__new__(_Surface)
        sub.a, sub.b, sub.c = self.a[idx], self.b[idx], self.c[idx]
        sub.n, sub.n_z = self.n[idx], self.n_z[idx]
        hit = sub._bary_inside(p)
        n, a = sub.n[hit], sub.a[hit]
        nz = sub.n_z[hit]
        z = a[:, 2] - (n[:, 0] * (p[0] - a[:, 0]) + n[:, 1] * (p[1] - a[:, 1])) / nz
        return np.sort(z[np.isfinite(z)])

    def z_near(self, p, ref_z, window=SURFACE_WINDOW, radius=0.0):
        """Height nearest ref_z within window, or NaN.

        `radius` also probes four points that far from p, so a mesh corner
        sitting exactly on a floor tile's edge is judged by the tile, not by
        whatever lies a hair beyond it.
        """
        offsets = ((0.0, 0.0),)
        if radius > 0.0:
            offsets += ((radius, 0.0), (-radius, 0.0), (0.0, radius), (0.0, -radius))
        best = float('nan')
        for dx, dy in offsets:
            zs = self.heights_at(np.array((p[0] + dx, p[1] + dy)))
            if not len(zs):
                continue
            k = int(np.argmin(np.abs(zs - ref_z)))
            if abs(zs[k] - ref_z) <= window and (
                    math.isnan(best) or abs(zs[k] - ref_z) < abs(best - ref_z)):
                best = float(zs[k])
        return best


def _mesh_soup(verts, tris):
    """Indexed triangles as a list of 3-point triangles."""
    return [tuple(tuple(verts[k]) for k in t) for t in tris]


def floor_samples(walk, bbox, zlo, zhi):
    """Grid points on walkable collision inside the region, `[(x, y, z)]`.

    Every walkable collision triangle is rasterized at FLOOR_STEP; a point
    under several floors (a mezzanine over a hall) yields one sample each.
    """
    surf = _Surface(walk)
    out = []
    x0 = math.floor(bbox[0] / FLOOR_STEP) * FLOOR_STEP
    y0 = math.floor(bbox[1] / FLOOR_STEP) * FLOOR_STEP
    x = x0
    while x <= bbox[2]:
        y = y0
        while y <= bbox[3]:
            for z in surf.heights_at(np.array((x, y))):
                if zlo <= z <= zhi:
                    out.append((x, y, float(z)))
            y += FLOOR_STEP
        x += FLOOR_STEP
    return out


def covered(surf, samples):
    """Per sample, True when the mesh has a triangle within a step of it."""
    return [not math.isnan(surf.z_near(np.array(s[:2]), s[2], params.MAX_CLIMB))
            for s in samples]


def surface_fit(verts, tris, floor):
    """Per triangle, worst `mesh_z - floor_z` over corners, edge midpoints, centroid.

    Returns `[(tri, worst, kind)]` with kind in `float`, `sink`, `on`, `void`.
    `void` means some probe found no floor within SURFACE_WINDOW at all.
    """
    out = []
    for t in tris:
        p = [np.array(verts[k], dtype=float) for k in t]
        probes = p + [(p[0] + p[1]) / 2, (p[1] + p[2]) / 2, (p[2] + p[0]) / 2,
                      (p[0] + p[1] + p[2]) / 3]
        worst, void = 0.0, False
        for q in probes:
            fz = floor.z_near(q[:2], q[2], radius=EDGE_PROBE_RADIUS)
            if math.isnan(fz):
                void = True
                continue
            d = float(q[2] - fz)
            if abs(d) > abs(worst):
                worst = d
        kind = 'void' if void else ('float' if worst > SURFACE_TOL else
                                   'sink' if worst < -SURFACE_TOL else 'on')
        out.append((t, worst, kind))
    return out


def _angles(verts, t):
    """The three interior angles of a triangle in plan, degrees."""
    p = [np.array(verts[k][:2], dtype=float) for k in t]
    out = []
    for i in range(3):
        u, v = p[(i + 1) % 3] - p[i], p[(i + 2) % 3] - p[i]
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        c = float(np.dot(u, v) / (nu * nv)) if nu and nv else 1.0
        out.append(math.degrees(math.acos(max(-1.0, min(1.0, c)))))
    return out


def _slope_deg(verts, t):
    """Tilt of a triangle's plane from horizontal, degrees."""
    a, b, c = (np.array(verts[k], dtype=float) for k in t)
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n)
    return math.degrees(math.acos(min(1.0, abs(n[2]) / ln))) if ln else 0.0


def _plan_area(verts, t):
    """Area of a triangle projected onto the XY plane."""
    a, b, c = (verts[k] for k in t)
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2


def quad_pairs(verts, tris):
    """Interior edges whose two triangles tile a near-rectangular convex quad."""
    owners = {}
    for ti, t in enumerate(tris):
        for i in range(3):
            e = tuple(sorted((t[i], t[(i + 1) % 3])))
            owners.setdefault(e, []).append(ti)
    quads = set()
    for e, ts in owners.items():
        if len(ts) != 2:
            continue
        ring = _quad_ring(tris[ts[0]], tris[ts[1]], e)
        if ring and _is_rectangular(verts, ring):
            quads.add(tuple(ts))
    return quads


def _quad_ring(t0, t1, e):
    """Vertex ring c-a-d-b of two triangles around shared edge e, or None."""
    c = [k for k in t0 if k not in e]
    d = [k for k in t1 if k not in e]
    if len(c) != 1 or len(d) != 1:
        return None
    return (c[0], e[0], d[0], e[1])


def _is_rectangular(verts, ring):
    """Convex, all four corners within QUAD_ANGLE_TOL of a right angle."""
    p = [np.array(verts[k][:2], dtype=float) for k in ring]
    sign = None
    for i in range(4):
        u = p[(i + 1) % 4] - p[i]
        v = p[(i - 1) % 4] - p[i]
        cross = u[0] * v[1] - u[1] * v[0]
        if sign is None:
            sign = cross > 0
        elif (cross > 0) != sign:
            return False
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if not nu or not nv:
            return False
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(u, v) / (nu * nv))))))
        if abs(ang - 90.0) > QUAD_ANGLE_TOL:
            return False
    return True


def shape_stats(verts, tris):
    """`dict` of region tiling facts: count, area, quads, slivers, slopes."""
    used = {k for t in tris for k in t}
    areas = [_plan_area(verts, t) for t in tris]
    quads = quad_pairs(verts, tris)
    in_quad = {ti for pair in quads for ti in pair}
    slopes = [_slope_deg(verts, t) for t in tris]
    return {
        'tris': len(tris), 'verts': len(used),
        'area': sum(areas),
        'median_area': float(np.median(areas)) if areas else 0.0,
        'quads': len(quads),
        'in_quad_frac': len(in_quad) / len(tris) if tris else 0.0,
        'slivers': sum(1 for t in tris if min(_angles(verts, t)) < SLIVER_DEG),
        'sloped': sum(1 for s in slopes if s > 5.0),
        'steep': sum(1 for s in slopes if s > params.MAX_SLOPE_DEG),
        'max_slope': max(slopes) if slopes else 0.0,
    }


def render_panels(cell, panels, coll, bbox, out, width=900):
    """Write `out`: one panel per (verts, tris, title), same frame, side by side."""
    images = []
    for verts, tris, title in panels:
        cv = draw.Canvas(bbox, width)
        draw.draw_collision(cv, coll)
        draw.draw_mesh(cv, verts, tris, z_shade=True)
        draw.draw_pathgrid(cv, cell.nodes, cell.edges, cell.doors, alpha=140)
        draw.draw_scalebar(cv, draw.draw_grid(cv))
        cv.dr.text((8, 8), '%s -- %s' % (cell.name, title),
                   fill=(255, 255, 255, 255))
        images.append(cv.img.convert('RGBA'))
    w = sum(p.width for p in images) + 8 * (len(images) - 1)
    h = max(p.height for p in images)
    im = Image.new('RGBA', (w, h), (0, 0, 0, 255))
    x = 0
    for p in images:
        im.paste(p, (x, 0))
        x += p.width + 8
    im.convert('RGB').save(out)


def _pct(n, d):
    """n as a percentage of d, 0 when d is 0."""
    return 100.0 * n / d if d else 0.0


def report_extent(surfs, samples):
    """Print floor coverage per mesh, and what the human added/removed.

    The first mesh is what the human started from, the last their target.
    """
    cov = {label: covered(surf, samples) for label, surf in surfs}
    print('  EXTENT  walkable floor samples in region: %d' % len(samples))
    for label, c in cov.items():
        print('    covered by %-9s: %5.1f%%' % (label, _pct(sum(c), len(samples))))
    cb, cf = cov[surfs[0][0]], cov[surfs[-1][0]]
    gained = sum(1 for b, f in zip(cb, cf) if f and not b)
    lost = sum(1 for b, f in zip(cb, cf) if b and not f)
    print('    floor the human ADDED mesh over   : %d samples (%.0f u^2)'
          % (gained, gained * FLOOR_STEP ** 2))
    print('    floor the human REMOVED mesh from : %d samples (%.0f u^2)'
          % (lost, lost * FLOOR_STEP ** 2))
    if 'now' in cov and surfs[0][0] != 'now':
        cn = cov['now']
        print('    of the ADDED floor, now covered   : %d / %d'
              % (sum(1 for b, f, n in zip(cb, cf, cn) if f and not b and n),
                 gained))


def report_surface(label, fit):
    """Print how the region's triangles sit on the collision floor."""
    kinds = {k: [w for (_t, w, kk) in fit if kk == k]
             for k in ('on', 'float', 'sink', 'void')}
    print('  SURFACE %-9s on floor %3d   floating %3d (max %+.0fu)   sunk %3d '
          '(max %+.0fu)   over nothing %3d'
          % (label, len(kinds['on']), len(kinds['float']),
             max(kinds['float'] or [0.0]), len(kinds['sink']),
             min(kinds['sink'] or [0.0]), len(kinds['void'])))


def report_shape(label, st):
    """Print how the region is tiled."""
    print('  SHAPE   %-9s %3d tris / %3d verts   median tri %5.0f u^2   '
          'quads %2d (%.0f%% of tris)   slivers %2d   sloped>5deg %2d   '
          'steep>%d %d   max %.0f deg'
          % (label, st['tris'], st['verts'], st['median_area'], st['quads'],
             100 * st['in_quad_frac'], st['slivers'], st['sloped'],
             params.MAX_SLOPE_DEG, st['steep'], st['max_slope']))


def _worst(fit, n=6):
    """The n triangles furthest off the floor, `[(tri, worst, kind)]`."""
    bad = [f for f in fit if f[2] != 'on']
    return sorted(bad, key=lambda f: -abs(f[1]) if f[2] != 'void' else -1e9)[:n]


def _centroid(verts, t):
    """Centroid of an indexed triangle as an (x, y, z) tuple."""
    return tuple(sum(verts[k][i] for k in t) / 3.0 for i in range(3))


def list_changes(base_v, fix_v, moved, added_v, removed_t, added_t):
    """Per-vertex and per-triangle diff, for reading one edit at a time."""
    for i in moved:
        a, b = base_v[i], fix_v[i]
        print('    v%-4d (%7.1f,%7.1f,%7.1f) -> (%7.1f,%7.1f,%7.1f)  dxy %5.1f dz %+5.1f'
              % (i, a[0], a[1], a[2], b[0], b[1], b[2],
                 math.dist(a[:2], b[:2]), b[2] - a[2]))
    for i in added_v:
        print('    v%-4d NEW at (%7.1f,%7.1f,%7.1f)' % ((i,) + tuple(fix_v[i])))
    for t in removed_t:
        print('    tri REMOVED %s at (%.0f,%.0f,%.0f)' % ((t,) + _centroid(base_v, t)))
    for t in added_t:
        print('    tri ADDED   %s at (%.0f,%.0f,%.0f)' % ((t,) + _centroid(fix_v, t)))


def _report_region(cell, meshes, bbox, zlo, zhi, out):
    """Measure and print EXTENT / SURFACE / SHAPE for each labelled mesh.

    `meshes` is `[(label, verts, tris)]` in report order; 'base' and
    'corrected' must be present.
    """
    region = [(label, verts, _in_region(verts, tris, bbox, zlo, zhi))
              for (label, verts, tris) in meshes]
    walk, block = draw.clip_collision(cell.collision(), zlo - SURFACE_WINDOW,
                                      zhi + params.AGENT_HEIGHT)
    floor = _Surface(walk)
    samples = floor_samples(walk, bbox, zlo - params.MAX_CLIMB,
                            zhi + params.MAX_CLIMB)
    report_extent([(label, _Surface(_mesh_soup(verts, tris)))
                   for (label, verts, tris) in region], samples)
    fits = [(label, surface_fit(verts, tris, floor))
            for (label, verts, tris) in region]
    for label, fit in fits:
        report_surface(label, fit)
    now = dict(fits).get('now', fits[0][1])
    now_v = dict((label, verts) for (label, verts, _t) in region)
    for (t, w, kind) in _worst(now):
        print('    worst now %-5s %+6.0fu  tri %s at (%.0f,%.0f,%.0f)'
              % ((kind, w, t) + _centroid(now_v.get('now', region[0][1]), t)))
    for label, verts, tris in region:
        report_shape(label, shape_stats(verts, tris))
    if out:
        d = os.path.dirname(out)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        render_panels(cell, [(verts, tris, label) for (label, verts, tris) in region],
                      (walk, block), bbox, out)
        print('  wrote %s' % out)


def _valid_tris(verts, tris, label):
    """Triangles whose corners exist; an editor bug can leave dangling indices."""
    ok = [t for t in tris if all(0 <= int(k) < len(verts) for k in t[:3])]
    if len(ok) != len(tris):
        print('  WARNING: %d %s triangles reference missing vertices, dropped'
              % (len(tris) - len(ok), label))
    return ok


def ops_region(ops, fix_v, pad):
    """`(bbox, zlo, zhi)` from the ops' POSITIONS alone, for a fix with no base.

    The ops still say nothing about intent; they only say where the human
    was working.
    """
    pts = []
    for op in ops:
        if 'to' in op:
            pts.append(tuple(float(c) for c in op['to']))
        for key in ('v', 'to_v'):
            if key in op and 0 <= int(op[key]) < len(fix_v):
                pts.append(tuple(fix_v[int(op[key])]))
        for k in op.get('verts', ()):
            if 0 <= int(k) < len(fix_v):
                pts.append(tuple(fix_v[int(k)]))
    xs, ys, zs = zip(*pts)
    bbox = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    return bbox, min(zs) - params.MAX_CLIMB, max(zs) + params.MAX_CLIMB


def _analyze_without_base(cell, entry, now, pad, out):
    """Score NOW against the corrected mesh where the human worked."""
    fix_v = entry['result']['verts']
    fix_t = _valid_tris(fix_v, entry['result']['tris'], 'corrected')
    print('%s / %s   (no `base` recorded; region from the op positions)'
          % (entry['plugin'], entry['cell']))
    bbox, zlo, zhi = ops_region(entry['ops'], fix_v, pad)
    print('  region : x %.0f..%.0f  y %.0f..%.0f  z %.0f..%.0f'
          % (bbox[0], bbox[2], bbox[1], bbox[3], zlo, zhi))
    _report_region(cell, [('now', now[0], now[1]), ('corrected', fix_v, fix_t)],
                   bbox, zlo, zhi, out)


def analyze(idx, entry, pad, out, listing=False, lattice=False):
    """Diff one correction against its base and score the generator NOW.

    `lattice` scores the prototype lattice generator as NOW instead.
    """
    cell = idx.cell(re.sub(r'\.\d+$', '', entry['cell']))
    if cell is None:
        print('%s: cell not found' % entry['cell'])
        return
    now_v, now_t = cell.build(lattice=lattice)
    print('=' * 72)
    same = mesh_hash(now_v, now_t) == entry.get('base_hash')
    base = entry.get('base')
    if base is None and not same:
        _analyze_without_base(cell, entry, (now_v, now_t), pad, out)
        return
    if base is None:
        base = {'verts': now_v, 'tris': now_t}
    base_v = base['verts']
    base_t = _valid_tris(base_v, base['tris'], 'base')
    fix_v = entry['result']['verts']
    fix_t = _valid_tris(fix_v, entry['result']['tris'], 'corrected')
    print('%s / %s%s' % (entry['plugin'], entry['cell'],
                         '' if same else '   (generator has moved since the fix)'))
    moved, added_v, removed_t, added_t = diff_meshes(base_v, base_t, fix_v, fix_t)
    if not (moved or added_v or removed_t or added_t):
        print('  no difference')
        return
    bbox, zlo, zhi = touched_region(fix_v, base_v, moved, added_v, removed_t,
                                    added_t, pad)
    print('  touched: %d verts moved, %d added, %d tris removed, %d added'
          % (len(moved), len(added_v), len(removed_t), len(added_t)))
    print('  region : x %.0f..%.0f  y %.0f..%.0f  z %.0f..%.0f'
          % (bbox[0], bbox[2], bbox[1], bbox[3], zlo, zhi))
    if listing:
        list_changes(base_v, fix_v, moved, added_v, removed_t, added_t)
    meshes = [('base', base_v, base_t)]
    if not same:
        meshes.append(('now', now_v, now_t))
    meshes.append(('corrected', fix_v, fix_t))
    _report_region(cell, meshes, bbox, zlo, zhi, out)


def main():
    """CLI: analyze every fix on disk, or one `--cell` of one `--plugin`."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cell', help='one corrected cell (default: every fix)')
    ap.add_argument('--plugin', default='Oblivion.esm')
    ap.add_argument('--pad', type=float, default=DEFAULT_PAD)
    ap.add_argument('--out', help='PNG path (default temp/fix_<cell>.png)')
    ap.add_argument('--no-png', action='store_true')
    ap.add_argument('--list', action='store_true', help='print every changed vertex/tri')
    ap.add_argument('--lattice', action='store_true',
                    help='score the prototype lattice generator as "now"')
    a = ap.parse_args()
    targets = [(a.plugin, a.cell)] if a.cell else fixed_cells()
    by_plugin = {}
    for plugin, cell in targets:
        by_plugin.setdefault(plugin, []).append(cell)
    for plugin, cells in by_plugin.items():
        idx = NavIndex(os.path.join('export', plugin))
        for cell in cells:
            entry = load_fix(plugin, cell)
            if entry is None:
                print('%s/%s: no fix on disk' % (plugin, cell))
                continue
            out = None if a.no_png else (a.out or 'temp/fix_%s.png' % cell)
            analyze(idx, entry, a.pad, out, listing=a.list, lattice=a.lattice)
    return 0


if __name__ == '__main__':
    sys.exit(main())
