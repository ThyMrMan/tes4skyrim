"""Repair inverted collision winding: the "I fall through the floor" fix.

Split out of collision.py.  A collision triangle whose winding points the
wrong way is one-sided the wrong side, so the player falls through it.  The
repair works purely on triangle index tuples and vertex lists -- it never
touches a NIF block -- and uses the RENDER mesh as its orientation oracle.

See: docs/commentary/asset_convert_collision.md#inverted-collision-winding-i-fall
See: docs/commentary/asset_convert_collision.md#morroblivion-collision-is-copied-render
"""

import math
from itertools import permutations

from core.collision_options import winding_fix_enabled
from asset_convert.collision.collision_falloutnv import is_fallout_source

#: An authored normal must oppose the face normal by this much to count.
AUTHORED_NORMAL_DOT = -0.3

#: Triangles rewound so far; a list so process workers can mutate it.
INVERTED_FLOOR_FLIPS = [0]

#: Vertex-set quantum for the twin match, in Skyrim havok units (~0.02 game).
_TWIN_QUANTUM = 0.02 / 69.9904

#: A render face must align with the collision face by at least this much.
_PARALLEL = 0.70

#: Slack (1 game unit) for "the skin is on the side its normal claims".
_SLAB_EPS = 1.0 / 7.0

#: A plank is THIN: a skin further than this (8 game units) is another surface.
_MAX_SLAB_DZ = 8.0 / 7.0

#: Candidates within this much of the nearest must agree, or the face abstains.
_CONSENSUS_MARGIN = 0.05

#: A render face further than this many triangle-widths away is another surface.
_MAX_MATCH_WIDTHS = 2.0

#: Two faces' normals must be this parallel (either sign) to count as one plane.
COPLANAR_DOT = 0.999


def face_normal(tri):
    """Normalized face normal for a triangle given as three xyz tuples."""
    (v0, v1, v2) = tri
    ux, uy, uz = v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2]
    vx, vy, vz = v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2]
    nx = uy*vz - uz*vy
    ny = uz*vx - ux*vz
    nz = ux*vy - uy*vx
    mag = math.sqrt(nx*nx + ny*ny + nz*nz)
    if mag > 0:
        nx /= mag; ny /= mag; nz /= mag
    return nx, ny, nz


def _vertex_key(tri):
    """Order-independent quantized key for a triangle's three corners."""
    return tuple(sorted(tuple(round(c / _TWIN_QUANTUM) for c in v)
                        for v in tri))


def _render_faces(visual_tris):
    """[(tri, normal)] for each render face with a usable normal."""
    out = []
    for t in visual_tris or ():
        n = face_normal(t)
        if n[0] or n[1] or n[2]:
            out.append((t, n))
    return out


def _render_states_a_floor(faces):
    """Whether the render mesh has any up-facing horizontal surface.

    A mesh whose horizontal faces ALL point down is itself wound backwards,
    so it cannot be the orientation oracle: trusting it inverts collision
    that was correct.  `inuvelothismalludju01` ships 0 up / 40 down and lost
    all 62 of its standable cells to it.
    See: docs/commentary/asset_convert_collision.md#round-4b-the-rule-must-abstain
    """
    up = down = 0
    for _t, n in faces:
        if n[2] > 0.5:
            up += 1
        elif n[2] < -0.5:
            down += 1
    return up > 0 or down == 0


def _twin_index(faces):
    """{vertex_key: [normal, ...]} over the render faces."""
    idx = {}
    for tri, n in faces:
        idx.setdefault(_vertex_key(tri), []).append(n)
    return idx


def _twin_says_inverted(tri, n, twins):
    """Whether the render face this collision face COPIES is opposed.

    None when no render face shares this exact vertex set.
    See: docs/commentary/asset_convert_collision.md#morroblivion-collision-is-copied-render
    """
    got = twins.get(_vertex_key(tri))
    if not got:
        return None
    best = max(got, key=lambda o: abs(n[0]*o[0] + n[1]*o[1] + n[2]*o[2]))
    dot = n[0]*best[0] + n[1]*best[1] + n[2]*best[2]
    return dot < 0 if abs(dot) > 0.5 else None


