"""Render a cell's generated navmesh to a PNG for eyeball inspection.

Numbers tell you a cell has 3 uncovered samples; only a picture tells you they
form a slit across a staircase.  This is the tool for "there is a hole in the
top stairs" style reports, and the instrument the authored-navmesh comparison is
judged with.

Layers and the colour contract live in tools/navmesh/draw.py: red/orange/yellow
are MESH DEFECTS only, collision and any authored underlay draw cool.

    # whole cell, with walls, height shading, grid and legend
    python tools/navmesh/render.py ImperialDungeon01 --collision --z-shade

    # what storeys are there?  (then isolate one)
    python tools/navmesh/render.py AnvilPinarusInventiusHouse --bands
    python tools/navmesh/render.py AnvilPinarusInventiusHouse --z 300 700

    # an AUTHORED navmesh from a shipped ESM, as the answer key
    python tools/navmesh/render.py --authored-esm "<path>/BSHeartland.esm" \
        --authored-cell BrumaChapelHall --authored-only

    # our mesh over the authored one, same frame
    python tools/navmesh/render.py BrumaChapelHall \
        --authored-esm "<path>/BSHeartland.esm" --authored-cell BrumaChapelHall

    # zoom on the area around a placed reference the user complained about
    python tools/navmesh/render.py --ref 1A01FC1E --pad 400 --cracks
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tes5_import.navmesh import params
from tools.navmesh import draw
from tools.navmesh.authored import load_authored
from tools.navmesh.index import NavIndex, DEFAULT_EXPORT
from tools.navmesh.metrics import (
    crossed_boundary_edges, open_notches,
)


def render(verts, tris, nodes, edges, doors, out, bbox=None, width=1400,
           bare=False, cracks=None, title=None, collision=None, ids=False,
           notches=None, z_shade=False, node_ids=False, path_alpha=200,
           authored=None, chrome=True):
    """Draw one cell to `out`; every argument is a plain array, not a cell.

    Taking arrays rather than a CellCtx is what lets the same renderer draw an
    authored navmesh parsed out of a shipped ESM.
    """
    frame = bbox or draw.mesh_bbox(verts or (authored or ([], []))[0])
    cv = draw.Canvas(frame, width)
    if collision:
        draw.draw_collision(cv, collision)
    if authored:
        draw.draw_authored(cv, authored[0], authored[1])
    draw.draw_mesh(cv, verts, tris, ids=ids, z_shade=z_shade)
    if cracks:
        draw.draw_cracks(cv, verts, cracks)
    if notches:
        draw.draw_notches(cv, verts, notches)
    if not bare:
        draw.draw_pathgrid(cv, nodes, edges, doors, alpha=path_alpha,
                           ids=node_ids)
    if chrome:
        draw.draw_scalebar(cv, draw.draw_grid(cv))
        draw.draw_legend(cv, draw.legend_for(collision, z_shade, authored,
                                             cracks, notches, mesh=bool(tris),
                                             pathgrid=not bare))
    cv.save(out)
    print('wrote %s (%d tris%s%s%s)%s'
          % (out, len(tris),
             ', %d authored' % len(authored[1]) if authored else '',
             ', %d crack edges' % len(cracks) if cracks else '',
             ', %d NOTCHES' % len(notches) if notches else '',
             ' [%s]' % title if title else ''))


def _add_args(ap):
    """Register every flag; kept apart so main() stays inside the shape limit."""
    ap.add_argument('cell', nargs='?', help='cell EditorID or FormID')
    ap.add_argument('--ref', help='center on this placed reference FormID '
                                  '(finds its cell automatically)')
    ap.add_argument('--pad', type=float, default=512.0,
                    help='half-extent around --ref (default 512)')
    ap.add_argument('-o', '--out', help='output PNG (default temp/<cell>.png)')
    ap.add_argument('--z', nargs=2, type=float, metavar=('ZMIN', 'ZMAX'),
                    help='keep only triangles whose centroid z is in range '
                         '(isolate ONE storey)')
    ap.add_argument('--bands', action='store_true',
                    help='print the storey bands and exit -- pick --z from '
                         'the cell data instead of guessing')
    ap.add_argument('--bbox', nargs=4, type=float,
                    metavar=('MINX', 'MINY', 'MAXX', 'MAXY'))
    ap.add_argument('--bare', action='store_true',
                    help='mesh only: no pathgrid, node or door overlay')
    ap.add_argument('--cracks', action='store_true',
                    help='highlight boundary edges a walked line crosses')
    ap.add_argument('--notches', action='store_true',
                    help='ring every open V-notch bitten into the surface')
    ap.add_argument('--collision', action='store_true',
                    help='draw the real collision underneath, clipped to the '
                         'storey the mesh occupies')
    ap.add_argument('--no-z-clip', action='store_true',
                    help='draw collision at every height (ceilings included)')
    ap.add_argument('--z-shade', action='store_true',
                    help='shade mesh triangles by height, so relief reads')
    ap.add_argument('--ids', action='store_true',
                    help='label each triangle with its index')
    ap.add_argument('--node-ids', action='store_true',
                    help='label each PATHGRID NODE with its index')
    ap.add_argument('--path-alpha', type=int, default=200,
                    help='pathgrid edge opacity 0-255 (default 200)')
    ap.add_argument('--no-chrome', action='store_true',
                    help='omit grid, scale bar and legend')
    ap.add_argument('--authored-esm', help='ESM/ESP to read an authored '
                                           'navmesh from (the answer key)')
    ap.add_argument('--authored-cell',
                    help='cell EditorID in --authored-esm (default: same name)')
    ap.add_argument('--authored-only', action='store_true',
                    help='render ONLY the authored mesh, with no cell of ours')
    ap.add_argument('--width', type=int, default=1400)
    ap.add_argument('--export', default=DEFAULT_EXPORT)
    ap.add_argument('--lattice', action='store_true',
                    help='build with the prototype lattice generator')


def _pick_cell(idx, a):
    """Resolve --ref / positional cell to `(CellCtx, bbox)`, or `(None, None)`."""
    bbox = tuple(a.bbox) if a.bbox else None
    if not a.ref:
        cell = idx.cell(a.cell)
        if cell is None:
            print('cell %s not found' % a.cell)
        return cell, bbox
    cell, refr = idx.cell_of_ref(a.ref)
    if cell is None:
        print('reference %s not found in any cell' % a.ref)
        return None, None
    from tes5_import.base.text_reader import get_float
    rx = get_float(refr, 'PosX', 0.0)
    ry = get_float(refr, 'PosY', 0.0)
    print('ref %s is in cell %s (%s) at (%.0f, %.0f)'
          % (a.ref, cell.name, cell.fid, rx, ry))
    return cell, bbox or (rx - a.pad, ry - a.pad, rx + a.pad, ry + a.pad)


def _print_bands(verts, tris):
    """Report the storey clusters so --z can be chosen from data."""
    for (lo, hi, n) in draw.storey_bands(verts, tris):
        print('  band z %8.1f .. %8.1f  %5d tris' % (lo, hi, n))


def _authored_render(a):
    """Render an authored navmesh on its own, with no cell of ours."""
    av, at = load_authored(a.authored_esm, a.authored_cell)
    if not at:
        print('no authored navmesh for %s' % a.authored_cell)
        return 1
    out = a.out or ('temp/%s_authored.png' % a.authored_cell)
    _ensure_dir(out)
    render([], [], [], [], [], out, bbox=tuple(a.bbox) if a.bbox else None,
           width=a.width, bare=True, title='%s (authored)' % a.authored_cell,
           authored=(av, at), chrome=not a.no_chrome)
    return 0


def _ensure_dir(out):
    """Create the output directory if the path names one."""
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)


def _collision_for(cell, verts, tris, a):
    """Cell collision, clipped to the mesh's own Z slab unless --no-z-clip."""
    coll = cell.collision()
    if a.no_z_clip:
        return coll
    zs = [verts[k][2] for t in tris for k in t]
    return draw.clip_collision(coll, min(zs) - params.MAX_CLIMB,
                               max(zs) + params.AGENT_HEIGHT)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_args(ap)
    a = ap.parse_args()
    if a.authored_only:
        return _authored_render(a)
    if not a.cell and not a.ref:
        ap.error('give a cell name, --ref, or --authored-only')

    idx = NavIndex(a.export)
    cell, bbox = _pick_cell(idx, a)
    if cell is None:
        return 1
    if not cell.has_pathgrid:
        print('%s: no pathgrid' % cell.name)
        return 1

    verts, tris = cell.build(lattice=a.lattice)
    if a.bands:
        _print_bands(verts, tris)
        return 0
    if a.z:
        tris = [tri for tri in tris
                if a.z[0] <= sum(verts[k][2] for k in tri) / 3.0 <= a.z[1]]
    if not tris:
        print('%s: no triangles in view' % cell.name)
        return 1

    authored = None
    if a.authored_esm:
        authored = load_authored(a.authored_esm, a.authored_cell or cell.name)
    cracks = crossed_boundary_edges(verts, tris, cell) if a.cracks else None
    notches = open_notches(verts, tris, cell) if a.notches else None
    coll = _collision_for(cell, verts, tris, a) if a.collision else None
    out = a.out or ('temp/%s.png' % (cell.name or 'cell'))
    _ensure_dir(out)
    render(verts, tris, cell.nodes, cell.edges, cell.doors, out,
           bbox=bbox, width=a.width, bare=a.bare, cracks=cracks,
           title=cell.name, collision=coll, ids=a.ids, notches=notches,
           z_shade=a.z_shade, node_ids=a.node_ids, path_alpha=a.path_alpha,
           authored=authored, chrome=not a.no_chrome)
    return 0


if __name__ == '__main__':
    sys.exit(main())
