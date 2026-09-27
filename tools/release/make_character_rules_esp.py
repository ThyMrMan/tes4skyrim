"""Build a converted game's character rules plugin, `<stem> Character Rules.esp`.

Reads the game's character data from its export (tes5_import.character_data)
and writes a Data folder: the plugin, its .seq, and the rules scripts from
`character_rules/scripts/source`, compiled. A TES4 game gets the skill-use
rules below; a Fallout game the XP rules of character_rules_falloutnv.py.

Usage:
  python tools/release/make_character_rules_esp.py --plugin Oblivion.esm
  python tools/release/make_character_rules_esp.py --plugin FalloutNV.esm
  python tools/release/make_character_rules_esp.py --plugin Oblivion.esm --outdir some/dir --no-compile

See: docs/commentary/character_rules.md#the-rules-plugin
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.plugin_masters import masters_from_export_header
from output_layout import plugin_esm, record_dir
from script_convert.message_menus import CHARGEN_CLASS_GLOBAL, chargen_class_names
from tes5_import.base.constants import RACE_MAP, TES4_ATTRIBUTE_NAMES, TES5_SKILL_ORDER
from tes5_import.base.text_reader import group_records_by_type, parse_export_directory
from tes5_import.base.writer import (count_records_and_groups, pack_formid_subrecord,
                                     pack_record, pack_string_subrecord, pack_tes4_header,
                                     pack_top_group, pack_uint32_subrecord)
from tes5_import.character_data import SPECIALIZATIONS, character_data
from tes5_import.overrides.master_index import MasterIndex
from tools.release.character_rules_falloutnv import build_fallout, is_fallout_export
from tools.release.character_rules_records import (ROOT, Forms, Obj, build_event_quest,
                                                   build_flst, build_glob, build_main_quest,
                                                   build_node, global_is, pack_script,
                                                   write_data_folder)

SCRIPTS = ('TES4Rules_Main', 'TES4Rules_Player', 'TES4Rules_SkillEvent')

#: The records character_data reads from the export.
EXPORT_TYPES = frozenset({'SKIL', 'CLAS', 'RACE', 'BSGN', 'GMST', 'WEAP', 'SPEL', 'MGEF', 'BOOK'})

#: Game plugin (lowercase) -> its id in TESGameSelectQuest (GAME_OBLIVION and the rest).
GAME_IDS = {'oblivion.esm': 1, 'morrowind_ob.esm': 3, 'nehrim.esm': 4}

#: Source skills credited by what the player was doing: TES4Rules_Main.FoldApplies names each.
FOLD_SKILLS = frozenset({'Blunt', 'Mysticism', 'Mercantile'})

#: Starting skill levels, as the game's chargen texts give them (sMajorSkills, sSpecialization).
MINOR_SKILL_START, MAJOR_SKILL_START, SPECIALIZATION_BONUS = 5, 25, 10

#: A race boosts at most this many skills; RaceBonusSkill holds this many slots per race.
RACE_BONUS_SLOTS = 7

#: The Skyrim.esm Story Manager node every skill increase passes (SMEN, ENAM SKIL), and its last child.
SKILL_EVENT_NODE, SKILL_EVENT_LAST_CHILD = 0x0002D386, 0x000F6F1C

#: The level-up menu's prompt; each attribute's line takes its bonus as %.0f.
LEVEL_UP_PROMPT = 'Choose three attributes to improve.'


# ---------------------------------------------------------------------------
# Tables from the character data
# ---------------------------------------------------------------------------

def skyrim_sources(skills: list) -> tuple:
    """Per Skyrim skill, the source skill it credits and the folded one, each an index or -1."""
    primary, fold = [], []
    for skyrim in TES5_SKILL_ORDER:
        credited = [i for i, skill in enumerate(skills) if skyrim in skill['skyrim']]
        folded = [i for i in credited if skills[i]['name'] in FOLD_SKILLS]
        plain = [i for i in credited if i not in folded]
        primary.append(plain[0] if plain else -1)
        fold.append(folded[0] if folded else -1)
    return primary, fold


def class_table(doc: dict) -> dict:
    """The chargen class menu's classes in menu order, as parallel arrays."""
    skills = [skill['name'] for skill in doc['skills']]
    by_name = {}
    for cls in doc.get('classes', []):
        if cls['playable'] and cls['name']:
            by_name.setdefault(cls['name'], cls)
    rows = [by_name[name] for name in chargen_class_names(by_name)]
    favored = [cls['attributes'] + [None, None] for cls in rows]
    return {'ClassIds': [cls['id'] for cls in rows],
            'ClassMajors': [sum(1 << skills.index(s) for s in cls['major'] if s in skills)
                            for cls in rows],
            'ClassSpecialization': [SPECIALIZATIONS.index(cls['specialization']) for cls in rows],
            'ClassFavored1': [_attribute_index(pair[0]) for pair in favored],
            'ClassFavored2': [_attribute_index(pair[1]) for pair in favored]}


