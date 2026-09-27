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
from output_layout import record_dir
from tes5_import.base.constants import TES4_ATTRIBUTE_NAMES, TES5_SKILL_ORDER
from tes5_import.base.text_reader import group_records_by_type, parse_export_directory
from tes5_import.base.writer import (count_records_and_groups, pack_formid_subrecord, pack_record,
                                     pack_string_subrecord, pack_tes4_header, pack_top_group,
                                     pack_uint32_subrecord)
from tes5_import.character_data_falloutnv import character_data, game_of
from tes5_import.record_types.world_falloutnv import FALLOUT_ONLY_SIGS
from tools.release.character_rules_records import (Forms, Obj, build_event_quest, build_glob,
                                                   build_main_quest, build_node, pack_script,
                                                   write_data_folder)
from tools.release.make_game_select_esp import FALLOUT_ONLY_STATS, FID_GLOB_PLAYER_ATTRIBUTES

SCRIPTS = ('FalloutRules_Main', 'FalloutRules_Player', 'FalloutRules_KillEvent', 'FalloutRules_LockEvent')

#: The records character_data_falloutnv reads for the rules.
EXPORT_TYPES = frozenset({'AVIF', 'CLAS', 'GMST', 'NPC_'})

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

#: Skyrim.esm KYWD ActorTypeNPC: people; converted creatures carry ActorTypeCreature or ActorTypeAnimal.
ACTOR_TYPE_NPC = 0x00013794

#: Quests per event node, so events close together each find one not already running.
EVENT_POOL = 4

#: Source skills a Skyrim skill can carry (Marksman: Small Guns, Energy Weapons, Big Guns).
SOURCES_PER_SKILL = 3

#: Skill buttons on the menu's first page: with the points left, a message shows at most nine values.
FIRST_PAGE_SKILLS = 8

#: Skill points per Intelligence per interval: New Vegas gives half a point (carried), Fallout 3 one.
_INTELLIGENCE_SHARE = {'falloutnv': 0.5, 'fallout3': 1.0}

#: New Vegas awards the kills of the player's companions too; Fallout 3 only the player's.
_TEAMMATE_KILLS = {'falloutnv': 1, 'fallout3': 0}

#: The skill menu's prompt and page buttons, and the notification words.
SKILL_MENU_PROMPT, MORE_BUTTON, BACK_BUTTON = 'Skill points to spend: %.0f', 'More skills', 'Back'
TEXTS = {'XPText': 'XP', 'LevelText': 'Level'}


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
    """The rules' numbers: the XP curve, skill points, skill formula and the reward tables."""
    interval = settings['iLevelUpSkillPointsInterval']
    out = {'XPBase': settings['iXPBase'], 'XPBumpBase': settings['iXPBumpBase'],
           'MaxLevel': settings['iMaxCharacterLevel'],
           'SkillPointsOffset': float(settings['iLevelUpSkillPointsBase'] - interval),
           'SkillPointsPerIntelligence': float(interval * _INTELLIGENCE_SHARE[game]),
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

def build_skill_menu(fid: int, edid: str, names: list, last_button: str) -> bytes:
    """One page of the skill menu: the points left, each skill's value, a button per skill and one more."""
    lines = [SKILL_MENU_PROMPT, ''] + [f'{name} %.0f' for name in names]
    subs = pack_string_subrecord('EDID', edid) + pack_string_subrecord('DESC', '\n'.join(lines))
    subs += pack_formid_subrecord('INAM', 0) + pack_uint32_subrecord('DNAM', 1)
    subs += b''.join(pack_string_subrecord('ITXT', name) for name in [*names, last_button])
    return pack_record('MESG', fid, 0, subs)


def build_fallout_plugin(doc: dict, masters: list, game_id: int, prefix: str) -> tuple:
    """The plugin's bytes, record count and rules quest, for `doc` from the masterless plugin masters[-1]."""
    forms = Forms(masters)
    active, main, first, second, kill_node, lock_node = (forms.new() for _ in range(6))
    kills = [forms.new() for _ in range(EVENT_POOL)]
    locks = [forms.new() for _ in range(EVENT_POOL)]
    names = [skill['name'] for skill in shown_skills(doc)]
    props = {'Plugin': masters[-1], 'GameId': game_id, 'Active': Obj(active),
             'ActorTypeNPC': Obj(forms.of(['Skyrim.esm', ACTOR_TYPE_NPC])),
             'SkillMenu': Obj(first), 'SkillMenuMore': Obj(second), 'FirstPageSkills': FIRST_PAGE_SKILLS,
             'SpecialGlobals': special_globals(), **skill_table(doc), **player_table(doc),
             **settings_table(doc['settings'], doc['game']), **TEXTS}
    quests = build_main_quest(main, f'{prefix}CharacterRules', pack_script(SCRIPTS[0], props), SCRIPTS[1])
    quests += b''.join(build_event_quest(fid, f'{prefix}Kill{i}', b'KILL', SCRIPTS[2], main)
                       for i, fid in enumerate(kills))
    quests += b''.join(build_event_quest(fid, f'{prefix}PickLock{i}', b'LOCK', SCRIPTS[3], main)
                       for i, fid in enumerate(locks))
    menus = (build_skill_menu(first, f'{prefix}SkillMenu', names[:FIRST_PAGE_SKILLS], MORE_BUTTON)
             + build_skill_menu(second, f'{prefix}SkillMenuMore', names[FIRST_PAGE_SKILLS:], BACK_BUTTON))
    nodes = (build_node(kill_node, f'{prefix}KillNode', (KILL_EVENT_NODE, KILL_EVENT_LAST_CHILD), kills, active)
             + build_node(lock_node, f'{prefix}PickLockNode', (LOCK_EVENT_NODE, 0), locks, active))
    groups = [pack_top_group('GLOB', build_glob(active, f'{prefix}RulesActive')),
              pack_top_group('MESG', menus), pack_top_group('QUST', quests), pack_top_group('SMQN', nodes)]
    count = sum(count_records_and_groups(group) for group in groups)
    header = pack_tes4_header(masters, num_records=count, next_object_id=forms.next,
                              author='TESConversion',
                              description=f'{masters[-1]} character rules', is_esm=False)
    return header + b''.join(groups), count, main


def build_fallout(plugin: str, outdir: str, export_root: str, compile_psc: bool) -> bool:
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
                                 f'FalloutRules{stem.replace(" ", "")}')
    return write_data_folder(outdir, f'{stem} Character Rules.esp', built, SCRIPTS, compile_psc)
