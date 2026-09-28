"""The XP half of make_character_rules_esp.py: a Fallout game's character rules plugin.

The player's S.P.E.C.I.A.L. lives in TESGameSelect.esp's player globals;
experience comes from kills and picked locks (Story Manager events) and from
quest rewards (the TESCharacterXP mod event converted `RewardXP` sends); a
level-up spends skill points in message boxes. Every number comes from the
game's character data (tes5_import.character_data_falloutnv).

See: docs/commentary/character_rules.md#fallout
"""
import os

from core.plugin_masters import masters_from_export_header
from output_layout import plugin_esm, record_dir
from tes5_import.base.constants import TES4_ATTRIBUTE_NAMES, TES5_SKILL_ORDER
from tes5_import.base.text_reader import group_records_by_type, parse_export_directory
from tes5_import.base.writer import (count_records_and_groups, pack_formid_subrecord, pack_record,
                                     pack_string_subrecord, pack_tes4_header, pack_top_group,
                                     pack_uint32_subrecord)
from tes5_import.character_data_falloutnv import character_data, game_of
from tes5_import.overrides.master_index import MasterIndex
from tes5_import.record_types.reputation_falloutnv import KARMA_GLOBAL
from tes5_import.record_types.world_falloutnv import FALLOUT_ONLY_SIGS
from tools.release.character_rules_perks import build_perk_menus
from tools.release.character_rules_standings import build_standings
from tools.release.character_rules_records import (Forms, Obj, build_event_quest, build_glob,
                                                   build_main_quest, build_node, pack_script,
                                                   write_data_folder)
from tools.release.make_game_select_esp import FALLOUT_ONLY_STATS, FID_GLOB_PLAYER_ATTRIBUTES

SCRIPTS = ('FalloutRules_Main', 'FalloutRules_Player', 'FalloutRules_KillEvent', 'FalloutRules_LockEvent',
           'FalloutRules_CrimeEvent')

#: The records character_data_falloutnv reads for the rules.
EXPORT_TYPES = frozenset({'AVIF', 'CLAS', 'CREA', 'FACT', 'GMST', 'LVLC', 'LVLN', 'NPC_', 'PERK'})

#: Game plugin (lowercase) -> its id in TESGameSelectQuest (GAME_FALLOUTNV).
GAME_IDS = {'falloutnv.esm': 6}

#: S.P.E.C.I.A.L. in actor value order, 5 to 11: the engine's fixed order.
SPECIAL = ('Strength', 'Perception', 'Endurance', 'Charisma', 'Intelligence', 'Agility', 'Luck')

#: The difficulty suffixes of the XP settings, in the engine's tier order.
TIERS = ('VeryEasy', 'Easy', 'Average', 'Hard', 'VeryHard')

#: The kill tables: (property, the level setting, the reward setting), paired as Fallout3.exe pairs them.
XP_TABLES = (('KillCreature', 'iXPLevelKillCreature', 'iXPRewardKillOpponent'),
             ('KillNPC', 'iXPLevelKillNPC', 'iXPRewardKillNPC'),
             ('PickLock', 'iXPLevelPickLock', 'iXPRewardPickLock'))

#: Skyrim.esm's kill event node (SMEN, ENAM KILL) and its last child; its lock event node, childless.
KILL_EVENT_NODE, KILL_EVENT_LAST_CHILD, LOCK_EVENT_NODE = 0x00013010, 0x0001E491, 0x0005BD7B

#: Skyrim.esm's crime gold event node (SMEN, ENAM ADCR), childless.
CRIME_EVENT_NODE = 0x0005B5DA

#: Skyrim.esm KYWD ActorTypeNPC: people; converted creatures carry ActorTypeCreature or ActorTypeAnimal.
ACTOR_TYPE_NPC = 0x00013794

#: Quests per event node, so events close together each find one not already running.
EVENT_POOL = 4

#: Source skills a Skyrim skill can carry (Marksman: Small Guns, Energy Weapons, Big Guns).
SOURCES_PER_SKILL = 3

#: Skill buttons on the menu's first page: with the points left, a message shows at most nine values.
FIRST_PAGE_SKILLS = 8

