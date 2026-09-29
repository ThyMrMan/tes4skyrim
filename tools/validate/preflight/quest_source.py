"""Quest stage setters and dialogue reachability read from a source export.

Every `SetStage` in a quest stage result, an INFO result, a package section
or a script becomes a `Setter`. A stage number that is not a literal is kept
as None, so the audit marks it for review instead of guessing.

See: docs/commentary/tools_preflight.md#source-setters
"""

import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from tes5_import.base.text_reader import get_int, get_str, info_result_script, parse_export_file

#: `SetStage Quest Stage`, with the space or comma separators FO3 allows.
SETSTAGE = re.compile(r'\bsetstage\s*[\s,]\s*(\w+)\s*[\s,]\s*([^\s;,]+)', re.I)

#: `StartQuest Quest`.
STARTQUEST = re.compile(r'\bstartquest\s*[\s,]\s*(\w+)', re.I)

#: The pseudo-stage a StartQuest site reaches, so quest starts ride the same graph as stages.
START = 'start'

#: `Begin OnFire` and the like: the block the following lines run in.
_BEGIN = re.compile(r'^\s*begin\s+(.+)$', re.I)

#: Commands whose arguments name a topic, which makes that topic reachable.
_TOPIC_COMMANDS = re.compile(r'\b(?:addtopic|say|sayto|startconversation|forcegreet)\b(.*)', re.I)

#: The package sections that carry a script in FO3 and FNV.
PACKAGE_SECTIONS = ('OnBegin', 'OnEnd', 'OnChange')

#: CTDA function index of GetIsID, the same in every game.
GET_IS_ID = 72

#: Export files of placements, geometry and dialogue, which never attach a script.
_NO_SCRIPT_FILES = frozenset({'REFR', 'ACHR', 'ACRE', 'LAND', 'NAVM', 'NAVI', 'CELL', 'PGRE',
                              'SCPT', 'INFO', 'DIAL'})

#: A `Key=0001ABCD` export line, whose value may be a script's FormID.
_FID_VALUE = re.compile(rb'^[^=\r\n]+=([0-9A-Fa-f]{8})\r?$', re.M)


def referenced_fids(export_dir: str) -> set:
    """Every FormID a base record in the export names, which includes each attached script."""
    out = set()
    for path in Path(export_dir).glob('*.txt'):
        if path.stem not in _NO_SCRIPT_FILES:
            out |= {int(v, 16) for v in _FID_VALUE.findall(path.read_bytes())}
    return out


@dataclass(frozen=True)
class Setter:
    """One `SetStage` site: where it lives and what it sets."""

    kind: str
    owner: str
    part: str
    quest: str
    stage: object
    raw: str = ''


@dataclass
class SourceInfo:
    """What the dialogue model needs of one INFO."""

    fid: int
    dial: int
    quest: int
    conditions: list
    choices: list
    link_from: list


def strip_comment(line: str) -> str:
    """`line` up to its `;` comment."""
    return line.split(';', 1)[0]


def script_lines(text: str) -> list:
    """The lines of a script text, whether its newlines are real or escaped."""
    return text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\r', '').split('\n')


def find_setters(text: str, quests: dict) -> list:
    """[(quest EditorID, stage, raw, block)] of the uncommented SetStages and StartQuests.

    The stage is an int, START for a StartQuest, or None when it is computed;
    the block is the `Begin` block the line sits in, or ''.
    """
    out, block = [], ''
    for line in script_lines(text):
        code = strip_comment(line)
        begin = _BEGIN.match(code)
        block = begin.group(1).strip() if begin else block
        for quest, stage in SETSTAGE.findall(code):
            if quest.lower() in quests:
                number = int(stage) if re.fullmatch(r'-?\d+', stage) else None
                out.append((quests[quest.lower()], number, line.strip(), block))
        out += [(quests[q.lower()], START, line.strip(), block) for q in STARTQUEST.findall(code)
                if q.lower() in quests]
    return out


