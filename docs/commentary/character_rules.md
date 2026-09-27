# Character rules: a converted game's leveling for the player

**Code:** `character_rules/scripts/source/TES4Rules_Main.psc`,
`TES4Rules_Player.psc`, `TES4Rules_SkillEvent.psc`, the `FalloutRules_*.psc`
scripts, `tools/release/make_character_rules_esp.py`, its shared records in
`character_rules_records.py` and its Fallout half in
`character_rules_falloutnv.py`,
`script_convert/static_scripts/TES4Polyfill.psc` (the attribute functions),
`script_convert/commands.py` (`actor_value`), `RewardXP` in
`script_convert/constants_falloutnv.py`, and the player attribute globals in
`tools/release/make_game_select_esp.py`.

It builds on TESRuntime's character rules
([tes_runtime_character.md](tes_runtime_character.md)), which change
Skyrim's own skill rates and leveling while these rules are on. Played in game
with `Oblivion.esm` under MO2: rules on at the Cyrodiil choice, the class taken
at the tutorial's class menu, and a level-up at rest that set the player's
level.

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
the others' characters. The game is read again at every load, because
TESGameSelect keeps it with the save and TESRuntime starts every load with the
rules off.

Both choices are made in message boxes whose answer is written after the box
closes, so the rules look every two seconds (`RegisterForSingleUpdate`) until
they know both, rather than waking on a menu event:

1. **The game.** `ChosenGame` reads Skyrim (0) while TESGameSelect's menu is
   open, so the rules take it only once `HasRun` is set, `Selecting` is off
   (the chosen game has started, after any fall-back to Skyrim) and the save's
   ids are current (`IdVersion`, renumbered by `MigrateIds`); TESGameSelect's
   travel quest takes the same answer. `ChosenGame` stays the game the
   character began in when the travel scroll moves them to another world, so
   the rules follow the starting world. Once the game is this one, Skyrim's
   leveling is handed to TESRuntime straight away, with no class multiplier,
   so the tutorial before the class menu is not leveled by Skyrim's rules.