#: New Vegas's fixed skill points: (offset, per Intelligence, Intelligence cap, the even-level point).
_NEW_VEGAS_SKILL_POINTS = (10.0, 0.5, 10, 1)

#: New Vegas awards the kills of the player's companions too; Fallout 3 only the player's.
_TEAMMATE_KILLS = {'falloutnv': 1, 'fallout3': 0}

#: The skill menu's prompt and page buttons, and the notification words.
SKILL_MENU_PROMPT, MORE_BUTTON, BACK_BUTTON = 'Skill points to spend: %.0f', 'More skills', 'Back'
TEXTS = {'XPText': 'XP', 'LevelText': 'Level'}

#: Character creation's prompts: the tag pages, then the S.P.E.C.I.A.L. menu's raise and lower modes.
TAG_MENU_PROMPT = 'Tag skills to choose: %.0f'
SPECIAL_PROMPTS = ('Choose a stat to raise. Points to spend: %.0f',
                   'Choose a stat to lower. Points to spend: %.0f')
SPECIAL_BUTTONS = (('Lower a stat', 'Done'), ('Raise a stat', 'Done'))

#: The rules' menu properties allocated after the event quests, in this order.
NEW_MENUS = ('SpecialMenu', 'SpecialLowerMenu', 'TagMenu', 'TagMenuMore')


# ---------------------------------------------------------------------------
# Tables from the character data
# ---------------------------------------------------------------------------

def is_fallout_export(export_dir: str) -> bool:
    """Whether an export has a record type only FO3/FNV write."""
    return any(os.path.isfile(os.path.join(export_dir, f'{sig}.txt')) for sig in FALLOUT_ONLY_SIGS)


def special_globals() -> list:
    """Each S.P.E.C.I.A.L. stat's player global id in TESGameSelect.esp."""
    names = TES4_ATTRIBUTE_NAMES + FALLOUT_ONLY_STATS
    return [(FID_GLOB_PLAYER_ATTRIBUTES & 0xFFFFFF) + names.index(stat) for stat in SPECIAL]


def _skill_base(skill: dict, settings: dict) -> float:
    """fAVDSkill<id>Base, else by name for a renamed skill (Survival)."""
    by_id = f'fAVDSkill{skill["id"][2:]}Base'
    by_name = f'fAVDSkill{skill["name"].replace(" ", "")}Base'
    return float(settings.get(by_id, settings.get(by_name, 0.0)))


def shown_skills(doc: dict) -> list:
    """The skills the game shows the player: all but the one its engine hides."""
    return [skill for skill in doc['skills'] if skill.get('playable', True)]


def skill_table(doc: dict) -> dict:
    """The shown skills, their governing stat and base, and the source skills each Skyrim skill carries."""
    skills = shown_skills(doc)
    sources = []
    for skyrim in TES5_SKILL_ORDER:
        credited = [i for i, skill in enumerate(skills) if skyrim in skill['skyrim']][:SOURCES_PER_SKILL]
        sources += credited + [-1] * (SOURCES_PER_SKILL - len(credited))
    return {'SkyrimSkillNames': list(TES5_SKILL_ORDER), 'SkyrimSources': sources,
            'SkillNames': [skill['name'] for skill in skills],
            'SkillAttribute': [SPECIAL.index(skill['attribute']) if skill['attribute'] in SPECIAL else -1
                               for skill in skills],
            'SkillBase': [_skill_base(skill, doc['settings']) for skill in skills]}


def player_table(doc: dict) -> dict:
    """The S.P.E.C.I.A.L. and tag skills of the player record's class, a new character's start."""
    form = doc.get('player', {}).get('class')
    cls = next((row for row in doc.get('classes', []) if row['form'] == form), None)
    if cls is None or len(cls['special']) != len(SPECIAL):
        raise SystemExit(f'{doc["plugin"]}: no player class with S.P.E.C.I.A.L. in its export')
    names = [skill['name'] for skill in shown_skills(doc)]
    return {'SpecialStart': list(cls['special'].values()),
            'TagSkills': [names.index(tag) for tag in cls['tags'] if tag in names]}


