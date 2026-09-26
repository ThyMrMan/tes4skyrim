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

### The player's rules need no DLL

Skyrim's Story Manager already raises an event for each of the things the
rules react to, and a quest's Papyrus script receives them
([checked](#checked)): `OnStoryIncreaseSkill(string asSkill)`,
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
  ([checked](#checked)). Overriding those would collide with any mod that
  changes skill rates, the last one loaded winning, and would change Skyrim's
  own skills whenever the plugin is loaded. The runtime instead writes the
  source game's rates, from the character data file, into the loaded skill
  records at load: Oblivion's and Morrowind's from their skill records, and
  zero for Fallout, whose skills rise only by points.
- **Skyrim's own leveling.** With a game's rules on, Skyrim's character level
  still rises from its own skill experience, and its level-up screen and perk
  point still arrive, so the player would level twice. In data that means
  overriding `fXPLevelUpBase` and `fXPLevelUpMult`; the runtime instead
  withholds Skyrim's level-up and perk point while the rules are on.

Mechanics Skyrim has no counterpart for follow the same rule: Fallout's perk
entry points that Skyrim lacks (action points, VATS, gun spread, damage
threshold) belong to `FalloutRuntime`.

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
  fold into one Skyrim skill (Blade and Blunt into One-Handed and Two-Handed;
  Mysticism's spells into Alteration; Mercantile and Speechcraft into Speech),
  the increase is credited by context: the weapon or spell last used, whether
  the player is trading ([checked](#skill-source)). Skyrim's own per-skill XP
  rates are set to the source game's, in memory by the runtime
  ([no base-game overrides](#no-base-overrides)).
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
- FO3/FNV `PERK` records converted to Skyrim perks. The record structure is
  shared, but most entry points are not ([checked](#checked)): quest-stage and
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
| I | Skyrim's behavior while a game's rules are on, in memory: the source game's skill XP rates, and Skyrim's level-up and perk point withheld | `tes_runtime/common/`, called by each game's runtime | A |
| D | Skill-use leveling for the player: rules quest on story events, GLOB stats, message-box level-up, class effects; the polyfill reads the GLOBs | rules plugin, `script_convert/` | A, I |
| E | Fallout XP leveling on story events, perk and trait conversion, karma and reputation; Fallout-only perk entry points | `tes5_import/*_falloutnv.py`, rules plugin, `tes_runtime/fallout/` | A, I |
| B | Shared stat store for per-actor stats; Morrowind switched over with identical behavior | `tes_runtime/common/` | A |
| C | Papyrus natives over B for NPC stats; the polyfill and FNV stubs call through | `tes_runtime/tes/`, `script_convert/` | B |
| F | Skills Skyrim lacks: Athletics, Acrobatics, Hand to Hand, Mysticism, Mercantile, and Fallout's unmapped skills | rules plugin, `tes_runtime/` if an event is missing | D or E |
| G | Menus: level-up, stats sheet, chargen pickers | `tools/generators/`, `tes_runtime/` | D or E |
| H | Item condition and repair | `tes_runtime/`, import | B |

## <a id="order"></a>Suggested order

1. **A, I and D, for Oblivion**: the character data, the runtime's two
   changes to Skyrim's own leveling, and the player's leveling. The rules
   themselves are Papyrus and new records; I is the only runtime work. It
   lets attribute gates be real without locking anyone out.
2. **E**: Fallout's XP and perks the same way. Most perk entries convert
   directly (84% for Fallout 3, 62% for New Vegas, counted); the
   Fallout-only mechanics go to `FalloutRuntime`.
3. **B and C** where per-actor stats matter: Morrowind first, proven by
   behaving exactly as before, then NPC stat reads for the other games.
4. **F, G, H** on top.

## <a id="constraints"></a>Constraints every piece follows

- **Off by default.** Nothing changes for a player who has not enabled it.
- **No base-game overrides.** No `Skyrim.esm` record or setting is
  overridden; a change to how Skyrim behaves lives in the runtime, only while
  a converted game's rules are on ([why](#no-base-overrides)).
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

Papyrus is the bigger risk: `Oblivion.esm`'s scripts carry 1,327 `GameMode`
blocks (Fallout 3 524, New Vegas 663, [counted](#checked)), each converted
into an `OnUpdate` poll ([scope](../commentary/script_convert.md#scope)). The systems layer
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
  records carry a 16-byte `AVSK`, in xEdit's order Skill Use Mult, Skill
  Offset Mult, Skill Improve Mult, Skill Improve Offset, one per skill plus two
  regeneration modifiers; for
  example One-Handed is 6.3 / 0 / 2 / 0 and Smithing 160 / 0 / 0.25 / 300. An
  override plugin could set them; the plan sets them in memory instead
  ([why](#no-base-overrides)). Skyrim's Illusion skill is the record named
  `AVMysticism`.
- **Oblivion's leveling table is engine defaults.** `Oblivion.esm` stores no
  leveling GMSTs; `Oblivion.exe` registers them with these defaults, read from
  the push before each name: `iLevelUpSkillCount` 10; `iLevelUp01Mult` to
  `iLevelUp04Mult` 2; `iLevelUp05Mult` to `iLevelUp07Mult` 3; `iLevelUp08Mult`
  and `iLevelUp09Mult` 4; `iLevelUp10Mult` 5. `Oblivion.esm` does carry the
  skill-use curve, `fSkillUseExp` 1.5 and `fSkillUseFactor` 0.35, and its 21
  `SKIL` records each give a governing attribute, a specialization and two use
  values (Athletics 0.03 / 0.04, Speechcraft 2.4 / 1).
- **Morrowind's leveling matches Oblivion's.** Unlike Oblivion, `Morrowind.esm`
  stores its leveling GMSTs: `iLevelupTotal` 10 and `iLevelUp01Mult` to
  `iLevelUp10Mult` 2, 2, 2, 2, 3, 3, 3, 4, 4, 5, the same table as Oblivion's
  engine defaults, plus skill XP modifiers by category (`fMajorSkillBonus`
  0.75, `fMinorSkillBonus` 1.0, `fMiscSkillBonus` 1.25, `fSpecialSkillBonus`
  0.8) and `fLevelUpHealthEndMult` 0.1. OpenMW's
  `apps/openmw/mwmechanics/npcstats.cpp` reads exactly these. One skill-use
  rule set with per-game settings covers both games.
- **Fallout perks share Skyrim's record structure, not its entry points.**
  `Fallout3.esm` has 87 `PERK` records, `FalloutNV.esm` 176, `Skyrim.esm` 375.
  All use `DATA`, `PRKE`, `PRKC`, `CTDA`, `EPFT`, `EPFD`, `PRKF`, `EPF2` and
  `EPF3`, with the same three entry kinds (quest stage, ability, entry point);
  New Vegas adds icons (169) and inline scripts on 5 perks, Skyrim adds
  `VMAD`, `NNAM` and `CIS2`. The entry points differ (xEdit's lists): Fallout
  3 has 37, New Vegas 74 (Fallout 3's list is its first 37), Skyrim 92. Only
  12 of New Vegas's exist in Skyrim by name, 3 at the same index. Counted over
  the actual perk entries, at least 99 of Fallout 3's 118 (84%) and 131 of New
  Vegas's 212 (62%) convert without new work: every quest-stage and ability
  entry, plus the entry points Skyrim has by name. The rest are Fallout-only:
  most-used are action point cost, VATS to-hit chance, gun spread and damage
  threshold.
- **New Vegas's XP rules are GMSTs.** `iLevelUpSkillPointsBase` 11,
  `iLevelUpSkillPointsInterval` 1, `fAVDTagSkillBonus` 15, `fBookPerkBonus` 3,
  `iTraitMenuMaxNumTraits` 2, and XP rewards per difficulty for kills,
  picked locks, hacked terminals, speech challenges and map markers
  (`iXPRewardKillOpponent*`, `iXPRewardPickLock*`, `iXPRewardHackComputer*`,
  `iXPLevelKill*`, `iXPRewardDiscoverMapMarker` 10). `Fallout3.esm` carries
  the same skill-point settings (11, 1).
- **Fallout's engine defaults, read from each game's GECK** (the editor shares
  the engine's setting table without the game exe's DRM; the method was
  checked against Oblivion.exe's known values first). New Vegas:
  `iLevelsPerPerk` 2, a perk every second level. Fallout 3 has no
  `iLevelsPerPerk` at all, so its one-perk-per-level schedule is fixed in
  code. Both: `iLevelUpSkillPointsBase` 7 and `iLevelUpSkillPointsInterval` 2,
  which both masters override to 11 and 1 (a plugin's GMST beats the engine
  default, as the data file assumes), and `iXPBase` 200.

How much converted content depends on these systems, counted over the
exports' scripts (`SCPT` text plus dialogue and quest-stage result scripts)
and their conditions:

| | Oblivion | Fallout 3 | New Vegas |
|---|---|---|---|
| Script bodies / `GameMode` blocks | 9,992 / 1,327 | 3,474 / 524 | 6,140 / 663 |
| Attribute or S.P.E.C.I.A.L. reads and writes in scripts | 54 in 14 scripts | 32 in 18 | 66 in 19 |
| Fame, infamy, karma in scripts | 244 in 212 (fame, infamy) | 67 in 43 (karma) | 43 in 42 (karma) |
| `RewardXP` | none | 60 in 58 scripts | 265 in 262 |
| Perks added, tested or removed in scripts | none | 44 in 16 | 256 in 107 |
| Reputation commands | none | none | 510 in 249 |
| Pip-Boy notes | none | 249 in 33 | 128 in 75 |
| Actor-value conditions (all values) | 120 | 869 | 1,481 |
| Biggest condition dependencies | class tests 114, `GetActorValue` on Illusion, fame and infamy | karma 277, `HasPerk` 115 | Speech 540, Barter 209, `GetReputationThreshold` 1,581, `HasPerk` 124 |

So for Oblivion, fame and infamy matter more than attributes; for Fallout,
dialogue skill checks, karma, reputation and perks dominate.

**Fallout actor-value conditions are translated with Oblivion's table.**
`fallout_function` remaps a FO3/FNV condition's function, but its actor-value
parameter then goes through `_TES4_AV_TO_TES5` in `_convert_params`
(`tes5_import/base/conditions.py`), and Fallout numbers its actor values
differently. Run through `convert_ctda` on the exports' real conditions:

| Condition tests | New Vegas | Fallout 3 | Converts to |
|---|---|---|---|
| Karma | 42 | 275 | the player's Illusion skill |
| Charisma | 27 | 37 | Health |
| Intelligence | 42 | 38 | Magicka |
| Repair | 14 | 3 | Infamy |
| Speech | 540 | none | dropped (the check always passes) |
| Medicine, Science, Strength | 137 | 75 | dropped |
| Barter | 209 | 26 | Speech (correct by coincidence) |

The fix is independent of this plan and is written, on its own branch
(`fix/fallout-av-conditions`): a Fallout actor-value table in
`conditions_falloutnv.py` maps the 25 values Skyrim has with the same meaning
(Speech and Barter to Speech, Lockpick to Lockpicking, Repair to Smithing,
Sneak, Health, Carry Weight, the resistances and others) and drops the rest
until pieces D and E give them a GLOB to read. It also pads Fallout's older
20- and 24-byte conditions to 28 bytes, so they are read with Fallout's
function numbering instead of Oblivion's.

**Converted Fallout scripts pass most Fallout-only actor values through as
names Skyrim does not know.** Scripts translate by name, not index
(`script_convert/commands.py` `actor_value`), through Oblivion's
`ACTOR_VALUE_MAP`; a name missing from it is emitted unchanged. Skyrim's
actor-value names, read from `CreationKit.exe`'s name table, do not include
most of Fallout's, and an unknown name reads 0 and rejects writes
([script_convert.md](../commentary/script_convert.md#skyrim-has-no-attributes)).
Counted over the exports' `SCPT` text and the result
scripts in `INFO`, `QUST`, `PACK`, `TERM`, `PERK` and `NOTE`:

| | Fallout 3 | New Vegas |
|---|---|---|
| Actor-value calls | 1,008 | 1,062 |
| Naming a value Skyrim does not know | 144 | 227 |
| Repair | 48 | 49 |
| Medicine, Science, Explosives | 32 | 97 |
| Karma | 32 | 4 |
| Perception, Charisma | 9 | 27 |
| Speech, Barter, Lockpick | 7 | 13 |
| Weapon skills, Survival, RadiationRads, ActionPoints, XP, BloodyMess | 16 | 37 |

Repair, Speech, Barter and Lockpick have a Skyrim value and should map the way
the condition fix maps them. Perception and Charisma also read 0, while
Strength, Endurance, Intelligence, Agility and Luck read 100, because
`TES4_ATTRIBUTES` lists Oblivion's attributes and five of them share a
name with S.P.E.C.I.A.L. stats: the same kind of gate falls open for one stat
and shut for another. The script-side fix is on the same branch: the four
renames, Perception and Charisma read as the other five stats do, and the
values Skyrim lacks become inert reads, which drop out of a comparison rather
than deciding it.

<a id="skill-source"></a>**A folded skill increase can be credited to its source
skill from authored data**, without a DLL. `OnStoryIncreaseSkill` names only
the Skyrim skill, so the rules keep the context themselves, on a player alias,
from vanilla events that fire only when the player acts:

- **Blade or Blunt** (One-Handed, Two-Handed): `OnObjectEquipped` records the
  weapon in hand. Import already knows each weapon's Oblivion type, so piece A
  writes Blade and Blunt weapons into two form lists and the rules test
  membership. This follows the authored skill rather than the Skyrim weapon
  type the conversion chose, so an Oblivion axe stays Blunt.
- **Mysticism** (Alteration): converted Mysticism effects are Alteration, or
  Conjuration for a few (`tes5_import/record_types/magic.py`
  `SCHOOL_TO_AV`), while scripts and conditions read Mysticism as Illusion.
  `OnSpellCast` records the last spell cast; a form list of converted
  Mysticism spells credits the increase. The rules' own Mysticism GLOB then
  replaces both of today's stand-ins.
- **Mercantile or Speechcraft** (Speech): Speech gained while the barter menu
  is open is Mercantile. The rules take a Speech snapshot when the menu opens
  and credit the difference when it closes (SKSE's `RegisterForMenu`, which
  converted scripts already use), so the result does not depend on whether
  the story event arrives before or after the menu closes.
- **Skill books and trainers** raise a skill with no use to observe, and a
  Blunt book read with a sword equipped would be misread. Both records name
  their Oblivion skill (`BOOK` `DATA.Teaches`, read in `equipment.py`;
  trainers' `Teaches`, read in `actor_common.py`), so piece A records it and
  the rules credit it directly: `OnRead` for books, the training menu's
  snapshot for trainers.

Still to check, in game: that a story event arriving a moment after the
action still finds the same weapon or spell recorded, and how the Story
Manager handles several skill increases in quick succession while the rules
quest is still running.

Still to check, in the executable: which code grants Skyrim's level-up and
perk point, so piece I can withhold them, read from the 1.6.1170 build.

## <a id="open-questions"></a>Open questions for the maintainer

1. `FalloutRuntime.dll` was split out so new Fallout systems need not
   overwrite base game data. The plan applies that to all four games: the
   player's rules are Papyrus and new records, and the runtime takes what
   would otherwise override `Skyrim.esm` (piece I), Fallout's perk entry
   points, per-actor stats, menus and item condition. Does that hold for
   Oblivion and Morrowind too, with `TESRuntime` and `MorrowindRuntime`
   carrying their parts as `FalloutRuntime` carries Fallout's?
2. Is moving the Morrowind stat store into `tes_runtime/common` acceptable, and
   in what shape?
3. The repo has no `LICENSE` file, while the About box says MIT and
   `external/openmw` is GPL-3.0. Where should the boundary sit for shared
   runtime code?
4. Separate rules plugin, or records inside the converted plugin behind a flag?
5. Piece I withholds Skyrim's own level-up and perk point while a game's
   rules are on, since otherwise the player levels twice. Should all of it be
   withheld, or should Skyrim's perk points stay available as an option beside
   the source game's rules?
