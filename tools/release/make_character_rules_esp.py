"""Build a converted TES4 game's character rules plugin, `<stem> Character Rules.esp`.

Reads the game's character data from its export (tes5_import.character_data)
and its converted plugin, and writes a Data folder: the plugin, its .seq, and
the rules scripts from `character_rules/scripts/source`, compiled.

Usage:
  python tools/release/make_character_rules_esp.py --plugin Oblivion.esm
  python tools/release/make_character_rules_esp.py --plugin Oblivion.esm --outdir some/dir --no-compile

See: docs/commentary/character_rules.md#the-rules-plugin
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from convert import load_config
from core.plugin_masters import masters_from_export_header
from core.subprocess_flags import windows_cmd
from output_layout import plugin_esm, record_dir
from papyrus_compile import find_skse_source_scripts, find_skyrim_source_scripts
from script_convert.message_menus import CHARGEN_CLASS_GLOBAL, chargen_class_names
from tes5_import.base.conditions import build_ctda
from tes5_import.base.constants import RACE_MAP, TES4_ATTRIBUTE_NAMES, TES5_SKILL_ORDER
from tes5_import.base.text_reader import group_records_by_type, parse_export_directory
from tes5_import.base.writer import (count_records_and_groups, pack_formid_subrecord,
                                     pack_record, pack_string_subrecord, pack_subrecord,
                                     pack_tes4_header, pack_top_group,
                                     pack_uint32_subrecord)
from tes5_import.character_data import SPECIALIZATIONS, character_data
from tes5_import.overrides.master_index import MasterIndex
from tes5_import.pipeline_finalize import write_seq_file

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DIR = os.path.join(ROOT, 'character_rules', 'scripts', 'source')
SELECTOR_SOURCE_DIR = os.path.join(ROOT, 'TESGameSelect', 'scripts', 'source')
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

#: SMQN DNAM: Shares event, so the vanilla skill-increase quests still run.
SHARES_EVENT = 0x00020000

#: QUST DNAM flags: Start Game Enabled and Starts Enabled; the player alias's FNAM.
SGE_FLAGS, PLAYER_ALIAS_FLAGS, PLAYER_REF = 0x0011, 0x00000292, 0x00000014

#: CTDA function 74, GetGlobalValue.
FUNC_GET_GLOBAL_VALUE = 74

#: This plugin's own local ids, from here up.
OWN_BASE = 0x800

#: VMAD property type by Python value kind; arrays are the scalar type + 10.
_OBJECT, _STRING, _INT, _FLOAT = 1, 2, 3, 4
_ARRAY = 10

#: The level-up menu's prompt; each attribute's line takes its bonus as %.0f.
LEVEL_UP_PROMPT = 'Choose three attributes to improve.'


# ---------------------------------------------------------------------------
# FormIDs
# ---------------------------------------------------------------------------

class Forms:
    """Local ids for this plugin's records, and form conversion into its master space."""

    def __init__(self, masters: list):
        """Records numbered from OWN_BASE, in the index after the masters."""
        self.masters = [name.lower() for name in masters]
        self.index = len(masters) << 24
        self.next = OWN_BASE

    def new(self) -> int:
        """The next unused own FormID."""
        fid = self.index | self.next
        self.next += 1
        return fid

    def of(self, form: list) -> int:
        """An `[owning plugin, local id]` form as a FormID in this plugin."""
        return (self.masters.index(form[0].lower()) << 24) | form[1]


# ---------------------------------------------------------------------------
# VMAD
# ---------------------------------------------------------------------------

def _wstring(text: str) -> bytes:
    """A u16-length string, as VMAD stores names and string values."""
    data = text.encode('utf-8')
    return struct.pack('<H', len(data)) + data


def _scalar(kind: int, value) -> bytes:
    """One VMAD value of `kind`: an object is (unused, alias -1, FormID)."""
    if kind == _OBJECT:
        return struct.pack('<HhI', 0, -1, value)
    if kind == _STRING:
        return _wstring(value)
    return struct.pack('<i' if kind == _INT else '<f', value)


def _kind(value) -> int:
    """The VMAD type for a property value: Obj(fid) is an object, a list an array."""
    sample = value[0] if isinstance(value, list) and value else value
    if isinstance(sample, Obj):
        kind = _OBJECT
    elif isinstance(sample, str):
        kind = _STRING
    else:
        kind = _FLOAT if isinstance(sample, float) else _INT
    return kind + _ARRAY if isinstance(value, list) else kind


class Obj(int):
    """A FormID a VMAD property binds as an object."""