def settings_table(settings: dict, game: str) -> dict:
    """The rules' numbers: the XP curve, skill points, skill formula and the reward tables.

    See: docs/commentary/character_rules.md#fallout
    """
    interval = settings['iLevelUpSkillPointsInterval']
    offset, per, cap, even = (_NEW_VEGAS_SKILL_POINTS if game == 'falloutnv' else
                              (float(settings['iLevelUpSkillPointsBase'] - interval), float(interval), 0, 0))
    out = {'XPBase': settings['iXPBase'], 'XPBumpBase': settings['iXPBumpBase'],
           'MaxLevel': settings['iMaxCharacterLevel'],
           'SkillPointsOffset': offset, 'SkillPointsPerIntelligence': per,
           'IntelligenceCap': cap, 'EvenLevelPoint': even,
           'TagSkillBonus': float(settings['fAVDTagSkillBonus']),
           'PrimaryBonusMult': float(settings['fAVDSkillPrimaryBonusMult']),
           'LuckBonusMult': float(settings['fAVDSkillLuckBonusMult']),
           'HealthPerLevel': float(settings['fAVDHealthLevelMult']),
           'TeammateKills': _TEAMMATE_KILLS[game]}
    for prop, level, reward in XP_TABLES:
        out[f'Level{prop}'] = [settings[level + tier] for tier in TIERS]
        out[f'Reward{prop}'] = [settings[reward + tier] for tier in TIERS]
    return out


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------

def build_menu(fid: int, edid: str, prompt: str, names: list, extra: tuple) -> bytes:
    """A message box: the prompt's count, each name's value, a button per name and the extra ones."""
    lines = [prompt, ''] + [f'{name} %.0f' for name in names]
    subs = pack_string_subrecord('EDID', edid) + pack_string_subrecord('DESC', '\n'.join(lines))
    subs += pack_formid_subrecord('INAM', 0) + pack_uint32_subrecord('DNAM', 1)
    subs += b''.join(pack_string_subrecord('ITXT', name) for name in [*names, *extra])
    return pack_record('MESG', fid, 0, subs)


def build_menus(fids: dict, prefix: str, names: list) -> bytes:
    """The skill pages, the two S.P.E.C.I.A.L. menus and the tag pages."""
    first, rest = names[:FIRST_PAGE_SKILLS], names[FIRST_PAGE_SKILLS:]
    pages = [('SkillMenu', SKILL_MENU_PROMPT, first, (MORE_BUTTON,)),
             ('SkillMenuMore', SKILL_MENU_PROMPT, rest, (BACK_BUTTON,)),
             ('SpecialMenu', SPECIAL_PROMPTS[0], list(SPECIAL), SPECIAL_BUTTONS[0]),
             ('SpecialLowerMenu', SPECIAL_PROMPTS[1], list(SPECIAL), SPECIAL_BUTTONS[1]),
             ('TagMenu', TAG_MENU_PROMPT, first, (MORE_BUTTON,)),
             ('TagMenuMore', TAG_MENU_PROMPT, rest, (BACK_BUTTON,))]
    return b''.join(build_menu(fids[key], f'{prefix}{key}', prompt, shown, extra)
                    for key, prompt, shown, extra in pages)


def _events(prefix: str, main: int, active: int, pools: tuple) -> tuple:
    """(QUST bytes, SMQN bytes) for each (name, event, script, node, place, quests) pool."""
    quests = b''.join(build_event_quest(fid, f'{prefix}{name}{i}', event, script, main)
                      for name, event, script, _, _, fids in pools for i, fid in enumerate(fids))
    nodes = b''.join(build_node(node, f'{prefix}{name}Node', place, fids, active)
                     for name, _, _, node, place, fids in pools)
    return quests, nodes


