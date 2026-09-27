# TESRuntime: Skyrim's skill rates and leveling under a converted game's rules

**Code:** `tes_runtime/tes/character_rules.cpp`, `tes_runtime/tes/character_rates.cpp`,
`tes_runtime/tes/character_rates_test.cpp`, `tes_runtime/tes/ids.h` (Character rules).

Played in game with `Oblivion.esm`'s [rules plugin](character_rules.md): the
layout verified on 1.6.1170, the rules turned on with the curve at 1.5, the
class rates followed Battlemage, and a level-up set the player's level to 2.
Without a rules plugin it loads the character data files, hooks the level-up
check and waits. Every `TESCharacter*` event it receives is logged as
`character: event <name> '<strArg>' <numArg>`.

## <a id="what-it-changes"></a>What it changes, and when

With a converted game's rules on, three things about Skyrim itself change, all
in memory:

- each skill's rates follow the source game's curve and the player's class
  ([skill rates](#skill-rates));
- Skyrim's own level-up, with its screen and perk point, is withheld, and the
  "Level up available" message stays quiet;
- the rules set the player's level, which leveled lists and encounter zones
  scale by.

No record is overridden and nothing is written to the save: turning the rules
off restores every value, and the save holds only what Skyrim itself keeps.
The rules are off at every load and new game (SKSE's `PreLoadGame` and
`NewGame` messages), so a character playing Skyrim's own rules is never
touched, whether the profile loads one world or all of them. A rules quest,
which only runs for a character of its game, turns them on after each load
with mod events, the channel converted scripts already use for `TES4Spin`:

| Event | `strArg` | `numArg` | Does |
|---|---|---|---|
| `TESCharacterRules` | the plugin, e.g. `Oblivion.esm` | 1 | on, with that plugin's `character.json` and every file's classes |
| `TESCharacterRules` | | 0 | off |
| `TESCharacterClass` | the class's EditorID | | the class the rates follow |
| `TESCharacterLevel` | | the level | sets the player's level |

A mod event arrives on a Papyrus thread; each is carried out on the main
thread.

## <a id="skill-rates"></a>Skill rates

Oblivion's XP for a skill's next level, read from `Oblivion.exe` (`0x548030`,
the only code reading all five settings), is

    (level × fSkillUseFactor) ^ fSkillUseExp
        × fSkillUseSpecMult, when the skill is in the class's specialization
        × fSkillUseMajorMult or fSkillUseMinorMult

and Skyrim's (the skill advance, `0x77ae60`) is
`improveMult × level ^ fSkillUseCurve + improveOffset`, where each skill gains
`useMult × base + useOffset` per action, `base` being whatever that action
measures: damage dealt, gold, a lock's difficulty.

The two games' per-action gains measure different things, so Oblivion's use
values cannot be carried over, and Skyrim's `useMult` and `useOffset` stay as
they are. What does carry over is the shape of the curve and the class:

- `fSkillUseCurve` becomes the source game's `fSkillUseExp` (1.5 for
  Oblivion, against Skyrim's 1.95), so higher levels come faster than in
  Skyrim;
- each skill's `improveMult` is set so that at level 25, where an Oblivion
  character's major skills start, it needs exactly what Skyrim's own rates
  ask, then follows the new curve, and `improveOffset` becomes 0;
- that is multiplied by the class: major 0.75 or minor 1.25, times 0.75 in
  the class's specialization. Where several source skills fold into one
  Skyrim skill (Blade and Blunt into One-Handed), the most favorable counts.
  Until the rules name a class, every multiplier is 1.

The baseline is whatever the load order's rates are when the rules turn on,
so a mod that changes Skyrim's skill rates still sets their scale. The anchor
level is a choice, not something either game states; it is the one number to
tune after playing.

## <a id="the-engine-side"></a>The engine side

Every address is an Address Library id, all in `tes/ids.h` and checked on
every shipped versionlib (`tools/validate/stable_id_check.py`):

- **The level-up is withheld at "can level up"** (41565), a five-instruction
  test of the skill data's experience against its stored threshold. Every
  direct call to it is repointed to a check that answers no while the rules
  are on: the Skills menu's level-up branch, a level-up loop that runs
  without the menu, a player notice and a menu flag. The perk count only
  rises in that Skills-menu branch, so the perk point is withheld with the
  level. Nothing is written, so the stored threshold in the save stays
  Skyrim's.
- **The message** reads a threshold computed from `fXPLevelUpBase` and
  `fXPLevelUpMult` (41560), so `fXPLevelUpBase` is raised to 1e30 in memory.
- **The level** is set through the engine's own set-level (41563), as the
  console's `SetLevel` on the player: no screen, no perk point, experience
  reset. `fXPLevelUpBase` is put back for the call, so the threshold its
  bookkeeping stores is Skyrim's.
- **The rates** live behind a pointer at `ActorValueInfo+0x108`, the entries
  read from the ActorValueList singleton (400267) from `+8`. Those offsets are
  read from 1.6.1170 only, so after the game's data loads each skill's rates
  are compared with what the engine's own reader (27244) returns; if any
  differs, the rates stay Skyrim's and the log says so.

`fSkillUseCurve` (374905) and `fXPLevelUpBase` (374908) resolve straight to
the settings' values.

SKSE 2.2.6's own headers agree with all of this: `ActorValueInfo::skillUsages`
at `+0x108`, in the order use mult, offset mult, improve mult, improve offset,
with the threshold computed the same way (`PapyrusActorValueInfo.cpp`), and
`PlayerSkills::data` pointing at the experience (`+0`) and its threshold
(`+4`), whose `SetLevel` is the same `0x77B350` (`GameFormComponents.h`).
SKSE's comment puts the skill pointer at `PlayerCharacter+0x9B0`; every
1.6.1170 caller disassembled here reads `+0x9b8`, which the runtime uses.
