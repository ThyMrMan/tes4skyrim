"""Predict VMAD property binding failures WITHOUT running the game.

The engine binds a VMAD object property only when the target record's type is
compatible with the type the script DECLARES. When it is not, the property
reads None for the whole session and silently aborts every function that
touches it -- and the only evidence is a line in the Papyrus log, which costs a
full play session to obtain.

Three checks, each a function the preflight audits also call:

* `type_mismatches`: each `<Type> Property <Name>` resolved BY NAME to the
  record of that EditorID in this plugin; a record type the declared type
  cannot hold cannot bind. A name two record types share is skipped.
* `cross_master_problems`: each bound property's real FormID resolved through
  this plugin's MAST list, catching an index byte copied verbatim from a master
  (ElsweyrPelletine's `ANQCORCorintheFaction` landed on a LAND record).
* `unbound_properties`: object properties a `.psc` declares but no VMAD binds,
  which read None just the same (the CharacterGen Emperor's `Player`).

Usage:
  python -m tools.validate.vmad_property_typecheck --plugin Oblivion.esm
  python -m tools.validate.vmad_property_typecheck --plugin Morrowind_ob.esm --verbose
  python -m tools.validate.vmad_property_typecheck --plugin ElsweyrPelletine.esp --cross-master --unbound

See: docs/commentary/tools_preflight.md#property-binding
"""
import argparse
import os
import re
from collections import Counter, defaultdict

from output_layout import paths
from tools.validate.preflight.plugin_index import first, load_plugin, zstring

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Papyrus type -> record signatures that satisfy it; a type not listed is skipped, never guessed.
ACCEPTS = {
    'Armor': {'ARMO'}, 'Weapon': {'WEAP'}, 'Book': {'BOOK'},
    'Potion': {'ALCH'}, 'Ingredient': {'INGR'}, 'Light': {'LIGH'},
    'MiscObject': {'MISC'}, 'Key': {'KEYM'}, 'Ammo': {'AMMO'},
    'SoulGem': {'SLGM'}, 'Scroll': {'SCRL'}, 'Activator': {'ACTI'},
    'Flora': {'FLOR'}, 'Furniture': {'FURN'}, 'Static': {'STAT'},
    'Container': {'CONT'}, 'Door': {'DOOR'},
    'LeveledItem': {'LVLI'}, 'LeveledActor': {'LVLN'},
    'LeveledSpell': {'LVSP'},
    'Quest': {'QUST'}, 'Faction': {'FACT'}, 'GlobalVariable': {'GLOB'},
    'Spell': {'SPEL'}, 'Enchantment': {'ENCH'}, 'MagicEffect': {'MGEF'},
    'Race': {'RACE'}, 'Class': {'CLAS'}, 'Package': {'PACK'},
    'Sound': {'SOUN', 'SNDR'}, 'Topic': {'DIAL'}, 'FormList': {'FLST'},
    'Keyword': {'KYWD'}, 'EffectShader': {'EFSH'}, 'Weather': {'WTHR'},
    'WorldSpace': {'WRLD'}, 'Message': {'MESG'}, 'Outfit': {'OTFT'},
    'VoiceType': {'VTYP'}, 'ImageSpaceModifier': {'IMAD'},
    'Explosion': {'EXPL'}, 'Projectile': {'PROJ'}, 'Hazard': {'HAZD'},
    'ImpactDataSet': {'IPDS'}, 'Idle': {'IDLE'}, 'Shout': {'SHOU'},
    'ActorBase': {'NPC_'}, 'Location': {'LCTN'}, 'Cell': {'CELL'},
    'ObjectReference': {'REFR', 'ACHR', 'ACRE'},
    'Actor': {'ACHR'},
}

#: Types that accept any record, so never reported.
PERMISSIVE = {'Form', 'ScriptObject', 'Alias', 'ReferenceAlias'}

#: `ScriptName X extends Y` at the head of a source.
_EXTENDS = re.compile(r'^\s*ScriptName\s+\w+\s+extends\s+(\w+)', re.I | re.M)

#: Record flag of a persistent reference, the only kind a property can hold.
_PERSISTENT = 0x400

#: Value types a VMAD never binds by FormID.
_VALUE_TYPES = ('int', 'float', 'bool', 'string')

#: `<Type> Property <Name>` at the start of a line, with whether it is `Auto`.
_DECLARATION = re.compile(r'^\s*([A-Za-z_]\w*)\s+Property\s+(\w+)(\s+Auto)?', re.M)


def declared_properties(src: str) -> dict:
    """{(script lower, property): (declared type, is Auto)} from the converted sources."""
    declared = {}
    for fn in sorted(os.listdir(src)):
        if fn.endswith('.psc'):
            with open(os.path.join(src, fn), encoding='utf-8', errors='replace') as fh:
                for m in _DECLARATION.finditer(fh.read()):
                    declared[(fn[:-4].lower(), m.group(2))] = (m.group(1), bool(m.group(3)))
    return declared


