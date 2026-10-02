"""Dialogue engine rules learned in play-tests, checked over the built plugin.

* A scene's shared copy plays only from an original held in a Shared Info or
  custom topic; one held in a bark topic (GBYE) never plays.
* A source GREETING line opens a talk only; said without IsInDialogueWithPlayer
  it is also barked on approach, again and again.
* A Fallout reply topic that is not Top-level must not open a menu branch, or
  its line shows out of order in the root menu.
* A Say Once line whose replies set a stage loses that stage when the player
  leaves mid-tree; the build keeps Say Once only when its script is unsafe to rerun.

See: docs/commentary/tools_preflight.md#dialogue-engine-rules
"""

import struct
from collections import defaultdict

from tes5_import.dialogue.say_once import SAY_ONCE
from tools.validate.preflight.findings import Finding
from tools.validate.preflight.plugin_index import every, first, u32
from tools.validate.preflight.quest_source import decode_condition, speakable

#: Built topic subtypes: a scene's lines, and a Shared Info topic holding originals.
_SCENE, _SHARED_INFO = 'SCEN', 'IDAT'

#: Topic subtypes a scene copy plays from: Shared Info, and a custom topic (CG02's intercom scene played so).
_HOLDS_SCENE_ORIGINALS = (_SHARED_INFO, 'CUST')

#: TES5 IsInDialogueWithPlayer.
_IN_DIALOGUE_WITH_PLAYER = 249

#: Source topic EditorID whose lines greet the player as a talk opens.
_GREETING = 'GREETING'

#: FO3/FNV DIAL DATA.Flags bit Top-level.
_TOP_LEVEL = 0x02

#: Source DIAL DATA.Type of a topic the player picks.
_PLAYER_TOPIC = 0

#: Reply depth followed below a Say Once line, as the importer follows it.
_MAX_DEPTH = 8

#: Sample lines listed per finding.
SAMPLES = 5


def _name(index, fid: int) -> str:
    """A record's EditorID, or its FormID in hex."""
    return index.edid(fid) or f'{fid:08X}'


def _quest_of(ctx, info) -> str:
    """The source quest EditorID a line belongs to, or 'no quest'."""
    return ctx.source.quest_fids.get(info.quest, 'no quest')


def scene_original_findings(game: str, index, dlg) -> list:
    """One error per topic holding originals that scene copies play from outside Shared Info."""
    held = defaultdict(list)
    for rec in index.by_type['INFO']:
        if dlg.subtype.get(rec.parent_dial) != _SCENE or len(first(rec, 'DNAM')) != 4:
            continue
        original = index.by_fid.get(u32(first(rec, 'DNAM')))
        topic = original.parent_dial if original is not None else 0
        if dlg.subtype.get(topic) not in _HOLDS_SCENE_ORIGINALS:
            held[topic].append(f'{rec.form_id:08X} -> {u32(first(rec, "DNAM")):08X}')
    return [Finding('dialogue', f'dialogue|{game}|scene-original|{_name(index, topic)}', 'error',
                    f'{len(rows)} scene lines copy originals held in {_name(index, topic) if topic else "no topic"}'
                    f' ({dlg.subtype.get(topic, "missing")}), not a Shared Info or custom topic; the copies never play',
                    tuple(rows[:SAMPLES]))
            for topic, rows in sorted(held.items())]


def _spoken(ctx, fid: int) -> list:
    """Built records a source line is said from, in live topics."""
    dlg, rec = ctx.dialogue, ctx.index.by_fid.get(fid)
    places = [rec] if rec is not None and dlg.subtype.get(rec.parent_dial) != _SHARED_INFO else []
    return [r for r in places + dlg.shared.get(fid, []) if r.parent_dial in dlg.live]


def _gated(rec) -> bool:
    """Whether a built line asks IsInDialogueWithPlayer."""
    return any(decode_condition(d)[2] == _IN_DIALOGUE_WITH_PLAYER for d in every(rec, 'CTDA'))


def greeting_gate_findings(ctx) -> list:
    """One error per quest whose source GREETING lines are said without the talk-open gate."""
    src, ungated = ctx.source, defaultdict(list)
    for info in src.infos.values():
        if (src.dials.get(info.dial, ('',))[0].upper() != _GREETING or info.dial not in ctx.source_topics
                or not speakable(info.conditions, src.present)):
            continue
        loose = [r for r in _spoken(ctx, ctx.built_fid(f'{info.fid:08X}')) if not _gated(r)]
        if loose:
            ungated[_quest_of(ctx, info)] += [f'{info.fid:08X} in {_name(ctx.index, r.parent_dial)}' for r in loose]
    return [Finding('dialogue', f'dialogue|{ctx.game}|greeting-gate|{quest}', 'error',
                    f'{quest}: {len(rows)} GREETING lines lack IsInDialogueWithPlayer, so they are barked on approach too',
                    tuple(rows[:SAMPLES]))
            for quest, rows in sorted(ungated.items())]


