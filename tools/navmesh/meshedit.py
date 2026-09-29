"""Hand-corrected navmesh triangles: a second, sharper kind of ground truth.

The pathgrid corpus says what the generator's INPUT should look like; this says
what its OUTPUT should have been.  A cell where the mesh is visibly wrong gets
fixed by hand, and the corrected mesh becomes a target to score against.

    from tools.navmesh.meshedit import load_fix, make_entry, replay, save_fix

Corrections live in `tests/navmesh_fixed/<plugin>/<cell>.json`, and apply to any
cell of any plugin -- not only the Bruma name-matches.  When `is_stale` reports
that the generator moved, the ops are suspect but `result` is still a target.

See: docs/commentary/tes5_import_navmesh.md#hand-corrected-navmesh-corpus
"""

import hashlib
import json
import os
import struct

#: Where hand-corrected meshes live, one folder per source plugin.
FIXES = os.path.join('tests', 'navmesh_fixed')

#: Ops a correction may contain; anything else is ignored, never guessed at.
OPS = ('add_vert', 'move_vert', 'snap_vert', 'add_tri', 'del_tri', 'set_door',
       'add_link', 'del_link')


def mesh_hash(verts, tris):
    """Digest of a generated mesh, to detect that ops went stale.

    Rounded to 0.01u so a rebuild's float jitter does not read as a change.
    """
    h = hashlib.sha1()
    for p in verts:
        h.update(struct.pack('<3i', *(int(round(c * 100.0)) for c in p)))
    for t in tris:
        h.update(struct.pack('<3i', *(int(i) for i in t[:3])))
    return h.hexdigest()


def fix_path(plugin, cell):
    """Path of the correction file for one cell of one plugin."""
    return os.path.join(FIXES, plugin, '%s.json' % cell)


def load_fix(plugin, cell):
    """The correction entry, or None when the cell has never been edited."""
    p = fix_path(plugin, cell)
    if not os.path.isfile(p):
        return None
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def free_cell_name(plugin, cell):
    """`cell`, or `cell.2` / `cell.3` ... when that correction already exists.

    Saving a second reading of one cell must never silently replace the first:
    a stale correction's `result` is still the only record of what the mesh
    should have looked like.
    """
    if not os.path.isfile(fix_path(plugin, cell)):
        return cell
    n = 2
    while os.path.isfile(fix_path(plugin, '%s.%d' % (cell, n))):
        n += 1
    return '%s.%d' % (cell, n)


def save_fix(plugin, cell, entry):
    """Write a correction file, creating its plugin folder on first use."""
    p = fix_path(plugin, cell)
    d = os.path.dirname(p)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(entry, fh, indent=2, sort_keys=True)
        fh.write('\n')
    return p


def _add_vert(op, state):
    """Append a vertex, so a triangle can EXTEND the mesh into open floor."""
    state['verts'].append([float(c) for c in op['to']])


def _move_vert(op, state):
    """Place one vertex at an absolute position."""
    verts = state['verts']
    i = int(op['v'])
    if 0 <= i < len(verts):
        verts[i] = [float(c) for c in op['to']]


def _snap_vert(op, state):
    """Weld vertex `v` INTO `to_v`: every triangle now references `to_v`.

    Moving `v` onto the same position is not enough -- a crack closes only when
    the two triangles SHARE the index. Triangles the weld leaves degenerate
    are dropped.

    See: docs/commentary/tes5_import_navmesh.md#welding-rewrites-the-index
    """
    verts, tris = state['verts'], state['tris']
    i, j = int(op['v']), int(op['to_v'])
    if not (0 <= i < len(verts) and 0 <= j < len(verts)):
        return
    verts[i] = list(verts[j])
    for n, t in enumerate(tris):
        if t is None:
            continue
        t[:] = [j if k == i else k for k in t]
        if len(set(t)) < 3:
            tris[n] = None


def _add_tri(op, state):
    """Append a triangle over three existing vertices."""
    state['tris'].append([int(k) for k in op['verts']])


def _del_tri(op, state):
    """Tombstone a triangle, keeping every later index stable."""
    tris = state['tris']
    i = int(op['tri'])
    if 0 <= i < len(tris):
        tris[i] = None


def _set_door(op, state):
    """Mark or clear a triangle as carrying a door threshold."""
    i = int(op['tri'])
    (state['doors'].add if op.get('on', True) else state['doors'].discard)(i)


def _add_link(op, state):
    """Add a drop-down link from an upper triangle to a lower one."""
    state['links'].add((int(op['up']), int(op['down'])))


def _del_link(op, state):
    """Remove a drop-down link."""
    state['links'].discard((int(op['up']), int(op['down'])))


