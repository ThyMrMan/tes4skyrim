"""A greeting that leads on is said from a Blocking topic; every spoken greeting is a shared copy."""

import struct

from tes5_import.base.tes5_reader import subrecords
from tes5_import.base.writer import PluginWriter, pack_record, pack_subrecord
from tes5_import.dialogue.arrest import info_records
from tes5_import.dialogue.greeting_choices import shared_greetings

_QUEST = 0x01014E84
_GREETING = 0x019EF665


def _info(fid: int, *tclt: int) -> bytes:
    """A packed INFO with one GetIsID condition and the given TCLT links."""
    subs = b''.join(pack_subrecord('TCLT', struct.pack('<I', t)) for t in tclt)
    subs += pack_subrecord('NAM1', b'line\x00')
    subs += pack_subrecord('CTDA', struct.pack('<B3xfHHIIIIi', 0, 1.0, 72, 0, 0x010300E9, 0, 0, 0, -1))
    return pack_record('INFO', fid, 0, subs)


def _split(ctx: dict):
    """shared_greetings over Amata's reply greeting and a plain greeting."""
    writer = PluginWriter([])
    writer.reserve_source_ids(set())
    group = {'src': {'EditorID': 'GREETING'}, 'cat': 1, 'snam': b'HELO', 'infos': [
        {'FormID': '010319BD', 'ChoiceCount': '1', 'Choice[0]': '010784A3'},
        {'FormID': '010784E0'}]}
    children = _info(0x010319BD, 0x010784A3) + _info(0x010784E0)
    return shared_greetings(writer, (_QUEST, 1), group, (_GREETING, 'GREETING_01014E84'), children, ctx)


def _topics(content: bytes) -> dict:
    """{DIAL FormID: (SNAM, {original FormID or own FormID: subrecords})} of the emitted topics."""
    out, pos = {}, 0
    while pos < len(content):
        size, _flags, fid = struct.unpack_from('<III', content, pos + 4)
        snam = dict(subrecords(content[pos + 24:pos + 24 + size]))[b'SNAM']
        group = content[pos + 24 + size:]
        glen = struct.unpack_from('<I', group, 4)[0]
        infos = {}
        for ifid, _f, body in info_records(group[24:glen]):
            subs = list(subrecords(body))
            infos[struct.unpack('<I', dict(subs)[b'DNAM'])[0] if b'DNAM' in dict(subs) else ifid] = subs
        out[fid] = (snam, infos)
        pos += 24 + size + glen
    return out


def test_greetings_split_into_held_originals_and_spoken_copies():
    """Originals held in IDAT; the reply line copied into Blocking with its link, the plain one into Hello.

    See: docs/commentary/tes5_import_dialogue.md#greeting-choices-block
    """
    content, dlbr, hello_fid = _split({'bark_dial_fids': {0xC8}, 'menu_topic_fids': set()})
    topics = _topics(content)
    assert topics[_GREETING][0] == b'IDAT'
    assert set(topics[_GREETING][1]) == {0x010319BD, 0x010784E0}
    assert set(topics[hello_fid][1]) == {0x010784E0}
    lead_fid = struct.unpack_from('<I', dlbr, len(dlbr) - 4)[0]
    assert set(topics[lead_fid][1]) == {0x010319BD}
    assert (b'TCLT', struct.pack('<I', 0x010784A3)) in topics[lead_fid][1][0x010319BD]


def test_a_greeting_whose_replies_are_all_menu_topics_stays_a_hello():
    """With every link a Top-Level topic the line keeps no link: nothing splits."""
    assert _split({'bark_dial_fids': {0xC8}, 'menu_topic_fids': {0x010784A3}}) is None
