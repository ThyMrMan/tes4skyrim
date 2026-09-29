# Character systems: attributes, skills, leveling, perks and the menu

Design only. What is built, played and next lives in
[ROADMAP.md](ROADMAP.md#character); measurements and in-game checks live in
[research/character_findings.md](research/character_findings.md).

Goal: a converted game plays by its own character rules, not Skyrim's.
Morrowind and Oblivion keep their attributes, skills, classes, birthsigns and
leveling; Fallout 3 and New Vegas keep S.P.E.C.I.A.L., their skills, XP,
perks, traits, karma and reputation. All four share one core that is built
once, fed by each game's own records, instead of four separate systems built
one after another. The player sees each game's own character sheet, not
Skyrim's.

## Contents

- [Where this plan came from](#sources)
- [Decisions](#decisions)
- [The four games side by side](#side-by-side)
- [Design](#design)
- [Skills: the source game's, with Skyrim's values underneath](#skills)
- [The menu](#menu)
- [The pieces](#pieces)
- [Constraints every piece follows](#constraints)
- [Open questions](#open-questions)

## <a id="sources"></a>Where this plan came from

Three documents covered this ground. This file replaces the first and third;
the second is upstream's and stays in `docs/plans/`, unedited.

| | Classic character systems (fork) | [Character sheet](../plans/character_sheet.md) (upstream) | Character menu draft (fork) |
|---|---|---|---|
| Scope | All four games' rules: data, leveling, perks, standings | A Morrowind-style stats window over Skyrim, plus Nehrim's leveling | Which skills the menu shows and how they reach the engine |
| What it gave | The character data file; event-driven Papyrus rules; no base-game overrides; piece I's level-up gate, read from the exe; crediting folded skills by context; per-world and all-worlds profiles; Fallout XP, perks, karma, reputation | Menu plumbing from the working Morrowind menu (M1) and its art pipeline (M2); a per-actor stat store for player and NPCs, with the mid-game-install rebuild (M3); a Statistics tab (M9); Strict attribute rules with a skill cap; bugs B1-B8, most now fixed | Per-world skill tables with a store and a Skyrim target per skill; two family layouts; the question of which engine reads matter |
| Still used here | All of it | M1, M2, M3, M9 and the Strict cap, as options | All of it, with the fix below |

Where they disagreed, and what this plan does:

| Question | Classic | Character sheet | Menu draft | This plan |
|---|---|---|---|---|
| Who levels the player | The rules; Skyrim's level-up and perk point are withheld (built, piece I) | Skyrim's own level-up, then the sheet opens for attributes | The rules | **The rules**, as built |
| Skills shown | Not decided | Skyrim's 18, then 4 kept legacy skills | The world's own list | **The world's own list** |
| Governing stats | Per game, from the data | One table for every game | Per world | **Per world**, from the data |
| Which rules apply after travel | The starting world's | The current game (`TESGS_CurrentGame`, changes on travel) | The starting world's | **The starting world's** |
| Folded skills (Blade and Blunt into One-Handed) | Skyrim's value is the skill; each increase is credited to the source skill by context | Read as the higher of the two | Separate numbers; Skyrim's value takes the highest | **Separate numbers; Skyrim's value holds the one in use** ([why](#active-skill)) |
| Health, Magicka, Stamina | Attributes feed them (Endurance to health, and so on) | Skyrim's +10 choice stays; attributes never feed them | Not covered | **Open** ([question 3](#open-questions)) |
| Nehrim | Not covered | Central | Deprioritized | **Deprioritized**; the sheet's Nehrim sections stay upstream's |

The menu draft's "highest wins" rule did not survive a closer look. Under
skill-use rules Skyrim's own use still raises the shared value, at the pace of
that value's level. With Blade at 40 and Blunt at 30, One-Handed shows 40, so
swinging a mace would train Blunt at Blade's pace, and writing back the higher
value would undo every Blunt gain. [The active skill](#active-skill) fixes
both.

## <a id="decisions"></a>Decisions

These replace the questions this plan used to put to the upstream maintainer.
The fork no longer aims to stay equivalent to upstream.

1. **The runtimes own what Papyrus cannot.** `TESRuntime`,
   `MorrowindRuntime` and `FalloutRuntime` carry their game's parts, as
   `FalloutRuntime` already carries Fallout's.
2. **The Morrowind stat store moves into `tes_runtime/common`**, keyed by stat
   name, and becomes the store for every game's per-actor stats.
3. **The rules are a separate generated plugin per game** (as built).
4. **Rules follow the character's starting world**, read from
   `TESGameSelectQuest.ChosenGame`, in both profile types.
5. **The menu shows the world's own skills.** Skyrim's skills menu is not
   extended.
6. **No universal skill table.** Two families: Elder Scrolls (Morrowind,
   Oblivion) and Fallout (Fallout 3, New Vegas).
7. **A skill's effect is built with the system it acts on**, never ahead of
   it: Science with terminals, Medicine with healing items, Explosives with
   mines, Survival with recipes.

## <a id="side-by-side"></a>The four games side by side

| System | Morrowind | Oblivion | Fallout 3 / NV | Shared? |
|---|---|---|---|---|
| Primary stats | 8 attributes | the same 8 | 7 S.P.E.C.I.A.L. | Yes: a named-stat store |
| Skills | 27 | 21 | 13 (NV: Survival replaces Big Guns; Small Guns becomes Guns) | Yes: the list is data |
| Definitions | SKIL, CLAS, BSGN, RACE | SKIL, CLAS, BSGN, RACE | AVIF, PERK, CLAS, RACE | Yes: one data file |
| Leveling | Skill increases make a level; attribute bonuses | Same model, different numbers | XP; skill points per level; perks | One engine, two rule sets |
| Level-up screen | Pick attributes | Pick attributes | Spend skill points, pick a perk | Shared logic, per-game content |
| Character creation | Race, class, birthsign | Race, class, birthsign | S.P.E.C.I.A.L., tag skills; NV traits | Shared "pick from a list" screens |
| Passive bonuses | Birthsign, racial abilities | Birthsign, mastery bonuses | Perks, traits | Yes: Skyrim perks and abilities |
| Player standing | Reputation | Fame, infamy | Karma; NV per-faction fame and infamy | Yes: named values mirrored to GLOBs |
| Item condition, repair | Yes | Yes | Yes | Yes |
| Stat checks in dialogue | Yes | Yes | Speech and S.P.E.C.I.A.L. checks | Yes: conditions read the mirror |
| Disposition, persuasion | Yes (formula ported) | Yes (minigame) | No | Morrowind and Oblivion |
| Game-specific | Script interpreter (built) | Tumbler lockpicking, persuasion wheel | Guns (built), VATS, terminals, NV hardcore | No |

## <a id="design"></a>Design

### Data: one file per plugin

Import writes `<plugin>.character.json` beside the other runtime sidecars
([tes_runtime_fragments.md](../reference/tes_runtime_fragments.md)). One schema
for all four games:

- **stats**: name, the Skyrim actor value that carries it or none, range.
- **skills**: name, governing stat, specialization, use values, the Skyrim
  actor value it maps to or none.
- **rules**: `skill-use` (Morrowind, Oblivion) or `xp` (Fallout), with the
  numbers read from the game's own GMSTs.
- **classes, races, signs, traits**: their stat and skill effects, and the
  converted SPEL or PERK each grants.
- **standings**: reputation, fame, infamy, karma, per-faction reputation.

Sources: Morrowind and Oblivion from SKIL, CLAS, BSGN, RACE and GMST; Fallout
from AVIF, PERK, CLAS, RACE, REPU and GMST. Everything is data, so a plugin
that changes classes or birthsigns carries through with no code change.

### The player's rules need no DLL

Skyrim's Story Manager already raises an event for each of the things the
rules react to, and a quest's Papyrus script receives them
([checked](research/character_findings.md#checked)): `OnStoryIncreaseSkill(string asSkill)`,
`OnStoryIncreaseLevel`, `OnStoryKillActor`, `OnStoryPickLock`,
`OnStoryCastMagic`, `OnStoryCraftItem`, and `OnStoryBribeNPC` /
`OnStoryIntimidateNPC` / `OnStoryFlatterNPC`. So the player's stats can be
GLOBs, which dialogue and quest conditions read directly, advanced by a rules
quest that wakes only on those events: no polling, and no new DLL code. Effects
land through vanilla Papyrus (`ModActorValue` on the player).

### <a id="no-base-overrides"></a>No base-game overrides

Nothing in the plan overrides a `Skyrim.esm` record or setting. The maintainer
split out `FalloutRuntime.dll` so that new Fallout systems need not overwrite
base game data, and the plan applies the same rule to every game: a change to
how Skyrim itself behaves happens in the runtime, in memory, and only while a
converted game's rules are on. Two such changes are needed:

- **Skill XP rates.** Skyrim keeps them in its 18 skill `AVIF` records
  ([checked](research/character_findings.md#checked)). Overriding those would collide with any mod that
  changes skill rates, the last one loaded winning, and would change Skyrim's
  own skills whenever the plugin is loaded. The runtime instead rewrites the
  loaded skill records' rates while the rules are on. The per-action gains
  measure different things in each game (Skyrim's damage dealt or gold, where
  Oblivion counts uses), so Skyrim's stay; the threshold curve takes the
  source game's exponent and its class multipliers, anchored to Skyrim's own
  rates at level 25 (Oblivion's formula, read from `Oblivion.exe`, is
  `(level x fSkillUseFactor) ^ fSkillUseExp x specialization x major or
  minor`). Fallout's are zero, as its skills rise only by points.
- **Skyrim's own leveling.** With a game's rules on, Skyrim's character level
  still rises from its own skill experience, and its level-up screen and perk
  point still arrive, so the player would level twice. In data that means
  overriding `fXPLevelUpBase` and `fXPLevelUpMult`; the runtime instead
  withholds Skyrim's level-up and perk point while the rules are on. One gate
  covers both ([checked](research/character_findings.md#level-up-in-the-exe)): every call to the "can level
  up" check answers no, which writes nothing the save keeps, and
  `fXPLevelUpBase` is raised in memory for the "Level up available" message,
  which works from the settings instead.
- **Raising the player's level.** Skyrim's level is what leveled lists and
  encounter zones scale by, so when the source game's rules grant a level,
  Skyrim's must follow. The engine's own set-level routine does exactly that,
  with no level-up screen, no perk point and no Health, Magicka or Stamina
  bonus; Papyrus has no way to call it, so the rules quest asks the runtime
  with a mod event (`TESCharacterLevel`), the channel converted scripts
  already use for `TES4Spin`, rather than a new native, which the runtimes'
  standalone SKSE interface cannot register without SKSE's source.

Mechanics Skyrim has no counterpart for follow the same rule: Fallout's perk
entry points that Skyrim lacks (action points, VATS, gun spread, damage
threshold) belong to `FalloutRuntime`.

### <a id="profiles"></a>Per-world and all-worlds profiles

Players set up converted worlds in one of two ways, or both, and every piece
works in either ([standalone play](standalone_play.md) offers both as MO2 profiles):

- **A per-world profile** loads `Skyrim.esm`, one world's plugins and the
  runtime DLLs. Only that world's rules plugin is present.
- **An all-worlds profile** loads every converted world, and one character can
  travel between them. Every world's rules plugin is present at once.

So the rules follow the **character**, not the load order or the current
worldspace. A character plays by the rules of the world it started in:
TESGameSelect already records that choice in the save, as
`TESGameSelectQuest.ChosenGame`. A character who starts in Cyrodiil keeps
Oblivion's rules after crossing into Skyrim, and one who starts in Skyrim
keeps Skyrim's own rules in Cyrodiil. What that means for each part:

- **Rules quests and Story Manager nodes** carry a condition on the
  character's game, so another world's rules never start for this character
  and cost nothing in an all-worlds profile.
- **The runtime** (piece I) changes Skyrim's skill rates and leveling only for
  a character whose game has rules, and only that game's.
- **Menus** are chosen by the character's game, not by the world the player
  is standing in.
- **A character with no recorded game** (a save from before TESGameSelect, or
  one made with it absent) keeps today's behavior, as with any plugin that is
  switched off.

What stays with the profile choice rather than the plan: a per-world profile
is still the only way to get world-specific visual mods, a smaller memory
footprint and separate save folders, and an all-worlds profile the only way
to travel between worlds with one character. Choosing the world on Skyrim's
main menu, recorded by `TESRuntime.dll`, would remove TESGameSelect's
override of `MQ101` in both profile types; it is its own proposal, and this
plan works with either way of recording the choice.

### Runtime: one stat store, for what Papyrus cannot hold

Per-actor stats Skyrim lacks (an NPC's Strength, Morrowind's scripts reading
any actor's stats) do need the DLL. The Morrowind store moves into
`tes_runtime/common`, keyed by stat name rather than TES3 index:

- A stat Skyrim has stays Skyrim's actor value; a stat it lacks is the DLL's
  own number per actor, in a versioned co-save record (as `JRNL` is), starting
  at the actor record's authored value.
- The Morrowind interpreter reads it through the existing `ActorSkill` /
  `ActorAttribute` calls. Oblivion and Fallout scripts read it through new
  Papyrus natives, which the polyfill calls when the module is present and
  falls back to today's behavior when it is not.
- Values dialogue and quest conditions test (player stats, standings) are
  mirrored into GLOBs, written only when they change, as Morrowind's
  published state already does.

### Leveling: two rule sets

- **skill-use** (Morrowind, Oblivion): skill increases count toward the next
  level, and each increase credits its governing attribute's level-up bonus.
  Skills Skyrim has advance through Skyrim's own skill use; the rules credit
  the levels gained, not the events: on each `OnStoryIncreaseSkill`, each
  menu close and each game load they compare every skill with their last
  snapshot, because one event can carry several levels and increases inside
  a menu share one event ([checked in game](research/character_findings.md#in-game-results)). Where several source skills
  fold into one Skyrim skill (Blade and Blunt into One-Handed and Two-Handed;
  Mysticism's spells into Alteration; Mercantile and Speechcraft into Speech),
  the increase is credited by context: the weapon or spell last used, whether
  the player is trading ([checked](research/character_findings.md#skill-source)),
  and the Skyrim value holds that skill while it is in use
  ([the active skill](#active-skill)). Skyrim's own per-skill XP
  rates are set to the source game's, in memory by the runtime
  ([no base-game overrides](#no-base-overrides)).
- **xp** (Fallout): XP from quests (`RewardXP`), kills (`OnStoryKillActor`),
  and lock (`OnStoryPickLock`), hack and speech successes, with the amounts
  read from the game's own `iXPReward*` / `iXPLevelKill*` GMSTs; skill points
  per level from Intelligence; the perk schedule from the game's settings.

Some of those numbers are engine defaults that the master file never stores,
because it only carries settings that differ from them: Oblivion's leveling
table is in `Oblivion.exe`, not `Oblivion.esm` ([checked](research/character_findings.md#checked)). The data
file therefore merges a per-game table of engine defaults with the plugin's
own GMST overrides, so a plugin that changes a setting still wins.

Effects apply when a value changes (level-up, a Fortify effect landing), as
actor value modifiers: Strength to carry weight and melee damage, Endurance to
health, Intelligence to magicka, and so on. Nothing is recalculated per frame.

### Records: a separate generated plugin

The rules ship as their own generated plugin per game, beside the converted
one, as the vanilla creature swap plan does
([vanilla_creature_swap.md](../plans/vanilla_creature_swap.md)):

- mastery bonuses, birthsign and racial abilities as abilities or perks;
- FO3/FNV `PERK` records converted to Skyrim perks, in the converted plugin
  after all, since its dialogue conditions and scripts name them. The record structure is
  shared, but most entry points are not ([checked](research/character_findings.md#checked)): quest-stage and
  ability entries convert directly, entry points with a Skyrim counterpart
  convert through a name-keyed table, and the Fallout-only ones (action
  points, VATS, karma, radiation, hacking) are handled by `FalloutRuntime` or
  reported as unconverted;
- NV recipes (`RCPE`) as Skyrim constructible objects;
- the rules quest, its Story Manager nodes (new nodes attached to Skyrim's
  event nodes, which stay unedited), and the player-stat GLOBs.

A separate plugin keeps the feature off unless it is enabled, and its FormIDs
come from `derive_formid` with new sites in its own file, so no converted
plugin's FormIDs move. It only adds records: it overrides nothing in
`Skyrim.esm` ([no base-game overrides](#no-base-overrides)), so
`tools/validate/plugin_load_audit.py`'s check for vanilla overrides applies to
it unchanged.


## <a id="skills"></a>Skills: the source game's, with Skyrim's values underneath

The menu is written from scratch, so mapping a source skill onto a Skyrim
skill no longer buys a free UI. What a mapping still decides is the
**engine**: Skyrim reads its own actor values for weapon damage, armor rating,
prices, sneak detection, potion strength and smithing, and those reads cannot
be detached. So two things are kept apart:

- **The character's skills**, in the source game's terms: the number, its
  governing stat, what raises it, what the menu calls it. The rules own them.
- **Skyrim's actor values**, kept only where the engine reads one, and written
  from the character's skill.

### <a id="families"></a>Two families

| Family | Worlds | Skills | Stats | Levels by |
|---|---|---|---|---|
| Elder Scrolls | Morrowind, Oblivion | 27 / 21 | 8 attributes | skill-use increases |
| Fallout | Fallout 3, New Vegas | 13 (Big Guns hidden in NV, Throwing in FO3) | 7 S.P.E.C.I.A.L. | XP, then skill points at level-up |

### <a id="skill-table"></a>The skill table

One row per skill per world. `name`, `av`, `attribute` and `skyrim` already
come from the character data (`<plugin>.character.json`); the rest are new
columns.

| Column | Meaning |
|---|---|
| Stat | governing attribute or S.P.E.C.I.A.L. stat |
| Group | the menu section: specialization for Elder Scrolls, none for Fallout |
| Store | `AV`: a Skyrim actor value is the skill itself. `OWN`: the rules keep it (a global for the player, the stat store for NPCs) |
| Drives | the Skyrim actor value it is written into, when the engine reads one |
| Effect | what the rules must supply when `Drives` is empty |

Under skill-use rules, Skyrim's own use still advances a skill (piece I sets
its rate), so a skill Skyrim has is `AV`. Under XP rules the runtime zeroes
Skyrim's skill use, so every Fallout skill is `OWN`.

### <a id="active-skill"></a>The active skill

Where several source skills drive one Skyrim value, that value holds **the
source skill in use**, not the highest:

- **When:** equipping a weapon (Blade, Blunt, Guns, Energy Weapons, Melee),
  casting a spell (Mysticism), opening the barter menu (Mercantile against
  Speechcraft). These are the context events the crediting already uses
  ([checked](research/character_findings.md#skill-source)).
- **What:** the rules write that skill's value into the Skyrim value, then
  update their own snapshot, so the write is not credited as a gain. The
  console's `SetAV` sends no skill event
  ([checked](research/character_findings.md#in-game-results)); Papyrus's
  `SetActorValue` is check S1.
- **Why it works:** the engine's damage, price and XP-pace reads then see the
  skill actually in use, and each increase lands on the right skill by the
  crediting that is already designed.
- **Scripts and conditions** read the source skill's global, not the Skyrim
  value.

### <a id="ob"></a>Oblivion (21)

| Skill | Group | Stat | Store | Drives | Effect to supply |
|---|---|---|---|---|---|
| Blade | Combat | Strength | OWN | One-Handed, Two-Handed (active) | none |
| Blunt | Combat | Strength | OWN | One-Handed, Two-Handed (active) | none |
| Hand to Hand | Combat | Strength | OWN | Unarmed Damage | unarmed and fatigue damage |
| Block | Combat | Endurance | AV | | none |
| Armorer | Combat | Endurance | AV (Smithing) | | none |
| Heavy Armor | Combat | Endurance | AV | | none |
| Athletics | Combat | Speed | OWN | | run and swim speed |
| Light Armor | Stealth | Speed | AV | | none |
| Acrobatics | Stealth | Speed | OWN | | jump height, fall damage |
| Marksman | Stealth | Agility | AV (Archery) | | none |
| Security | Stealth | Agility | AV (Lockpicking) | | none |
| Sneak | Stealth | Agility | AV | | none |
| Mercantile | Stealth | Personality | OWN | Speech (active in barter) | none |
| Speechcraft | Stealth | Personality | OWN | Speech (active otherwise) | none |
| Alchemy | Magic | Intelligence | AV | | none |
| Conjuration | Magic | Intelligence | AV | | none |
| Mysticism | Magic | Intelligence | OWN | Alteration, Conjuration (active on cast) | none |
| Alteration | Magic | Willpower | AV | | none |
| Destruction | Magic | Willpower | AV | | none |
| Restoration | Magic | Willpower | AV | | none |
| Illusion | Magic | Personality | AV | | none |

### <a id="fnv"></a>New Vegas (13 shown)

Fallout 3 has the same rows with Throwing in place of Survival, governed as
`character_data_falloutnv.py` `_SURVIVAL` says.

| Skill | Stat | Drives | Effect to supply, with its system |
|---|---|---|---|
| Barter | Charisma | Speech (active in barter) | none |
| Speech | Charisma | Speech (active otherwise) | none: speech challenges roll the global (built for Fallout 3) |
| Lockpick | Perception | Lockpicking | lock tiers |
| Repair | Intelligence | Smithing | item condition (piece H) |
| Sneak | Agility | Sneak | none |
| Guns | Agility | Marksman (active) | damage, spread (`FalloutRuntime`) |
| Energy Weapons | Perception | Marksman (active) | the same |
| Melee Weapons | Strength | One-Handed, Two-Handed (active) | none |
| Unarmed | Endurance | Unarmed Damage | none |
| Explosives | Perception | | mines and grenades |
| Medicine | Intelligence | | healing items |
| Science | Intelligence | | terminals (`TERM` is a plain activator today) |
| Survival | Endurance | | recipes (`RCPE` is not imported) |

The effects column summarizes how the games play; each formula must be read
from `Fallout3.exe` before it is built, as piece E's were.

### <a id="mw"></a>Morrowind (27)

Rows to be generated from `Morrowind.esm` `SKIL`. The folds already settled
upstream carry over as `Drives`: Long Blade, Axe and Blunt Weapon to One- and
Two-Handed; Short Blade to One-Handed; Spear to Two-Handed; Medium Armor to
Light and Heavy Armor; Mysticism to Alteration; Mercantile to Speech; Enchant
to Enchanting. Morrowind adds the major, minor and miscellaneous split.

## <a id="menu"></a>The menu

Message boxes first, as the Fallout chargen, perk and trait menus already are
([menus](../commentary/character_rules.md#fallout-perks)). Then one custom
menu shell with two layouts, both read from the skill table, so the shell
holds no per-skill code:

- **Plumbing:** the working custom `IMenu` moves from
  `tes_runtime/morrowind/plugin/menu.cpp` into `tes_runtime/common/`
  (upstream's [M1](../plans/character_sheet.md#m1-menu)).
- **Art:** each family's art from that game's own install, as the Morrowind
  dialogue menu is built (upstream's [M2](../plans/character_sheet.md#m2-swf)).
  Oblivion and Fallout each need an extractor beside
  `asset_convert/ui/morrowind_menu_art.py`. No install means no sheet.
- **Read-only first.** The first sheet only shows values; it writes nothing, so
  it cannot damage a save. Level-up and chargen move into it afterwards.
- **Chosen by the character's game**, not the world the player stands in.

```
Elder Scrolls                               Fallout
+-----------------------------------------+ +-----------------------------------+
| Name  Race  Class        Level 7 [xp]   | | STATS  SKILLS  PERKS  GENERAL     |
+--------------+--------------------------+ +-----------------------------------+
| Strength  52 | COMBAT   MAGIC   STEALTH | | Barter        25  tag  | details  |
| Intellig. 44 | Blade 45 Alch 30 Acro 25 | | Energy Weap.  30       | governed |
| ...          | ...                      | | ...                    | by, what |
| Luck      50 |                          | |                        | it does  |
+--------------+--------------------------+ +-----------------------------------+
| tooltip: stat, raised by, what it does  | | Level 9  XP 8,400/9,000  Points 12|
+-----------------------------------------+ +-----------------------------------+
```

Morrowind uses the Elder Scrolls grid with major, minor and miscellaneous
panels in place of specializations. Fallout's `GENERAL` tab shows karma,
reputations and factions from the data's `alignments`, `reputations` and
`factions`; a Statistics tab follows upstream's
[M9](../plans/character_sheet.md#m9-statistics).

## <a id="pieces"></a>The pieces

Status of each is in the [roadmap](ROADMAP.md#character).

| # | Piece | Where | Depends on |
|---|---|---|---|
| A | Character data, all four games, engine defaults merged under each plugin's GMSTs | `tes5_import/character_data*.py`, `tes4_export/record_types/character_falloutnv.py` | nothing |
| I | Skyrim's behavior while a game's rules are on: source XP rates, Skyrim's level-up and perk point withheld, a mod event that sets the level | `tes_runtime/tes/character_rules.cpp` | A |
| D | Skill-use leveling: rules quest on story events, player stats as globals, level-up | `tools/release/make_character_rules_esp.py`, `character_rules/` | A, I |
| E | Fallout XP leveling, perks and traits, karma and reputation | `tools/release/character_rules_falloutnv.py`, `tes5_import/*_falloutnv.py` | A, I |
| B | Shared per-actor stat store; Morrowind switched over with identical behavior | `tes_runtime/common/` | A |
| C | Papyrus natives over B for NPC stats | `tes_runtime/tes/`, `script_convert/` | B |
| T | The skill table's new columns (store, drives, group) in the character data, plus Morrowind's rows | `tes5_import/character_data*.py` | A |
| G1 | Read-only stats sheet: shell, Oblivion layout, then Fallout's | `tes_runtime/common/`, `tools/generators/` | T |
| F | Own-store skills and [the active skill](#active-skill) | rules plugin | T, and the checks below |
| G2 | Level-up and chargen moved into the sheet | `tes_runtime/`, rules plugin | G1, F |
| H | Item condition and repair | `tes_runtime/`, import | B |
| J | Skill effects, each with its system (terminals, healing items, mines, recipes, movement) | per system | F |

**Checks before F** (none needs the user's game time until the last):

| # | Question | Where to look |
|---|---|---|
| S1 | Does writing a skill value fire perk entry points or other events that loop back? | `probes\skill_event_probe` |
| S2 | What in 1.6.1170 reads each skill's actor value? Decides which `Drives` matter | `skyrim_disasm.py` on the unpacked exe |
| S3 | Is `UnarmedDamage` a writable per-actor value? | the same probe |
| S4 | Does swapping the active skill on equip keep up with fast weapon switches? | in game, after S1 |

## <a id="order"></a>Order

1. Play the written pieces that have not been played (list in the
   [roadmap](ROADMAP.md#character)).
2. T, then G1: data and a sheet that writes nothing.
3. S1 to S3, then F.
4. G2, then H and J by gameplay value.

## <a id="constraints"></a>Constraints every piece follows

- **Off by default.** Nothing changes for a player who has not enabled it.
- **No base-game overrides.** No `Skyrim.esm` record or setting is
  overridden; a change to how Skyrim behaves lives in the runtime, only while
  a converted game's rules are on ([why](#no-base-overrides)).
- **Both profile types.** Every piece works in a per-world profile and in an
  all-worlds profile, keyed on the character's starting world; a piece that
  behaves differently in the two says how ([profiles](#profiles)).
- **One branch per piece**, each useful alone; no output without a reader.
- **Generic.** Every rule comes from the plugin's own records and GMSTs, never
  from a table naming one plugin.
- **New modules, one-line hooks.** `import_main.py`, `convert.py` and `gui.py`
  get a call, not a feature.
- **Saves survive.** Co-save records are versioned; a missing or older data
  file degrades to today's behavior
  ([end-user state](../../CLAUDE.md#end-user-state)).
- **Headless tests.** Leveling and effect rules are pure logic: computed at
  import in Python and tested there, or, in the DLL, tested the way
  `store_test.cpp`, `filter_test.cpp` and `alchemy_test.cpp` test theirs.
- **Licensing.** Oblivion and Fallout rules are written from their own records
  and documented formulas. Code ported from OpenMW (GPL-3.0) stays in the
  Morrowind module.

## <a id="open-questions"></a>Open questions

1. **Licensing.** The repo has no `LICENSE` file, the About box says MIT, and
   `external/openmw` is GPL-3.0. Where does the boundary sit for runtime code
   shared between the Morrowind module and the rest?
2. **Skyrim's perk points.** Piece I withholds them while a game's rules are
   on. Should they stay available as an option beside the source game's
   rules?
3. **Health, Magicka and Stamina.** Do attributes feed them (Endurance to
   health, as the source games do), or does Skyrim's +10 choice stay?
4. **Strict attribute rules** (upstream's
   [skill cap](../plans/character_sheet.md#rules)): offered as a new-game
   option, or left out?
