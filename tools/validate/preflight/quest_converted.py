"""The converted side of the quest audit: Papyrus SetStage calls and Skyrim dialogue.

Each generated `.psc` is read for its SetStage calls, the function each call
sits in, and the `;NE:` lines that left a SetStage inert. The built plugin
gives Skyrim's dialogue model: which topics a player can reach and which
lines a placed actor can speak.

See: docs/commentary/tools_preflight.md#converted-setters
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.validate.preflight.plugin_index import every, first, u32, zstring
from tools.validate.preflight.quest_source import SETSTAGE, START, STARTQUEST, decode_condition, speakable

#: `X.TES4SetStage(Quest as Type, 5)` or a bare `TES4SetStage(Quest, 5)`.
_TES4_SETSTAGE = re.compile(r'\bTES4SetStage\(\s*([\w.()]+)(?:\s+as\s+\w+)?\s*,\s*(-?\d+)\s*\)', re.I)

#: `Quest.SetStage(5)`, including `GetOwningQuest().SetStage(5)`.
_DOT_SETSTAGE = re.compile(r'([\w.()]+)\.SetStage\(\s*(-?\d+)\s*\)', re.I)

#: A bare `SetStage(5)` inside a quest script, which sets its own quest.
_BARE_SETSTAGE = re.compile(r'(?<![\w.])SetStage\(\s*(-?\d+)\s*\)', re.I)

#: `Quest.Start()`, the converted StartQuest of a quest with no script.
_DOT_START = re.compile(r'([\w.()]+)\.Start\(\s*\)', re.I)

#: `X.TES4Start(Quest as X)`, the converted StartQuest of a quest with a script.
_TES4_START = re.compile(r'\bTES4Start\(\s*([\w.()]+)(?:\s+as\s+\w+)?\s*\)', re.I)

#: The start of a Papyrus function, whatever it returns.
_FUNCTION = re.compile(r'^\s*(?:\w+\s+)?function\s+(\w+)', re.I)

#: Quest expressions that mean the script's own quest.
SELF_QUEST = ('self', 'getowningquest()', '')

#: Skyrim DLBR flags that put a branch in front of the player: top-level and blocking.
_OPEN_BRANCH = 0x01 | 0x02


@dataclass(frozen=True)
class Call:
    """One converted SetStage: the function it is in, its quest expression and stage."""

    function: str
    quest_expr: str
    stage: int


@dataclass
class Script:
    """A generated script's SetStage calls, inert SetStages (as `(Call, why)`), and whether it compiled."""

    name: str
    compiled: bool
    calls: list = field(default_factory=list)
    inert: list = field(default_factory=list)

#: The header the converter writes over a source block it keeps only as comments.
_DEAD_BLOCK = re.compile(r'---\s*TES4\s*`([^`]+)`')


def strip_papyrus_comment(line: str) -> str:
    """`line` up to a `;` that is not inside a string."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ';' and not quoted:
            return line[:i]
    return line


def _line_calls(code: str, function: str) -> list:
    """Every SetStage call on one uncommented line."""
    calls = [Call(function, q.lower(), int(s)) for q, s in _TES4_SETSTAGE.findall(code)]
    calls += [Call(function, q.lower(), int(s)) for q, s in _DOT_SETSTAGE.findall(code)]
    if not calls:
        calls += [Call(function, '', int(s)) for s in _BARE_SETSTAGE.findall(code)]
    starts = _DOT_START.findall(code) + _TES4_START.findall(code)
    return calls + [Call(function, q.lower(), START) for q in starts]


def _inert_calls(comment: str, function: str, block: str) -> list:
    """[(Call, why)] for a SetStage kept only in a comment: a `;NE:` line or a dead block."""
    body = comment.lstrip(';').strip()
    if ';NE' in comment:
        calls = [Call(function, q.lower(), int(s)) for q, s in SETSTAGE.findall(body)
                 if re.fullmatch(r'-?\d+', s)]
        calls += [Call(function, q.lower(), START) for q in STARTQUEST.findall(body)]
        return [(c, f'left as {comment.strip()[:80]}') for c in calls]
    why = f'sits in `{block}`, which the converter keeps only as comments' if block \
        else f'commented out: {body[:80]}'
    return [(c, why) for c in _line_calls(body, function)]


def parse_script(name: str, text: str, compiled: bool) -> Script:
    """The SetStage calls and commented-out SetStages of one script's source."""
    script = Script(name, compiled)
    function, block = '', ''
    for line in text.splitlines():
        match = _FUNCTION.match(line) or re.match(r'^\s*event\s+(\w+)', line, re.I)
        if match:
            function, block = match.group(1).lower(), ''
        header = _DEAD_BLOCK.search(line)
        if header:
            block = header.group(1)
        code = strip_papyrus_comment(line)
        script.calls += _line_calls(code, function)
        comment = line[len(code):]
        if any(word in comment.lower() for word in ('setstage', 'startquest', 'start(')):
            script.inert += _inert_calls(comment, function, block if not code.strip() else '')
    return script