def pack_script(name: str, props: dict) -> bytes:
    """One VMAD script entry with typed properties (objects, strings, ints, floats, arrays)."""
    out = _wstring(name) + struct.pack('<BH', 0, len(props))
    for pname, value in props.items():
        kind = _kind(value)
        out += _wstring(pname) + struct.pack('<BB', kind, 1)
        if kind > _ARRAY:
            out += struct.pack('<I', len(value))
            out += b''.join(_scalar(kind - _ARRAY, item) for item in value)
        else:
            out += _scalar(kind, value)
    return out


def pack_quest_vmad(script: bytes, quest_fid: int, alias_scripts: tuple = ()) -> bytes:
    """A QUST VMAD: one script, no fragments, and scripts on alias 0."""
    out = struct.pack('<HHH', 5, 2, 1) + script + struct.pack('<bH', 2, 0) + _wstring('')
    out += struct.pack('<h', 1 if alias_scripts else 0)
    if alias_scripts:
        out += struct.pack('<HhI', 0, 0, quest_fid) + struct.pack('<hhh', 5, 2, len(alias_scripts))
        out += b''.join(alias_scripts)
    return out


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
# Records
# ---------------------------------------------------------------------------

def build_glob(fid: int, edid: str) -> bytes:
    """A short global, 0."""
    subs = pack_string_subrecord('EDID', edid) + pack_subrecord('FNAM', b's')
    return pack_record('GLOB', fid, 0, subs + pack_subrecord('FLTV', struct.pack('<f', 0.0)))


def build_flst(fid: int, edid: str, entries: list) -> bytes:
    """A form list of `entries`."""
    subs = pack_string_subrecord('EDID', edid)
    subs += b''.join(pack_formid_subrecord('LNAM', entry) for entry in entries)
    return pack_record('FLST', fid, 0, subs)


def build_level_up_menu(fid: int, prefix: str, names: list, picked: list) -> bytes:
    """The attribute menu: a button per attribute, hidden once picked this level-up."""
    lines = [LEVEL_UP_PROMPT, ''] + [f'{name} +%.0f' for name in names]
    subs = pack_string_subrecord('EDID', f'{prefix}LevelUpMenu')
    subs += pack_string_subrecord('DESC', '\n'.join(lines))
    subs += pack_formid_subrecord('INAM', 0) + pack_uint32_subrecord('DNAM', 1)
    for name, glob in zip(names, picked):
        subs += pack_string_subrecord('ITXT', name)
        subs += pack_subrecord('CTDA', build_ctda(FUNC_GET_GLOBAL_VALUE, param1=glob,
                                                  comp_value=0.0, operator=0x00))
    return pack_record('MESG', fid, 0, subs)


def build_main_quest(fid: int, prefix: str, props: dict) -> bytes:
    """The rules quest: Start Game Enabled, the rules script, and the player alias."""
    player = pack_script('TES4Rules_Player', {'Rules': Obj(fid)})
    subs = pack_string_subrecord('EDID', f'{prefix}CharacterRules')
    subs += pack_subrecord('VMAD', pack_quest_vmad(pack_script('TES4Rules_Main', props),
                                                   fid, (player,)))
    subs += pack_subrecord('DNAM', struct.pack('<HBBII', SGE_FLAGS, 0, 0, 0, 0))
    subs += pack_subrecord('NEXT', b'') + pack_uint32_subrecord('ANAM', 1)
    subs += pack_uint32_subrecord('ALST', 0) + pack_string_subrecord('ALID', 'Player')
    subs += pack_uint32_subrecord('FNAM', PLAYER_ALIAS_FLAGS)
    subs += pack_formid_subrecord('ALFR', PLAYER_REF) + pack_formid_subrecord('VTCK', 0)
    return pack_record('QUST', fid, 0, subs + pack_subrecord('ALED', b''))


def build_event_quest(fid: int, prefix: str, main_fid: int) -> bytes:
    """The quest the Story Manager starts on each skill increase."""
    script = pack_script('TES4Rules_SkillEvent', {'Rules': Obj(main_fid)})
    subs = pack_string_subrecord('EDID', f'{prefix}SkillIncrease')
    subs += pack_subrecord('VMAD', pack_quest_vmad(script, fid))
    subs += pack_subrecord('DNAM', struct.pack('<HBBII', 0, 0, 0, 0, 0))
    subs += pack_subrecord('ENAM', b'SKIL') + pack_subrecord('NEXT', b'')
    return pack_record('QUST', fid, 0, subs + pack_uint32_subrecord('ANAM', 0))