def accepted(ptype: str, script_types: set):
    """Signatures a property of `ptype` binds; () for a script type (any record); None to skip."""
    if ptype is None or ptype in PERMISSIVE:
        return None
    if ptype.lower() in script_types:
        return ()
    return ACCEPTS.get(ptype)


def exterior_cells(index) -> set:
    """EditorIDs (lower) of exterior cells, which a Cell property cannot hold."""
    return {zstring(first(r, 'EDID')).lower() for r in index.by_type['CELL']
            if first(r, 'DATA')[:1] and not first(r, 'DATA')[0] & 1}


def type_mismatches(index, declared: dict) -> list:
    """[(script, property, declared type, actual signature)] that resolve by name and cannot bind.

    `Player` binds to PlayerRef, never to the base NPC_ that shares its name.
    """
    types, shared = index.edid_types()
    exterior = exterior_cells(index)
    out = []
    for (script, name), (ptype, _auto) in sorted(declared.items()):
        key = name.lower()
        allowed = ACCEPTS.get(ptype)
        if (allowed is None or ptype in PERMISSIVE or ptype.startswith('TES4_') or key in shared
                or key in ('player', 'playerref') or key not in types):
            continue
        if types[key] not in allowed:
            out.append((script, name, ptype, types[key]))
        elif ptype == 'Cell' and key in exterior:
            out.append((script, name, ptype, 'CELL(exterior)'))
    return out


def unbound_properties(index, declared: dict) -> list:
    """[(script, property, type)] declared `Auto` on an attached script, unbound."""
    return [(script, name, ptype) for (script, name), (ptype, auto) in sorted(declared.items())
            if auto and script in index.bound and ptype.lower() not in _VALUE_TYPES
            and name.lower() not in index.bound[script]]


def local_table(index) -> dict:
    """{local FormID: [(signature, EditorID)]}, every record under an id, whatever its type."""
    table = defaultdict(list)
    for recs in index.by_type.values():
        for rec in recs:
            table[rec.form_id & 0xFFFFFF].append((rec.type, zstring(first(rec, 'EDID'))))
    return table


def masters_of(esm: str) -> list:
    """The MAST names of the plugin at `esm`, in load order."""
    with open(esm, 'rb') as fh:
        head = fh.read(24)
        body = fh.read(int.from_bytes(head[4:8], 'little'))
    out, pos = [], 0
    while pos + 6 <= len(body):
        size = int.from_bytes(body[pos + 4:pos + 6], 'little')
        if body[pos:pos + 4] == b'MAST':
            out.append(body[pos + 6:pos + 6 + size].rstrip(b'\0').decode('latin-1'))
        pos += 6 + size
    return out


class MasterTables:
    """Record tables of this plugin and its masters, each read from its OWN converted output."""

    def __init__(self, plugin: str, index, esm: str, out_dir: str):
        """This plugin's table now; masters load on first use."""
        self.plugin, self.out_dir = plugin, out_dir
        self.masters = masters_of(esm)
        self.own = local_table(index)
        self.cache = {}

    def table_for(self, slot: int) -> tuple:
        """(file name, table or None) for an index byte; (None, None) past the MAST list."""
        if slot == len(self.masters):
            return self.plugin, self.own
        if slot > len(self.masters):
            return None, None
        name = self.masters[slot]
        if name not in self.cache:
            path = str(paths(name, out_root=self.out_dir).esm)
            self.cache[name] = local_table(load_plugin(path)) if os.path.exists(path) else None
        return name, self.cache[name]


def binding_problem(hits: list, accepts) -> tuple:
    """(signature, EditorID) of why a FormID cannot bind, or None when ANY record under it fits."""
    if not hits:
        return '<no such record>', None
    if not accepts or any(sig in accepts for sig, _ in hits):
        return None
    return '/'.join(sorted({s for s, _ in hits})), hits[0][1]


def script_extends(src: str) -> dict:
    """{script lower: the type it extends, lower} from the converted sources' headers."""
    out = {}
    for fn in os.listdir(src):
        if fn.endswith('.psc'):
            with open(os.path.join(src, fn), encoding='utf-8', errors='replace') as fh:
                match = _EXTENDS.search(fh.read(4096))
            if match:
                out[fn[:-4].lower()] = match.group(1).lower()
    return out


def needs_reference(ptype: str, extends: dict) -> bool:
    """Whether a property type is, or is a script extending, ObjectReference or Actor."""
    name, seen = ptype.lower(), set()
    while name in extends and name not in seen:
        seen.add(name)
        name = extends[name]
    return name in ('objectreference', 'actor')


