"""FO3/FNV terminals: each menu page and result text as a MESG, and the terminal's script bound on its ACTI.

A TERM converts as an ACTI (its model and name). Its menus become message
pages (script_convert.terminal_plan): one button per item, carrying the
item's converted conditions, then More and a leave button. The terminal's TM_
script, appended to any object script the ACTI already carries, runs the
items; this module binds its pages, lock, password note, notes, result
messages and the records its item scripts name. It runs last in the import,
patching the written ACTIs, so the messages' hashed FormIDs never displace
another generated record's.

See: docs/commentary/script_convert.md#terminals
"""

import struct

from script_convert.terminal_plan import (BACK, EXIT, MORE, item_count, item_text, menu_pages, page_edid,
                                          plan_items, reachable_menus, result_edid, sub_menus)
from ..base.conditions import convert_ctda_list_with_strings
from ..base.owned_records import WELL_KNOWN_PROPERTIES
from ..base.text_reader import get_formid, get_int, remap_formid
from ..base.writer import pack_record, pack_string_subrecord, pack_subrecord

#: Message box text past this many characters crashes the game (CK wiki, Message); longer text is cut.
MAX_TEXT = 1000

#: MESG DNAM flag Message Box: shown as a dialog that waits for a button.
_MESSAGE_BOX = 1

#: TERM DNAM flag Unlocked.
_UNLOCKED = 0x02

#: Bytes of a record header, and of a subrecord header before its data.
_RECORD_HEADER, _SUB_HEADER = 24, 6


def _text(value: str) -> str:
    """Message text cut to what a message box can show."""
    return value if len(value) <= MAX_TEXT else value[:MAX_TEXT - 3] + '...'


def _button(label: str, conditions: list = ()) -> bytes:
    """One menu button: its text, then the conditions that show it."""
    subs = pack_string_subrecord('ITXT', label)
    for ctda, cis2 in conditions:
        subs += pack_subrecord('CTDA', ctda)
        if cis2:
            subs += pack_string_subrecord('CIS2', cis2)
    return subs


def _message(writer, edid: str, text: str, buttons: bytes = b'') -> int:
    """Write a message-box MESG keyed by its EditorID; returns its FormID."""
    fid = writer.derive_formid('TERMINAL_MESG', edid)
    subs = pack_string_subrecord('EDID', edid) + pack_string_subrecord('DESC', _text(text))
    subs += pack_subrecord('INAM', struct.pack('<I', 0)) + pack_subrecord('DNAM', struct.pack('<I', _MESSAGE_BOX))
    writer.add_record('MESG', pack_record('MESG', fid, 0, subs + buttons))
    return fid


def _write_pages(writer, rec: dict, script_vars: dict, opened: bool) -> dict:
    """Write one TERM's pages and result messages; {EditorID: FormID}. An `opened` TERM is another's sub-menu."""
    made, text = {}, rec.get('DESC') or rec.get('FULL') or ''
    for n, page in enumerate(menu_pages(rec)):
        buttons = b''.join(_button(item_text(rec, i), convert_ctda_list_with_strings(
            rec, script_vars, prefix=f'Item[{i}].')) for i in page.items)
        buttons += _button(MORE) if page.more else b''
        buttons += _button(EXIT if not opened and n == 0 else BACK)
        made[page_edid(rec, page)] = _message(writer, page_edid(rec, page), text, buttons)
    for i in range(item_count(rec)):
        if rec.get(f'Item[{i}].Result'):
            made[result_edid(rec, i)] = _message(writer, result_edid(rec, i), rec[f'Item[{i}].Result'])
    return made


def _item_props(menus: list, messages: dict) -> dict:
    """{property: FormID} of each item's note and result message, by the item's plan number."""
    props = {}
    for k, (rec, i) in enumerate(plan_items(menus)):
        if rec.get(f'Item[{i}].Note'):
            props[f'TES4Note{k}'] = remap_formid(int(rec[f'Item[{i}].Note'], 16))
        if rec.get(f'Item[{i}].Result'):
            props[f'TES4Result{k}'] = messages[result_edid(rec, i)]
    return props


def _subrecords(blob: bytes) -> list:
    """[(signature, data)] of a packed, uncompressed record."""
    out, pos = [], _RECORD_HEADER
    while pos + _SUB_HEADER <= len(blob):
        size = struct.unpack_from('<H', blob, pos + 4)[0]
        out.append((blob[pos:pos + 4].decode('latin-1'), blob[pos + _SUB_HEADER:pos + _SUB_HEADER + size]))
        pos += _SUB_HEADER + size
    return out


def with_script(blob: bytes, script: tuple) -> bytes:
    """A packed record with (name, object props, value props) appended to its VMAD, which follows EDID.

    script_convert.pipeline is imported here: it imports the importer's
    dialogue package, a cycle at load.
    """
    from script_convert.pipeline import append_vmad_object_script
    subs = _subrecords(blob)
    old = next((d for sig, d in subs if sig == 'VMAD'), b'')
    vmad = pack_subrecord('VMAD', append_vmad_object_script(old, *script))
    rest = [pack_subrecord(sig, d) for sig, d in subs if sig != 'VMAD']
    at = 1 if subs and subs[0][0] == 'EDID' else 0
    body = b''.join(rest[:at]) + vmad + b''.join(rest[at:])
    return blob[:4] + struct.pack('<I', len(body)) + blob[8:_RECORD_HEADER] + body


def _script(root: dict, menus: list, messages: dict, xref) -> tuple:
    """(name, object props, value props) of the root terminal's TM_ script.

    script_convert.terminal_scripts and the dialogue converter are imported
    here, not at module scope: script_convert imports the importer's dialogue
    package, a cycle at load.
    """
    from script_convert.terminal_scripts import terminal_property_refs, terminal_script_name
    from ..dialogue.converter import bind_script_properties
    props = bind_script_properties(terminal_property_refs(menus, xref), xref, WELL_KNOWN_PROPERTIES)
    props.update(_item_props(menus, messages))
    if root.get('PNAM'):
        props['TES4Password'] = remap_formid(int(root['PNAM'], 16))
    values = {'TES4Pages': ('objects', [messages[page_edid(m, p)] for m in menus for p in menu_pages(m)]),
              'TES4Difficulty': ('int', get_int(root, 'DNAM.Difficulty')),
              'TES4Locked': ('bool', not get_int(root, 'DNAM.Flags') & _UNLOCKED)}
    return terminal_script_name(root['FormID']), props, values


def build_terminals(by_type: dict, writer, xref, script_vars: dict) -> int:
    """Write every terminal's message pages and append each menu terminal's script to its written ACTI; the count."""
    terms = {r['FormID'].upper(): r for r in by_type.get('TERM', ())}
    roots, opened = [r for r in terms.values() if item_count(r)], sub_menus(terms.values())
    messages = {}
    for fid, rec in terms.items():
        messages.update(_write_pages(writer, rec, script_vars, fid in opened))
    scripts = {get_formid(root, 'FormID'): _script(root, reachable_menus(root, terms), messages, xref)
               for root in roots}

    def patch(blob: bytes) -> bytes:
        """The ACTI with its terminal's script appended, or unchanged."""
        script = scripts.get(struct.unpack_from('<I', blob, 12)[0])
        return with_script(blob, script) if script else blob
    return writer.patch_records('ACTI', patch)
