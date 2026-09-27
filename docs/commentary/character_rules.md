# Character rules: a converted game's leveling for the player

**Code:** `character_rules/scripts/source/TES4Rules_Main.psc`,
`TES4Rules_Player.psc`, `TES4Rules_SkillEvent.psc`,
`tools/release/make_character_rules_esp.py`,
`script_convert/static_scripts/TES4Polyfill.psc` (the attribute functions),
`script_convert/commands.py` (`actor_value`), and the player attribute globals
in `tools/release/make_game_select_esp.py`.

**Not yet played in game.** It builds on TESRuntime's character rules
([tes_runtime_character.md](tes_runtime_character.md)), which change
Skyrim's own skill rates and leveling while these rules are on.

## <a id="what-it-does"></a>What it does

A character who starts in a converted TES4 game levels by that game's rules:

- the eight attributes exist, start from the race and class, and are what
  converted scripts' attribute checks read ([attributes](#attributes));
- skills start from the class, and every Skyrim skill increase counts toward
  the source game's skill it stands for ([skill increases](#skill-increases));
- ten increases of major skills make a level, taken at rest, where the player
  raises three attributes by what their skills earned ([level-up](#level-up));
- Skyrim's own level-up and perk points are withheld, and the level the rules
  grant becomes Skyrim's, which leveled lists scale by.

Everything is data: the numbers and texts come from the game's own records and
settings through its [character data file](tes5_import_character_data.md), so
another TES4 game with its own classes or settings needs no code change.

## <a id="the-rules-plugin"></a>The rules plugin

`python tools/release/make_character_rules_esp.py --plugin Oblivion.esm`
writes `output/Oblivion Character Rules/`, a Data folder holding
`Oblivion Character Rules.esp`, its `.seq`, and the three scripts. It reads the
game's export, for the character data, and its converted plugin, for the
chargen class global; both must exist. The plugin masters `Skyrim.esm` and the
game's plugin and overrides nothing:

| Record | What it is |
|---|---|
| QUST `...CharacterRules` | Start Game Enabled; `TES4Rules_Main` holds the rules and every table as properties; `TES4Rules_Player` sits on a player alias |
| QUST `...SkillIncrease` | Started by the Story Manager on each skill increase (`ENAM SKIL`); `TES4Rules_SkillEvent` asks the rules to recount, then stops |
| SMQN `...SkillIncreaseNode` | A child of Skyrim's skill-increase event node (`0002D386`), after its last child (`000F6F1C`), sharing the event so Skyrim's own skill quests still run, and only while `...RulesActive` is 1 |
| GLOB | `...RulesActive`, and one "picked" flag per attribute for the level-up menu |
| FLST | Blunt weapons, Mysticism spells, one list of skill books per skill, and the Skyrim races in the race tables' order |
| MESG | The level-up menu: a button per attribute, hidden once picked |

A probe plugin with the same node was checked in game: it receives every
skill-increase event (the classic character systems plan records the results).

A player installs four things: this Data folder, `TESRuntime.zip` (piece I),
`TESGameSelect.zip` built with the attribute globals, and the converted game
with its scripts rebuilt, since attribute reads now go through the polyfill.

## <a id="whose-rules"></a>Whose rules

The rules follow the character, not the load order: they run only for a
character whose TESGameSelect choice (`TESGameSelectQuest.ChosenGame`) is this
game, so in a profile with every world loaded each game's rules stay off for
the others' characters. Until the choice is made (a new game, before the menu)
the quest waits on message-box closes; once the save's game is known and is
another one, it stops listening for good. With no TESGameSelect there is no
recorded game, and Skyrim's own rules stay.

## <a id="character-creation"></a>Character creation

The rules begin once the converted chargen's class menu has been answered
(`TES4ChargenClassChoice`, the menu index plus one, the menu sorted by class
name as `message_menus.chargen_class_names` sorts it):

- **Attributes:** the race's base values for the player's sex, plus
  `fAttributeClassPrimaryBonus` and `fAttributeClassSecondaryBonus` (5 each in
  `Oblivion.esm`) for the class's two favored attributes. The player's Skyrim
  race is matched to the source race through `RACE_MAP`; an unmatched race
  starts every attribute at 40.
- **Skills:** 5, or 25 for a major skill, plus 10 in the class's
  specialization, plus the race's bonus: the values `Oblivion.esm`'s own chargen
  texts state (`sMajorSkills`, `sSpecialization`), not yet traced in the exe.
  Each Skyrim skill is raised to the best of the source skills credited from
  it and never lowered, so installing the rules on a character already played
  keeps its skills; a higher Skyrim level then becomes that source skill's.

Birthsigns already grant their spells through the converted chargen.

## <a id="skill-increases"></a>Skill increases

The rules never count events. On every skill-increase event, every close of the
barter, book, training, crafting and lockpicking menus, every rest and every
load, they compare each Skyrim skill with their last snapshot and credit what
rose, because one event can carry several levels, increases in a menu share one
event sent after it closes, and an increase that arrives while the event quest
is running gets none (all measured in game with the probe). An increase is
credited to:

1. the skill a skill book teaches, when one was just read (a book's authored
   skill, read from `BOOK DATA.Teaches`, so a Blunt book read with a sword in
   hand is still Blunt);
2. a folded skill, when what the player was doing names it: a Blunt weapon last
   equipped for One-Handed and Two-Handed, a Mysticism spell last cast for
   Alteration and Conjuration, the barter menu open for Speech (Mercantile);
3. otherwise the Skyrim skill's own source skill (Blade, Alteration,
   Speechcraft).

Each credited level counts toward its governing attribute's level-up bonus,
and a major skill's toward the next level. When ten have come in, the game's own
`sMeditate` says so.

## <a id="level-up"></a>The level-up

At the end of a rest with enough major increases, the game's `sLevelUp<N>`
passage for the new level shows, then the attribute menu, three times. Each
attribute's bonus is `iLevelUp<NN>Mult` for the increases its skills earned, 1
for none, the tenth for ten or more, and always 1 for Luck, as `Oblivion.exe`
looks it up (`0x5480a0`). Raising an attribute raises what it governs, by
`Oblivion.exe`'s formulas: Endurance the Health base by `fPCBaseHealthMult`
(`0x548020`), Intelligence the Magicka base by one plus `fPCBaseMagickaMult`
(`0x5482b0`), and Strength the carry weight by `fActorStrengthEncumbranceMult`.
Each level adds a tenth of Endurance to Health. The ten increases are spent,
any beyond them carry over, and the rules send TESRuntime the new level.

## <a id="attributes"></a>Attributes where scripts read them

Converted scripts read and write attributes through `TES4Polyfill`
(`GetTES4ActorValue`, `SetTES4ActorValue`, `ModTES4ActorValue`), never as a
Skyrim actor value ([why](script_convert.md#skyrim-has-no-attributes)). The
player's values live in `TESGameSelect.esp`, one global per attribute
(`TESGS_PlayerStrength` at `0xAF0` to `TESGS_PlayerLuck` at `0xAF7`,
[below the travel menus](tesgameselect.md#records)): the one
plugin every converted world shares, so whichever game's rules a character
plays by, the same globals hold its attributes, and a script in any world reads
them. A value of 0 means no rules keep it, and the read falls open at 100 as
before; NPCs always read 100 until per-actor stats exist.

## <a id="not-yet"></a>Not yet

- Athletics, Acrobatics and Hand to Hand have no Skyrim skill to rise with, so
  nothing credits them; a class with them as majors levels more slowly.
- Trainers credit the Skyrim skill's own source, not their authored skill.
- Birthsign attribute bonuses, Speed, and Fatigue (Skyrim's Stamina) are not
  applied; Fatigue's formula has not been read from the exe.
- Dialogue conditions on attributes are still dropped at import.
- Scripts' attribute writes change the global only, not what it governs.
