"""AI packages that point at nothing, never run, or send an actor where it cannot walk.

Checks over the built plugin's PACK records and their users (NPC_ PKID lists
and quest aliases' ALPC lists):
* a location (PLDT) or target (PTDA) naming a record that is missing or of the
  wrong kind, or a quest alias its quest does not have;
* a schedule (PSDT) outside the engine's value ranges;
* a user naming a package that does not exist;
* GetIsID conditions that exclude every actor holding the package, marked for
  review since the source package may be just as dead;
* a destination in a cell with no navmesh, marked for review;
* a run-once guard (GetInFaction TES4RunOnce_*) no alias script watches, so
  the package never ends.

See: docs/commentary/tools_preflight.md#packages
"""

import struct
from collections import defaultdict

from tools.validate.preflight.findings import Finding
from tools.validate.preflight.plugin_index import every, first, u32
from tools.validate.preflight.quest_source import decode_condition, required_speakers
from tools.validate.preflight.quest_start import aliases

#: PLDT location types that name a record: near a reference, in a cell, an object.
_LOCATION_RECORD = {0: ('REFR', 'ACHR'), 1: ('CELL',), 4: None}

#: PTDA target types that name a record: a specific reference, an object.
_TARGET_RECORD = {0: ('REFR', 'ACHR'), 1: None}

#: PLDT and PTDA types that name a quest alias.
_ALIAS_TYPE = {'PLDT': 8, 'PTDA': 4}

#: PSDT field ranges, -1 meaning any: month, day of week (7 to 10 are day groups), date, hour, minute.
_SCHEDULE_RANGES = ((-1, 11), (-1, 10), (0, 31), (-1, 23), (-1, 59))

#: Byte offset of the u16 template flags in NPC_ ACBS.
_TEMPLATE_FLAGS_AT = 18

#: ACBS template flag: the NPC runs its template's AI packages.
_USE_AI_PACKAGES = 0x20

#: Samples listed per finding.
SAMPLES = 5

#: EditorID prefix of the hidden faction marking an actor done with a run-once package.
RUN_ONCE_PREFIX = 'TES4RunOnce_'

#: TES5 GetInFaction.
_GET_IN_FACTION = 71


def _slots(pack) -> list:
    """[(subrecord, type, value)] of a package's PLDT and PTDA entries."""
    return [(sig, u32(d), u32(d, 4)) for sig in ('PLDT', 'PTDA') for d in every(pack, sig) if len(d) >= 8]


def slot_problem(index, pack, slot: tuple, quest_aliases: dict) -> str:
    """'' when one location or target names something it can use, else why not."""
    sig, kind, value = slot
    allowed = _LOCATION_RECORD if sig == 'PLDT' else _TARGET_RECORD
    if kind == _ALIAS_TYPE[sig]:
        quest = u32(first(pack, 'QNAM'))
        return '' if value in quest_aliases.get(quest, ()) else \
            f'{sig} names alias {value}, which quest {index.edid(quest) or hex(quest)} lacks'
    if kind not in allowed or not value or not index.is_own(value):
        return ''
    rec = index.by_fid.get(value)
    if rec is None:
        return f'{sig} names {value:08X}, which is not in the plugin'
    if allowed[kind] and rec.type not in allowed[kind]:
        return f'{sig} names {index.edid(value) or hex(value)}, a {rec.type}'
    return ''


def record_problems(index, pack, quest_aliases: dict) -> list:
    """Why each location or target of `pack` names nothing it can use."""
    return [p for p in (slot_problem(index, pack, slot, quest_aliases) for slot in _slots(pack)) if p]


def schedule_problem(pack) -> str:
    """'' when the PSDT schedule is within the engine's ranges, else the field that is not."""
    data = first(pack, 'PSDT')
    if len(data) < 5:
        return ''
    values = struct.unpack_from('<bbBbb', data)
    names = ('month', 'day of week', 'date', 'hour', 'minute')
    bad = [f'{n} {v}' for n, v, (lo, hi) in zip(names, values, _SCHEDULE_RANGES) if not lo <= v <= hi]
    return ', '.join(bad)


def package_source(index, npc):
    """The NPC_ whose PKID list `npc` runs: itself, or the template it takes AI packages from."""
    seen = set()
    while npc.form_id not in seen:
        seen.add(npc.form_id)
        acbs, template = first(npc, 'ACBS'), index.by_fid.get(u32(first(npc, 'TPLT')))
        flags = struct.unpack_from('<H', acbs, _TEMPLATE_FLAGS_AT)[0] if len(acbs) >= _TEMPLATE_FLAGS_AT + 2 else 0
        if not flags & _USE_AI_PACKAGES or template is None or template.type != 'NPC_':
            return npc
        npc = template
    return npc