def reference_problem(index, fid: int, ptype: str, extends: dict):
    """(problem, EditorID) when a reference-typed property names a base record or a non-persistent reference."""
    rec = index.by_fid.get(fid)
    if rec is None or not needs_reference(ptype, extends):
        return None
    if rec.type not in ('REFR', 'ACHR'):
        return f'a {rec.type} base, not a reference', index.edid(fid)
    if not rec.flags & _PERSISTENT:
        return 'a reference that is not persistent', index.edid(fid)
    return None


def lacks_script(index, fid: int, script: str) -> bool:
    """Whether this plugin's record `fid`, and the base it places, both lack `script`.

    A script-typed property binds only to a record carrying that script, on the
    reference itself or on its base.
    See: docs/commentary/tools_preflight.md#property-binding
    """
    rec = index.by_fid.get(fid)
    holders = set(index.attached.get(script, ()))
    base = int.from_bytes(first(rec, 'NAME')[:4], 'little') if rec is not None else 0
    return rec is not None and fid not in holders and base not in holders


def own_target_problem(index, fid: int, ptype: str, accepts, extends: dict):
    """(problem, EditorID) for a type-correct own target that cannot bind."""
    if accepts == () and lacks_script(index, fid, ptype.lower()):
        return f'lacks {ptype}', index.edid(fid)
    return reference_problem(index, fid, ptype, extends)


def cross_master_problems(tables, index, declared: dict, extends: dict = None) -> tuple:
    """(checked, [(script, property, type, FormID, file, signature, EditorID)], {unbuilt master: count}).

    For this plugin's own targets it also checks that a script-typed property
    names a record carrying that script, and, given `extends`, that a
    reference-typed one names a persistent placed reference.
    """
    script_types = {s for s, _p in declared}
    types = {(s, p.lower()): t for (s, p), (t, _auto) in declared.items()}
    checked, bad, unresolved = 0, [], Counter()
    for script, prop, fid in index.object_props:
        accepts = accepted(types.get((script, prop)), script_types)
        if accepts is None:
            continue
        name, table = tables.table_for(fid >> 24)
        if name is None:
            bad.append((script, prop, types[(script, prop)], f'{fid:08X}',
                        f'<index {fid >> 24:02X} out of range>', '<unresolvable>', None))
        elif table is None:
            unresolved[name] += 1
        else:
            checked += 1
            ptype = types[(script, prop)]
            problem = binding_problem(table.get(fid & 0xFFFFFF), accepts)
            if not problem and table is tables.own:
                problem = own_target_problem(index, fid, ptype, accepts, extends or {})
            if problem:
                bad.append((script, prop, ptype, f'{fid:08X}', name, *problem))
    return checked, bad, unresolved


def _print_rows(title: str, rows: list, limit: int) -> None:
    """A count line, then up to `limit` rows."""
    print(f'\n{title}: {len(rows)}')
    for row in rows[:limit]:
        print('  ' + '  '.join(str(v) for v in row if v is not None))
    if len(rows) > limit:
        print(f'  ... {len(rows) - limit} more (use --max)')


def main() -> int:
    """Print the requested checks for one plugin; 1 when anything cannot bind."""
    ap = argparse.ArgumentParser(description='Statically predict VMAD property binding failures')
    ap.add_argument('--plugin', default='Oblivion.esm')
    ap.add_argument('--unbound', action='store_true', help='also report declared properties no VMAD binds')
    ap.add_argument('--cross-master', action='store_true',
                    help="resolve each bound property's real FormID through the MAST list")
    ap.add_argument('--verbose', '-v', action='store_true', help='list every row, not the first --max')
    ap.add_argument('--max', type=int, default=25)
    args = ap.parse_args()
    out_dir = os.path.join(ROOT, 'output')
    esm = str(paths(args.plugin, out_root=out_dir).esm)
    index = load_plugin(esm)
    declared = declared_properties(os.path.join(out_dir, args.plugin, 'scripts', 'source'))
    limit = 10 ** 9 if args.verbose else args.max
    bad = type_mismatches(index, declared)
    _print_rows(f'{args.plugin}: predicted binding failures by name', bad, limit)
    if args.cross_master:
        checked, crossed, unresolved = cross_master_problems(
            MasterTables(args.plugin, index, esm, out_dir), index, declared,
            script_extends(os.path.join(out_dir, args.plugin, 'scripts', 'source')))
        print(f'\ncross-master: {checked} object properties resolved; masters not built: {dict(unresolved)}')
        _print_rows('cross-master: mis-routed or unbindable', crossed, limit)
        bad += crossed
    if args.unbound:
        _print_rows('declared but unbound object properties', unbound_properties(index, declared), limit)
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
