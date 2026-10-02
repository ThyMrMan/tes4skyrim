"""FO3/FNV activators whose model opens and closes: their Open/Close sequences earn a behavior graph.

A door's Open/Close is played by the engine, and a graph on a door mesh made
the engine bind it through the graph and crash, so those names are left out
of the graph. A FO3/FNV activator with the same sequences (the Overseer's desk,
the vault gear door, wall switches) is opened by `TES4_TwoStateActivator`'s
`PlayAnimation("Open")`, which needs a graph. So a model placed by an ACTI and
by no DOOR keeps Open and Close as graph states.

See: docs/commentary/asset_convert_nif.md#activator-open-close
"""

import os

#: The two sequence names a door plays natively.
OPEN_CLOSE = ('open', 'close')

#: Export folder -> (models of its ACTI records, models of its DOOR records), lowercase, meshes-relative.
_MODELS: dict = {}


def _models_of(path: str) -> set:
    """The lowercase, slash-separated Model.MODL values of one export text file."""
    out = set()
    if not os.path.isfile(path):
        return out
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('Model.MODL='):
                out.add(line[11:].strip().lower().replace('\\\\', '/').replace('\\', '/'))
    return out


def _split(src_path: str) -> tuple:
    """(export folder, meshes-relative model) of a mesh under `<export>/meshes/`, or ('', '')."""
    norm = src_path.replace('\\', '/')
    head, sep, rel = norm.lower().rpartition('/meshes/')
    return (norm[:len(head)], rel) if sep else ('', '')


def activator_only(src_path: str) -> bool:
    """Whether the mesh at `src_path` is placed by an activator and by no door."""
    export, rel = _split(src_path)
    if not export:
        return False
    if export not in _MODELS:
        _MODELS[export] = (_models_of(os.path.join(export, 'ACTI.txt')),
                           _models_of(os.path.join(export, 'DOOR.txt')))
    actis, doors = _MODELS[export]
    return rel in actis and rel not in doors
