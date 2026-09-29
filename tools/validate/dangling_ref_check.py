"""Find FormID references that resolve to NOTHING in a plugin's load order.

The engine builds its FormID table while PARSING a plugin, before any cell
loads. A reference naming a record that no loaded file defines is a classic
cause of a main-menu hang with no crash and no log: xEdit reports the file as
clean because a dangling reference is legal on disk, but the engine never
finishes linking it.

Every FormID-valued subrecord is checked against:

  * the records the plugin itself defines
  * each converted master's own records, routed BY INDEX BYTE (two masters'
    id spaces overlap almost completely, so a first-match scan lies)

References into a master we cannot read (Skyrim.esm and other vanilla files
are not in output/) are NOT judged -- they are reported separately as
unchecked so an absent master never invents thousands of fake findings.

`FORMID_SUBS` is deliberately narrow, per xEdit's definitions: a mis-typed
entry invents dangling references that do not exist, which is far worse than
missing a real one. `NOT_FORMID` lists the pairs from it whose payload is not a
FormID on that record type, so it is the accuracy-critical half of the tool.

Usage:
  python -m tools.validate.dangling_ref_check TWMP_ValenwoodImproved.esp
  python -m tools.validate.dangling_ref_check --max 40 Plugin.esp
"""
import argparse
import os
import struct
import sys
from collections import Counter

from output_layout import paths
from tes5_import.base.tes5_reader import REC_HDR, records, subrecords

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Subrecords whose payload is exactly one FormID.
FORMID_SUBS = {
    b'NAME', b'XEZN', b'XOWN', b'XGLB', b'XESP', b'XLCN', b'XLRT',
    b'XCWT', b'XCIM', b'XCMO', b'XLCM', b'XCCM', b'INAM', b'PNAM',
    b'ZNAM', b'CNAM', b'QNAM', b'RNAM', b'SNAM', b'VNAM', b'WNAM',
    b'YNAM', b'KNAM', b'LNAM', b'GNAM', b'HNAM', b'JNAM', b'TNAM',
    b'EITM', b'ETYP', b'SCRI', b'VTCK', b'TPLT', b'RCLR', b'ATKR',
}

#: (record, subrecord) pairs of FORMID_SUBS whose payload is not a FormID on that record type.
NOT_FORMID = {
    (b'WRLD', b'DNAM'), (b'WRLD', b'MNAM'), (b'WRLD', b'ONAM'),
    (b'WRLD', b'PNAM'), (b'WRLD', b'TNAM'),
    (b'CELL', b'XCLC'),
    (b'LAND', b'DATA'),
    (b'CLMT', b'TNAM'), (b'CLMT', b'FNAM'), (b'CLMT', b'GNAM'),
    (b'WTHR', b'FNAM'), (b'WTHR', b'CNAM'), (b'WTHR', b'NNAM'),
    (b'NPC_', b'ANAM'), (b'RACE', b'ANAM'), (b'SOUN', b'FNAM'),
    (b'QUST', b'ANAM'), (b'INFO', b'ANAM'), (b'DIAL', b'TNAM'),
    (b'BOOK', b'CNAM'), (b'IDLE', b'ANAM'),
    (b'PACK', b'ANAM'), (b'PACK', b'PNAM'), (b'PACK', b'TNAM'),
    (b'PACK', b'UNAM'), (b'PACK', b'XNAM'),
    (b'FURN', b'MNAM'), (b'FURN', b'WNAM'), (b'FURN', b'ONAM'),
    (b'FURN', b'ANAM'),
    (b'SNDR', b'CNAM'), (b'SNDR', b'ANAM'),
    (b'SOPM', b'ANAM'), (b'SOPM', b'ONAM'), (b'SOPM', b'NAM1'),
    (b'REGN', b'RNAM'), (b'REGN', b'ICON'),
    (b'IMGS', b'TNAM'), (b'IMGS', b'CNAM'), (b'IMGS', b'ANAM'),
    (b'IMGS', b'HNAM'),
    (b'PROJ', b'VNAM'), (b'MOVT', b'INAM'),
    (b'LCTN', b'RNAM'), (b'LCTN', b'MNAM'), (b'LCTN', b'ANAM'),
    (b'FLOR', b'PNAM'), (b'ACTI', b'FNAM'), (b'VTYP', b'DNAM'),
    (b'BPTD', b'INAM'), (b'BPTD', b'NAM1'),
    (b'DOOR', b'FNAM'), (b'DOOR', b'SNAM'), (b'DOOR', b'ANAM'),
    (b'DOOR', b'BNAM'),
    (b'TREE', b'CNAM'), (b'DLBR', b'SNAM'), (b'DLVW', b'TNAM'),
    (b'MGEF', b'PNAM'), (b'ARMA', b'NAM0'), (b'ARMA', b'NAM1'),
}


