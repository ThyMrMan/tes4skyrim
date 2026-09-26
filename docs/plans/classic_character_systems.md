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
- [Check before building](#check-first)
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

### Runtime: one stat store, shared

The Morrowind store moves into `tes_runtime/common`, keyed by stat name rather
than TES3 index:

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
  Skills Skyrim has advance through Skyrim's own skill use; the runtime only
  counts the increases. Where several source skills fold into one Skyrim skill
  (Blade and Blunt into One-Handed; Mercantile and Speechcraft into Speech),
  the increase is credited by context: the equipped weapon's type, whether the
  barter menu is open.
- **xp** (Fallout): XP from quests (`RewardXP`), kills, and lock, hack and
  speech successes; skill points per level from Intelligence; the perk
  schedule from the game's settings.

Effects apply when a value changes (level-up, a Fortify effect landing), as
actor value modifiers: Strength to carry weight and melee damage, Endurance to
health, Intelligence to magicka, and so on. Nothing is recalculated per frame.

### Records: a separate generated plugin

The rules ship as their own generated plugin per game, beside the converted
one, as the vanilla creature swap plan does
([vanilla_creature_swap.md](vanilla_creature_swap.md)):

- mastery bonuses, birthsign and racial abilities as abilities or perks;
- FO3/FNV `PERK` records converted to Skyrim perks. Fallout 3's perk format is
  the one Skyrim's builds on, so this is expected to be close to direct;
  check it record by record first;
- NV recipes (`RCPE`) as Skyrim constructible objects.

A separate plugin keeps the feature off unless it is enabled, and its FormIDs
come from `derive_formid` with new sites in its own file, so no converted
plugin's FormIDs move.

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
| A | Character data file, all four games, with its first reader (B) in the same PR | `tes5_import/` new module | nothing |
| B | Shared stat store; Morrowind switched over with identical behavior | `tes_runtime/common/` | A |
| C | Papyrus natives and the GLOB mirror; the polyfill and FNV stubs call through | `tes_runtime/tes/`, `script_convert/` | B |
| D | Skill-use leveling, message-box level-up, class effects | `tes_runtime/`, rules plugin | C |
| E | Fallout XP leveling, perk and trait conversion, karma and reputation | `tes5_import/*_falloutnv.py`, `tes_runtime/` | C |
| F | Skills Skyrim lacks: Athletics, Acrobatics, Hand to Hand, Mysticism, Mercantile, and Fallout's unmapped skills | `tes_runtime/` | D or E |
| G | Menus: level-up, stats sheet, chargen pickers | `tools/generators/`, `tes_runtime/` | D or E |
| H | Item condition and repair | `tes_runtime/`, import | B |

## <a id="order"></a>Suggested order

1. **A and B together**: the data file and the shared store, proven by
   Morrowind behaving exactly as before.
2. **C, then D for Oblivion**: the smallest step from Morrowind's store to a
   second game, and it lets attribute gates be real without locking anyone
   out.
3. **E**: Fallout perks may be the cheapest real gain, since the records map
   closely onto Skyrim's.
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
- **Headless tests.** Leveling and effect rules are pure logic, tested the way
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
therefore lives in C++, and:

1. reacts to engine events (hits, casts, locks, sales, skill increases)
   rather than polling; any poll runs at most every 33 ms and does nothing
   unless something changed;
2. precomputes tables at import and resolves FormIDs once per load;
3. applies effects when values change, never per frame;
4. writes a GLOB only when its value changes;
5. keeps a custom menu's per-frame callback trivial;
6. does nothing when its game's plugin is not loaded;
7. sleeps in whole milliseconds with at most one tick queued
   ([one queued tick](../commentary/morrowind_runtime.md#one-queued-tick));
8. records a headless benchmark and an in-game frame-time comparison, DLL on
   and off, in each piece's commentary doc.

## <a id="check-first"></a>Check before building

- Whether the DLL can be told when a Skyrim skill increases, which the
  skill-use rule set leans on.
- Where Skyrim keeps its per-skill XP rates, and whether an override plugin can
  set them from Oblivion's SKIL use values.
- Oblivion's attribute multiplier table and leveling GMSTs.
- How closely FO3/FNV `PERK` entry points match Skyrim's, record by record.
- The Fallout 3 and New Vegas perk schedules, and Fallout 3's conversion
  coverage in general (most Fallout notes so far are New Vegas).
- How Nehrim, which changes Oblivion's leveling, expresses that in its records
  and scripts.

## <a id="open-questions"></a>Open questions for the maintainer

1. Is new `tes_runtime` functionality for this wanted at all, given DLLs are a
   last resort?
2. Is moving the Morrowind stat store into `tes_runtime/common` acceptable, and
   in what shape?
3. The repo has no `LICENSE` file, while the About box says MIT and
   `external/openmw` is GPL-3.0. Where should the boundary sit for shared
   runtime code?
4. Separate rules plugin, or records inside the converted plugin behind a flag?
5. Should Skyrim's own perk points and leveling be switched off when a game's
   rules are on, or run alongside?
