"""Greetings whose player replies the build never offers, grouped by quest.

A source GREETING or HELLO line with Choices into player topics opens a menu
of replies (Choices into Conversation topics are another NPC's answer). Skyrim
closes a Hello line before any menu, so a reply shows only when the line (or a
shared copy of it) is spoken from a reachable non-Hello topic that keeps the
link, or when the reply is a menu topic of its own. A reply with neither is
never offered, and whatever the source gated behind it is lost.

See: docs/commentary/tools_preflight.md#greeting-replies
"""

from collections import defaultdict

from tools.validate.preflight.findings import Finding
from tools.validate.preflight.plugin_index import every, u32
from tools.validate.preflight.quest_source import required_speakers, speakable

#: Source topic EditorIDs whose lines greet the player when a conversation opens.
GREETING_TOPICS = ('GREETING', 'HELLO')

#: Source DIAL DATA.Type of a topic the player picks; type 1 replies are NPC-to-NPC conversation.
PLAYER_TOPIC = 0

#: Sample greetings listed per finding.
SAMPLES = 5


def source_greetings(ctx) -> list:
    """Source greeting lines with replies that the source can say."""
    src = ctx.source
    return [info for info in src.infos.values()
            if info.choices and info.dial in ctx.source_topics
            and src.dials.get(info.dial, ('',))[0].upper() in GREETING_TOPICS
            and speakable(info.conditions, src.present)]


def links_after(ctx, info) -> set:
    """Built topics linked from wherever the greeting is spoken outside a Hello topic."""
    dlg = ctx.dialogue
    built = ctx.built_fid(f'{info.fid:08X}')
    spoken = [ctx.index.by_fid.get(built)] + dlg.shared.get(built, [])
    return {u32(d) for rec in spoken
            if rec is not None and rec.type == 'INFO' and rec.parent_dial in dlg.live
            and dlg.subtype.get(rec.parent_dial) != 'HELO' for d in every(rec, 'TCLT')}


def player_replies(ctx, info, spoken: set) -> list:
    """The greeting's Choices into player topics (source type 0) holding a line; the source hides empty ones."""
    return [t for t in info.choices if t in spoken and ctx.source.dials.get(t, ('', -1))[1] == PLAYER_TOPIC]


def reply_modes(ctx, info, spoken: set) -> dict:
    """{source player reply topic: 'after', 'menu', 'none' or 'missing'}; `spoken` = source topics with lines."""
    after = links_after(ctx, info)
    out = {}
    for topic in player_replies(ctx, info, spoken):
        built = ctx.built_fid(f'{topic:08X}')
        rec = ctx.index.by_fid.get(built)
        out[topic] = ('missing' if rec is None or rec.type != 'DIAL'
                      else 'after' if built in after
                      else 'menu' if built in ctx.dialogue.open_starts else 'none')
    return out


def _sample(ctx, info, topics: list) -> str:
    """`speaker: greeting FormID -> reply topics` for one greeting."""
    src = ctx.source
    speakers = ', '.join(src.actor_names.get(f, f'{f:08X}') for f in required_speakers(info.conditions) or ())
    names = ', '.join(src.dials.get(t, (f'{t:08X}',))[0] or f'{t:08X}' for t in topics)
    return f'{speakers or "anyone"}: {info.fid:08X} -> {names}'


#: Finding wording per unshown mode: a built topic nothing offers, or a reply topic the build lacks.
_WHY = {'none': 'replies the build has but never shows', 'missing': 'replies whose topic the build lacks'}


def audit(ctx) -> list:
    """One error per (quest, why) whose greetings offer player replies the build never shows."""
    lost = defaultdict(list)
    spoken = {i.dial for i in ctx.source.infos.values()}
    for info in source_greetings(ctx):
        modes = reply_modes(ctx, info, spoken)
        for why in _WHY:
            unshown = [t for t, mode in modes.items() if mode == why]
            if unshown:
                lost[(ctx.source.quest_fids.get(info.quest, 'no quest'), why)].append((info, unshown))
    return [Finding('dialogue', f'dialogue|{ctx.game}|greeting-replies|{why}|{quest}', 'error',
                    f'{quest}: {len(rows)} greeting lines offer {sum(len(u) for _i, u in rows)} {_WHY[why]}',
                    tuple(_sample(ctx, info, unshown) for info, unshown in rows[:SAMPLES]))
            for (quest, why), rows in sorted(lost.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
