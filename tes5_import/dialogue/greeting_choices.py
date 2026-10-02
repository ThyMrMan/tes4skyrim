"""A quest's greetings as vanilla shares lines: originals held, every spoken line a shared copy.

A Hello line cannot hold a menu, and a Blocking topic replaces the whole menu,
so only the greeting lines that lead on (a kept reply link or a follow-up) are
said from a Blocking topic, which Skyrim says before Hello; the rest are said
from Hello. A shared copy plays its original's responses and voice (by the
original's topic and FormID), and misplays when the original cannot pass, so
the originals stay whole in an unreachable Shared Info (IDAT) topic that keeps
the quest greeting's FormID and EditorID, as vanilla keeps all 3,411 of its
shared originals. Each line is then spoken from exactly one place. A force
greet opens the Blocking topic only for a speaker one of its lines names. A
Blocking line asks IsInDialogueWithPlayer, or Skyrim also says it as the
speaker's Hello on approach and again when the force greet opens the menu.

See: docs/commentary/tes5_import_dialogue.md#greeting-choices-block
"""

import struct

from ..base.conditions import build_ctda, read_getisid_fids
from ..base.writer import pack_group, pack_subrecord
from ..record_types.common import get_formid
from .arrest import info_records, shared_copy
from .converter import LEAD_SPEAKERS_BY_QUEST, LEAD_TOPIC_BY_QUEST, convert_DIAL, info_tclt
from .follow_ups_falloutnv import FOLLOW_UP_TOPICS, blocking_branch
from .greeting_order import order_greetings
from ..packages.conversations_falloutnv import LINE_SCENES

#: Greeting lines reordered this build: Goodbyes moved to Blocking, leading lines gated, pairs left as they were.
GREETING_ORDER_STATS = {'moved': 0, 'gated': 0, 'unordered': 0}

#: Vanilla's Shared Info topic shape: category Misc, subtype 84, SNAM IDAT.
_SHARED_INFO = (7, 84, b'IDAT')

#: LEAD_SPEAKERS_BY_QUEST entry for a leading line that names no speaker.
ANYONE = 0

#: TES5 IsInDialogueWithPlayer.
_FUNC_IN_DIALOGUE_WITH_PLAYER = 249

#: `IsInDialogueWithPlayer == 1`: a greeting line valid only in the dialogue menu, so never also barked on approach.
IN_DIALOGUE_MENU = pack_subrecord('CTDA', build_ctda(_FUNC_IN_DIALOGUE_WITH_PLAYER))


def leads_on(rec: dict, ctx: dict) -> bool:
    """Whether a greeting line continues: it has follow-ups or keeps a reply link."""
    return (get_formid(rec, 'FormID') in FOLLOW_UP_TOPICS
            or bool(info_tclt(rec, ctx.get('bark_dial_fids'), ctx.get('menu_topic_fids', ()))))


def _copies(writer, g, children: bytes, lead: set, offset: int) -> tuple:
    """(Hello copies, Blocking copies): leading lines to Blocking, valid only in the dialogue menu; the rest to Hello.

    A plain line above a leading one still wins ([greeting order](greeting_order.py)).
    """
    source = {get_formid(r, 'FormID'): r for r in g['infos']}
    infos = [(fid, flags, body) for fid, flags, body in info_records(children) if fid in source]
    moved, gates, unordered = order_greetings([(fid, body, source[fid], fid in lead) for fid, _f, body in infos],
                                              offset)
    GREETING_ORDER_STATS['moved'] += len(moved)
    GREETING_ORDER_STATS['gated'] += len(gates)
    GREETING_ORDER_STATS['unordered'] += unordered
    hello, blocking = [], []
    for fid, flags, body in infos:
        site = 'GREETING_LEAD_INFO' if fid in lead else 'GREETING_HELLO_INFO'
        copy = shared_copy(body, fid, writer.derive_formid(site, source[fid]['FormID']), flags,
                           gate=gates.get(fid, b''))
        (blocking if fid in lead or fid in moved else hello).append(copy)
    return hello, blocking