def decode_condition(data: bytes) -> tuple:
    """(type, comparison value, function, parameter 1, run-on) of a CTDA; a short one reads zeros past its end.

    See: docs/commentary/tes5_import_conditions.md#fallout-short-ctda
    """
    data = data + bytes(max(0, 24 - len(data)))
    ctype, comp = data[0], struct.unpack_from('<f', data, 4)[0]
    func, param = struct.unpack_from('<HxxI', data, 8)
    return ctype, comp, func, param, struct.unpack_from('<I', data, 20)[0]


def _requires_id(condition: tuple) -> bool:
    """Whether a condition is `GetIsID X == 1` (or `!= 0`) on the subject."""
    ctype, comp, func, _param, run_on = condition
    return func == GET_IS_ID and run_on == 0 and ((ctype >> 5 == 0 and comp == 1.0)
                                                   or (ctype >> 5 == 1 and comp == 0.0))


def or_groups(conditions: list) -> list:
    """The conditions split into OR chains; a chain ends at a condition without the OR flag."""
    groups, current = [], []
    for condition in conditions:
        current.append(condition)
        if not condition[0] & 0x01:
            groups.append(current)
            current = []
    return groups + ([current] if current else [])


def required_speakers(conditions: list):
    """Bases the GetIsID chains allow to speak, or None when anyone may.

    See: docs/commentary/tools_preflight.md#source-setters
    """
    chains = [{c[3] for c in group} for group in or_groups(conditions)
              if all(_requires_id(c) for c in group)]
    return sorted(set.intersection(*chains)) if chains else None


def speakable(conditions: list, present: set) -> bool:
    """False when no placed actor is a base the line's GetIsID conditions allow."""
    required = required_speakers(conditions)
    return required is None or any(fid in present for fid in required)


def _fids(rec: dict, prefix: str) -> list:
    """Every `prefix[i]` FormID value of `rec`."""
    return [int(v, 16) for k, v in rec.items() if k.startswith(prefix + '[') and v]


def _records(export_dir: str, sig: str) -> list:
    """Every record of the export file `sig`.txt, or [] when it is absent."""
    path = os.path.join(export_dir, f'{sig}.txt')
    return parse_export_file(path) if os.path.isfile(path) else []


