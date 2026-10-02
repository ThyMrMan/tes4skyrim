"""FO3/FNV terminal menus as a Papyrus script extending TES4_Terminal.

The script answers TES4Pick for each of the terminal's pages: an item runs its
converted result script on the terminal, opens its note, shows its result
text, and opens its sub-menu; More opens the menu's next page; the last button
leaves. Each item's note and result message is a property named by its number
in the plan, which the importer binds.

See: docs/commentary/script_convert.md#terminals
"""

from script_convert.constants import script_prefix
from script_convert.converter import ScriptConverter
from script_convert.scro_refs import add_scro_ref, resolve_scro_aliases, scro_list
from script_convert.symbols import property_declarations
from script_convert.terminal_plan import plan_items, sub_menu, terminal_pages

#: TES4Pick results: leave the page, show it again.
LEAVE, STAY = -1, -2

#: Item flag Add Note: the displayed note goes to the player's inventory.
ADD_NOTE = 0x01

#: Names the parent script and the generated code already declare.
_TAKEN = {'tes4pages', 'tes4password', 'tes4difficulty', 'tes4locked'}


def terminal_script_name(formid: str) -> str:
    """The TM_ script name of the terminal with source FormID `formid`."""
    return f'{script_prefix("_TM__")}{formid.upper()}'


def _convert_items(menus: list, xref) -> tuple:
    """(converter, {item number: body lines}) for the items that run a script."""
    conv, bodies = ScriptConverter(xref), {}
    for k, (rec, i) in enumerate(plan_items(menus)):
        source = rec.get(f'Item[{i}].Script') or ''
        if not source.strip():
            continue
        refs = scro_list(rec, f'Item[{i}].')
        for fid in refs:
            add_scro_ref(conv, fid, xref)
        conv.set_scro_aliases(resolve_scro_aliases(source, refs, xref))
        bodies[k] = conv.convert_fragment(source, 'ObjectReference')
    return conv, bodies


def _item_lines(rec: dict, i: int, k: int, bodies: dict, first_page: dict) -> list:
    """The TES4Pick branch body for item number `k` (item `i` of `rec`)."""
    out = [f'    TES4Item{k}()'] if k in bodies else []
    if rec.get(f'Item[{i}].Note'):
        add = 'true' if int(rec.get(f'Item[{i}].Flags') or 0) & ADD_NOTE else 'false'
        out.append(f'    TES4Read(TES4Note{k}, {add})')
    if rec.get(f'Item[{i}].Result'):
        out.append(f'    TES4Result{k}.Show()')
    return out + [f'    Return {first_page.get(sub_menu(rec, i), STAY)}']


def _page_function(n: int, page, rec: dict, numbers: dict, bodies: dict, first_page: dict) -> list:
    """`Int Function TES4Page<n>(Int button)`: one branch per item, then More."""
    out = [f'Int Function TES4Page{n}(Int button)']
    for b, i in enumerate(page.items):
        out += [f'  {"If" if b == 0 else "ElseIf"} button == {b}']
        out += _item_lines(rec, i, numbers[(rec['FormID'].upper(), i)], bodies, first_page)
    if page.more:
        out += [f'  {"If" if not page.items else "ElseIf"} button == {len(page.items)}', f'    Return {n + 1}']
    if page.items or page.more:
        out.append('  EndIf')
    return out + [f'  Return {LEAVE}', 'EndFunction', '']


def _pick(pages: list) -> list:
    """The TES4Pick override dispatching to each page's function."""
    out = ['Int Function TES4Pick(Int page, Int button)']
    out += [f'  {"If" if n == 0 else "ElseIf"} page == {n}\n    Return TES4Page{n}(button)' for n in range(len(pages))]
    return out + ['  EndIf', f'  Return {LEAVE}', 'EndFunction', '']


def _declarations(menus: list, conv) -> list:
    """The note, result and converted-script property lines."""
    out = []
    for k, (rec, i) in enumerate(plan_items(menus)):
        out += [f'Book Property TES4Note{k} Auto'] if rec.get(f'Item[{i}].Note') else []
        out += [f'Message Property TES4Result{k} Auto'] if rec.get(f'Item[{i}].Result') else []
    taken = set(_TAKEN) | {line.split()[2].lower() for line in out}
    return out + property_declarations(dict(conv.sc.property_refs), taken)


def terminal_psc(menus: list, xref) -> str:
    """The Papyrus of one terminal's script; `menus` is terminal_plan.reachable_menus."""
    conv, bodies = _convert_items(menus, xref)
    pages = terminal_pages(menus)
    by_fid = {rec['FormID'].upper(): rec for rec in menus}
    first_page = {}
    for n, page in enumerate(pages):
        first_page.setdefault(page.term, n)
    numbers = {(rec['FormID'].upper(), i): k for k, (rec, i) in enumerate(plan_items(menus))}
    out = [f'ScriptName {terminal_script_name(menus[0]["FormID"])} extends TES4_Terminal', '']
    out += _declarations(menus, conv) + [''] + _pick(pages)
    for n, page in enumerate(pages):
        out += _page_function(n, page, by_fid[page.term], numbers, bodies, first_page)
    for k, body in sorted(bodies.items()):
        out += [f'Function TES4Item{k}()'] + body + ['EndFunction', '']
    return '\n'.join(out + conv.get_cell_family_helpers())


def terminal_property_refs(menus: list, xref) -> dict:
    """{property: Papyrus type} the terminal's script declares from its item scripts."""
    return dict(_convert_items(menus, xref)[0].sc.property_refs)