def topic_record(src: dict, fid: int, edid: str, quest: int, shape: tuple, infos: list, branch: int = 0) -> bytes:
    """One DIAL of `shape` (category, subtype, SNAM) and its group of packed INFO records."""
    count = sum(1 for chunk in infos for _rec in info_records(chunk))
    dial = convert_DIAL(src, info_count=count, dlbr_fid=branch, quest_fid=quest,
                        category=shape[0], subtype=shape[1], snam=shape[2],
                        edid_override=edid, formid_override=fid)
    children = b''.join(infos)
    return dial + (pack_group(7, struct.pack('<I', fid), children) if children else b'')


def scene_held(writer, key, g, topic: tuple, children: bytes):
    """(topics' bytes, live DIAL FormID) holding the group's originals in IDAT, or None when no scene copies a line.

    A scene's shared copy plays only from an original held where vanilla keeps
    all 727 of its scene originals, a Shared Info topic; the group's lines are
    then said from copies in a live topic of its own shape.
    See: docs/commentary/tes5_import_dialogue.md#fallout-conversation-scenes
    """
    if not any(get_formid(r, 'FormID') in LINE_SCENES for r in g['infos']):
        return None
    owner_qfid, subtype = key
    dial_fid, edid = topic
    source = {get_formid(r, 'FormID'): r['FormID'] for r in g['infos']}
    said = [shared_copy(body, fid, writer.derive_formid('SCENE_HELD_INFO', source[fid]), flags)
            for fid, flags, body in info_records(children) if fid in source]
    live = writer.derive_formid('SCENE_HELD_DIAL', key)
    return (topic_record(g['src'], dial_fid, edid, owner_qfid, _SHARED_INFO, [children])
            + topic_record(g['src'], live, f'{edid}_Said', owner_qfid, (g['cat'], subtype, g['snam']), said)), live


def _note_speakers(g, lead: set, quest: int, offset: int) -> None:
    """Record the speakers the quest's leading lines name, ANYONE for a line naming none."""
    speakers = LEAD_SPEAKERS_BY_QUEST.setdefault(quest, set())
    for rec in g['infos']:
        if get_formid(rec, 'FormID') in lead:
            speakers |= read_getisid_fids(rec, offset=offset, positive_only=True) or {ANYONE}


def shared_greetings(writer, key, g, topic: tuple, children: bytes, ctx: dict) -> tuple:
    """(topics' bytes, Blocking DLBR, Hello DIAL FormID or the Blocking one), or None with no lead.

    `topic` is the greeting's (FormID, EditorID), which the held originals keep.
    """
    owner_qfid, subtype = key
    dial_fid, edid = topic
    lead = {get_formid(r, 'FormID') for r in g['infos'] if leads_on(r, ctx)}
    if not lead:
        return None
    hello, blocking = _copies(writer, g, children, lead, ctx.get('offset', 0))
    content = topic_record(g["src"], dial_fid, edid, owner_qfid, _SHARED_INFO, [children])
    plain = len(lead) < len(g['infos'])
    hello_fid = writer.derive_formid('GREETING_HELLO_DIAL', key) if plain else 0
    if plain:
        content += topic_record(g["src"], hello_fid, f'{edid}_Hello', owner_qfid, (g['cat'], subtype, g['snam']), hello)
    lead_fid = writer.derive_formid('GREETING_LEAD_DIAL', key)
    branch, dlbr = blocking_branch(writer, key, f'{edid}_Lead', owner_qfid, lead_fid)
    content += topic_record(g["src"], lead_fid, f'{edid}_Lead', owner_qfid, (0, 0, b'CUST'), blocking, branch)
    LEAD_TOPIC_BY_QUEST[owner_qfid] = lead_fid
    _note_speakers(g, lead, owner_qfid, ctx.get('offset', 0))
    return content, dlbr, hello_fid or lead_fid
