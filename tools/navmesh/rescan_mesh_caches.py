#!/usr/bin/env python
"""Rebuild the mesh bounds + collision caches for named plugins, without an import.

    python tools/navmesh/rescan_mesh_caches.py Nehrim.esm Oblivion.esm
    python tools/navmesh/rescan_mesh_caches.py TR_Mainland.esm --force

Each plugin's converted `output/<group>/meshes` is scanned into
`export/<group>/collision_cache.bin` and `mesh_bounds_cache.json`, exactly as the
import does.  A current cache is left alone unless `--force` is given.  Takes the
machine-wide heavy-job lock, so it queues behind a running build.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.heavy_lock import hold_heavy_lock
from output_layout import paths as plugin_paths
from tes5_import.pipeline import rescan_mesh_caches


def rescan(plugin: str, force: bool) -> None:
    """Rescan one plugin's caches and print what happened."""
    handle = plugin_paths(plugin)
    mesh_dir = os.path.join(str(handle.out), 'meshes')
    print(f'== {plugin}: {handle.records} <- {mesh_dir}', flush=True)
    if not os.path.isdir(handle.records) or not os.path.isdir(mesh_dir):
        print('   export or mesh folder missing, skipped', flush=True)
        return
    rewritten = rescan_mesh_caches(str(handle.records), mesh_dir, force=force)
    print('   rewritten' if rewritten else '   already current', flush=True)


def main() -> None:
    """Parse plugin names, take the heavy lock, rescan each in turn."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('plugins', nargs='+', help='plugin filenames, e.g. Nehrim.esm')
    ap.add_argument('--force', action='store_true',
                    help='rescan even when the caches are current')
    args = ap.parse_args()
    hold_heavy_lock(f'rescan mesh caches: {" ".join(args.plugins)}')
    for plugin in args.plugins:
        rescan(plugin, args.force)


if __name__ == '__main__':
    main()
