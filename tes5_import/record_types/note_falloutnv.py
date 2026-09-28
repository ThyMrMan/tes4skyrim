"""FO3/FNV NOTE: a Pip-Boy note, carried in Skyrim as a BOOK the player holds.

Quests test for a note in the player's inventory (converted `GetHasNote`), so
it must be an item; a text note reads as its text, any other kind as its name.
A voice note plays its recording when read.

See: docs/commentary/tes4_export_falloutnv.md#notes-are-items
"""

from collections import Counter

from ..base.text_reader import get_formid, remap_formid
from ..base.writer import pack_subrecord
from .common import get_int
from .equipment import convert_BOOK

#: NOTE DATA.Type Text: TNAM holds what the player reads.
_TEXT = 1

#: NOTE DATA.Type Voice: TNAM.Topic is the recording, SNAM its speaker.
_VOICE = 3

#: The static script a voice note's book carries.
VOICE_NOTE_SCRIPT = 'TES4_VoiceNote'

#: Actor base FormID (upper hex) -> its one placed reference, filled by index_note_speakers.
_SPEAKER_REFS: dict = {}


def index_note_speakers(by_type: dict) -> None:
    """Record each actor base placed exactly once, the speaker a voice note can bind."""
    counts = Counter((r.get('NAME') or '').upper() for sig in ('ACHR', 'ACRE')
                     for r in by_type.get(sig, ()))
    _SPEAKER_REFS.clear()
    _SPEAKER_REFS.update({(r.get('NAME') or '').upper(): r['FormID'] for sig in ('ACHR', 'ACRE')
                          for r in by_type.get(sig, ()) if counts[(r.get('NAME') or '').upper()] == 1})


def voice_note_vmad(rec: dict) -> bytes:
    """The packed VMAD playing a voice note's recording when read; b'' for other notes.

    script_convert is imported here, not at module scope: its pipeline
    imports the importer's dialogue package back, a cycle at load.
    See: docs/commentary/tes4_export_falloutnv.md#voice-notes-play-when-read
    """
    from script_convert.pipeline import build_vmad_object_script
    topic = rec.get('TNAM.Topic') or ''
    if get_int(rec, 'DATA.Type', _TEXT) != _VOICE or not int(topic or '0', 16):
        return b''
    props = {'Recording': remap_formid(int(topic, 16))}
    speaker = _SPEAKER_REFS.get((rec.get('SNAM') or '').upper())
    if speaker:
        props['Speaker'] = remap_formid(int(speaker, 16))
    return pack_subrecord('VMAD', build_vmad_object_script(VOICE_NOTE_SCRIPT, props))


def note_as_book(rec: dict) -> dict:
    """The NOTE as the book record convert_BOOK reads: weightless, worthless, readable."""
    text = rec.get('TNAM.Text', '') if get_int(rec, 'DATA.Type', _TEXT) == _TEXT else ''
    return {**rec, 'DESC': text or rec.get('FULL', ''), 'DATA.Value': '0', 'DATA.Weight': '0'}


def convert_NOTE(rec: dict, writer=None) -> bytes:
    """NOTE -> BOOK at the note's own FormID, a voice note carrying its player script.

    object_scripts is imported here: it imports script_convert.pipeline, a cycle.
    See: docs/reference/tes5_import_architecture.md#object-scripts-import-is-deferred
    """
    from ..base.object_scripts import set_object_vmad
    vmad = voice_note_vmad(rec)
    if vmad:
        set_object_vmad(get_formid(rec, 'FormID'), vmad)
    return convert_BOOK(note_as_book(rec), writer)
