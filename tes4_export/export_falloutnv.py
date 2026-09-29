"""
FO3/FNV export: the whole-file context its record exporters need.

Some FO3/FNV fields cannot be read from a record alone. LTEX names its texture
through a TNAM pointing at a TXST, so the TXST group has to be indexed before
any LTEX can be formatted. That is a property of the FILE, not of a record
type, so it lives beside export.py rather than in record_types/.

See: docs/commentary/tes4_export_falloutnv.md#ltex-moved-its-texture-to-a-txst
"""

import struct

from .record_types.common import escape_value
from .record_types.falloutnv import (EFFECT_TYPES, FALLOUT_BASE_EXPORTERS,
                                     MGEF_EDITOR_IDS, SUPERSEDED_ACTOR_KEYS,
                                     SUPERSEDED_EFFECT_KEYS, export_deltas)
from .record_types.quest_falloutnv import SUPERSEDED_QUEST_KEYS
from .tes4_reader import Record, get_string, get_subrecord, read_group_records

#: TXST FormID -> its TX00 diffuse path, rebuilt per source file.
_TEXTURE_SETS = {}

#: Source path whose TXST records this process has already indexed.
_INDEXED_SOURCE = [None]

#: TES4-layout CSTY keys; FO3/FNV lay CSTD and CSAD out differently, so they would be misread.
_TES4_COMBAT_STYLE_KEYS = ("CSTD.", "CSAD.")

#: LTEX ICON is relative to Textures\\Landscape\\; FO3/FNV TX00 spells that prefix out.
_LANDSCAPE_PREFIX = 'landscape' + chr(92)


def base_exporter(sig: str):
    """The exporter for a FO3/FNV-only base-object type, or None."""
    return FALLOUT_BASE_EXPORTERS.get(sig)


def superseded_keys(rec: Record) -> tuple:
    """KEY= prefixes format_record drops, this game re-emitting them itself."""
    if rec.type in ("CREA", "NPC_"):
        return SUPERSEDED_ACTOR_KEYS
    if rec.type in EFFECT_TYPES:
        return SUPERSEDED_EFFECT_KEYS
    if rec.type == "QUST":
        return SUPERSEDED_QUEST_KEYS
    if rec.type == "CSTY":
        return _TES4_COMBAT_STYLE_KEYS
    return ()


def export_lines(rec: Record) -> list:
    """Every FO3/FNV-only line for one record: its deltas, plus LTEX's texture."""
    lines = []
    if rec.type == "LTEX":
        icon = _ltex_icon_path(rec)
        if icon:
            lines.append(f"ICON={escape_value(icon)}")
    lines.extend(export_deltas(rec))
    return lines


def prepare_source(mm, size: int, hdr_size: int, source_path: str) -> None:
    """Index this file's TXST records once per process, from its own mmap.

    Export workers are spawned with no initializer and never receive the
    parent's globals, so each builds the index itself.  MGEF is indexed here
    too: an FO3/FNV effect names its MGEF by FormID, and the import keys its
    effect registry on the EditorID.
    """
    if _INDEXED_SOURCE[0] == source_path:
        return
    _TEXTURE_SETS.clear()
    for rec in read_group_records(mm, size, hdr_size, b'TXST'):
        tx00 = get_subrecord(rec, 'TX00')
        if tx00:
            _TEXTURE_SETS[rec.form_id] = get_string(tx00)
    MGEF_EDITOR_IDS.clear()
    for rec in read_group_records(mm, size, hdr_size, b'MGEF'):
        edid = get_subrecord(rec, 'EDID')
        if edid:
            MGEF_EDITOR_IDS[rec.form_id] = get_string(edid)
    _INDEXED_SOURCE[0] = source_path


def _ltex_icon_path(rec: Record) -> str:
    """The landscape texture a FO3/FNV LTEX names, in Oblivion's ICON form.

    Relative to Textures\\Landscape\\, which is what convert_LTEX
    expects; empty when the TNAM resolves to nothing.
    """
    tnam = get_subrecord(rec, 'TNAM')
    if not tnam or len(tnam.data) < 4:
        return ''
    path = _TEXTURE_SETS.get(struct.unpack_from('<I', tnam.data, 0)[0], '')
    normalized = path.replace('/', chr(92))
    if normalized.lower().startswith(_LANDSCAPE_PREFIX):
        return normalized[len(_LANDSCAPE_PREFIX):]
    return normalized
