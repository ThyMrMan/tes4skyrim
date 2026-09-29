"""After a play-test: the Papyrus errors this game's scripts raised, and where each touched quest stopped.

Papyrus text comes from the newest `Papyrus.0.log` and from the flight
recorder's `papyrus` events, which keep arriving after the log stops flushing.
Only lines naming this game's generated scripts (or the shared TES4 ones) are
kept. They are grouped by cause and compared with the previous session
(`Papyrus.1.log` and recorder run 1), so the report tags what is new.

For every quest the recorder saw change stage, a review names its last stage,
the next authored stage, and each source setter of that stage with the quest
audit's verdict on it.

See: docs/commentary/tools_preflight.md#log-triage
"""

import re
from collections import defaultdict
from pathlib import Path

from tools.live.flight_log import events_path, read_events
from tools.script.papyrus_tail import log_dir
from tools.validate.preflight.findings import Finding
from tools.validate.preflight.script_health import attach_mismatches
from tools.validate.preflight.quest_progression import describe, judge
from tools.validate.vmad_property_typecheck import (MasterTables, cross_master_problems, declared_properties,
                                                    script_extends, unbound_properties)

#: `Property P on script S attached to X (ID) cannot be bound because [<nullptr form>] (ID) ...`.
_BINDING = re.compile(r'Property (\w+) on script (\w+) attached to .*?cannot be bound because (<nullptr form>)?')

#: `Unable to bind script S to X because their base types do not match`.
_UNBOUND_SCRIPT = re.compile(r'Unable to bind script (\w+) to (.*?) because')

#: `Cannot open store for class "S", missing file?`.
_MISSING_CLASS = re.compile(r'Cannot open store for class "(\w+)"')

#: `Property P on script S ... cannot be initialized because the script no longer contains that property`.
_STALE = re.compile(r'Property (\w+) on script (\w+) .*cannot be initialized')

#: A stack frame: `[owner (ID)].Script.Function() - "file" Line N`.
_FRAME = re.compile(r'\]\.(\w+)\.(\w+)\(\)')

#: An identifier in a runtime error message (an underscore, a digit, or an inner capital), masked to group causes.
_NAME = re.compile(r'\b\w*(?:[_\d]|[a-z][A-Z])\w*\b')

#: Scripts every converted game ships, whose errors belong to each game.
_SHARED = ('tes4polyfill', 'tes4_')

#: The property slot a predicted "script cannot attach" is filed under.
ATTACH = '<attach>'

#: Samples listed per finding.
SAMPLES = 4


def strip_stamp(line: str) -> str:
    """A log line without its leading `[timestamp]`."""
    return re.sub(r'^\[[^\]]*\]\s*', '', line.rstrip('\n'))


def session_lines(papyrus: Path, run: int) -> list:
    """The Papyrus lines of one session: the log's, then recorder lines the log lacks."""
    lines = [strip_stamp(line) for line in papyrus.read_text(encoding='utf-8', errors='replace').splitlines()] \
        if papyrus.is_file() else []
    events = read_events(events_path(run)) if events_path(run).is_file() else []
    seen = set(lines)
    return lines + [e['text'] for e in events if e.get('ev') == 'papyrus' and e.get('text') not in seen]


def classify(lines: list) -> list:
    """[(cause key, script, detail)] for every error or warning line, stacks folded into their error."""
    out, pending = [], None
    for line in lines:
        if line.strip() == 'stack:':
            continue
        frame = _FRAME.search(line) if line.startswith('\t') else None
        if pending and frame:
            out.append((f'runtime|{pending}|{frame.group(1)}.{frame.group(2)}', frame.group(1), pending))
            pending = None
            continue
        pending = None
        cause = _line_cause(line)
        if cause is None and line.startswith('error:'):
            pending = _NAME.sub('#', line[len('error:'):]).strip()[:80]
        elif cause:
            out.append(cause)
    return out


def _line_cause(line: str):
    """(cause key, script, detail) for a single-line error or warning, or None."""
    match = _BINDING.search(line)
    if match:
        kind = 'names no record' if match.group(3) else 'wrong type'
        return f'binding|{match.group(2)}|{match.group(1)}', match.group(2), f'property {match.group(1)}: {kind}'
    match = _UNBOUND_SCRIPT.search(line)
    if match:
        return f'bind-script|{match.group(1)}', match.group(1), f'cannot attach to {match.group(2)[:60]}'
    match = _MISSING_CLASS.search(line)
    if match:
        return f'missing-class|{match.group(1)}', match.group(1), 'no .pex loaded'
    match = _STALE.search(line)
    if match:
        return f'stale|{match.group(2)}|{match.group(1)}', match.group(2), f'save holds removed property {match.group(1)}'
    return None


def ours(script: str, prefix: str) -> bool:
    """Whether a script belongs to this game, or is a shared TES4 script."""
    name = script.lower()
    return name.startswith(prefix.lower()) or name.startswith(_SHARED)


def predicted_bindings(ctx, output: Path) -> set:
    """{(script lower, property lower)} the static scripts audit already reports as unbindable."""
    source = str(Path(output) / ctx.game / 'scripts' / 'source')
    declared, extends = declared_properties(source), script_extends(source)
    tables = MasterTables(ctx.game, ctx.index, str(Path(output) / ctx.game / ctx.game), str(output))
    _checked, bad, _unresolved = cross_master_problems(tables, ctx.index, declared, extends)
    return ({(row[0], row[1].lower()) for row in bad}
            | {(script, prop.lower()) for script, prop, _t in unbound_properties(ctx.index, declared)}
            | {(script, ATTACH) for rows in attach_mismatches(ctx.index, extends).values() for script, _f in rows})


