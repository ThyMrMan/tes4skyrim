"""The NVNM lookup grid: which triangles the engine tests for a point.

The engine's point lookup scans only the grid cell under the point, so every
triangle is listed in every cell it overlaps, as vanilla does.

See: docs/reference/navmesh_engine_contracts.md#the-lookup-grid
"""


def tri_hits_rect(xs, ys, x0, y0, x1, y1):
    """Separating-axis test: does the plan triangle overlap the rectangle (touching counts)?"""
    if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
        return False
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    for k in range(3):
        ax, ay, bx, by = xs[k], ys[k], xs[(k + 1) % 3], ys[(k + 1) % 3]
        nx, ny = by - ay, ax - bx
        side = nx * (xs[(k + 2) % 3] - ax) + ny * (ys[(k + 2) % 3] - ay)
        if all((nx * (px - ax) + ny * (py - ay)) * side < 0 for px, py in corners):
            return False
    return True


def _cell_range(lo, hi, origin, size, g):
    """Grid columns (or rows) a coordinate interval spans, clamped to the grid."""
    first = min(max(int((lo - origin) // size), 0), g - 1)
    last = min(max(int((hi - origin) // size), 0), g - 1)
    return range(first, last + 1)


def build_navmesh_grid(verts, tris, min_x, min_y, max_x, max_y, divisor):
    """Row-major `divisor x divisor` lists of the triangles overlapping each cell.

    Cell size is span / divisor, the value packed beside the grid.
    See: docs/reference/navmesh_engine_contracts.md#the-lookup-grid
    """
    g = divisor
    cw = (max_x - min_x if max_x > min_x else 1.0) / g
    ch = (max_y - min_y if max_y > min_y else 1.0) / g
    grid = [[] for _ in range(g * g)]
    for ti, tri in enumerate(tris):
        xs = [verts[v][0] for v in tri[:3]]
        ys = [verts[v][1] for v in tri[:3]]
        for row in _cell_range(min(ys), max(ys), min_y, ch, g):
            for col in _cell_range(min(xs), max(xs), min_x, cw, g):
                y0, x0 = min_y + row * ch, min_x + col * cw
                if tri_hits_rect(xs, ys, x0, y0, x0 + cw, y0 + ch):
                    grid[row * g + col].append(ti)
    return grid
