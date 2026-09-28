"""The perk and trait menus of a Fallout game's character rules plugin.

The perks themselves are records of the converted plugin
(tes5_import.record_types.perk_falloutnv); this builds the table the rules'
Papyrus reads (each perk, its level, ranks, text and requirements) and the
message-box pages it shows, one button per perk, shown while a slot global
the script sets says the perk can be taken.

See: docs/commentary/character_rules.md#fallout-perks
"""
import struct

from tes5_import.base.writer import (pack_formid_subrecord, pack_record, pack_string_subrecord,
                                     pack_uint32_subrecord)
from tools.release.character_rules_records import Obj, build_glob, global_is

#: Perks per menu page; the page's More and Back buttons follow them.
PAGE = 8

#: The pages' prompts and buttons, and the confirmation after a perk's description.
PERK_PROMPT, TRAIT_PROMPT = 'Choose a perk.', 'Traits to choose: %.0f'
MORE_BUTTON, BACK_BUTTON, DONE_BUTTON = 'More', 'Back', 'Done'
CONFIRM_PROMPT, CONFIRM_BUTTONS = 'Take this one?', ('Take it', 'Back')

#: Papyrus arrays hold at most 128 elements.
PAPYRUS_ARRAY_MAX = 128

#: Requirement kinds the rules read: a S.P.E.C.I.A.L. stat, a skill, the level, the sex, a perk.
REQ_STAT, REQ_SKILL, REQ_LEVEL, REQ_SEX, REQ_PERK = range(5)

#: Fallout condition functions perk requirements use -> kind; GetPermanentActorValue reads a stat or skill.
_FUNCTIONS = {495: None, 70: REQ_SEX, 80: REQ_LEVEL, 449: REQ_PERK}

#: The S.P.E.C.I.A.L. actor values, 5 to 11.
_FIRST_STAT, _STATS = 5, 7

#: CTDA type bits: OR with the next condition; the comparison value is a global.
_OR, _USE_GLOBAL = 0x01, 0x04


def menu_entries(doc: dict) -> tuple:
    """(perks, traits): the level-up perks by level then name, and the playable traits by name."""
    perks = [p for p in doc.get('perks', []) if p['playable'] and not p['hidden'] and not p['trait']
             and p['level'] > 0]
    traits = [p for p in doc.get('perks', []) if p['trait'] and p['playable']]
    return sorted(perks, key=lambda p: (p['level'], p['name'])), sorted(traits, key=lambda p: p['name'])


def _requirement(raw: str, skills: dict, entries: dict) -> 'tuple | None':
    """(kind, index, operator, value, or) for one requirement condition, or None when the rules cannot read it."""
    data = bytes.fromhex(raw).ljust(28, b'\0')
    value, function, param = struct.unpack_from('<f', data, 4)[0], *struct.unpack_from('<HxxI', data, 8)
    kind = _FUNCTIONS.get(function, -1)
    index = 0
    if data[0] & _USE_GLOBAL or kind == -1:
        return None
    if kind is None and _FIRST_STAT <= param < _FIRST_STAT + _STATS:
        kind, index = REQ_STAT, param - _FIRST_STAT
    elif kind is None:
        kind, index = REQ_SKILL, skills.get(param, -1)
    elif kind == REQ_PERK:
        index = entries.get(param & 0xFFFFFF, -1)
    elif kind == REQ_SEX:
        index = param
    if index < 0:
        return None
    return kind, index, data[0] >> 5, value, data[0] & _OR


def perk_table(doc: dict, forms, skills: list) -> dict:
    """The rules' perk properties: forms, names, texts, levels, ranks, requirements and the first trait."""
    perks, traits = menu_entries(doc)
    entries = perks + traits
    by_av = {skill.get('av'): i for i, skill in enumerate(skills)}
    by_form = {entry['form'][1]: i for i, entry in enumerate(entries)}
    table = {'PerkForms': [], 'PerkNames': [], 'PerkTexts': [], 'PerkLevel': [], 'PerkRanks': [],
             'PerkReqStart': [], 'PerkReqCount': [], 'ReqKind': [], 'ReqIndex': [], 'ReqOp': [],
             'ReqValue': [], 'ReqOr': []}
    for entry in entries:
        rows = [row for row in (_requirement(raw, by_av, by_form) for raw in entry['requirements']) if row]
        table['PerkReqStart'].append(len(table['ReqKind']))
        table['PerkReqCount'].append(len(rows))
        for column, values in zip(('ReqKind', 'ReqIndex', 'ReqOp', 'ReqValue', 'ReqOr'), zip(*rows)):
            table[column] += list(values)
        table['PerkForms'].append(Obj(forms.of(entry['form'])))
        table['PerkNames'].append(entry['name'])
        table['PerkTexts'].append(entry.get('text', ''))
        table['PerkLevel'].append(entry['level'])
        table['PerkRanks'].append(max(1, entry['ranks']))
    table['ReqValue'] = [float(value) for value in table['ReqValue']]
    too_long = [name for name, column in table.items() if len(column) > PAPYRUS_ARRAY_MAX]
    if too_long:
        raise SystemExit(f'{doc["plugin"]}: perk table columns over {PAPYRUS_ARRAY_MAX}: {too_long}')
    return {**table, 'FirstTrait': len(perks)}


