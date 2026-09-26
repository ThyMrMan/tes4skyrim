# Classic character systems: attributes, skills, leveling and perks - design plan

**Status: PLAN, unimplemented.** No code has been written. Every piece below is
meant to land as its own small PR, and every piece is off by default.

Goal: a converted game plays by its own character rules, not Skyrim's.
Morrowind and Oblivion keep their attributes, skills, classes, birthsigns and
leveling; Fallout 3 and New Vegas keep S.P.E.C.I.A.L., their skills, XP,
perks, traits, karma and reputation. All four share one core that is built
once, fed by each game's own records, instead of four separate systems built
one after another.

## Contents

- [Where things stand](#where-things-stand)
- [The four games side by side](#side-by-side)
- [Design](#design)
- [The pieces](#pieces)
- [Suggested order](#order)
- [Constraints every piece follows](#constraints)
- [Performance](#performance)
- [Checked, and still to check](#checked)
- [Open questions for the maintainer](#open-questions)

## <a id="where-things-stand"></a>Where things stand

Each game loses the same things today, in parallel:

- **Morrowind** is the furthest along. `MorrowindRuntime` already keeps every
  stat Skyrim lacks (all 8 attributes, Athletics, Acrobatics) as its own
  number per actor in the co-save, read by both script commands and the
  dialogue filter
  ([morrowind_runtime.md](../commentary/morrowind_runtime.md#stat-commands)).
  Values the engine must see, such as reputation, are copied into GLOBs each
  tick ([published state](../commentary/morrowind_runtime.md#published-state)).
  Import already derives autocalc NPC stats from race, class and skill records
  (`tes5_import/dialogue/morrowind_autocalc.py`). Nothing levels.
- **Oblivion** skips `SKIL`, `BSGN`, `RACE` and `GMST` at import
  (`tes5_import/registry.py` `SKIP_TYPES`). Every attribute read in a converted
  script returns 100 (`TES4Polyfill.psc` `IsTES4Attribute` /
  `TES4AttributeStub`), so attribute gates always pass; that is deliberate,
  because a Skyrim character cannot raise an attribute. Athletics and
  Acrobatics read Stamina. Birthsigns already work: the converted chargen
  grants the chosen sign's spells, and the class choice is saved in the GLOB
  `TES4ChargenClassChoice`, but the class has no effect
  (`script_convert/message_menus.py`).
- **Fallout 3 / New Vegas**: `script_convert/constants_falloutnv.py` stubs
  `RewardXP` ("Skyrim has no experience points"), `HasPerk` (read as 0), every
  reputation command (read as 0) and Pip-Boy notes. `PERK`, `AVIF`, `RCPE` and
  `CHAL` are not imported; `TERM` and `NOTE` become plain activators. The
  condition remap already maps FNV `HasPerk` (449) onto Skyrim's (448)
  (`tes5_import/generated/ctda_fnv_remap.py`). Guns are handled by
  `FalloutRuntime`.

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

### The player's side needs no DLL

Skyrim's Story Manager already raises an event for each of the things the
rules react to, and a quest's Papyrus script receives them
([checked](#checked)): `OnStoryIncreaseSkill(string asSkill)`,
`OnStoryIncreaseLevel`, `OnStoryKillActor`, `OnStoryPickLock`,
`OnStoryCastMagic`, `OnStoryCraftItem`, and `OnStoryBribeNPC` /
`OnStoryIntimidateNPC` / `OnStoryFlatterNPC`. So the player's stats can be
GLOBs, which dialogue and quest conditions read directly, advanced by a rules
quest that wakes only on those events: no polling, and no new DLL code. Effects
land through vanilla Papyrus (`ModActorValue` on the player).

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
  Skills Skyrim has advance through Skyrim's own skill use; the rules only
  count the increases (`OnStoryIncreaseSkill`). Where several source skills
  fold into one Skyrim skill (Blade and Blunt into One-Handed; Mercantile and
  Speechcraft into Speech), the increase is credited by context: the equipped
  weapon's type, whether the player is trading. Skyrim's own per-skill XP
  rates can be set from the source game's skill records, since both live in
  records ([checked](#checked)).
- **xp** (Fallout): XP from quests (`RewardXP`), kills (`OnStoryKillActor`),
  and lock (`OnStoryPickLock`), hack and speech successes, with the amounts
  read from the game's own `iXPReward*` / `iXPLevelKill*` GMSTs; skill points
  per level from Intelligence; the perk schedule from the game's settings.

Some of those numbers are engine defaults that the master file never stores,
because it only carries settings that differ from them: Oblivion's leveling
table is in `Oblivion.exe`, not `Oblivion.esm` ([checked](#checked)). The data
file therefore merges a per-game table of engine defaults with the plugin's
own GMST overrides, so a plugin that changes a setting still wins.

Effects apply when a value changes (level-up, a Fortify effect landing), as
actor value modifiers: Strength to carry weight and melee damage, Endurance to
health, Intelligence to magicka, and so on. Nothing is recalculated per frame.

### Records: a separate generated plugin

The rules ship as their own generated plugin per game, beside the converted
one, as the vanilla creature swap plan does
([vanilla_creature_swap.md](vanilla_creature_swap.md)):

- mastery bonuses, birthsign and racial abilities as abilities or perks;
- FO3/FNV `PERK` records converted to Skyrim perks. The two share their
  structure ([checked](#checked)), so this is close to direct; the entry-point
  numbering still needs a mapping table;
- NV recipes (`RCPE`) as Skyrim constructible objects;
- the rules quest, its Story Manager event nodes, and the player-stat GLOBs;
- overrides of Skyrim's skill `AVIF` records, carrying the source game's XP
  rates.

A separate plugin keeps the feature off unless it is enabled, and its FormIDs
come from `derive_formid` with new sites in its own file, so no converted
plugin's FormIDs move. The `AVIF` overrides are the one place it deliberately
edits Skyrim.esm records; `tools/validate/plugin_load_audit.py` flags vanilla
overrides in converted output, so the rules plugin needs its own whitelist
there.

### Menus

Message boxes first: the level-up choice works as a `Message.Show()` chain,
the way the chargen class and birthsign menus already do. Real menus follow by
generalizing `tools/generators/gen_morrowind_menu_swf.py`, which already builds
a standalone movie from the source game's own art and draws in game
([the real menu](../commentary/morrowind_runtime.md#the-real-menu)), with one
art source per game read from that game's install.

## <a id="pieces"></a>The pieces

| # | Piece | Where | Depends on |
|---|---|---|---|
| A | Character data, all four games, with engine defaults merged under each plugin's GMSTs | `tes5_import/` new module | nothing |
| D | Skill-use leveling for the player: rules quest on story events, GLOB stats, message-box level-up, class effects; the polyfill reads the GLOBs. No DLL | rules plugin, `script_convert/` | A |
| E | Fallout XP leveling on story events, perk and trait conversion, karma and reputation. No DLL | `tes5_import/*_falloutnv.py`, rules plugin | A |
| B | Shared stat store for per-actor stats; Morrowind switched over with identical behavior | `tes_runtime/common/` | A |
| C | Papyrus natives over B for NPC stats; the polyfill and FNV stubs call through | `tes_runtime/tes/`, `script_convert/` | B |
| F | Skills Skyrim lacks: Athletics, Acrobatics, Hand to Hand, Mysticism, Mercantile, and Fallout's unmapped skills | rules plugin, `tes_runtime/` if an event is missing | D or E |
| G | Menus: level-up, stats sheet, chargen pickers | `tools/generators/`, `tes_runtime/` | D or E |
| H | Item condition and repair | `tes_runtime/`, import | B |

## <a id="order"></a>Suggested order

1. **A with D, for Oblivion**: the character data and the player's leveling,
   with no DLL work, so it needs no sign-off beyond the feature itself. It
   lets attribute gates be real without locking anyone out.
2. **E**: Fallout's XP and perks the same way; the perk records map closely
   onto Skyrim's.
3. **B and C** where per-actor stats matter: Morrowind first, proven by
   behaving exactly as before, then NPC stat reads for the other games.
4. **F, G, H** on top.

## <a id="constraints"></a>Constraints every piece follows

- **Off by default.** Nothing changes for a player who has not enabled it.
- **One PR per piece**, each useful alone; no output without a reader.
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

## <a id="performance"></a>Performance

The DLL side is cheap when it is event-driven. Measured so far: the Morrowind
tick costs 0.03 ms over the real Morrowind, Tribunal and Bloodmoon sidecars
(10,640 placements), about 0.015 ms per frame at 60 fps. The one fps incident
was a timer that re-ran the tick back to back after about 156 hours of uptime
([whole milliseconds](../commentary/morrowind_runtime.md#the-tick-sleeps-whole-milliseconds)),
not the tick's own work.

Papyrus is the bigger risk: the script conversion census counts 1,335
`GameMode` blocks across 2,393 TES4 scripts, each already an `OnUpdate` poll
([scope](../commentary/script_convert.md#scope)). The systems layer
therefore never polls from Papyrus: its Papyrus runs only when a Story Manager
event fires, and anything that needs more lives in C++. Either way it:

1. reacts to engine events (skill increases, kills, casts, locks, sales)
   rather than polling; any poll in C++ runs at most every 33 ms and does
   nothing unless something changed;
2. precomputes tables at import and resolves FormIDs once per load;
3. applies effects when values change, never per frame;
4. writes a GLOB only when its value changes;
5. keeps a custom menu's per-frame callback trivial;
6. does nothing when its game's plugin is not loaded;
7. sleeps in whole milliseconds with at most one tick queued
   ([one queued tick](../commentary/morrowind_runtime.md#one-queued-tick));
8. records a headless benchmark and an in-game frame-time comparison, DLL on
   and off, in each piece's commentary doc.

## <a id="checked"></a>Checked, and still to check

Read from the installed Skyrim SE, Oblivion and New Vegas files:

- **Skill increases are an engine event.** `Skyrim.esm` has 24 Story Manager
  event nodes (`SMEN`), one of them `SKIL` (Skill Increase), beside `LEVL`,
  `KILL`, `LOCK`, `CAST`, `CRFT`, `BRIB`, `INTM` and `FLAT`. Skyrim's own
  `Quest.psc` declares the matching events, `OnStoryIncreaseSkill(string
  asSkill)` among them.
- **Skyrim's per-skill XP rates are records.** 20 of `Skyrim.esm`'s 149 `AVIF`
  records carry a 16-byte `AVSK` (four floats: the skill's use and improve
  multipliers and offsets; confirm the field order against xEdit), one per
  skill plus two regeneration modifiers; for
  example One-Handed is 6.3 / 0 / 2 / 0 and Smithing 160 / 0 / 0.25 / 300. An
  override plugin can set them. Skyrim's Illusion skill is the record named
  `AVMysticism`.
- **Oblivion's leveling table is engine defaults.** `Oblivion.esm` stores no
  leveling GMSTs; `Oblivion.exe` registers them with these defaults, read from
  the push before each name: `iLevelUpSkillCount` 10; `iLevelUp01Mult` to
  `iLevelUp04Mult` 2; `iLevelUp05Mult` to `iLevelUp07Mult` 3; `iLevelUp08Mult`
  and `iLevelUp09Mult` 4; `iLevelUp10Mult` 5. `Oblivion.esm` does carry the
  skill-use curve, `fSkillUseExp` 1.5 and `fSkillUseFactor` 0.35, and its 21
  `SKIL` records each give a governing attribute, a specialization and two use
  values (Athletics 0.03 / 0.04, Speechcraft 2.4 / 1).
- **Fallout perks share Skyrim's structure.** `FalloutNV.esm` has 176 `PERK`
  records, `Skyrim.esm` 375. Both use `DATA`, `PRKE`, `PRKC`, `CTDA`, `EPFT`,
  `EPFD`, `PRKF`, `EPF2` and `EPF3`, with the same three entry kinds (quest
  stage, ability, entry point). New Vegas adds icons (169) and inline scripts
  on 5 perks; Skyrim adds `VMAD`, `NNAM` and `CIS2`.
- **New Vegas's XP rules are GMSTs.** `iLevelUpSkillPointsBase` 11,
  `iLevelUpSkillPointsInterval` 1, `fAVDTagSkillBonus` 15, `fBookPerkBonus` 3,
  `iTraitMenuMaxNumTraits` 2, and XP rewards per difficulty for kills,
  picked locks, hacked terminals, speech challenges and map markers
  (`iXPRewardKillOpponent*`, `iXPRewardPickLock*`, `iXPRewardHackComputer*`,
  `iXPLevelKill*`, `iXPRewardDiscoverMapMarker` 10). `iLevelsPerPerk` exists
  in `FalloutNV.exe` but not in the master; its default was not read.

Still to check:

- The mapping from FO3/FNV perk entry-point numbers to Skyrim's (needs the
  xEdit definitions).
- `iLevelsPerPerk`'s default, and Fallout 3 in general (not installed where
  this was checked; most Fallout notes so far are New Vegas).
- Morrowind's leveling settings (not installed where this was checked;
  OpenMW's source documents them).
- How Nehrim, which changes Oblivion's leveling, expresses that in its records
  and scripts (not installed where this was checked).
- Whether a skill increase can be told apart by source skill in every folded
  case (Blade or Blunt, Mercantile or Speechcraft) from what Papyrus can see
  at the moment the event fires.

## <a id="open-questions"></a>Open questions for the maintainer

1. The player's side (pieces A, D, E) needs no DLL. Is new `tes_runtime`
   functionality for the rest (per-actor stats, menus, item condition) wanted
   at all, given DLLs are a last resort?
2. Is moving the Morrowind stat store into `tes_runtime/common` acceptable, and
   in what shape?
3. The repo has no `LICENSE` file, while the About box says MIT and
   `external/openmw` is GPL-3.0. Where should the boundary sit for shared
   runtime code?
4. Separate rules plugin, or records inside the converted plugin behind a flag?
5. Should Skyrim's own perk points and leveling be switched off when a game's
   rules are on, or run alongside?
