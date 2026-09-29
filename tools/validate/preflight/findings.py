"""What an audit reports, the review ledger that silences it, and the report.

A finding is an `error` (the audit is sure the build is broken) or a `review`
(the audit could not tell, so a person decides). The ledger records each
decision by key or key pattern: `ok` and `skip` hide the finding, `bug` keeps
it listed with the note. Each run also remembers its findings, so the report
marks what is new since the last run.

See: docs/commentary/tools_preflight.md#findings-and-the-review-ledger
"""

import datetime
import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

#: The committed file holding every manual review decision.
LEDGER = Path(__file__).with_name('review_ledger.json')

#: Ledger statuses: `ok` works as intended, `skip` stops checking, `bug` is confirmed broken.
STATUSES = ('ok', 'skip', 'bug')

#: Lines printed per report section before the rest go only to the report file.
SECTION_LIMIT = 25


@dataclass(frozen=True)
class Finding:
    """One problem an audit found, or one question it could not answer."""

    audit: str
    key: str
    severity: str
    summary: str
    detail: tuple = field(default=())


def load_ledger(path: Path = LEDGER) -> dict:
    """{key or pattern: {status, note, date}} from the ledger file."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8')).get('entries', {})


def save_ledger(entries: dict, path: Path = LEDGER) -> None:
    """Write the ledger, sorted so its diffs stay readable."""
    body = {'version': 1, 'entries': dict(sorted(entries.items()))}
    path.write_text(json.dumps(body, indent=1) + '\n', encoding='utf-8')


def mark(entries: dict, key: str, status: str, note: str) -> dict:
    """The ledger with `key` (an exact key or an fnmatch pattern) decided."""
    if status not in STATUSES:
        raise ValueError(f'status must be one of {STATUSES}')
    out = dict(entries)
    out[key] = {'status': status, 'note': note,
                'date': datetime.date.today().isoformat()}
    return out


def decision(entries: dict, key: str):
    """The ledger entry deciding `key`: its exact entry, else the longest matching pattern."""
    if key in entries:
        return entries[key]
    hits = [p for p in entries if any(c in p for c in '*?[') and fnmatch.fnmatchcase(key, p)]
    return entries[max(hits, key=len)] if hits else None


def triage(findings: list, entries: dict, previous: set) -> dict:
    """{section: [(finding, tag)]} for sections error, review and hidden.

    A `bug` decision lists the finding as an error whatever the audit said;
    `ok` and `skip` move it to hidden. The tag is `new` for a key missing from
    `previous`, the last run's keys, or the ledger note.
    """
    out = {'error': [], 'review': [], 'hidden': []}
    for f in findings:
        entry = decision(entries, f.key)
        status = entry['status'] if entry else None
        tag = entry.get('note', '') if entry else ('new' if f.key not in previous else '')
        if status in ('ok', 'skip'):
            out['hidden'].append((f, status))
        elif status == 'bug':
            out['error'].append((f, 'bug: ' + tag if tag else 'bug'))
        else:
            out[f.severity].append((f, tag))
    return out


def state_dir(output_root: Path, game: str) -> Path:
    """The ignored folder holding one game's audit state and reports."""
    path = Path(output_root) / 'preflight' / game
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_previous(folder: Path, audit: str) -> set:
    """The finding keys the last run of `audit` reported."""
    path = folder / f'{audit}_last.json'
    return set(json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else set()


def save_previous(folder: Path, audit: str, findings: list) -> None:
    """Remember this run's keys so the next report can mark what is new."""
    keys = sorted({f.key for f in findings})
    (folder / f'{audit}_last.json').write_text(json.dumps(keys, indent=0), encoding='utf-8')


def _section_lines(title: str, rows: list, full: bool) -> list:
    """Printed lines for one section, capped unless `full`."""
    if not rows:
        return []
    out = [f'  {title}: {len(rows)}']
    shown = rows if full else rows[:SECTION_LIMIT]
    for f, tag in shown:
        out.append(f'    [{tag}] {f.summary}' if tag else f'    {f.summary}')
        out.append(f'        key: {f.key}')
        out += [f'        {line}' for line in f.detail]
    if len(rows) > len(shown):
        out.append(f'    ... {len(rows) - len(shown)} more in the report file')
    return out


def render(audit: str, sections: dict, full: bool) -> list:
    """The report lines for one audit's triaged findings."""
    hidden = sections['hidden']
    new = sum(1 for rows in (sections['error'], sections['review'])
              for _f, tag in rows if tag == 'new')
    head = (f'{audit}: {len(sections["error"])} errors, {len(sections["review"])} to review, '
            f'{new} new, {len(hidden)} hidden by the ledger')
    return ([head] + _section_lines('ERRORS', sections['error'], full)
            + _section_lines('NEEDS MANUAL REVIEW', sections['review'], full))
