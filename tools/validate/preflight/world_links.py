"""Doors that lead nowhere, interiors with no way out, and quest targets or map markers that point at nothing.

* A teleport door (REFR XTEL) whose destination is missing or is not a door
  is an error; one whose destination leads back to a different door is marked
  for review, since some one-way links are authored.
* An interior a door leads into, with no teleport door out, is marked for
  review: a script may move the player out.
* A quest objective target (QSTA) naming an alias its quest lacks is an error.
* A map marker (REFR XMRK) with no name is marked for review.

See: docs/commentary/tools_preflight.md#world-links
"""

import struct
from collections import defaultdict

from tools.validate.preflight.findings import Finding
from tools.validate.preflight.plugin_index import first, u32

#: Samples listed per finding.
SAMPLES = 5


def door_findings(game: str, index) -> list:
    """Findings for teleport doors whose destination is missing, not a door, or leads back elsewhere."""
    out = []
    for rec in index.by_type['REFR']:
        target = u32(first(rec, 'XTEL'))
        if not target or not index.is_own(target):
            continue
        name = index.edid(rec.form_id) or f'{rec.form_id:08X}'
        dest = index.by_fid.get(target)
        back = u32(first(dest, 'XTEL')) if dest is not None else 0
        key = f'world|{game}|door|{rec.form_id:08X}'
        if dest is None or not back:
            why = 'is not in the plugin' if dest is None else 'has no door back'
            out.append(Finding('world', key, 'error', f'door {name} leads to {target:08X}, which {why}',
                               (f'in cell {index.edid(rec.parent_cell) or hex(rec.parent_cell)}',)))
        elif back != rec.form_id:
            out.append(Finding('world', key, 'review',
                               f'door {name} leads to {target:08X}, whose door leads back to {back:08X} instead',
                               (f'in cell {index.edid(rec.parent_cell) or hex(rec.parent_cell)}',)))
    return out


def trapped_findings(game: str, index) -> list:
    """One review per interior that a door leads into and no teleport door leads out of."""
    doors = [r for r in index.by_type['REFR'] if u32(first(r, 'XTEL'))]
    exits, interiors = {r.parent_cell for r in doors}, index.interior_cells()
    entered = defaultdict(list)
    for rec in doors:
        dest = index.by_fid.get(u32(first(rec, 'XTEL')))
        if dest is not None:
            entered[dest.parent_cell].append(index.edid(rec.parent_cell) or f'{rec.parent_cell:08X}')
    return [Finding('world', f'world|{game}|trapped|{index.edid(cell) or f"{cell:08X}"}', 'review',
                    f'interior {index.edid(cell) or f"{cell:08X}"} has a door in but no door out',
                    tuple(f'entered from {c}' for c in sorted(set(froms))[:SAMPLES]))
            for cell, froms in sorted(entered.items())
            if cell in interiors and cell not in exits]


def target_findings(game: str, index) -> list:
    """One error per quest whose objective targets name aliases it lacks."""
    out = []
    for quest in index.by_type['QUST']:
        ids = {u32(s.data) for s in quest.subrecords if s.type in ('ALST', 'ALLS')}
        bad = sorted({struct.unpack_from('<i', s.data)[0] for s in quest.subrecords
                      if s.type == 'QSTA' and len(s.data) >= 4} - ids)
        if bad:
            name = index.edid(quest.form_id)
            out.append(Finding('world', f'world|{game}|target|{name}', 'error',
                               f'{name} objective targets name aliases {bad}, which it lacks'))
    return out


def marker_findings(game: str, index) -> list:
    """One review listing map markers that carry no name."""
    nameless = [index.edid(r.form_id) or f'{r.form_id:08X}' for r in index.by_type['REFR']
                if any(s.type == 'XMRK' for s in r.subrecords) and not first(r, 'FULL')]
    if not nameless:
        return []
    return [Finding('world', f'world|{game}|marker|nameless', 'review',
                    f'{len(nameless)} map markers have no name', tuple(sorted(nameless)[:SAMPLES]))]


def audit(game: str, index) -> list:
    """The world linkage findings for one game."""
    return (door_findings(game, index) + trapped_findings(game, index)
            + target_findings(game, index) + marker_findings(game, index))