def _attribute_index(name) -> int:
    """An attribute name's index, 0-7, or -1."""
    return TES4_ATTRIBUTE_NAMES.index(name) if name in TES4_ATTRIBUTE_NAMES else -1


def race_table(doc: dict, forms: Forms) -> dict:
    """The playable races the player can pick in Skyrim, as parallel arrays and Skyrim race FormIDs."""
    skills = [skill['name'] for skill in doc['skills']]
    rows = [race for race in doc.get('races', []) if race['playable'] and race['id'] in RACE_MAP]
    out = {'races': [forms.of(['Skyrim.esm', RACE_MAP[race['id']]]) for race in rows],
           'RaceMale': [], 'RaceFemale': [], 'RaceBonusSkill': [], 'RaceBonusValue': []}
    for race in rows:
        out['RaceMale'] += [race['male'].get(a, 0) for a in TES4_ATTRIBUTE_NAMES]
        out['RaceFemale'] += [race['female'].get(a, 0) for a in TES4_ATTRIBUTE_NAMES]
        bonuses = list(race['skills'].items())[:RACE_BONUS_SLOTS]
        bonuses += [(None, 0)] * (RACE_BONUS_SLOTS - len(bonuses))
        out['RaceBonusSkill'] += [skills.index(s) if s in skills else -1 for s, _v in bonuses]
        out['RaceBonusValue'] += [value for _s, value in bonuses]
    return out


def settings_table(settings: dict) -> dict:
    """The rules' numbers and texts, from the game's settings."""
    return {'LevelUpMults': [1] + [settings[f'iLevelUp{n:02d}Mult'] for n in range(1, 11)],
            'LevelUpTexts': [settings[f'sLevelUp{n}'] for n in range(2, 21)],
            'MeditateText': settings['sMeditate'],
            'SkillsPerLevel': settings['iLevelUpSkillCount'],
            'FavoredBonus1': float(settings['fAttributeClassPrimaryBonus']),
            'FavoredBonus2': float(settings['fAttributeClassSecondaryBonus']),
            'HealthMult': float(settings['fPCBaseHealthMult']),
            'MagickaMult': float(settings['fPCBaseMagickaMult']),
            'EncumbranceMult': float(settings['fActorStrengthEncumbranceMult'])}


def skill_table(doc: dict) -> dict:
    """The source skills and how each Skyrim skill credits them."""
    skills = doc['skills']
    primary, fold = skyrim_sources(skills)
    return {'SkyrimSkillNames': list(TES5_SKILL_ORDER),
            'SkillNames': [skill['name'] for skill in skills],
            'SkillAttribute': [_attribute_index(skill['attribute']) for skill in skills],
            'SkillSpecialization': [SPECIALIZATIONS.index(skill['specialization'])
                                    for skill in skills],
            'SkyrimPrimary': primary, 'SkyrimFold': fold,
            'MinorSkillStart': MINOR_SKILL_START, 'MajorSkillStart': MAJOR_SKILL_START,
            'SpecializationBonus': SPECIALIZATION_BONUS}


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------

def build_level_up_menu(fid: int, prefix: str, names: list, picked: list) -> bytes:
    """The attribute menu: a button per attribute, hidden once picked this level-up."""
    lines = [LEVEL_UP_PROMPT, ''] + [f'{name} +%.0f' for name in names]
    subs = pack_string_subrecord('EDID', f'{prefix}LevelUpMenu')
    subs += pack_string_subrecord('DESC', '\n'.join(lines))
    subs += pack_formid_subrecord('INAM', 0) + pack_uint32_subrecord('DNAM', 1)
    for name, glob in zip(names, picked):
        subs += pack_string_subrecord('ITXT', name) + global_is(glob, 0.0)
    return pack_record('MESG', fid, 0, subs)


def _lists(doc: dict, forms: Forms, prefix: str, races: list) -> tuple:
    """(FLST records, their FormIDs by role): folded skills, races and skill books."""
    folds = doc.get('folds', {})
    fids = {role: forms.new() for role in ('Blunt', 'Mysticism', 'Races', 'Picked', 'Books')}
    book_fids = [forms.new() for _skill in doc['skills']]
    records = [build_flst(fids['Blunt'], f'{prefix}BluntWeapons',
                          [forms.of(f) for f in folds.get('Blunt', [])]),
               build_flst(fids['Mysticism'], f'{prefix}MysticismSpells',
                          [forms.of(f) for f in folds.get('Mysticism', [])]),
               build_flst(fids['Races'], f'{prefix}Races', races),
               build_flst(fids['Books'], f'{prefix}SkillBooks', book_fids)]
    for fid, skill in zip(book_fids, doc['skills']):
        books = [forms.of(f) for f in doc.get('books', {}).get(skill['name'], [])]
        records.append(build_flst(fid, f'{prefix}Books{skill["name"]}', books))
    return records, fids