def build_node(fid: int, prefix: str, quest_fid: int, active_fid: int) -> bytes:
    """The Story Manager quest node on Skyrim's skill-increase event, while the rules are on."""
    subs = pack_string_subrecord('EDID', f'{prefix}SkillIncreaseNode')
    subs += pack_formid_subrecord('PNAM', SKILL_EVENT_NODE)
    subs += pack_formid_subrecord('SNAM', SKILL_EVENT_LAST_CHILD)
    subs += pack_uint32_subrecord('CITC', 1)
    subs += pack_subrecord('CTDA', build_ctda(FUNC_GET_GLOBAL_VALUE, param1=active_fid,
                                              comp_value=1.0, operator=0x00))
    subs += pack_uint32_subrecord('DNAM', SHARES_EVENT) + pack_uint32_subrecord('XNAM', 0)
    subs += pack_uint32_subrecord('QNAM', 1)
    return pack_record('SMQN', fid, 0, subs + pack_formid_subrecord('NNAM', quest_fid))


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------

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
    """The plugin's bytes and record count, for `doc` from the masterless plugin masters[-1]."""
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
    groups = [pack_top_group('GLOB', b''.join(globs)),
              pack_top_group('FLST', b''.join(lists)),
              pack_top_group('MESG', build_level_up_menu(menu, prefix, names, picked)),
              pack_top_group('QUST', build_main_quest(main, prefix, props)
                             + build_event_quest(event, prefix, main)),
              pack_top_group('SMQN', build_node(node, prefix, event, active))]
    count = sum(count_records_and_groups(group) for group in groups)
    header = pack_tes4_header(masters, num_records=count, next_object_id=forms.next,
                              author='TESConversion',
                              description=f'{masters[-1]} character rules', is_esm=False)
    return header + b''.join(groups), count, main


# ---------------------------------------------------------------------------
# Inputs, compile and the Data folder
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


def compile_scripts(outdir: str) -> bool:
    """Compile the rules scripts against Skyrim's, SKSE's and TESGameSelect's headers."""
    try:
        cfg = load_config()
    except (FileNotFoundError, OSError):
        cfg = {}
    headers = [find_skyrim_source_scripts(cfg), find_skse_source_scripts(cfg),
               SELECTOR_SOURCE_DIR, SOURCE_DIR]
    compiler = os.path.join(ROOT, 'external', 'papyrus-compiler', 'papyrus.exe')
    out_dir = os.path.join(outdir, 'scripts')
    ok = True
    for name in SCRIPTS:
        cmd = [compiler, 'compile', '-nocache', '-i', os.path.join(SOURCE_DIR, name + '.psc'),
               '-o', out_dir]
        for header in filter(None, headers):
            cmd += ['-h', header]
        run = subprocess.run(windows_cmd(cmd), capture_output=True, text=True, timeout=90, cwd=ROOT)
        built = os.path.isfile(os.path.join(out_dir, name + '.pex'))
        print(f'  {"compiled" if run.returncode == 0 and built else "COMPILE FAILED"} {name}')
        if run.returncode != 0 or not built:
            print('   ', ((run.stdout or '') + (run.stderr or '')).strip().replace('\n', '\n    '))
            ok = False
    return ok


def build(plugin: str, outdir: str, export_root: str, output_root: str,
          compile_psc: bool = True) -> bool:
    """Build the Data folder into `outdir`; True when it is shippable."""
    doc, masters, class_choice = load_inputs(plugin, export_root, output_root)
    game_id = GAME_IDS.get(plugin.lower())
    if game_id is None:
        raise SystemExit(f'{plugin} is not a game TESGameSelect starts')
    stem = os.path.splitext(plugin)[0]
    prefix = f'TES4Rules{stem.replace(" ", "")}'
    data, count, main = build_plugin(doc, [*masters, plugin], class_choice, game_id, prefix)
    esp = os.path.join(outdir, f'{stem} Character Rules.esp')
    os.makedirs(os.path.join(outdir, 'scripts', 'source'), exist_ok=True)
    with open(esp, 'wb') as handle:
        handle.write(data)
    print(f'Wrote {esp} ({len(data)} bytes, {count} records and groups)')
    write_seq_file(esp, {main})
    for name in SCRIPTS:
        shutil.copyfile(os.path.join(SOURCE_DIR, name + '.psc'),
                        os.path.join(outdir, 'scripts', 'source', name + '.psc'))
    return compile_scripts(outdir) if compile_psc else True


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