class SourceGame:
    """A source game's quests, stage setters, dialogue and placed actors."""

    def __init__(self, export_dir: str):
        """Read one game's export folder."""
        self.quests, self.quest_fids, self.start_enabled = {}, {}, set()
        for rec in _records(export_dir, 'QUST'):
            edid = get_str(rec, 'EditorID')
            if edid:
                self.quests[edid.lower()] = edid
                self.quest_fids[int(rec['FormID'], 16)] = edid
            if edid and get_int(rec, 'DATA.Flags') & 0x01:
                self.start_enabled.add(edid.lower())
        self.packages = {rec['FormID'].upper(): rec for rec in _records(export_dir, 'PACK')}
        self.setters, self.texts = [], []
        self.dials, self.infos = {}, {}
        self.present = set()
        self.external_topics = set()
        self.used_scripts = set()
        self.actor_names = {}
        self.stages = {}
        self._read(export_dir)

    def _add(self, kind: str, owner: str, part: str, text: str) -> None:
        """Record the setters in one script text and keep the text for topic lookups."""
        self.texts.append(text)
        for quest, stage, raw, block in find_setters(text, self.quests):
            self.setters.append(Setter(kind, owner, block if kind == 'script' else part, quest, stage, raw))

    def _read(self, export_dir: str) -> None:
        """Fill the model from the export's QUST, PACK, SCPT, DIAL, INFO and actor files."""
        for rec in _records(export_dir, 'QUST'):
            self._read_quest(rec)
        for fid, rec in self.packages.items():
            for section in PACKAGE_SECTIONS:
                self._add('package', fid, section, rec.get(f'{section}.Script', ''))
            topic = int(rec.get('PKDD.Topic', '0') or '0', 16)
            if topic:
                self.external_topics.add(topic)
        named = referenced_fids(export_dir)
        for rec in _records(export_dir, 'SCPT'):
            self._add('script', get_str(rec, 'EditorID'), '', rec.get('SCTX', ''))
            if int(rec['FormID'], 16) in named:
                self.used_scripts.add(get_str(rec, 'EditorID').lower())
        for rec in _records(export_dir, 'DIAL'):
            self.dials[int(rec['FormID'], 16)] = (get_str(rec, 'EditorID'),
                                                  get_int(rec, 'DATA.Type'),
                                                  get_int(rec, 'DATA.Flags'))
        for rec in _records(export_dir, 'INFO'):
            self._read_info(rec)
        for sig in ('ACHR', 'ACRE'):
            self.present |= {int(r['NAME'], 16) for r in _records(export_dir, sig) if r.get('NAME')}
        for sig in ('NPC_', 'CREA'):
            self.actor_names.update((int(r['FormID'], 16), get_str(r, 'EditorID'))
                                    for r in _records(export_dir, sig))
        self._topics_named_by_scripts()

    def _read_quest(self, rec: dict) -> None:
        """Record one quest's stage list and the setters in every stage result script."""
        edid = get_str(rec, 'EditorID')
        for i in range(get_int(rec, 'StageCount')):
            stage = get_int(rec, f'Stage[{i}].Index')
            self.stages.setdefault(edid.lower(), []).append(stage)
            for j in range(get_int(rec, f'Stage[{i}].LogCount')):
                text = rec.get(f'Stage[{i}].Log[{j}].ResultScript', '')
                self._add('stage', f'{edid}|{stage}', str(j), text)

    def _read_info(self, rec: dict) -> None:
        """Record one INFO's setters, dialogue links and conditions."""
        fid = int(rec['FormID'], 16)
        self._add('info', rec['FormID'].upper(), '', info_result_script(rec))
        conds = [decode_condition(bytes.fromhex(rec[f'Condition[{i}].Raw']))
                 for i in range(get_int(rec, 'ConditionCount'))
                 if rec.get(f'Condition[{i}].Raw')]
        self.infos[fid] = SourceInfo(fid, int(rec.get('ParentDIAL', '0'), 16),
                                     int(rec.get('QSTI.Quest', '0') or '0', 16), conds,
                                     _fids(rec, 'Choice'), _fids(rec, 'LinkFrom'))
        self.external_topics.update(_fids(rec, 'AddTopic'))

    def _topics_named_by_scripts(self) -> None:
        """Add every topic a script names after AddTopic, Say, SayTo or StartConversation."""
        by_edid = {edid.lower(): fid for fid, (edid, _t, _f) in self.dials.items() if edid}
        for text in self.texts:
            for line in script_lines(text):
                for rest in _TOPIC_COMMANDS.findall(strip_comment(line)):
                    self.external_topics.update(by_edid[w.lower()] for w in re.findall(r'\w+', rest)
                                                if w.lower() in by_edid)

    def reachable_topics(self) -> set:
        """Topics a player can reach in the source game, by a fixed point over links.

        A topic starts reachable when it is not a plain Topic (a greeting, bark
        or conversation), is top-level, is GREETING, or is named by AddTopic, a
        package or a script. Choices from, and links into, a speakable line in a
        reachable topic make that topic reachable too.
        """
        live = {fid for fid, (edid, dtype, flags) in self.dials.items()
                if dtype != 0 or flags & 0x02 or edid.upper() == 'GREETING'}
        live |= self.external_topics
        changed = True
        while changed:
            before = len(live)
            for info in self.infos.values():
                if info.dial in live and speakable(info.conditions, self.present):
                    live.update(info.choices)
                if info.dial not in live and any(t in live for t in info.link_from):
                    live.add(info.dial)
            changed = len(live) != before
        return live
