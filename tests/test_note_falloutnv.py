"""FO3/FNV notes: exported whole, carried as books, and tested as items by converted scripts.

See: docs/commentary/tes4_export_falloutnv.md#notes-are-items
"""
import struct

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
from tes4_export.record_types.falloutnv import export_NOTE
from tes4_export.tes4_reader import Record, Subrecord
from tes5_import.record_types.note_falloutnv import convert_NOTE, index_note_speakers

TEXT, VOICE = 1, 3


def _export(kind, tnam):
    """export_NOTE over a Beagle's-journal-like NOTE, as a record dict."""
    subs = [('EDID', b'VMQ01BeagleJournalNote\0'), ('FULL', b"Deputy Beagle's Journal\0"),
            ('DATA', bytes([kind])), ('TNAM', tnam), ('ONAM', struct.pack('<I', 0x104C1C))]
    lines = export_NOTE(Record('NOTE', 0, 0, 0x1618BF, [Subrecord(t, d) for t, d in subs]))
    rec = dict(line.split('=', 1) for line in lines)
    return dict(rec, FormID='001618BF', RecordFlags='0'), lines


def _subs(record: bytes) -> dict:
    """{subrecord: data} of a packed record."""
    out, pos = {}, 24
    while pos < len(record):
        size = struct.unpack_from('<H', record, pos + 4)[0]
        out[record[pos:pos + 4].decode()] = record[pos + 6:pos + 6 + size]
        pos += 6 + size
    return out


def test_a_text_note_exports_its_type_text_and_quest():
    """The note's type, text and quests all reach the export."""
    _rec, lines = _export(TEXT, b'Day 1. They came at night.\0')
    assert 'DATA.Type=1' in lines and 'TNAM.Text=Day 1. They came at night.' in lines
    assert 'Quest[0]=00104C1C' in lines


def test_a_note_becomes_a_book_the_player_reads():
    """The BOOK keeps the note's FormID; a text note reads as its text, a voice note as its name."""
    text, _lines = _export(TEXT, b'Day 1. They came at night.\0')
    voice, _lines = _export(VOICE, struct.pack('<I', 0x104C66))
    book = convert_NOTE(text)
    assert book[:4] == b'BOOK' and struct.unpack_from('<I', book, 12)[0] == 0x1618BF
    assert _subs(book)['DESC'].rstrip(b'\0') == b'Day 1. They came at night.'
    assert _subs(convert_NOTE(voice))['DESC'].rstrip(b'\0') == b"Deputy Beagle's Journal"


def test_note_commands_are_item_operations_on_the_player():
    """GetHasNote reads the player's count; AddNote and RemoveNote add and take the book."""
    src = ('scn T\nshort x\nbegin GameMode\n  if GetHasNote VMQ01BeagleJournalNote == 0\n'
           '    AddNote VMQ01BeagleJournalNote\n  endif\n  RemoveNote VMQ01BeagleJournalNote\nend\n')
    out = ScriptConverter(CrossRefGraph()).convert_standalone('T', src, 'Quest', 'T')
    assert 'Book Property VMQ01BeagleJournalNote Auto' in out
    assert 'If Game.GetPlayer().GetItemCount(VMQ01BeagleJournalNote) == 0' in out
    assert 'Game.GetPlayer().AddItem(VMQ01BeagleJournalNote, 1, False)' in out
    assert 'Game.GetPlayer().RemoveItem(VMQ01BeagleJournalNote, 1, True)' in out


def test_a_voice_note_plays_its_recording_as_its_speaker():
    """A voice note's book carries TES4_VoiceNote bound to its topic and its speaker's one placed ref."""
    index_note_speakers({'ACHR': [{'FormID': '000D7F59', 'NAME': '000D7F57'}]})
    voice, _lines = _export(VOICE, struct.pack('<I', 0x1618B4))
    vmad = _subs(convert_NOTE(dict(voice, SNAM='000D7F57')))['VMAD']
    assert b'TES4_VoiceNote' in vmad and b'Recording' in vmad and b'Speaker' in vmad
    assert struct.pack('<I', 0x1618B4) in vmad and struct.pack('<I', 0xD7F59) in vmad
    text, _lines = _export(TEXT, b'Day 1.\0')
    assert 'VMAD' not in _subs(convert_NOTE(dict(text, FormID='001618C0')))