def build_plugin(doc: dict, masters: list, class_choice: int, game_id: int, prefix: str) -> tuple:
    """The plugin's bytes, record count and rules quest, for `doc` from the masterless plugin masters[-1]."""
    forms = Forms(masters)
    active, main, event, node, menu = (forms.new() for _ in range(5))
    picked = [forms.new() for _ in TES4_ATTRIBUTE_NAMES]
    races = race_table(doc, forms)
    lists, fids = _lists(doc, forms, prefix, races.pop('races'))
    lists.append(build_flst(fids['Picked'], f'{prefix}PickedAttributes', picked))
    names = [doc['settings'].get(f'sAttributeName{a}', a) for a in TES4_ATTRIBUTE_NAMES]
    props = {'Plugin': masters[-1], 'GameId': game_id, 'Active': Obj(active),
             'ClassChoice': Obj(class_choice), 'BluntWeapons': Obj(fids['Blunt']),
             'MysticismSpells': Obj(fids['Mysticism']), 'SkillBooks': Obj(fids['Books']),
             'Races': Obj(fids['Races']), 'PickedGlobals': Obj(fids['Picked']),
             'LevelUpMenu': Obj(menu), **skill_table(doc), **class_table(doc), **races,
             **settings_table(doc['settings'])}
    globs = [build_glob(active, f'{prefix}RulesActive')] + [
        build_glob(fid, f'{prefix}Picked{a}') for fid, a in zip(picked, TES4_ATTRIBUTE_NAMES)]
    quests = (build_main_quest(main, f'{prefix}CharacterRules', pack_script(SCRIPTS[0], props), SCRIPTS[1])
              + build_event_quest(event, f'{prefix}SkillIncrease', b'SKIL', SCRIPTS[2], main))
    groups = [pack_top_group('GLOB', b''.join(globs)),
              pack_top_group('FLST', b''.join(lists)),
              pack_top_group('MESG', build_level_up_menu(menu, prefix, names, picked)),
              pack_top_group('QUST', quests),
              pack_top_group('SMQN', build_node(node, f'{prefix}SkillIncreaseNode',
                                                (SKILL_EVENT_NODE, SKILL_EVENT_LAST_CHILD), [event], active))]
    count = sum(count_records_and_groups(group) for group in groups)
    header = pack_tes4_header(masters, num_records=count, next_object_id=forms.next,
                              author='TESConversion',
                              description=f'{masters[-1]} character rules', is_esm=False)
    return header + b''.join(groups), count, main


# ---------------------------------------------------------------------------
# Inputs and the Data folder
# ---------------------------------------------------------------------------

def load_inputs(plugin: str, export_root: str, output_root: str) -> tuple:
    """(character data, converted masters, the class choice GLOB) for a masterless plugin."""
    export_dir = str(record_dir(export_root, plugin))
    if masters_from_export_header(export_dir):
        raise SystemExit(f'{plugin} has masters; build the rules for its masterless game plugin')
    records = parse_export_directory(export_dir, type_filter=set(EXPORT_TYPES))
    doc = character_data(group_records_by_type(records), [], plugin)
    esm = str(plugin_esm(output_root, plugin, export_root))
    index = MasterIndex(esm)
    choice = index.find_by_edid(b'GLOB', CHARGEN_CLASS_GLOBAL)
    if not doc.get('skills') or not choice:
        raise SystemExit(f'{plugin}: no skills in its export (re-export it) or no '
                         f'{CHARGEN_CLASS_GLOBAL} in {esm} (convert it first)')
    return doc, index.masters, choice


def build(plugin: str, outdir: str, export_root: str, output_root: str,
          compile_psc: bool = True) -> bool:
    """Build the Data folder into `outdir`; True when it is shippable."""
    if is_fallout_export(str(record_dir(export_root, plugin))):
        return build_fallout(plugin, outdir, export_root, compile_psc)
    doc, masters, class_choice = load_inputs(plugin, export_root, output_root)
    game_id = GAME_IDS.get(plugin.lower())
    if game_id is None:
        raise SystemExit(f'{plugin} is not a game TESGameSelect starts')
    stem = os.path.splitext(plugin)[0]
    built = build_plugin(doc, [*masters, plugin], class_choice, game_id,
                         f'TES4Rules{stem.replace(" ", "")}')
    return write_data_folder(outdir, f'{stem} Character Rules.esp', built, SCRIPTS, compile_psc)


def main() -> int:
    """Command line entry point."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugin', required=True, help="the game's masterless plugin, e.g. Oblivion.esm")
    ap.add_argument('--export-root', default=os.path.join(ROOT, 'export'))
    ap.add_argument('--output-root', default=os.path.join(ROOT, 'output'))
    ap.add_argument('--outdir', help='Data folder to write (default: output/<stem> Character Rules)')
    ap.add_argument('--no-compile', action='store_true', help='skip the Papyrus compile')
    args = ap.parse_args()
    outdir = args.outdir or os.path.join(
        args.output_root, f'{os.path.splitext(args.plugin)[0]} Character Rules')
    ok = build(args.plugin, outdir, args.export_root, args.output_root, not args.no_compile)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
