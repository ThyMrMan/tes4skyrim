"""merge_fragments: a fragment from another collision schema is never merged.

See: docs/commentary/tes5_import_pipeline.md#producer-emitted-mesh-entries
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_convert.collision import collision_extract as ce
from asset_convert.collision import mesh_scan_fragments as frags


def _write_fragment(assets, header):
    """Write one fragment holding a single mesh entry under `header`."""
    frag_dir = frags.fragment_dir(assets)
    os.makedirs(frag_dir)
    rec = {'k': 'a.nif', 'o': [0, 0, 0, 1, 1, 1], 'w': [1.0] * 9, 'b': []}
    with open(os.path.join(frag_dir, 'w_1.jsonl'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(header) + '\n' + json.dumps(rec) + '\n')


def test_current_fragment_is_merged(tmp_path):
    """A fragment stamped with this build's versions contributes its entry."""
    _write_fragment(tmp_path, {'v': frags.FRAGMENT_VERSION,
                               'c': ce.COLLISION_SCHEMA_VERSION})
    bounds, collision = frags.merge_fragments(tmp_path)
    assert 'a.nif' in bounds and 'a.nif' in collision


def test_fragment_from_older_collision_schema_is_skipped(tmp_path):
    """A soup extracted before a collision fix must be re-parsed, not reused."""
    _write_fragment(tmp_path, {'v': frags.FRAGMENT_VERSION})
    assert frags.merge_fragments(tmp_path) == ({}, {})