2. **The class.** Then the rules begin ([character creation](#character-creation))
   and TESRuntime is told the class.

Another game's character settles on Skyrim's rules for the session. So does a
loaded save whose TESGameSelect menu never ran (begun before it was installed);
a new game waits, because the menu runs after this quest starts. With no
TESGameSelect there is no recorded game, and Skyrim's own rules stay.

The rules quest's start fires `OnInit` twice in a new game, as Start Game
Enabled quests do; both runs are harmless. Each decision is traced to the
Papyrus log under `[TES4Rules]`, and TESRuntime logs every `TESCharacter*` event
it receives.

### <a id="papyrus-names-ignore-case"></a>🛑 Papyrus names ignore case

The first build never turned the rules on, in four playtests, because a local
`selector` shared its name with the property `SELECTOR` (`"TESGameSelect.esp"`).
To the compiler they are one name: the call read the unset local, looking up a
file called None (`GetModByName` answered 255, `GetFormFromFile` "File "None"
does not exist"), and the assignment compiled to a property write, logged as
`Property setter for property SELECTOR not found`. Every run read "no
TESGameSelect" and settled on Skyrim's rules. The compiled `.pex` showed it
(`cast ::temp3 selector`, `propset selector self`). No local or parameter in the
rules scripts may share a script-level name in any case;
`tests/test_character_rules_esp.py` checks it.

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

## <a id="fallout"></a>Fallout: experience and skill points

`make_character_rules_esp.py --plugin FalloutNV.esm` builds a Fallout game's
rules plugin from its export alone (`character_rules_falloutnv.py`); the rules
reference only `Skyrim.esm` forms, so the converted plugin is not read. Built
and compiled for `FalloutNV.esm`; not yet played. Fallout 3 has no
TESGameSelect game, so its rules cannot start yet, though its data builds.

| Record | What it is |
|---|---|
| QUST `...CharacterRules` | Start Game Enabled; `FalloutRules_Main` holds the rules; `FalloutRules_Player` on the player alias reports each load |
| QUST `...Kill0`-`3`, `...PickLock0`-`3` | Started by the Story Manager on a kill (`ENAM KILL`) or a picked lock (`LOCK`); each stops, then hands the event to the rules |
| SMQN `...KillNode` | A child of Skyrim's kill event node (`00013010`), after its last child (`0001E491`), sharing the event, while `...RulesActive` is 1 |
| SMQN `...PickLockNode` | The first child of Skyrim's lock event node (`0005BD7B`, childless), the same way |
| GLOB | `...RulesActive` |
| MESG | The skill menu, two pages: eight skills and "More skills", then the rest and "Back" |

Each node lists four quests. The Story Manager skips an event whose quest is
still running (the skill event does, measured with the probe), and a node's
quest list lets it start another instead, so kills close together, as from one
explosion, should each find a free quest; that the engine takes the next one
in the list is not yet checked in game.
Two vanilla kill nodes come first and can take a kill without sharing it:
`DA08KillFriendNode` (a friend killed with the Ebony Blade) and
`WIKillEventsBranchNode` (Skyrim's town kill reactions).

**Whose rules and starting values.** The same TESGameSelect check as the TES4
rules ([whose rules](#whose-rules)); the rules begin at once, with no class
menu. S.P.E.C.I.A.L. starts from the class of the player's own record ("Vault
Dweller", 5 in every stat, in New Vegas); each skill from its
[formula](tes5_import_character_data.md#fallout-governing-stats), plus
`fAVDTagSkillBonus` for the class's tags (none). A Skyrim skill already higher
raises the source skills it carries, as the TES4 rules do. The chargen pickers
belong to the menus piece.

**Where the values live.** S.P.E.C.I.A.L. uses TESGameSelect's player globals:
Strength, Intelligence, Agility, Endurance and Luck share the TES4 attribute
of the same name, which `TES4Polyfill` already reads, and Perception and
Charisma have their own at `0xAF8` and `0xAF9`
([ranges](tesgameselect.md#records)), which the polyfill's attribute index
gives as 8 and 9. A character plays one game's rules, so the shared five never
hold two games' values. Skills live in the rules
script; each Skyrim skill carries the best of its source skills (Marksman:
Guns and Energy Weapons; Speech: Barter and Speech), set by the rules after
every level-up. TESRuntime keeps Skyrim's skills from rising by use while an
XP game's rules are on ([XP rules](tes_runtime_character.md#what-it-changes)).

**Experience**, each amount as the game's own settings give it:

- **Quests:** converted `RewardXP` sends the mod event `TESCharacterXP` with
  the amount (265 calls in New Vegas's scripts, 60 in Fallout 3's).
- **Kills**, read from `Fallout3.exe`: the victim's level picks the first tier
  whose `iXPLevelKillCreature*` (or `iXPLevelKillNPC*` for a person, by
  `ActorTypeNPC`) it does not pass, else the last, and the reward is that
  tier's `iXPRewardKillOpponent*` (or `iXPRewardKillNPC*`) (lookup `0x5ca3c0`,
  table `0x10fd908`). With Fallout 3's master values a Radroach (level 1)
  gives 1 and a Deathclaw 50, as fallout.wiki gives them. Fallout 3 counts a
  kill only when the player did more than `iXPDeathRewardHealthThreshold`
  (75) percent of the victim's Health in damage (`0x5ca2f0`), which Papyrus
  cannot see; the rules count the player's kills, and in New Vegas also the
  companions', as that game does.
- **Picked locks:** the lock's Skyrim level, 1 to 100, is tier 0 to 4, read
  against `iXPLevelPickLock*` the same way, rewarding `iXPRewardPickLock*`.

**The level-up.** The experience for level L is (L - 1) × `iXPBase` +
`iXPBumpBase` × (L - 1)(L - 2) / 2 (`Fallout3.exe` `0x601dc0`; New Vegas's
200 and 150 give fallout.wiki's 200, 550, 1,050, 1,700). When enough has come
in, outside combat and menus (checked again every five seconds), each level
adds `fAVDHealthLevelMult` Health and skill points: Fallout 3's
`iLevelUpSkillPointsBase` + (Intelligence - 1) × `iLevelUpSkillPointsInterval`
(`0x601b50`, 10 + Intelligence with its master's 11 and 1), New Vegas's
10 + Intelligence / 2 with the half point carried (fallout.wiki; its exe is
encrypted). Points go one per press in the skill menu, to at most 100; then
the rules send TESRuntime the new level, up to `iMaxCharacterLevel`.

**Not yet:** perks and traits (the perk every `iLevelsPerPerk` levels), hacked
terminals, passed speech challenges and discovered map markers (their
`iXPReward*` settings are in the data, with no Skyrim event yet), Fallout 3's
difficulty multiplier (`fDiffMultXP*`, `0x600ec0`; New Vegas has none),
karma and reputation, and Health and carry weight from Endurance and Strength.
