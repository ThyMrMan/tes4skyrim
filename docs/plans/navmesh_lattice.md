# Lattice navmesh generator (prototype)

**Status: EXPERIMENTAL, opt-in; not ready to be the default after in-game
testing.** The generator lives in `tes5_import/navmesh/lattice/`.
`build_navmesh` runs it only when `--navmesh-generator lattice` (GUI:
Settings > Navmesh generator) sets `TESCONV_NAVMESH_GENERATOR`; the corridor
generator is the default. The tools pick either explicitly
(`CellCtx.build(lattice=...)`, cellview's **lattice generator** checkbox,
`render.py --lattice`, `engine_check.py --build`, `fix_analyze.py --lattice`).
A lattice run caches into its own `navmesh_geom_cache_lattice/` folder under a
tag that adds `lattice/*.py` (`pool.tag_sources`); the corridor's published
`navmesh_geom_cache/` tag never hashes `lattice/`, so editing the lattice
neither invalidates the published cache nor gates a push. The pipeline hands the plugin's ACTI bases to
`lattice.build.set_activators` in the parent and in every pool worker. It
becomes commentary once the corridor generator is removed.

## Why

The corridor generator starts from thin ribbons on the pathgrid and grows them
outward, then stitches the pieces with ~6,000 lines of union/merge/cleanup.
That produces narrow corridors, overlapping triangles and holes. The lattice
generator starts from the room instead.

## The pipeline

1. **Columns** (`columns.py`). Collision is rasterized onto 16u columns
   (32u in exteriors): every walkable triangle over a column's center is a
   FLOOR; the next surface overhead is its HEADROOM. Every blocking triangle is
   cut along the column center lines and recorded on the ARMS it crosses (the
   half-segments from a column's center to its sides) with its height band, so
   a wall is caught however thin it is.
2. **Graph** (`graph.py`). A floor is alive when it has headroom (112u) and no
   wall on its arms in the actor band. Neighbouring floors within a step (34u)
   LINK, one partner per side, so the lattice is manifold.
   - **Seeds.** Every pathgrid edge is walked column by column following the
     floor (a step at a time, preferring floor an actor can stand in).
   - **Protected corridor.** Floor within 2 columns of a line, at the line's
     height, is protected like the line: exempt from wall and headroom tests,
     linking to the rest of its line's band across walls and across steps up
     to 68u. A surface over the band more than a step but under headroom
     (a closed secret wall's collision) is dropped. The band stops at walls it
     meets sideways, so a line hugging a wall does not push floor into it.
   - **Moving activators.** An ACTI placement a pathgrid edge walks straight
     through at body height (the prison's `prisonSecretWall01`) is left out of
     the collision, as door panels already are.
   - **Teleport doors.** The pathgrid decides which side of a load door is this
     cell; a wall is placed one column past the threshold on the other side and
     only the inside half of the doorway is seeded.
   - **Reach.** Floor is kept within 1024u walked from the pathgrid, flooding
     only through floor open on all four sides and adding the rim back after,
     so a gap in the collision narrower than three columns carries no flood.
   - **Small holes.** Gaps of up to 24 columns fully enclosed by kept floor,
     over an obstacle lower than 64u, are filled; a 1–2 column crack is filled
     even with no collision under it. Pits and tall obstacles stay cut.
3. **Lattice** (`mesh.py`). One quad per kept span; linked spans share their
   corner vertices; a corner's height is the mean of its spans (stairs become
   ramps). Two spans of one column never share a corner.
4. **Flat merge** (`merge.py`). Aligned 2x2 blocks of fully linked quads merge
   level by level into quads of up to 128u while every vertex lies within 4u of
   one plane and every neighbour across a side is at most one level smaller
   (so a side keeps at most one extra vertex). A merged quad is two triangles,
   or a fan from its center vertex where a side keeps a vertex a smaller
   neighbour uses. Dropped lattice vertices go to simplify as probes, so the
   16u surface rule still holds against them. Merging halves to thirds the
   triangles simplify starts from (ImperialDungeon01 36,212 → 13,519; Nehrim
   exterior 00004440 24,576 → 11,168).
5. **Exterior seams** (`build.seam_roles`). Border vertices on 128u world
   multiples, cell corners and the ends of each run of floor along an edge are
   pinned; both neighbours keep the same ones, so edge links still pair. Every
   other border vertex may only collapse along its own edge line, so the mesh
   still meets the cell edge exactly, with border edges up to 128u instead of
   32u (00004440: 99 border edges, none longer than 128u, no vertex pulled off
   the edge).
6. **Simplify** (`simplify.py`). The outline is simplified once (Douglas-Peucker,
   14u, edges at most 128u); then rounds of shortest-first half-edge collapses,
   improving flips and smoothing onto the lattice surface. Every change keeps
   CCW plan area, corner angle (22°, 15° on the outline), edge length ≤ 256u,
   every lattice point within 16u vertically, every pathgrid seed and door
   threshold covered, and never folds over a neighbouring triangle.

## Measured against the corridor generator

Five interiors most iterated on with the corridor generator (AnvilFightersGuild,
AnvilPinarusInventiusHouse, ImperialDungeon01-03), checked by
`engine_check.py --build`:

| | Corridor | Lattice |
|---|---|---|
| Pathgrid nodes off the mesh | 3 | 0 |
| Pathgrid edges split | 0 | 0 |
| Mislocated samples (overlapping layers) | 0 | 0 |
| Doors standing on a triangle | 39 of 41 | 40 of 41 (the miss has no floor within 120u) |
| SHORT32 open-edge length | 16,908u | ~6,300u |
| Triangles past the shape contract (badness > 1) | 14–22% | 24–29% |
| Triangles past badness 2 | 3–14 per cell | 0 |
| Triangle count | 1× | ~1.6× |
| Build time per cell | 1–6s | 0.6–6s |

Flat merge and seam thinning, measured old path vs new on the same inputs in
one run: the five interiors 27.8s → 15.5s (1.8×) with triangle counts within
±14 and identical `engine_check` results; seven Nehrim exteriors 1.5× faster
with 15% fewer triangles. What is left: simplify's first collapse round, the
link matching in `graph.match_links` (a third of SchattenrufMinePart04's build),
and rounds 2–8 of simplify, which land almost nothing (about 1.4s of 00004440).
