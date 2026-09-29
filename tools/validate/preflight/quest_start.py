"""Quests that start in the source game and never start in the build, and aliases that never fill.

A quest starts when it is Start Game Enabled, when a StartQuest runs, or when
a SetStage on it runs, which starts a stopped quest in both engines. The
StartQuest sites ride the quest progression graph as the pseudo-stage START.

A Skyrim quest whose required alias cannot fill never starts, and says
nothing. An optional alias that never fills silently drops its packages.

See: docs/commentary/tools_preflight.md#quest-start
"""

from collections import defaultdict

from tools.validate.preflight.findings import Finding
from tools.validate.preflight.plugin_index import first, u32
from tools.validate.preflight.quest_progression import graphs, site_lines
from tools.validate.preflight.quest_source import START

#: QUST DNAM flag: Start Game Enabled.
_START_GAME_ENABLED = 0x0001

#: Alias FNAM flags: the alias may stay empty, and it may hold a disabled reference.
_OPTIONAL, _ALLOW_DISABLED = 0x0002, 0x0080

#: Record header flags: deleted, and initially disabled.
_DELETED, _INITIALLY_DISABLED = 0x0020, 0x0800

#: Record types a forced-reference alias can hold.
_PLACED = frozenset({'REFR', 'ACHR', 'PGRE', 'PHZD', 'PARW', 'PBAR', 'PBEA', 'PCON', 'PFLA', 'PMIS'})


def built_start_enabled(index) -> set:
    """EditorIDs (lower) of the built quests flagged Start Game Enabled."""
    return {index.edid(r.form_id).lower() for r in index.by_type['QUST']
            if u32(first(r, 'DNAM')) & _START_GAME_ENABLED}


def started(reached: set, quest: str) -> bool:
    """Whether any reached stage or StartQuest of `quest` runs, which starts it."""
    return any(q == quest for q, _stage in reached)


def start_findings(ctx) -> list:
    """Findings for quests the source starts that the build never starts."""
    verdicts, source, hopeful, strict = graphs(ctx)
    built_sge = built_start_enabled(ctx.index)
    out = []
    for quest, name in sorted(ctx.source.quests.items()):
        sge = quest in ctx.source.start_enabled
        if not (sge or started(source, quest)) or quest in built_sge or started(strict, quest):
            continue
        detail = ['starts at game load in the source, but the built quest is not Start Game Enabled'] if sge else []
        detail += site_lines([s for s in verdicts if (s.quest.lower(), s.stage) == (quest, START)],
                             verdicts, ctx, hopeful)
        lost = not started(hopeful, quest)
        out.append(Finding('start', f'start|{ctx.game}|{name}', 'error' if lost else 'review',
                           f'{name} never starts after conversion' if lost else
                           f'{name} starts only through setters the audit could not confirm', tuple(detail)))
    return out


def aliases(rec) -> list:
    """[(alias name, {subrecord: [data]})] of a QUST's reference aliases, in order."""
    out, current = [], None
    for sub in rec.subrecords:
        if sub.type == 'ALST':
            current = defaultdict(list)
        elif sub.type == 'ALED' and current is not None:
            out.append((first_text(current['ALID']), current))
            current = None
        elif current is not None:
            current[sub.type].append(sub.data)
    return out


def first_text(values: list) -> str:
    """The first of a list of NUL-terminated strings, or ''."""
    return values[0].split(b'\0', 1)[0].decode('latin-1') if values else ''


def fill_problem(subs: dict, index, placed: set) -> str:
    """'' when a forced or unique-actor alias can fill, else why not; master targets are not judged."""
    flags = u32(subs['FNAM'][0]) if subs['FNAM'] else 0
    if subs['ALFR']:
        target = u32(subs['ALFR'][0])
        rec = index.by_fid.get(target)
        if not index.is_own(target):
            return ''
        if rec is None:
            return f'forced reference {target:08X} is not in the plugin'
        if rec.type not in _PLACED:
            return f'forced reference {index.edid(target) or hex(target)} is a {rec.type}, not a placed reference'
        if rec.flags & _DELETED:
            return f'forced reference {index.edid(target) or hex(target)} is deleted'
        if rec.flags & _INITIALLY_DISABLED and not flags & _ALLOW_DISABLED:
            return f'forced reference {index.edid(target) or hex(target)} starts disabled'
    if subs['ALUA'] and index.is_own(u32(subs['ALUA'][0])) and u32(subs['ALUA'][0]) not in placed:
        return f'unique actor {index.edid(u32(subs["ALUA"][0]))} is never placed'
    return ''


def _alias_finding(game: str, quest: str, name: str, subs: dict, problem: str):
    """One alias's finding, or None when it fills or may stay empty harmlessly."""
    optional = (u32(subs['FNAM'][0]) if subs['FNAM'] else 0) & _OPTIONAL
    key = f'alias|{game}|{quest}|{name}'
    if problem and not optional:
        return Finding('start', key, 'error', f'{quest} cannot start: required alias {name} never fills',
                       (problem,))
    if problem and subs['ALPC']:
        return Finding('start', key, 'error', f'{quest} alias {name} never fills, so its packages never run',
                       (problem,))
    if problem:
        return Finding('start', key, 'review', f'{quest} alias {name} never fills', (problem,))
    if not optional and not (subs['ALFR'] or subs['ALUA']):
        return Finding('start', key, 'review',
                       f'{quest} requires alias {name}, filled in a way the audit cannot evaluate')
    return None


def alias_findings(game: str, index) -> list:
    """Findings for aliases that never fill, or required ones the audit cannot judge."""
    placed = index.placed_bases()
    out = []
    for rec in index.by_type['QUST']:
        quest = index.edid(rec.form_id)
        for name, subs in aliases(rec):
            finding = _alias_finding(game, quest, name, subs, fill_problem(subs, index, placed))
            if finding:
                out.append(finding)
    return out


def audit(ctx) -> list:
    """The quest start and alias fill findings for one game."""
    return start_findings(ctx) + alias_findings(ctx.game, ctx.index)
