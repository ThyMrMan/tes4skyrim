"""FO3/FNV TERM: a terminal's welcome text, lock, password note and menu items.

After the activator fields come DESC (welcome text), SNAM (looping sound),
PNAM (password note) and DNAM (hacking difficulty, flags, server type), then
one run per menu item: ITXT item text, RNAM result text, ANAM flags, INAM
display note, TNAM sub-menu, an embedded script (SCHR SCDA SCTX, locals,
SCRO/SCRV) and CTDA conditions (xEdit wbDefinitionsFO3/FNV TERM). An item is
written as `Item[i].<field>`.

See: docs/commentary/tes4_export_falloutnv.md#terminals
"""

import struct

from ..tes4_reader import Record, get_formid_str, get_string, get_subrecord
from .common import emit_formid, emit_string, escape_value

#: An item's string subrecords -> field name.
_ITEM_TEXT = {'ITXT': 'Text', 'RNAM': 'Result'}

#: An item's FormID subrecords -> field name; SCRO is numbered in order instead.
_ITEM_FORMIDS = {'INAM': 'Note', 'TNAM': 'SubMenu', 'SCRO': ''}


def _starts_item(sig: str, item: dict) -> bool:
    """Whether `sig` opens an item: an ITXT, or an RNAM after a whole item."""
    return sig == 'ITXT' or (sig == 'RNAM' and (item is None or 'Result' in item))


def _numbered(item: dict, name: str) -> str:
    """`name[n]` for the item's next numbered field of that name."""
    n = item.get(f'_{name}', 0)
    item[f'_{name}'] = n + 1
    return f'{name}[{n}]'


def _item_field(item: dict, sub) -> None:
    """Record one item subrecord in `item` under its export field name."""
    if sub.type in _ITEM_TEXT:
        item[_ITEM_TEXT[sub.type]] = escape_value(get_string(sub))
        return
    if sub.type == 'ANAM' and sub.data:
        item['Flags'] = str(sub.data[0])
        return
    if sub.type == 'SCTX':
        item['Script'] = escape_value(get_string(sub))
        return
    if sub.type == 'CTDA':
        item[_numbered(item, 'Condition') + '.Raw'] = sub.data.hex()
        return
    if sub.type in _ITEM_FORMIDS and sub.data[:4].strip(b'\0'):
        name = _ITEM_FORMIDS[sub.type] or _numbered(item, 'SCRO')
        item[name] = get_formid_str(struct.unpack_from('<I', sub.data, 0)[0])


def _items(rec: Record) -> list:
    """Each menu item's fields, walked in stream order."""
    items, item = [], None
    for sub in rec.subrecords:
        if sub.type in ('ITXT', 'RNAM') and _starts_item(sub.type, item):
            item = {}
            items.append(item)
        if item is not None:
            _item_field(item, sub)
    return items


def emit_terminal(lines: list, rec: Record) -> None:
    """Append a TERM's welcome text, sound, password note, lock data and menu items."""
    emit_string(lines, 'DESC', get_subrecord(rec, 'DESC'))
    emit_formid(lines, 'SNAM', get_subrecord(rec, 'SNAM'))
    emit_formid(lines, 'PNAM', get_subrecord(rec, 'PNAM'))
    dnam = get_subrecord(rec, 'DNAM')
    if dnam and len(dnam.data) >= 3:
        lines += [f'DNAM.Difficulty={dnam.data[0]}', f'DNAM.Flags={dnam.data[1]}', f'DNAM.Server={dnam.data[2]}']
    items = _items(rec)
    lines.append(f'ItemCount={len(items)}')
    for i, item in enumerate(items):
        lines += [f'Item[{i}].{k}={v}' for k, v in item.items() if not k.startswith('_')]
