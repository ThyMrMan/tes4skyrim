"""FO3/FNV talking activators as Skyrim TACTs: an activator the engine accepts as a dialogue speaker.

Fallout's intercoms, loudspeakers and Harold's tree speak quest lines gated on
their own GetIsID, and Skyrim's TACT does the same (vanilla's Augur). Written
as a plain ACTI they had no voice and could not speak at all.

See: docs/commentary/tes5_import_dialogue.md#fallout-talking-activators
"""

import struct

from ..base.owned_records import FALLOUT_VTYP_BY_SOURCE
from ..base.text_reader import get_formid, get_int, get_str
from ..base.writer import pack_formid_subrecord, pack_record, pack_string_subrecord, pack_subrecord
from .common import common_header_subs, prefix_path

#: Source TACT record flags Skyrim keeps: Random Anim Start (Fallout's other bits are radio and map flags).
_KEPT_FLAGS = 0x00010000


def tact_voice(rec: dict) -> int:
    """The written voice type of a source TACT's VNAM, or 0."""
    return FALLOUT_VTYP_BY_SOURCE.get(get_formid(rec, 'VNAM'), 0)


def convert_TACT(rec: dict) -> bytes:
    """One TACT in vanilla's order: EDID VMAD OBND FULL MODL PNAM SNAM FNAM VNAM.

    SNAM holds the source looping SOUN until the sound-descriptor patch.
    """
    subs = common_header_subs(rec, obnd_sig='TACT')
    path = get_str(rec, 'Model.MODL')
    if path:
        subs += pack_string_subrecord('MODL', prefix_path(path))
    subs += pack_subrecord('PNAM', struct.pack('<I', 0))
    if get_formid(rec, 'SNAM'):
        subs += pack_formid_subrecord('SNAM', get_formid(rec, 'SNAM'))
    subs += pack_subrecord('FNAM', struct.pack('<H', 0))
    if tact_voice(rec):
        subs += pack_formid_subrecord('VNAM', tact_voice(rec))
    return pack_record('TACT', get_formid(rec, 'FormID'), get_int(rec, 'RecordFlags') & _KEPT_FLAGS, subs)
