"""FO3/FNV patrol points: Skyrim's own patrol data, plus a script for the embedded one.

A FO3/FNV patrol point (a REFR on a Patrol package's linked chain) carries an
idle time, an idle, an embedded script and a topic. Skyrim's REFR keeps the
idle time, the Patrol Script Marker and a topic natively (XPRD XPPA INAM
PDTO, 3,179 vanilla markers); only the script has nowhere to go. A marker with
a script gets a PM_ script instead, run on the actor that arrives on one of
the patrol packages routed through the marker.

See: docs/commentary/tes5_import_package.md#patrol-points
"""

import os
import struct

from ..base.owned_records import WELL_KNOWN_PROPERTIES
from ..base.text_reader import get_float, get_formid, parse_record_block, remap_formid
from ..base.writer import pack_subrecord
from .scripts_falloutnv import has_code

#: The key every exported patrol point carries (its XPRD idle time).
PATROL_KEY = 'Patrol.IdleTime'

#: FO3/FNV PKDT.Type of a Patrol package, and PLDT type 0 (its start marker named outright).
_PATROL_TYPE, _NEAR_REFERENCE = '13', '0'

#: A linked chain longer than this is a loop the walk has lost.
_MAX_CHAIN = 512

#: Patrol marker REFR FormID (upper hex) -> its packed VMAD, filled by build_patrol_vmads.
_PATROL_VMADS: dict = {}


def is_patrol_point(rec: dict) -> bool:
    """Whether a reference is a FO3/FNV patrol point."""
    return PATROL_KEY in rec


def has_patrol_script(rec: dict) -> bool:
    """Whether a patrol point's embedded script does anything."""
    return has_code(rec.get('Patrol.Script') or '')


def patrol_subrecords(rec: dict) -> bytes:
    """XPRD XPPA INAM PDTO, Skyrim's patrol data, for a patrol point; b'' otherwise.

    The idle stays 0 as on every vanilla marker: a FO3/FNV IDLE names no
    Skyrim animation. The topic is a Topic Ref PDTO, 0 when there is none.
    """
    if not is_patrol_point(rec):
        return b''
    return (pack_subrecord('XPRD', struct.pack('<f', get_float(rec, PATROL_KEY)))
            + pack_subrecord('XPPA', b'') + pack_subrecord('INAM', bytes(4))
            + pack_subrecord('PDTO', struct.pack('<II', 0, get_formid(rec, 'Patrol.Topic'))))


def patrol_scan_source(rec: dict, formid_to_edid: dict) -> str:
    """A patrol point's script and `Say <topic>`, for the call-site scans."""
    topic = formid_to_edid.get((rec.get('Patrol.Topic') or '').upper(), '')
    return (rec.get('Patrol.Script') or '') + (f'\nSay {topic}\n' if topic else '')


def load_patrol_points(export_dir: str) -> list:
    """The REFR records carrying patrol data, without parsing every other REFR."""
    path = os.path.join(export_dir, 'REFR.txt')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8', errors='replace') as f:
        chunks = f.read().split('---RECORD_BEGIN---')
    return [parse_record_block(c.splitlines()) for c in chunks if f'\n{PATROL_KEY}=' in c]


def _links(by_type: dict) -> dict:
    """{reference FormID: its linked reference}, both upper hex."""
    return {r['FormID'].upper(): r['XLKR.LinkedRef'].upper()
            for sig in ('REFR', 'ACHR', 'ACRE') for r in by_type.get(sig, ())
            if r.get('FormID') and r.get('XLKR.LinkedRef')}


def _chain(start: str, links: dict):
    """Every reference down a linked chain from `start`, each once."""
    seen = set()
    while start and start not in seen and len(seen) < _MAX_CHAIN:
        seen.add(start)
        yield start
        start = links.get(start)


def patrol_routes(by_type: dict, pack_runner_refs: dict) -> dict:
    """{marker FormID: [PACK FormIDs]} for every package that brings an actor to a marker.

    A patrol walks the linked chain from the marker its PLDT names, else from
    each of its actors' own linked reference (`pack_runner_refs` maps a PACK's
    low 24 bits to its actors'); any other package arrives at the marker its
    PLDT names, as a Travel or Guard does.
    """
    links = _links(by_type)
    ref_by_low = {int(r['FormID'], 16) & 0xFFFFFF: r['FormID'].upper()
                  for sig in ('ACHR', 'ACRE') for r in by_type.get(sig, ()) if r.get('FormID')}
    routes = {}
    for pack in by_type.get('PACK', ()):
        fid = pack['FormID'].upper()
        named = (pack.get('PLDT.Location') or '').upper()
        if pack.get('PLDT.Type') != _NEAR_REFERENCE or not named:
            named = ''
        if pack.get('PKDT.Type') != _PATROL_TYPE:
            markers = [named] if named else []
        elif named:
            markers = list(_chain(named, links))
        else:
            runners = pack_runner_refs.get(int(fid, 16) & 0xFFFFFF, ())
            markers = [m for r in runners for m in _chain(links.get(ref_by_low.get(r, '')), links)]
        for marker in markers:
            routes.setdefault(marker, []).append(fid)
    return routes


def build_patrol_vmads(by_type: dict, pack_runner_refs: dict, xref) -> int:
    """Bind each scripted marker a patrol walks to its PM_ script; returns how many.

    script_convert is imported here, not at module scope: its converter
    imports the importer's dialogue package, a cycle at load.
    """
    from script_convert.patrol_scripts import patrol_property_refs, patrol_script_name
    from script_convert.pipeline import build_vmad_object_script
    from ..dialogue.converter import bind_script_properties
    _PATROL_VMADS.clear()
    routes = patrol_routes(by_type, pack_runner_refs)
    for rec in by_type.get('REFR', ()):
        fid = (rec.get('FormID') or '').upper()
        if fid not in routes or not has_patrol_script(rec):
            continue
        props = bind_script_properties(patrol_property_refs(rec, xref), xref, WELL_KNOWN_PROPERTIES)
        packages = sorted({remap_formid(int(p, 16)) for p in routes[fid]})
        _PATROL_VMADS[fid] = pack_subrecord('VMAD', build_vmad_object_script(
            patrol_script_name(fid), props, {'TES4PatrolPackages': ('objects', packages)}))
    return len(_PATROL_VMADS)


def patrol_vmad(rec: dict) -> bytes:
    """The packed VMAD a patrol marker's PM_ script needs, or b''."""
    return _PATROL_VMADS.get((rec.get('FormID') or '').upper(), b'')
