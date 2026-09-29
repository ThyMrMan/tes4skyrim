"""Per-mesh bounds/collision entries emitted by the stage that WROTE the mesh.

The import pipeline's mesh scan re-parses every converted NIF, and the parse is
~96% of its cost -- work the mesh stage already did moments earlier.  A producer
that still holds the converted graph computes the same entries for ~8 ms instead
of ~185 ms, writes them here, and the scan merges them and parses only what no
producer claimed.

Each process appends to its OWN fragment file, so pool workers never contend and
nothing is threaded back through the result pickle (collision soups are large).
Records are written as they are produced rather than buffered until exit: mp.Pool
TERMINATES its children, so anything buffered would be lost.  Each line is one
JSON record; `w`/`b` are flat triangle lists in game units, exactly as
`collision_from_data` returns them.

    set_fragment_dir(dir)    -- once per producer process
    record_mesh_entry(...)   -- in the producer, after the mesh is written
    merge_fragments(dir)     -- in the import pipeline, before scanning

See: docs/commentary/tes5_import_pipeline.md#producer-emitted-mesh-entries
"""

import json
import os

from asset_convert.collision.collision_extract import COLLISION_SCHEMA_VERSION

#: Directory name under the export asset root holding the fragment files.
FRAGMENT_DIRNAME = 'mesh_scan_fragments'

#: Bumped when a fragment record gains a field or a field changes meaning.
FRAGMENT_VERSION = 1

#: First line of every fragment; a collision-extraction change strands older soups.
_HEADER = {'v': FRAGMENT_VERSION, 'c': COLLISION_SCHEMA_VERSION}

#: [open fragment file, directory] for THIS process.
_HANDLE: list = [None, None]


def fragment_dir(assets_dir) -> str:
    """Directory holding this plugin's fragments."""
    return os.path.join(str(assets_dir), FRAGMENT_DIRNAME)


def set_fragment_dir(assets_dir) -> None:
    """Point this process at *assets_dir*; a falsy value stops recording."""
    close_fragments()
    _HANDLE[1] = str(assets_dir) if assets_dir else None


def close_fragments() -> None:
    """Close this process's fragment file, if it opened one."""
    if _HANDLE[0] is not None:
        try:
            _HANDLE[0].close()
        except OSError:
            pass
        _HANDLE[0] = None


def _writer():
    """This process's fragment file, opened and version-stamped on demand."""
    if _HANDLE[0] is not None:
        return _HANDLE[0]
    if not _HANDLE[1]:
        return None
    frag_dir = fragment_dir(_HANDLE[1])
    os.makedirs(frag_dir, exist_ok=True)
    path = os.path.join(frag_dir, 'w_%d.jsonl' % os.getpid())
    fresh = not os.path.exists(path)
    fh = open(path, 'a', encoding='utf-8')
    if fresh:
        fh.write(json.dumps(_HEADER) + '\n')
    _HANDLE[0] = fh
    return fh


def _emit(rec: dict) -> None:
    """Append one record, flushed so a terminated worker loses nothing."""
    fh = _writer()
    if fh is None:
        return
    fh.write(json.dumps(rec) + '\n')
    fh.flush()


def record_mesh_entry(rel_key: str, bounds, physics: int, collision) -> None:
    """Record one converted mesh's analysis.

    rel_key is lowercase forward-slash, relative to the mesh root -- the key
    `_list_nifs` would produce.  bounds is the OBND 6-tuple (or None), physics
    the flag bits, collision the {'w': [...], 'b': [...]} soup (or None).
    """
    rec = {'k': rel_key}
    if bounds is not None:
        rec['o'] = list(bounds)
        if physics:
            rec['p'] = int(physics)
    if collision is not None:
        rec['w'] = [float(v) for v in collision['w']]
        rec['b'] = [float(v) for v in collision['b']]
    _emit(rec)


def record_alias(rel_key: str, source_key: str) -> None:
    """Record *rel_key* as a byte-identical copy of *source_key*."""
    _emit({'k': rel_key, 'a': source_key})


def record_removal(rel_key: str) -> None:
    """Record the deletion of *rel_key* (a producer removed the file)."""
    _emit({'k': rel_key, 'x': 1})


def _read_fragment(path: str, bounds: dict, collision: dict,
                   aliases: dict, removed: set) -> None:
    """Fold one fragment file into the accumulating tables; skip one from another version."""
    with open(path, encoding='utf-8') as fh:
        try:
            if json.loads(fh.readline()) != _HEADER:
                return
        except ValueError:
            return
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            key = rec.get('k')
            if not key:
                continue
            if rec.get('x'):
                removed.add(key)
                continue
            removed.discard(key)
            if 'a' in rec:
                aliases[key] = rec['a']
                continue
            if 'o' in rec:
                ob = tuple(rec['o'])
                bounds[key] = ob + (rec['p'],) if rec.get('p') else ob
            if 'w' in rec:
                collision[key] = {'w': rec['w'], 'b': rec['b']}


def merge_fragments(assets_dir):
    """Merge every fragment into ({key: bounds}, {key: collision}).

    Later records win, so a mesh rewritten by a later stage supersedes the
    earlier entry.  Aliases resolve to their source's geometry, and removals
    drop the key entirely.
    """
    frag_dir = fragment_dir(assets_dir)
    bounds: dict = {}
    collision: dict = {}
    aliases: dict = {}
    removed: set = set()
    if not os.path.isdir(frag_dir):
        return bounds, collision
    for name in sorted(os.listdir(frag_dir)):
        if not name.endswith('.jsonl'):
            continue
        try:
            _read_fragment(os.path.join(frag_dir, name), bounds, collision,
                           aliases, removed)
        except OSError:
            continue
    for key, src in aliases.items():
        if src in bounds:
            bounds[key] = bounds[src]
        if src in collision:
            collision[key] = collision[src]
    for key in removed:
        bounds.pop(key, None)
        collision.pop(key, None)
    return bounds, collision


def clear_fragments(assets_dir) -> None:
    """Delete the fragment directory once its records are in the caches."""
    close_fragments()
    frag_dir = fragment_dir(assets_dir)
    if not os.path.isdir(frag_dir):
        return
    for name in os.listdir(frag_dir):
        try:
            os.unlink(os.path.join(frag_dir, name))
        except OSError:
            pass
    try:
        os.rmdir(frag_dir)
    except OSError:
        pass