def _predicted_finding(game: str, rows: list):
    """One review folding the binding and attach errors the scripts audit already reports, or None."""
    if not rows:
        return None
    return Finding('logs', f'logs|{game}|binding|predicted', 'review',
                   f'{len(rows)} binding errors the scripts audit already reports',
                   tuple(sorted(rows)[:SAMPLES]))


def papyrus_findings(game: str, prefix: str, current: list, predicted: set = frozenset()) -> list:
    """One finding per cause; stale-save warnings are reviews, the rest errors.

    Binding errors the static scripts audit predicts fold into one review, so
    the ones it missed stand out.
    """
    grouped, folded = defaultdict(list), set()
    for key, script, detail in current:
        parts = key.split('|')
        if not ours(script, prefix):
            continue
        if ((parts[0] == 'binding' and (parts[1].lower(), parts[2].lower()) in predicted)
                or (parts[0] == 'bind-script' and (parts[1].lower(), ATTACH) in predicted)):
            folded.add('.'.join(parts[1:]))
            continue
        grouped[key].append(f'{script}: {detail}')
    out = [f for f in (_predicted_finding(game, sorted(folded)),) if f]
    for key, rows in sorted(grouped.items()):
        kind = key.split('|', 1)[0]
        summary = {'binding': 'property cannot be bound', 'bind-script': 'script cannot attach to its record',
                   'missing-class': 'script class is missing', 'stale': 'save holds a property the script lost',
                   'runtime': 'runtime error'}[kind]
        detail = sorted(set(rows))
        out.append(Finding('logs', f'logs|{game}|{key}', 'review' if kind == 'stale' else 'error',
                           f'{summary}: {key.split("|", 1)[1]} (x{len(rows)})',
                           tuple(detail[:SAMPLES]) + ((f'... {len(detail) - SAMPLES} more',) if len(detail) > SAMPLES else ())))
    return out


def detect_prefix(index, quest_ids: set):
    """The load-order byte under which the recorder's quest ids are this plugin's quests, or None."""
    own = len(index.masters)
    votes = defaultdict(int)
    for rid in quest_ids:
        rec = index.by_fid.get((own << 24) | (rid & 0xFFFFFF))
        if rec is not None and rec.type == 'QUST' and rid >> 24 not in (0, 0xFE, 0xFF):
            votes[rid >> 24] += 1
    return max(votes, key=votes.get) if votes else None


def stages_seen(index, events: list) -> list:
    """[(quest EditorID lower, stage)] in the order the recorder saw this plugin's quests change stage."""
    stages = [(int(e['quest'], 16), e.get('stage')) for e in events if e.get('ev') == 'quest_stage' and 'quest' in e]
    prefix = detect_prefix(index, {q for q, _s in stages})
    own = len(index.masters)
    return [(index.edid((own << 24) | (rid & 0xFFFFFF)).lower(), stage) for rid, stage in stages
            if prefix is not None and rid >> 24 == prefix and isinstance(stage, int)]


def setter_line(site, ctx, verdicts: dict, seen: set) -> str:
    """One setter of a quest's next stage, its verdict, and whether its own stage ran this session."""
    if site not in verdicts:
        return f'{describe(site, ctx)}: not live in the source'
    status, reason = verdicts[site]
    line = f'{describe(site, ctx)}: {status}' + (f' - {reason}' if reason else '')
    owner = site.owner.split('|')
    if site.kind == 'stage' and (owner[0].lower(), int(owner[1])) not in seen:
        line += f'; stage {owner[1]} did not run this session'
    return line


def quest_findings(ctx, events: list) -> list:
    """One review per touched quest: its last stage, the next one, and that stage's setters."""
    verdicts, order = judge(ctx), stages_seen(ctx.index, events)
    seen, last = set(order), dict(order)
    out = []
    for quest, stage in sorted(last.items()):
        later = sorted(s for s in ctx.source.stages.get(quest, ()) if s > stage)
        if not later:
            continue
        name = ctx.source.quests.get(quest, quest)
        sites = [s for s in ctx.source.setters if (s.quest.lower(), s.stage) == (quest, later[0])]
        detail = [setter_line(s, ctx, verdicts, seen) for s in sites[:SAMPLES]]
        detail = detail or ['no setter of it in the source that the audit models']
        out.append(Finding('logs', f'logs|{ctx.game}|quest|{name}|{stage}', 'review',
                           f'{name} was left at stage {stage}; next is {later[0]}', tuple(detail)))
    return out


def audit(ctx, output: Path, logs: Path = None) -> tuple:
    """(the play-test findings for one game, the previous session's finding keys)."""
    folder = Path(logs) if logs else log_dir()
    predicted = predicted_bindings(ctx, output)
    current = classify(session_lines(folder / 'Papyrus.0.log', 0))
    previous = papyrus_findings(ctx.game, ctx.prefix, classify(session_lines(folder / 'Papyrus.1.log', 1)), predicted)
    events = read_events(events_path(0)) if events_path(0).is_file() else []
    found = papyrus_findings(ctx.game, ctx.prefix, current, predicted) + quest_findings(ctx, events)
    return found, {f.key for f in previous}