def build_page(fid: int, edid: str, prompt: str, names: list, globs: dict, done: bool) -> bytes:
    """One page: a button per name while its slot global is 1, More and Back while theirs are, and Done."""
    subs = pack_string_subrecord('EDID', edid) + pack_string_subrecord('DESC', prompt)
    subs += pack_formid_subrecord('INAM', 0) + pack_uint32_subrecord('DNAM', 1)
    for name, slot in zip(names, globs['slots']):
        subs += pack_string_subrecord('ITXT', name) + global_is(slot, 1.0)
    subs += pack_string_subrecord('ITXT', MORE_BUTTON) + global_is(globs['more'], 1.0)
    subs += pack_string_subrecord('ITXT', BACK_BUTTON) + global_is(globs['back'], 1.0)
    if done:
        subs += pack_string_subrecord('ITXT', DONE_BUTTON)
    return pack_record('MESG', fid, 0, subs)


def build_confirm(fid: int, edid: str) -> bytes:
    """Take the perk just described, or go back to the page."""
    subs = pack_string_subrecord('EDID', edid) + pack_string_subrecord('DESC', CONFIRM_PROMPT)
    subs += pack_formid_subrecord('INAM', 0) + pack_uint32_subrecord('DNAM', 1)
    subs += b''.join(pack_string_subrecord('ITXT', text) for text in CONFIRM_BUTTONS)
    return pack_record('MESG', fid, 0, subs)


def _pages(names: list) -> list:
    """`names` in pages of PAGE."""
    return [names[i:i + PAGE] for i in range(0, len(names), PAGE)]


def build_perk_menus(forms, doc: dict, prefix: str, skills: list) -> tuple:
    """(properties, MESG bytes, GLOB bytes): the perk table, the slot globals, the confirmation and the pages."""
    table = perk_table(doc, forms, skills)
    confirm = forms.new()
    globs = {'slots': [forms.new() for _ in range(PAGE)], 'more': forms.new(), 'back': forms.new()}
    names = table['PerkNames']
    perk_pages, trait_pages = _pages(names[:table['FirstTrait']]), _pages(names[table['FirstTrait']:])
    perk_fids = [forms.new() for _ in perk_pages]
    trait_fids = [forms.new() for _ in trait_pages]
    mesgs = build_confirm(confirm, f'{prefix}PerkConfirm')
    mesgs += b''.join(build_page(fid, f'{prefix}PerkPage{i}', PERK_PROMPT, page, globs, False)
                      for i, (fid, page) in enumerate(zip(perk_fids, perk_pages)))
    mesgs += b''.join(build_page(fid, f'{prefix}TraitPage{i}', TRAIT_PROMPT, page, globs, True)
                      for i, (fid, page) in enumerate(zip(trait_fids, trait_pages)))
    glob_names = [(fid, f'Slot{k}') for k, fid in enumerate(globs['slots'])]
    glob_names += [(globs['more'], 'SlotMore'), (globs['back'], 'SlotBack')]
    glob_bytes = b''.join(build_glob(fid, f'{prefix}Perk{name}') for fid, name in glob_names)
    settings = doc['settings']
    props = {**table, 'PerkConfirm': Obj(confirm), 'PerkPages': [Obj(fid) for fid in perk_fids],
             'TraitPages': [Obj(fid) for fid in trait_fids], 'PickSlots': [Obj(fid) for fid in globs['slots']],
             'PickMore': Obj(globs['more']), 'PickBack': Obj(globs['back']),
             'LevelsPerPerk': int(settings.get('iLevelsPerPerk', 1)),
             'MaxTraits': int(settings.get('iTraitMenuMaxNumTraits', 0))}
    return props, mesgs, glob_bytes