def read_masters(data):
    """The plugin's MAST names, in declaration order, CASE PRESERVED.

    `tes5_reader.masters` lowercases; these names are used as output/<name>
    path components, so the on-disk spelling has to survive.
    """
    size = struct.unpack_from('<I', data, 4)[0]
    return [d.rstrip(b'\0').decode('ascii', 'replace')
            for tag, d in subrecords(data[REC_HDR:REC_HDR + size])
            if tag == b'MAST']


def own_formids(data):
    """FormIDs this file's records carry."""
    return {rec.form_id for rec in records(data, bodies=())}


def iter_refs(data):
    """(record_sig, record_fid, sub_sig, referenced_fid) across the file."""
    for rec in records(data):
        for st, payload in rec.subs():
            if (st in FORMID_SUBS and len(payload) == 4
                    and (rec.sig, st) not in NOT_FORMID):
                yield (rec.sig, rec.form_id, st,
                       struct.unpack_from('<I', payload, 0)[0])


def master_slots(masters: list, output_dir: str) -> dict:
    """{slot: ids that master defines, restated in this plugin's space, or None when unbuilt}."""
    by_slot = {}
    for slot, name in enumerate(masters):
        path = str(paths(name, out_root=output_dir).esm)
        if not os.path.isfile(path):
            by_slot[slot] = None
            continue
        with open(path, 'rb') as f:
            mdata = f.read()
        m_own = len(read_masters(mdata))
        by_slot[slot] = {(slot << 24) | (i & 0xFFFFFF) for i in own_formids(mdata) if (i >> 24) == m_own}
    return by_slot


def dangling_refs(name: str, output_dir: str):
    """(checked, unchecked, Counter of (record, subrecord, FormID, expected file)), or None when unbuilt."""
    path = str(paths(name, out_root=output_dir).esm)
    if not os.path.isfile(path):
        return None
    with open(path, 'rb') as f:
        data = f.read()
    masters = read_masters(data)
    by_slot = master_slots(masters, output_dir)
    by_slot[len(masters)] = own_formids(data)
    dangling, checked, unchecked = Counter(), 0, 0
    for sig, _fid, st, ref in iter_refs(data):
        if not ref:
            continue
        known = by_slot.get(ref >> 24)
        if known is None:
            unchecked += 1
            continue
        checked += 1
        if ref not in known:
            slot = ref >> 24
            where = 'this plugin' if slot == len(masters) else (
                masters[slot] if slot < len(masters) else f'slot {slot}')
            dangling[(sig.decode(), st.decode(), f'{ref:08X}', where)] += 1
    return checked, unchecked, dangling


def audit(name, output_dir, max_list):
    """Print one plugin's dangling references; their count."""
    result = dangling_refs(name, output_dir)
    if result is None:
        print(f"--- {name}: NOT BUILT")
        return 0
    checked, unchecked, dangling = result
    n = sum(dangling.values())
    print(f"--- {name}: {checked} references checked "
          f"({unchecked} into unreadable masters, not judged) -> {f'{n} DANGLING' if n else 'CLEAN'}")
    for (rsig, ssig, target, where), count in dangling.most_common(max_list):
        print(f"    {rsig}.{ssig} -> {target} (expected in {where}) x{count}")
    return n


def main():
    """Audit each named plugin; the total dangling count."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plugin', nargs='+')
    ap.add_argument('--output-dir', default=os.path.join(SCRIPT_DIR, 'output'))
    ap.add_argument('--max', type=int, default=25,
                    help='most-common dangling targets to list (default 25)')
    args = ap.parse_args()
    total = sum(audit(name, args.output_dir, args.max) for name in args.plugin)
    print(f"\nTOTAL DANGLING: {total}")
    return total


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