_HANDLERS = {'add_vert': _add_vert,
             'move_vert': _move_vert, 'snap_vert': _snap_vert,
             'add_tri': _add_tri, 'del_tri': _del_tri, 'set_door': _set_door,
             'add_link': _add_link, 'del_link': _del_link}


def _play(verts, tris, ops, doors=(), links=()):
    """The replay state after `ops`: deleted triangles tombstoned as None, nothing compacted."""
    state = {
        'verts': [list(p) for p in verts],
        'tris': [list(t[:3]) for t in tris],
        'doors': set(int(i) for i in doors),
        'links': {(int(a), int(b)) for (a, b) in links},
    }
    for op in ops or ():
        fn = _HANDLERS.get(op.get('op'))
        if fn is not None:
            fn(op, state)
    return state


def replay(verts, tris, ops, doors=(), links=()):
    """`(verts, tris, doors, links)` after applying `ops` to a mesh.

    Deletions tombstone and compact only at the end, so every op addresses
    triangles by their ORIGINAL index -- what the page and changelist speak.
    A link whose triangle was deleted is dropped with it.
    """
    state = _play(verts, tris, ops, doors, links)
    keep = [i for i, t in enumerate(state['tris']) if t is not None]
    remap = {old: new for new, old in enumerate(keep)}
    return (state['verts'], [state['tris'][i] for i in keep],
            sorted(remap[i] for i in state['doors'] if i in remap),
            sorted((remap[a], remap[b]) for (a, b) in state['links']
                   if a in remap and b in remap))


#: Op fields that name a TRIANGLE; every other index an op carries is a vertex.
TRI_FIELDS = ('tri', 'up', 'down')


def _survivors(verts, tris, ops):
    """`(surviving replay triangle indices, replay triangle count)` after `ops`."""
    played = _play(verts, tris, ops)['tris']
    return [i for i, t in enumerate(played) if t is not None], len(played)


def rebase_ops(verts, tris, ops, new_ops):
    """`ops` then `new_ops`, where `new_ops` were made over the RESULT of `ops`.

    Result vertices ARE replay vertices -- replay never compacts them -- so
    only triangle indices move: result triangle j is the j-th survivor, and a
    triangle added after the result follows the replay's own list.

    See: docs/commentary/tes5_import_navmesh.md#editing-a-saved-result
    """
    live, count = _survivors(verts, tris, ops)

    def tri(j):
        """Replay index of result triangle `j`."""
        return live[j] if j < len(live) else count + (j - len(live))
    out = list(ops or ())
    for op in new_ops or ():
        out.append({k: (tri(int(v)) if k in TRI_FIELDS else v)
                    for k, v in op.items()})
    return out


def result_marks(verts, tris, ops, result):
    """`(doors, links)` in base indices that replaying `ops` turns back into `result`'s own.

    A correction stores no base doors or links.  Mapping the result's back
    through the survivors reproduces them: set_door and link ops are
    idempotent, so the last one on a triangle decides either way.
    """
    live, _count = _survivors(verts, tris, ops)
    doors = [live[j] for j in result.get('doors', ()) if j < len(live)]
    links = [(live[a], live[b]) for (a, b) in result.get('links', ())
             if a < len(live) and b < len(live)]
    return doors, links


def make_entry(plugin, cell, verts, tris, ops, doors=(), links=()):
    """A correction file's full contents: the base mesh, the ops AND the result.

    `base` is the generator mesh the human edited, kept so the diff that says
    WHAT they changed survives the generator moving (`tools/navmesh/fix_analyze.py`).
    """
    rv, rt, rd, rl = replay(verts, tris, ops, doors, links)
    return {
        'plugin': plugin,
        'cell': cell,
        'base_hash': mesh_hash(verts, tris),
        'base': {
            'verts': [[round(float(c), 3) for c in p] for p in verts],
            'tris': [[int(k) for k in t[:3]] for t in tris],
        },
        'ops': list(ops or ()),
        'result': {
            'verts': [[round(c, 3) for c in p] for p in rv],
            'tris': [list(t) for t in rt],
            'doors': rd,
            'links': [list(p) for p in rl],
        },
    }


def is_stale(entry, verts, tris):
    """True when the generator moved under a correction's ops."""
    return bool(entry) and entry.get('base_hash') != mesh_hash(verts, tris)


def fixed_cells():
    """`[(plugin, cell)]` for every correction on disk."""
    if not os.path.isdir(FIXES):
        return []
    out = []
    for plugin in sorted(os.listdir(FIXES)):
        d = os.path.join(FIXES, plugin)
        if not os.path.isdir(d):
            continue
        out += [(plugin, f[:-5]) for f in sorted(os.listdir(d))
                if f.endswith('.json')]
    return out
