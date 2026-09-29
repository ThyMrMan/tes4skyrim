#!/usr/bin/env python3
"""Flag converted `Actor Property` declarations that can never bind.

A Papyrus property typed `Actor` binds only to a reference whose BASE record is
an NPC_ or CREA.  Point one at an XMarker (STAT), a shrine (ACTI) or a door and
the VM refuses the bind ("cannot be bound because <fid> is not the right type"):
the property comes back **None** and the FIRST call on it aborts the enclosing
function.  Nothing is logged at conversion time, so the failure only shows up
in-game as a dead script.

This is how the Imperial City Arena softlock was found: the announcer speaks
through four XMarker STATs, all of which the `Say` handler had promoted to
`Actor` -- see docs/commentary/script_convert.md.

    # audit a converted plugin
    python tools/validate/property_type_audit.py -f Oblivion.esm

    # audit an arbitrary directory of .psc (e.g. a subset rebuild)
    python tools/validate/property_type_audit.py -f Oblivion.esm --src temp/arena_fix

    # also report which TES4 calls named each bad ref, to find the promoter
    python tools/validate/property_type_audit.py -f Oblivion.esm --blame

Exit status is 1 when anything is flagged, so it works as a CI gate.
"""
import argparse
import glob
import os
import re
import sys

#: Base record types an Actor property's reference may have; LVLC spawns an actor at runtime.
ACTOR_BASES = {'NPC_', 'CREA', 'LVLC'}

#: Export files that never hold a base record.
_NOT_BASES = ('REFR', 'ACHR', 'ACRE', 'CELL', 'LAND', 'INFO', 'DIAL', 'SCPT', 'QUST')

_PROP_RE = re.compile(r'^Actor Property (\w+) Auto', re.M)


def iter_records(path):
    """Yield each record in an export .txt as a dict of its scalar fields."""
    cur = {}
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n')
            if line == '---RECORD_END---' and cur:
                yield cur
            if line in ('---RECORD_BEGIN---', '---RECORD_END---'):
                cur = {}
            elif '=' in line:
                k, _, v = line.partition('=')
                cur.setdefault(k, v)


def build_ref_map(export_dir):
    """(EditorID -> base FormID, base FormID -> record signature)."""
    edid_to_base = {}
    for sig in ('REFR', 'ACHR', 'ACRE'):
        path = os.path.join(export_dir, f'{sig}.txt')
        if os.path.exists(path):
            edid_to_base.update((rec['EditorID'].lower(), rec['NAME']) for rec in iter_records(path)
                                if 'EditorID' in rec and 'NAME' in rec)
    base_type = {}
    for path in glob.glob(os.path.join(export_dir, '*.txt')):
        sig = os.path.basename(path)[:-4]
        if sig not in _NOT_BASES:
            base_type.update((rec['FormID'], sig) for rec in iter_records(path) if rec.get('FormID'))
    return edid_to_base, base_type


def unbindable_actor_properties(export_dir, src) -> dict:
    """{(property name, base signature): [script files]} of Actor properties on non-actor refs."""
    edid_to_base, base_type = build_ref_map(export_dir)
    bad = {}
    for path in glob.glob(os.path.join(src, '*.psc')):
        with open(path, encoding='utf-8', errors='replace') as fh:
            names = _PROP_RE.findall(fh.read())
        for name in names:
            base = edid_to_base.get(name.lower())
            sig = base_type.get(base, '?') if base else None
            if sig and sig not in ACTOR_BASES:
                bad.setdefault((name, sig), []).append(os.path.basename(path))
    return bad


def blame(export_dir, names):
    """Which TES4 calls name each ref -- i.e. which handler promoted it."""
    if not names:
        return {}
    pat = re.compile(
        r'\b(' + '|'.join(re.escape(n) for n in names) + r')\s*\.\s*(\w+)',
        re.I)
    found = {}
    for sig in ('SCPT', 'INFO', 'QUST'):
        path = os.path.join(export_dir, f'{sig}.txt')
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8', errors='replace') as fh:
            for m in pat.finditer(fh.read()):
                found.setdefault(m.group(1).lower(), set()).add(m.group(2).lower())
    return found


def _print_bad(bad: dict, blamed: dict) -> None:
    """Each unbindable property with its scripts and, when blamed, the TES4 calls naming it."""
    print(f'{len(bad)} Actor Property declaration(s) that cannot bind:\n')
    for (name, sig), files in sorted(bad.items(), key=lambda kv: -len(kv[1])):
        print(f'  {name:34s} base={sig:5s} in {len(files)} script(s)')
        for f in sorted(files)[:5]:
            print(f'      {f}')
        if len(files) > 5:
            print(f'      ... and {len(files) - 5} more')
        calls = sorted(blamed.get(name.lower(), ()))
        if calls:
            print(f'      TES4 calls: {", ".join(calls)}')


def main():
    """Audit one plugin; 1 when any Actor property cannot bind."""
    ap = argparse.ArgumentParser(
        description='Flag Actor Property declarations bound to non-actor refs.')
    ap.add_argument('-f', '--plugin', default='Oblivion.esm',
                    help='plugin name, for locating export/ and output/')
    ap.add_argument('--src', help='directory of .psc to audit (default: output/<plugin>/scripts/source)')
    ap.add_argument('--export', help='export directory (default: export/<plugin>)')
    ap.add_argument('--blame', action='store_true',
                    help='also list the TES4 calls that named each bad ref')
    args = ap.parse_args()

    export_dir = args.export or os.path.join('export', args.plugin)
    src = args.src or os.path.join('output', args.plugin, 'scripts', 'source')
    for folder in (export_dir, src):
        if not os.path.isdir(folder):
            sys.exit(f'no such directory: {folder}')
    print(f'export: {export_dir}\nsource: {src}')
    bad = unbindable_actor_properties(export_dir, src)
    if not bad:
        print('CLEAN: no Actor Property bound to a non-actor reference.')
        return 0
    _print_bad(bad, blame(export_dir, [n for n, _ in bad]) if args.blame else {})
    return 1


if __name__ == '__main__':
    sys.exit(main())
