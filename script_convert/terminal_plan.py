"""A FO3/FNV terminal's menus as message pages, planned alike for the importer and the script converter.

A terminal and every sub-menu it reaches (`Item[i].SubMenu`, breadth first)
are its menus. A menu of up to nine items is one page: its items, then a
button that leaves it. A longer menu splits into pages of eight items, each
with More and leave buttons, since Message.Show returns buttons 0 to 9.

See: docs/commentary/script_convert.md#terminals
"""

from dataclasses import dataclass

from tes5_import.base.text_reader import get_int

#: Buttons one message can show: Show() returns 0 to 9.
MAX_BUTTONS = 10

#: The leave button on the terminal's first page, and on every other page.
EXIT, BACK = 'Exit', 'Back'

#: The button that turns to a menu's next page.
MORE = 'More'


@dataclass(frozen=True)
class Page:
    """One message page: the TERM it lists (FormID, upper hex), its item indexes, and whether More follows."""

    term: str
    items: tuple
    more: bool


def item_count(rec: dict) -> int:
    """The number of menu items a TERM has."""
    return max(get_int(rec, 'ItemCount'), 0)


def menu_pages(rec: dict) -> list:
    """The pages one TERM's own items fill."""
    fid, count = rec['FormID'].upper(), item_count(rec)
    if count < MAX_BUTTONS:
        return [Page(fid, tuple(range(count)), False)]
    size = MAX_BUTTONS - 2
    return [Page(fid, tuple(range(s, min(s + size, count))), s + size < count) for s in range(0, count, size)]


def sub_menu(rec: dict, item: int) -> str:
    """The FormID (upper hex) of the TERM an item opens, or ''."""
    return (rec.get(f'Item[{item}].SubMenu') or '').upper()


def reachable_menus(root: dict, terms: dict) -> list:
    """The root TERM, then every TERM its items open, breadth first; `terms` is {FormID upper: record}."""
    order, seen = [root], {root['FormID'].upper()}
    for rec in order:
        for fid in (sub_menu(rec, i) for i in range(item_count(rec))):
            if fid in terms and fid not in seen:
                seen.add(fid)
                order.append(terms[fid])
    return order


def terminal_pages(menus: list) -> list:
    """Every page of a terminal's menus, in order; page 0 is the terminal's own first."""
    return [page for rec in menus for page in menu_pages(rec)]


def plan_items(menus: list) -> list:
    """[(record, item index)] of a terminal's items; an item's number is its position."""
    return [(rec, i) for rec in menus for i in range(item_count(rec))]


def sub_menus(terms) -> set:
    """FormIDs (upper hex) of the TERMs another TERM's item opens."""
    return {sub_menu(rec, i) for rec in terms for i in range(item_count(rec))} - {''}


def page_edid(rec: dict, page: Page) -> str:
    """The MESG EditorID of one page of a TERM."""
    return f"TES4Term_{rec.get('EditorID') or rec['FormID']}_{page.items[0] if page.items else 0:02d}"


def result_edid(rec: dict, item: int) -> str:
    """The MESG EditorID showing one item's result text."""
    return f"TES4TermResult_{rec.get('EditorID') or rec['FormID']}_{item:02d}"


def item_text(rec: dict, item: int) -> str:
    """An item's button text: its item text, else its result text."""
    return rec.get(f'Item[{item}].Text') or rec.get(f'Item[{item}].Result') or '...'