def users(index) -> tuple:
    """({package: {actor base FormIDs}}, [(holder, missing package FormID)]) over PKID and ALPC.

    An alias with no forced reference in this plugin holds its packages for an
    actor only known at runtime, recorded as base 0.
    """
    held, missing = defaultdict(set), []
    for npc in index.by_type['NPC_']:
        for data in every(package_source(index, npc), 'PKID'):
            held[u32(data)].add(npc.form_id)
    for quest in index.by_type['QUST']:
        for name, subs in aliases(quest):
            ref = index.by_fid.get(u32(subs['ALFR'][0])) if subs['ALFR'] else None
            base = u32(first(ref, 'NAME')) if ref else 0
            for data in subs['ALPC']:
                held[u32(data)].add(base)
    for pack, bases in held.items():
        if index.is_own(pack) and pack not in index.by_fid:
            missing += [(base, pack) for base in bases]
    return held, missing


def quest_alias_ids(index) -> dict:
    """{quest FormID: {alias ids}} over reference and location aliases."""
    return {q.form_id: {u32(s.data) for s in q.subrecords if s.type in ('ALST', 'ALLS')}
            for q in index.by_type['QUST']}


def _pack_findings(game: str, index, pack, holders: set, quest_aliases: dict) -> list:
    """The record, schedule and condition findings for one package."""
    name = index.edid(pack.form_id) or f'{pack.form_id:08X}'
    out = []
    problems = record_problems(index, pack, quest_aliases)
    if problems:
        out.append(Finding('packages', f'packages|{game}|record|{name}', 'error',
                           f'package {name} points at records it cannot use', tuple(problems[:SAMPLES])))
    bad = schedule_problem(pack)
    if bad:
        out.append(Finding('packages', f'packages|{game}|schedule|{name}', 'error',
                           f'package {name} has a schedule outside the engine ranges: {bad}'))
    required = required_speakers([decode_condition(d) for d in every(pack, 'CTDA')])
    if required is not None and holders and 0 not in holders and not holders & set(required):
        out.append(Finding('packages', f'packages|{game}|conditions|{name}', 'review',
                           f'package {name} requires GetIsID {", ".join(index.edid(f) or hex(f) for f in required) or "of two different actors"}, '
                           'which no actor holding it is', tuple(index.edid(h) or hex(h) for h in sorted(holders))[:SAMPLES]))
    return out


def navmesh_findings(game: str, index) -> list:
    """One review per cell that package destinations name but no navmesh covers."""
    navmeshed, by_cell = index.navmesh_cells(), defaultdict(set)
    for pack in index.by_type['PACK']:
        for sig, kind, value in _slots(pack):
            rec = index.by_fid.get(value) if (sig, kind) in (('PLDT', 0), ('PTDA', 0), ('PLDT', 1)) else None
            cell = rec.form_id if rec is not None and rec.type == 'CELL' else (
                index.home_cell(rec) if rec is not None and rec.type in ('REFR', 'ACHR') else 0)
            if cell and cell not in navmeshed:
                by_cell[cell].add(index.edid(pack.form_id))
    return [Finding('packages', f'packages|{game}|navmesh|{index.edid(cell) or f"{cell:08X}"}', 'review',
                    f'{len(packs)} packages send actors into cell {index.edid(cell) or f"{cell:08X}"}, '
                    'which has no navmesh', tuple(sorted(packs)[:SAMPLES]))
            for cell, packs in sorted(by_cell.items())]


def _watched(index, pack: int, faction: int) -> bool:
    """Whether an alias holds `pack` and its quest's VMAD names both."""
    need = (struct.pack('<I', pack), struct.pack('<I', faction))
    return any(any(u32(d) == pack for _n, subs in aliases(q) for d in subs['ALPC'])
               and all(b in first(q, 'VMAD') for b in need) for q in index.by_type['QUST'])


def run_once_findings(game: str, index, held: dict) -> list:
    """One error per held run-once package whose end no alias script sees, so its faction is never added."""
    factions = {r.form_id for r in index.by_type['FACT'] if index.edid(r.form_id).startswith(RUN_ONCE_PREFIX)}
    out = []
    for pack in (p for p in index.by_type['PACK'] if p.form_id in held):
        guards = [c[3] for c in map(decode_condition, every(pack, 'CTDA'))
                  if c[2] == _GET_IN_FACTION and c[3] in factions]
        if any(not _watched(index, pack.form_id, f) for f in guards):
            name = index.edid(pack.form_id) or f'{pack.form_id:08X}'
            out.append(Finding('packages', f'packages|{game}|run-once|{name}', 'error',
                               f'run-once package {name} is held by an actor, but no alias script watches it, '
                               'so it never ends and reruns forever', tuple(index.edid(h) or 'an alias' for h in
                                                                             sorted(held[pack.form_id]))[:SAMPLES]))
    return out


def audit(game: str, index) -> list:
    """The package and AI findings for one game."""
    held, missing = users(index)
    quest_aliases = quest_alias_ids(index)
    out = [f for pack in index.by_type['PACK']
           for f in _pack_findings(game, index, pack, held.get(pack.form_id, set()), quest_aliases)]
    out += [Finding('packages', f'packages|{game}|missing|{pack:08X}', 'error',
                    f'{index.edid(holder) or hex(holder)} holds package {pack:08X}, which is not in the plugin')
            for holder, pack in missing]
    return out + navmesh_findings(game, index) + run_once_findings(game, index, held)