def load_scripts(scripts_dir: Path) -> dict:
    """{script name lower: Script} for every generated source under `scripts_dir`."""
    source = Path(scripts_dir) / 'source'
    compiled = {p.stem.lower() for p in Path(scripts_dir).glob('*.pex')}
    out = {}
    for path in source.glob('*.psc'):
        text = path.read_text(encoding='utf-8', errors='replace')
        out[path.stem.lower()] = parse_script(path.stem, text, path.stem.lower() in compiled)
    return out


class ConvertedDialogue:
    """Skyrim's dialogue model over a built plugin: reachable topics and speakable lines."""

    def __init__(self, index):
        """Read topics, branches and placed actors from a PluginIndex, then solve reachability."""
        self.index = index
        self.present = index.placed_bases()
        self.subtype = {r.form_id: zstring(first(r, 'SNAM'))[:4] for r in index.by_type['DIAL']}
        self.open_starts = {u32(first(r, 'SNAM')) for r in index.by_type['DLBR']
                            if u32(first(r, 'DNAM')) & _OPEN_BRANCH}
        self.external = self._externally_named()
        self.live = self._reachable()

    def _externally_named(self) -> set:
        """Custom topics a scene, a package or a script property names."""
        wanted = {fid for fid, sub in self.subtype.items() if sub == 'CUST'}
        named = {fid for props in self.index.script_props.values()
                 for fid in props.values() if fid in wanted}
        for sig in ('SCEN', 'PACK'):
            for rec in self.index.by_type[sig]:
                named |= {u32(s.data, i) for s in rec.subrecords
                          for i in range(0, len(s.data) - 3)} & wanted
        return named

    def conditions(self, rec) -> list:
        """The decoded CTDAs of one built INFO."""
        return [decode_condition(data) for data in every(rec, 'CTDA')]

    def line_speakable(self, rec) -> bool:
        """Whether a placed actor passes the line's GetIsID requirements."""
        return speakable(self.conditions(rec), self.present)

    def _reachable(self) -> set:
        """Topics a player can reach: non-custom, open branch starts, named, or linked.

        A choice (TCLT) counts only from a line outside a Hello topic, since a
        Hello line closes the conversation before its replies show.
        """
        live = {fid for fid, sub in self.subtype.items() if sub != 'CUST'}
        live |= self.open_starts | self.external
        linking = [rec for rec in self.index.by_type['INFO']
                   if self.subtype.get(rec.parent_dial) != 'HELO' and every(rec, 'TCLT')
                   and self.line_speakable(rec)]
        changed = True
        while changed:
            before = len(live)
            for rec in linking:
                if rec.parent_dial in live:
                    live.update(u32(d) for d in every(rec, 'TCLT'))
            changed = len(live) != before
        return live

    def reachable_info(self, fid: int) -> str:
        """'' when the built INFO `fid` can be spoken, else why it cannot."""
        rec = self.index.by_fid.get(fid)
        if rec is None or rec.type != 'INFO':
            return 'the INFO is missing from the built plugin'
        if rec.parent_dial not in self.live:
            return (f'its topic {self.index.edid(rec.parent_dial) or hex(rec.parent_dial)} '
                    'is not reachable in Skyrim')
        if not self.line_speakable(rec):
            return 'no placed actor passes its GetIsID condition'
        return ''