def _topic_quests(ctx) -> dict:
    """{source topic: {quest EditorIDs its lines belong to}}."""
    out = defaultdict(set)
    for info in ctx.source.infos.values():
        out[info.dial].add(_quest_of(ctx, info))
    return out


def reply_topic_findings(ctx) -> list:
    """One error per quest whose Fallout reply topics (not Top-level, never added) open a menu branch."""
    src = ctx.source
    if not src.fallout:
        return []
    quests, opened = _topic_quests(ctx), defaultdict(list)
    for fid, (edid, dtype, flags) in src.dials.items():
        if (dtype == _PLAYER_TOPIC and not flags & _TOP_LEVEL and edid.upper() != _GREETING
                and fid not in src.external_topics and fid in ctx.source_topics
                and ctx.built_fid(f'{fid:08X}') in ctx.dialogue.open_starts):
            for quest in quests.get(fid, {'no quest'}):
                opened[quest].append(edid or f'{fid:08X}')
    return [Finding('dialogue', f'dialogue|{ctx.game}|reply-top-level|{quest}', 'error',
                    f'{quest}: {len(topics)} reply topics open a menu branch, so their lines show out of order',
                    tuple(sorted(topics)[:SAMPLES]))
            for quest, topics in sorted(opened.items())]


def _info_stages(src) -> dict:
    """{source INFO FormID: {(quest, stage)}} its result scripts set."""
    out = defaultdict(set)
    for s in src.setters:
        if s.kind == 'info' and isinstance(s.stage, int):
            out[int(s.owner, 16)].add((s.quest, s.stage))
    return out


def tree_stages(info, by_dial: dict, own: dict) -> set:
    """{(quest, stage)} the replies below a line set, breadth first to _MAX_DEPTH."""
    found, seen, level = set(), set(), list(info.choices)
    for _depth in range(_MAX_DEPTH):
        nxt = []
        for dial in (d for d in level if d not in seen):
            seen.add(dial)
            for reply in by_dial.get(dial, ()):
                found |= own.get(reply.fid, set())
                nxt += reply.choices
        level = nxt
    return found


def _still_say_once(ctx, info) -> bool:
    """Whether the built line kept Say Once (ENAM flags)."""
    rec = ctx.index.by_fid.get(ctx.built_fid(f'{info.fid:08X}'))
    enam = first(rec, 'ENAM') if rec is not None else b''
    return len(enam) >= 2 and bool(struct.unpack_from('<H', enam)[0] & SAY_ONCE)


def say_once_tree_findings(ctx) -> list:
    """One review per quest whose Say Once lines lead to stage-setting replies and stay Say Once."""
    src, by_dial, lost = ctx.source, defaultdict(list), defaultdict(list)
    for info in src.infos.values():
        by_dial[info.dial].append(info)
    own = _info_stages(src)
    for info in src.infos.values():
        if (info.flags & SAY_ONCE and info.choices and src.dials.get(info.dial, ('', -1))[1] == _PLAYER_TOPIC
                and info.dial in ctx.source_topics and _still_say_once(ctx, info)):
            stages = tree_stages(info, by_dial, own)
            if stages:
                lost[_quest_of(ctx, info)].append(
                    f'{info.fid:08X} -> ' + ', '.join(f'{q} {n}' for q, n in sorted(stages)))
    return [Finding('dialogue', f'dialogue|{ctx.game}|say-once-tree|{quest}', 'review',
                    f'{quest}: {len(rows)} Say Once lines lead to replies that set a stage; '
                    'leaving the talk mid-tree loses it (the line\'s own script is unsafe to rerun)',
                    tuple(rows[:SAMPLES]))
            for quest, rows in sorted(lost.items())]


def audit(ctx) -> list:
    """The dialogue engine rule findings for one game."""
    return (scene_original_findings(ctx.game, ctx.index, ctx.dialogue) + greeting_gate_findings(ctx)
            + reply_topic_findings(ctx) + say_once_tree_findings(ctx))
