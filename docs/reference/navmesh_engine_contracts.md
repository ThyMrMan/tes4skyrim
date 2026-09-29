# Navmesh contracts read out of the pathfinder

What Skyrim's pathfinder actually does with a written NVNM, read from the
`bspathfinding` library. The addresses are **CreationKit.exe** (Steam, not
DRM-packed), which compiles the same library as the game and keeps its assert
paths (`e:\_skyrimhd\code\gamesln\bspathfinding\*.cpp`) and log strings. The
game build lays the same code out differently, so these functions were not
byte-matched in SkyrimSE 1.6.1170; treat them as the library's behavior, confirmed
by data where noted.

`tools/navmesh/engine_check.py` applies these rules to a built ESM.

## Crossing an edge: the neighbour slot is the only link

`BSNavmesh::GetMatchingTri` (CK `0x282ad30`, `bsnavmesh.cpp`). A triangle is 16
bytes: three vertex indices, three neighbour slots at +6/+8/+A, flags at +C.
To cross edge *i*:

- slot == `0xFFFF` → the edge is a wall; no crossing.
- flag bit *i* (`0x1/0x2/0x4`) set → the slot indexes the Edge Link table; the
  link names the other navmesh and triangle.
- otherwise the slot IS the neighbouring triangle's index.

Geometry is never consulted. Two triangles one unit apart, or sharing corner
positions through different vertex indices, are walls to each other unless a
slot names the other. Our writer derives slots from shared vertex indices
(`from_pgrd.compute_adjacency`), so every crack and every unwelded duplicate
vertex is a wall.

## Finding the triangle under a point

`BSPathingLocation` triangle lookup (CK `0x2844330`, `bspathinglocation.cpp`)
calls a per-navmesh finder (CK `0x2830170`, `bsnavmesh.cpp`) for every navmesh
in the location's cell:

1. Take the lookup-grid cell under the point (see below).
2. Scan that cell's triangle list in order, skipping flag `0x20` (Overlapping).
   For each triangle whose plan contains the point, keep the one with the
   smallest vertical distance; stop at the first that is within **40** units
   (an exact hit).
3. No containing triangle in the list → the triangle with the nearest
   **center** (3D) in that list.
4. Empty or missing grid cell → nearest center over the whole mesh.

Across navmeshes, an exact hit wins; otherwise the lowest
`dx² + dy² + k·dz²` to the triangle center, `k = 5` for a point above the center
and `10` below. The point is then pulled onto the chosen triangle
(`0.9 × closest point + 0.1 × center`). There is **no distance cap**: an off-mesh
point always resolves somewhere as long as the cell has a navmesh. The path
fails outright ("Start/Goal Location is not on the navmesh", CK `0x28711c0`)
only when the lookup returns no navmesh at all.

The fallback in step 3 picks by triangle *center*, not by nearest surface, so a
small triangle across a wall or on another storey can beat the large floor
triangle the actor stands beside.

## The lookup grid

The NVNM tail carries a `divisor × divisor` grid over the mesh bbox: cell
width/height = span / divisor, lists stored **row-major** (`row × divisor +
col`, row = Y). Vanilla lists a triangle in **every cell it truly overlaps**:
over 300 Skyrim.esm navmeshes (91,574 triangles) the exact triangle/rectangle
overlap rule reproduces 91,109 lists exactly; the rest differ only by cells a
triangle touches along an edge. Vanilla grids hold ~1.5–2 entries per triangle
(949 for 554, 1,254 for 784).

`tes5_import/navmesh/lookup_grid.py` builds it the same way. The writer used to
list each triangle once, in the cell holding its centroid, so a point on a
triangle whose centroid lay in a neighbouring grid cell was not found by step 2
and fell to the nearest-center guess of step 3: 494 of 1,742 triangles in
Nehrim's SchattenrufMinePart01, 333 of 6,968 surface samples mislocated. With
the overlap rule, the rebuilt Nehrim.esm (2,942 navmeshes) and Oblivion.esm
(8,238) have no grid misses, at 1.48 and 1.50 entries per triangle. Over 300
vanilla navmeshes the builder reproduces 91,112 of 91,574 triangles' cell sets;
the remaining vanilla-only entries lie up to 173 units from cells the triangle
does not touch, which is harmless to the lookup. The module is excluded from the
navmesh cache tag: it packs, it never shapes cached geometry.

## The path build

`BSPathBuilder` (CK `0x2873410`, `bspathbuilder.cpp`) runs, in order: a
straight-line walk across triangles, the triangle A* search, then
`BSPathSmootherPOV` (CK `0x284ec30`, `bspathsmootherpov.cpp`). Failures:
"Could not find a valid start/goal triangle", "No triangle path", "Path
Smoothing failed and returned %d bad nodes", "End of smoothed path is NOT within
goal radius, and incomplete paths are not allowed".

## Clearance is for objects, not walls

The smoother adds circular obstacles of radius **actor radius (request +0xC4)
+ obstacle radius + 5**: request obstacles (CK `0x28c1700`) and actors tracked
by the movement arbiter (CK `0x28c1d10`, `movementpathmanagerarbiter.cpp`). The
triangle corridor itself is used as-is: nothing in the corridor code reads the
actor radius. The engine trusts every triangle completely — a triangle inside
collision is walked into indefinitely, and there is no wall check to stop it.

A path around an obstacle circle must stay on the mesh, so a corridor that
stops short of its walls leaves no room to detour and smoothing fails.

## What the checker tests

| Rule | Meaning | Source |
|---|---|---|
| GRID_MISS | triangle absent from a grid cell it overlaps | the lookup grid |
| MISLOCATE | a point on triangle T resolves to another triangle; `SPLIT` = another component | the point lookup |
| PG_OFF / PG_SPLIT | pathgrid node with no exact hit / edge whose ends resolve into different components | lookup + neighbour slots |
| INSIDE / NO_FLOOR / HEADROOM | an actor cannot stand on the triangle | engine trusts every triangle |
| SHORT32 / SHORT64 | open edge with walkable floor that far past it, no wall on the way and nothing overhead within actor height (floor under a bed or table does not count) | clearance for obstacles |

INSIDE uses collision winding: a point is inside a solid when at least 5 of 8
horizontal waist-height probes hit a face from behind. The vertical probes
accept either face, because single meshes are wound inconsistently — Nehrim's
`dungeons/caves/crock02.nif` has downward-facing top faces, and a
backface-means-inside rule called 13 standable pathgrid nodes on it "inside".
The report prints a calibration line — what the standing rules say about the
pathgrid nodes, which are known standable — so a rule misfiring in a cell shows
up there.