def _projected_overlap(ctri, cn, rtri):
    """Whether the two triangles overlap projected along cn's dominant axis."""
    ax = max(range(3), key=lambda i: abs(cn[i]))
    u, v = [i for i in range(3) if i != ax]
    a = [(p[u], p[v]) for p in ctri]
    b = [(p[u], p[v]) for p in rtri]
    for poly, other in ((a, b), (b, a)):
        for i in range(3):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % 3]
            nx, ny = -(y2 - y1), (x2 - x1)
            pa = [nx * (px - x1) + ny * (py - y1) for px, py in poly]
            pb = [nx * (px - x1) + ny * (py - y1) for px, py in other]
            if max(pb) < min(pa) - 1e-6 or min(pb) > max(pa) + 1e-6:
                return False
    return True


def _triangle_width(t):
    """Mean edge length: the triangle's own scale, for a relative distance cap."""
    e = 0.0
    for i in range(3):
        p, q = t[i], t[(i + 1) % 3]
        e += math.sqrt((p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2)
    return e / 3.0


def _vertex_set_distance(a, b):
    """Least total corner-to-corner distance over the six pairings."""
    best = None
    for p in permutations(range(3)):
        d = 0.0
        for i in range(3):
            q = b[p[i]]
            d += math.sqrt((a[i][0]-q[0])**2 + (a[i][1]-q[1])**2
                           + (a[i][2]-q[2])**2)
        if best is None or d < best:
            best = d
    return best


def _wrong_side_of_slab(tri, n, rtri):
    """Whether `rtri` sits on the side `n` does not face.

    A thin plank's two skins are both within any usable distance, so nearest
    alone picks between them at random.  A skin may only decide a face it
    could BE: an up-facing face by a skin at or above it, a down-facing face
    by one at or below, and within `_MAX_SLAB_DZ` either way -- a plank is
    thin, so a skin further off is a different surface entirely.
    See: docs/commentary/asset_convert_collision.md#round-4b-the-rule-must-abstain
    """
    if abs(n[2]) < 0.5:
        return False
    dz = (sum(p[2] for p in rtri) / 3.0) - (sum(p[2] for p in tri) / 3.0)
    if abs(dz) > _MAX_SLAB_DZ:
        return True
    if n[2] > 0 and dz < -_SLAB_EPS:
        return True
    return n[2] < 0 and dz > _SLAB_EPS


def _covers_xy(tri, x, y):
    """Whether the triangle's XY projection contains the point."""
    (ax, ay, _az), (bx, by, _bz), (cx, cy, _cz) = tri
    d1 = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
    d2 = (cx - bx) * (y - by) - (cy - by) * (x - bx)
    d3 = (ax - cx) * (y - cy) - (ay - cy) * (x - cx)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def _floor_says_inverted(tri, n, faces):
    """Whether a flat face under a walkable skin points down; None without one.

    An up-facing render face over the face's centre, at or within a plank's
    thickness above it, is a floor stood on from above; collision is
    one-sided, so the face must face up. Nearest-skin cannot say so: its slab
    gate never lets a skin above decide a down-facing face.
    See: docs/commentary/asset_convert_collision.md#round-4d-a-face-under-a-floor-faces-up
    """
    if abs(n[2]) < 0.5:
        return None
    x, y, z = (sum(p[i] for p in tri) / 3.0 for i in range(3))
    for rtri, rn in faces:
        dz = sum(p[2] for p in rtri) / 3.0 - z
        if rn[2] < _PARALLEL or not -_SLAB_EPS <= dz <= _MAX_SLAB_DZ:
            continue
        if _covers_xy(rtri, x, y):
            return n[2] < 0
    return None


def _nearest_says_inverted(tri, n, faces):
    """Whether the closest coincident render surface is opposed.

    Nearest by VERTEX SET, for collision that is a simplification of the
    render mesh rather than a copy of it.  None when the candidates tied for
    nearest disagree: a coarse shell far from any skin has no evidence, and
    guessing there turns a solid floor into a fall-through.
    See: docs/commentary/asset_convert_collision.md#round-4b-the-rule-must-abstain
    """
    cands = []
    for rtri, rn in faces:
        align = n[0]*rn[0] + n[1]*rn[1] + n[2]*rn[2]
        if abs(align) < _PARALLEL:
            continue
        if _wrong_side_of_slab(tri, n, rtri):
            continue
        if not _projected_overlap(tri, n, rtri):
            continue
        cands.append((_vertex_set_distance(tri, rtri), align))
    if not cands:
        return None
    cands.sort()
    if cands[0][0] > _MAX_MATCH_WIDTHS * _triangle_width(tri):
        return None
    limit = cands[0][0] * (1.0 + _CONSENSUS_MARGIN) + 1e-9
    if len({c[1] < 0 for c in cands if c[0] <= limit}) > 1:
        return None
    return cands[0][1] < 0


def _authored_flips(tris, authored_normals):
    """Step 0: triangles whose winding contradicts their own stored normal.

    Ungated: it reads a fact the file states about itself, so it is safe on
    every plugin and inert wherever winding and normal already agree.
    See: docs/commentary/asset_convert_collision.md#rewritten-2026-08-20-round-3--the-winding-is-authored-stop-inferring-it
    """
    out = set()
    if not authored_normals or len(authored_normals) != len(tris):
        return out
    for i, (t, an) in enumerate(zip(tris, authored_normals)):
        if an is None:
            continue
        alen = math.sqrt(an[0]**2 + an[1]**2 + an[2]**2)
        if alen < 1e-6:
            continue
        n = face_normal(t)
        if (n[0]*an[0] + n[1]*an[1] + n[2]*an[2]) / alen < AUTHORED_NORMAL_DOT:
            out.add(i)
    return out


def _render_verdicts(tris, faces):
    """{index: inverted?} for each face the render mesh decides."""
    twins = _twin_index(faces)
    verdicts = {}
    for i, t in enumerate(tris):
        n = face_normal(t)
        if not (n[0] or n[1] or n[2]):
            continue
        verdict = _twin_says_inverted(t, n, twins)
        if verdict is None:
            verdict = _floor_says_inverted(t, n, faces)
        if verdict is None:
            verdict = _nearest_says_inverted(t, n, faces)
        if verdict is not None:
            verdicts[i] = verdict
    return verdicts


def _edge_neighbours(tris):
    """{index: [indices sharing an edge]}, corners matched by the twin quantum."""
    by_edge = {}
    for i, t in enumerate(tris):
        keys = [tuple(round(c / _TWIN_QUANTUM) for c in v) for v in t]
        for a in range(3):
            by_edge.setdefault(frozenset((keys[a], keys[(a + 1) % 3])), []).append(i)
    out = {}
    for owners in by_edge.values():
        for i in owners:
            out.setdefault(i, []).extend(j for j in owners if j != i)
    return out


def _coplanar(a, na, b, nb):
    """Whether two edge-sharing faces continue one plane: parallel normals,
    the same offset, and the two faces on opposite sides of their edge (a
    face folded back over the other is a two-sided sheet, left alone)."""
    if abs(na[0]*nb[0] + na[1]*nb[1] + na[2]*nb[2]) < COPLANAR_DOT:
        return False
    offset = sum(na[k] * (a[0][k] - b[0][k]) for k in range(3))
    if abs(offset) > _TWIN_QUANTUM * 4:
        return False
    return _edge_side(a, b, na) * _edge_side(b, a, na) < 0


def _edge_side(t, other, n):
    """Which side of the edge shared with `other` t's third corner lies on."""
    def key(v):
        """The corner quantized as the twin match does."""
        return tuple(round(c / _TWIN_QUANTUM) for c in v)

    keys = {key(v) for v in other}
    shared = sorted((v for v in t if key(v) in keys), key=key)
    apex = [v for v in t if key(v) not in keys]
    if len(shared) != 2 or len(apex) != 1:
        return 0.0
    (p, q), r = shared, apex[0]
    e = [q[k] - p[k] for k in range(3)]
    d = [r[k] - p[k] for k in range(3)]
    cross = (e[1]*d[2] - e[2]*d[1], e[2]*d[0] - e[0]*d[2], e[0]*d[1] - e[1]*d[0])
    return sum(cross[k] * n[k] for k in range(3))


def _spread_to_coplanar(tris, verdicts):
    """Decide each undecided face from a decided coplanar edge neighbour.

    Two triangles of one flat surface must face the same way; a face the
    render mesh cannot see (a gap between render planks) takes its winding
    from the half of its quad that it can. Neighbours that disagree decide
    nothing.
    See: docs/commentary/asset_convert_collision.md#coplanar-neighbours-agree
    """
    normals = [face_normal(t) for t in tris]
    neighbours = _edge_neighbours(tris)
    changed = True
    while changed:
        changed = False
        for i in range(len(tris)):
            if i in verdicts or not any(normals[i]):
                continue
            wants = {_opposes(normals[i], normals[j], verdicts[j])
                     for j in neighbours.get(i, ())
                     if j in verdicts and _coplanar(tris[i], normals[i], tris[j], normals[j])}
            if len(wants) == 1:
                verdicts[i] = wants.pop()
                changed = True
    return verdicts


def _opposes(n, other, other_inverted):
    """Whether normal `n` faces against `other` as it will be once repaired."""
    dot = n[0]*other[0] + n[1]*other[1] + n[2]*other[2]
    return (dot < 0) != other_inverted


def _render_flips(tris, faces):
    """Indices the render mesh says are wound backwards."""
    verdicts = _spread_to_coplanar(tris, _render_verdicts(tris, faces))
    return {i for i, inverted in verdicts.items() if inverted}


def _rewound(tris, flip):
    """`(tris, n)` with every index in `flip` reversed; the input when empty."""
    if not flip:
        return tris, 0
    out = [(t[0], t[2], t[1]) if i in flip else t
           for i, t in enumerate(tris)]
    return out, len(flip)


def repair_inverted_floors(tris, visual_tris=None, groups=None,
                           authored_normals=None):
    """Rewind collision triangles wound backwards; `(repaired_tris, n_flipped)`.

    Step 0 (the authored normal) is ungated; the render-mesh repair is gated
    per plugin except for FO3/FNV sources, and supersedes step 0 where it
    reaches a verdict.  `groups` is accepted for call compatibility only.
    See: docs/commentary/asset_convert_collision.md#morroblivion-collision-is-copied-render
    See: docs/commentary/asset_convert_falloutnv.md#two-sided-welding
    """
    if not tris:
        return tris, 0

    flip = _authored_flips(tris, authored_normals)
    if not (winding_fix_enabled() or is_fallout_source()):
        return _rewound(tris, flip)

    faces = _render_faces(visual_tris)
    if faces and _render_states_a_floor(faces):
        flip = _render_flips(tris, faces)
    return _rewound(tris, flip)


def two_sided_floors(tris, materials, visual_tris):
    """`(tris, materials)` plus a reversed copy of each face only the floor rule decided (FO3/FNV).

    A face with no render twin under a walkable skin is turned up, but FO3/FNV
    collide both sides: a slab placed upside down is then stood on from its
    underside, so that face is kept from both sides.
    See: docs/commentary/asset_convert_falloutnv.md#upside-down-slabs
    """
    faces = _render_faces(visual_tris)
    if not faces:
        return tris, materials
    twins = _twin_index(faces)
    extra = [i for i, t in enumerate(tris) if any(face_normal(t))
             and _twin_says_inverted(t, face_normal(t), twins) is None
             and _floor_says_inverted(t, face_normal(t), faces) is not None]
    return (list(tris) + [(tris[i][0], tris[i][2], tris[i][1]) for i in extra],
            list(materials) + [materials[i] for i in extra])