def build_fallout_plugin(doc: dict, masters: list, game_id: int, prefix: str, karma: int) -> tuple:
    """The plugin's bytes, record count and rules quest, for `doc` from the masterless plugin masters[-1],
    whose karma global has the local id `karma`."""
    forms = Forms(masters)
    active, main, first, second, kill_node, lock_node = (forms.new() for _ in range(6))
    kills = [forms.new() for _ in range(EVENT_POOL)]
    locks = [forms.new() for _ in range(EVENT_POOL)]
    menu_fids = {'SkillMenu': first, 'SkillMenuMore': second, **{key: forms.new() for key in NEW_MENUS}}
    names = [skill['name'] for skill in shown_skills(doc)]
    perk_props, perk_menus, perk_globs = build_perk_menus(forms, doc, prefix, shown_skills(doc))
    crime_node, crimes = forms.new(), [forms.new() for _ in range(EVENT_POOL)]
    standing_props, standing_lists = build_standings(forms, doc, prefix, forms.of([masters[-1], karma]))
    props = {'Plugin': masters[-1], 'GameId': game_id, 'Active': Obj(active),
             'ActorTypeNPC': Obj(forms.of(['Skyrim.esm', ACTOR_TYPE_NPC])),
             **{key: Obj(fid) for key, fid in menu_fids.items()}, 'FirstPageSkills': FIRST_PAGE_SKILLS,
             'SpecialGlobals': special_globals(), **skill_table(doc), **player_table(doc),
             **settings_table(doc['settings'], doc['game']), **TEXTS, **perk_props, **standing_props}
    pools = (('Kill', b'KILL', SCRIPTS[2], kill_node, (KILL_EVENT_NODE, KILL_EVENT_LAST_CHILD), kills),
             ('PickLock', b'LOCK', SCRIPTS[3], lock_node, (LOCK_EVENT_NODE, 0), locks),
             ('Crime', b'ADCR', SCRIPTS[4], crime_node, (CRIME_EVENT_NODE, 0), crimes))
    event_quests, nodes = _events(prefix, main, active, pools)
    quests = build_main_quest(main, f'{prefix}CharacterRules', pack_script(SCRIPTS[0], props), SCRIPTS[1])
    menus = build_menus(menu_fids, prefix, names) + perk_menus
    groups = [pack_top_group('GLOB', build_glob(active, f'{prefix}RulesActive') + perk_globs),
              pack_top_group('FLST', standing_lists), pack_top_group('MESG', menus),
              pack_top_group('QUST', quests + event_quests), pack_top_group('SMQN', nodes)]
    count = sum(count_records_and_groups(group) for group in groups)
    header = pack_tes4_header(masters, num_records=count, next_object_id=forms.next,
                              author='TESConversion',
                              description=f'{masters[-1]} character rules', is_esm=False)
    return header + b''.join(groups), count, main


def karma_global(plugin: str, export_root: str, output_root: str) -> int:
    """The local id of the converted plugin's karma global; exits when it has not been converted."""
    esm = str(plugin_esm(output_root, plugin, export_root))
    fid = MasterIndex(esm).find_by_edid(b'GLOB', KARMA_GLOBAL) if os.path.isfile(esm) else 0
    if not fid:
        raise SystemExit(f'{plugin}: no {KARMA_GLOBAL} in {esm} (convert it first)')
    return fid & 0xFFFFFF


def build_fallout(plugin: str, outdir: str, export_root: str, output_root: str, compile_psc: bool) -> bool:
    """Build a Fallout game's rules Data folder into `outdir`; True when it is shippable."""
    export_dir = str(record_dir(export_root, plugin))
    if masters_from_export_header(export_dir):
        raise SystemExit(f'{plugin} has masters; build the rules for its masterless game plugin')
    game_id = GAME_IDS.get(plugin.lower())
    if game_id is None:
        raise SystemExit(f'{plugin} is not a game TESGameSelect starts')
    records = parse_export_directory(export_dir, type_filter=set(EXPORT_TYPES))
    doc = character_data(group_records_by_type(records), [], plugin, game_of(export_dir))
    if not doc.get('skills'):
        raise SystemExit(f'{plugin}: no skills in its export (re-export it)')
    stem = os.path.splitext(plugin)[0]
    built = build_fallout_plugin(doc, ['Skyrim.esm', plugin], game_id,
                                 f'FalloutRules{stem.replace(" ", "")}',
                                 karma_global(plugin, export_root, output_root))
    return write_data_folder(outdir, f'{stem} Character Rules.esp', built, SCRIPTS, compile_psc)
