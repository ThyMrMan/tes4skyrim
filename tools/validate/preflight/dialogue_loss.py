"""Dialogue lines the source game can say and the build cannot, ranked by who loses them.

A line counts when the source can say it: its topic is reachable and a placed
actor passes its GetIsID conditions. It is lost when the built INFO is missing,
its topic is unreachable in Skyrim, or no placed actor can speak it. Losses are
grouped by the named speaker, or by the line's quest when anyone may say it,
so the NPCs who lost the most show first.

Skyrim also honors one topic of each bark subtype per owning quest; a quest
with two keeps only one of them speaking.

See: docs/commentary/tools_preflight.md#dialogue-loss
"""

import re
from collections import Counter, defaultdict

from tools.validate.preflight.findings import Finding
from tools.validate.preflight.plugin_index import first, u32, zstring
from tools.validate.preflight.quest_source import required_speakers, speakable

#: Topic subtypes a player picks or a scene plays, which the one-per-quest rule does not cover.
_CHOSEN_SUBTYPES = ('CUST', 'SCEN', '')

#: Source DIAL DATA.Type names, the same in Oblivion, Fallout 3 and New Vegas up to Radio.
TOPIC_TYPES = {0: 'Topic', 1: 'Conversation', 2: 'Combat', 3: 'Persuasion', 4: 'Detection',
               5: 'Service', 6: 'Miscellaneous', 7: 'Radio'}

#: Topics and sample lines listed per finding.
SAMPLES = 5


def bark_findings(game: str, index) -> list:
    """One error per (quest, bark subtype) that owns more than one topic."""
    groups = defaultdict(list)
    for rec in index.by_type['DIAL']:
        subtype = zstring(first(rec, 'SNAM'))[:4]
        if subtype not in _CHOSEN_SUBTYPES:
            groups[(u32(first(rec, 'QNAM')), subtype)].append(index.edid(rec.form_id) or f'{rec.form_id:08X}')
    return [Finding('dialogue', f'dialogue|{game}|bark|{index.edid(quest) or f"{quest:08X}"}|{subtype}', 'error',
                    f'{index.edid(quest) or f"{quest:08X}"} owns {len(topics)} {subtype} topics; '
                    'Skyrim honors only one, so the others never speak', tuple(sorted(topics)[:SAMPLES]))
            for (quest, subtype), topics in sorted(groups.items()) if len(topics) > 1]


def lost_lines(ctx) -> list:
    """[(source INFO, reason)] for lines the source can say that the build cannot.

    The reason names the source topic's type, so a whole type the converter
    drops (conversations, radio) reads as one cause.
    """
    out = []
    for info in ctx.source.infos.values():
        if info.dial not in ctx.source_topics or not speakable(info.conditions, ctx.source.present):
            continue
        reason = ctx.dialogue.reachable_info(ctx.built_fid(f'{info.fid:08X}'))
        if reason:
            kind = TOPIC_TYPES.get(ctx.source.dials.get(info.dial, ('', 0))[1], 'unknown')
            via = ', which the source reaches through LinkFrom' if info.link_from and 'topic' in reason else ''
            out.append((info, f'{reason}{via} (source {kind} topic)'))
    return out


def _speakers(info, ctx) -> list:
    """The named speakers a line is for, or its quest when anyone may say it."""
    names = [ctx.source.actor_names.get(fid, f'{fid:08X}') for fid in required_speakers(info.conditions) or ()
             if fid in ctx.source.present]
    if names:
        return [('npc', name) for name in names]
    return [('anyone', ctx.source.quest_fids.get(info.quest, 'no quest'))]


def speaker_findings(ctx, lost: list) -> list:
    """One error per speaker, or per quest for lines anyone may say, most lines lost first."""
    groups = defaultdict(list)
    for info, reason in lost:
        topic = ctx.source.dials.get(info.dial, ('?',))[0]
        for kind, name in _speakers(info, ctx):
            groups[(kind, name)].append((topic, re.sub(r'topic \S+ ', 'topic ', reason)))
    out = []
    for (kind, name), rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        why = Counter(reason for _t, reason in rows).most_common(3)
        topics = Counter(topic for topic, _r in rows).most_common(SAMPLES)
        who = name if kind == 'npc' else f'lines anyone may say in {name}'
        out.append(Finding('dialogue', f'dialogue|{ctx.game}|{kind}|{name}', 'error',
                           f'{who} lost {len(rows)} dialogue lines',
                           tuple(f'{n} x {r}' for r, n in why)
                           + (f'topics: {", ".join(f"{t} ({n})" for t, n in topics)}',)))
    return out


def audit(ctx) -> list:
    """The dialogue loss findings for one game."""
    return speaker_findings(ctx, lost_lines(ctx)) + bark_findings(ctx.game, ctx.index)
