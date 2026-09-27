# The character data file

**Code:** `tes5_import/character_data.py`, `tes5_import/character_data_falloutnv.py`,
`tes4_export/record_types/actors.py` (`export_SKIL`),
`tes4_export/record_types/character_falloutnv.py`,
`tools/disasm/oblivion_engine_extract.py` (`--settings`, `--settings-json`),
`tes4_export/oblivion_engine_tables.json` (`settings`),
`tes4_export/falloutnv_engine_settings.json`, `tes4_export/fallout3_engine_settings.json`.

TESRuntime reads it for Skyrim's skill rates while a game's rules are on
([tes_runtime_character.md](tes_runtime_character.md#skill-rates)), and the
rules plugin is built from it ([character_rules.md](character_rules.md#the-rules-plugin)).

## <a id="the-character-data-file"></a>What it holds

Every TES4-format plugin that defines a skill, class, race, birthsign or
leveling setting writes `SKSE/Plugins/TESRuntime/<plugin>.character.json`,
beside the other TESRuntime sidecars, so the
[sidecar sweep](tes5_import_pipeline.md#stale-runtime-sidecars) removes it
when a rebuild stops writing it. FO3/FNV plugins write their own shape
([Fallout](#fallout)); TES3 sources write none yet.

| Key | Holds |
|---|---|
| `version`, `plugin`, `rules` | schema version 1, the plugin, and the rule set: `skill-use` for TES4 |
| `skills` | each `SKIL`: name, actor value, governing attribute, specialization, its two use values, and the [Skyrim skills](#skyrim-skills) its increases can be credited from |
| `classes` | each `CLAS`: its two primary attributes, specialization, seven major skills, and whether chargen offers it |
| `races` | each `RACE`: skill bonuses, base attributes for each sex, the spells it grants, and whether chargen offers it |
| `signs` | each `BSGN` and the spells it grants |
| `folds` | the Blunt weapons (`WEAP` type 2 or 3) and Mysticism spells (first effect's `MGEF` school 4, found in the master chain) whose use credits a [folded skill](#skyrim-skills) |
| `books` | each skill's books, by `BOOK DATA.Teaches` |
| `settings` | the [leveling settings](#engine-defaults), and the texts the level-up shows: `sMeditate`, `sLevelUp2` to `sLevelUp20`, the eight `sAttributeName`s |
| `attributes`, `standings` | a masterless plugin only: the engine's eight attributes, and Fame and Infamy with the Skyrim actor values that already carry them |

Every record is a form `[owning plugin, local id]`, resolved against the
plugin's own masters, so a plugin that overrides `Oblivion.esm`'s Knight class
names `["Oblivion.esm", 0x1C3AA]`. A plugin with masters carries only the
records and settings it defines: a reader layers the files in load order, a
later file's record replacing an earlier one with the same form. Only the
masterless plugin carries the engine defaults, so an expansion never restates
them.

## <a id="engine-defaults"></a>Engine defaults under the plugin's settings

A master stores only the settings that differ from the engine's defaults.
Of the settings the leveling rules read, `Oblivion.esm` stores only
`fSkillUseExp` (1.5), `fSkillUseFactor` (0.35) and `fPCBaseMagickaMult` (1.0). So a masterless plugin's `settings`
starts from the engine's own defaults and lays its GMSTs over them.

The defaults come from `Oblivion.exe` itself, read by
`oblivion_engine_extract.py --settings` into `oblivion_engine_tables.json`.
Each setting registers as a constructor call preceded by its default and its
name: `push imm8` or `push imm32` for an integer (a string pointer for an
`s` setting), and for a float `fld1`, `fldz` or `fld dword [constant]`
followed by `push ecx; fstp dword [esp]`. Read from the Steam `Oblivion.exe`:
2,302 settings. 378 of the 382 GMSTs `Oblivion.esm` overrides are among them;
the other four are `fRegionGenTex*`, the region generator's, apparently
editor-only. The dialogue tables the same file already held came out
identical, so it is the same build as the Nehrim install's.

| Setting | Default | `Oblivion.esm` |
|---|---|---|
| `iLevelUpSkillCount` | 10 | |
| `iLevelUp01Mult` to `iLevelUp10Mult` | 2, 2, 2, 2, 3, 3, 3, 4, 4, 5 | |
| `fSkillUseExp`, `fSkillUseFactor` | 1.0, 1.0 | 1.5, 0.35 |
| `fSkillUseMajorMult`, `fSkillUseMinorMult`, `fSkillUseSpecMult` | 0.75, 1.25, 0.75 | |
| `fPCBaseHealthMult`, `fPCBaseMagickaMult` | 2.0, 0.5 | `fPCBaseMagickaMult` 1.0 |
| `iTrainingSkills` | 5 | |

## <a id="skyrim-skills"></a>Which Skyrim skills a source skill is credited from

Skyrim reports a skill increase by its own skill's name, so the rules need to
know which source skill each Skyrim skill can stand for. Several fold
together, and the rules pick between them from what the player was doing (the
weapon in hand, the spell last cast, whether the barter menu was open):

| Source skill | Skyrim skills |
|---|---|
| Blade, Blunt | One-Handed, Two-Handed |
| Mysticism | Alteration, Conjuration, the schools converted Mysticism effects land in (`magic.py` `SCHOOL_TO_AV`) |
| Mercantile, Speechcraft | Speech |
| Armorer | Smithing |
| Marksman | Archery (`Marksman`) |
| Security | Lockpicking |
| Athletics, Acrobatics, Hand to Hand | none: Skyrim has no counterpart, so the rules raise them themselves |
| the others | the Skyrim skill of the same name |

This is deliberately not `TES4_SKILL_TO_TES5` (`base/constants.py`), which
picks the one Skyrim skill an NPC's authored value is written to and puts
Mercantile on Pickpocket. That table answers where a value goes; this one
answers where a player's increase can come from.

## <a id="skil-export"></a>The SKIL export read every field one slot early

`SKIL`'s `DATA` is action, attribute, specialization and two use values, 20
bytes (xEdit `wbDefinitionsTES4`), with the skill itself in `INDX`. The
exporter read it as four fields from offset 0 and skipped `INDX`, so
`DATA.Attribute` held the action, `DATA.Specialization` the attribute,
`DATA.UseValue1` the specialization's integer read as a float
(`1.401298464324817e-45` for Alchemy's 1), `DATA.UseValue2` the first use
value, and the second was never written. Nothing read it: `SKIL` is in
`SKIP_TYPES`. It now exports `INDX.Skill`, `DATA.Action`, `DATA.Attribute`,
`DATA.Specialization`, `DATA.UseValue1` and `DATA.UseValue2`; Athletics reads
0.03 and 0.04, Speechcraft 2.4 and 1.0. An export made before the fix has no
`INDX.Skill`, so its skills are left out of the file until it is re-exported.

## <a id="fallout"></a>Fallout 3 and New Vegas

**Code:** `tes5_import/character_data_falloutnv.py`.

An FO3/FNV plugin's file has `rules: xp` and a `game` (`falloutnv` or
`fallout3`, from the plugin header's own version: New Vegas writes 1.34,
Fallout 3 0.94). It reads the records the exporter now
[decodes](tes4_export_falloutnv.md#character-records):

| Key | Holds |
|---|---|
| `attributes` | the seven S.P.E.C.I.A.L. names, from the plugin's own `AVIF`s |
| `skills` | each skill `AVIF`: EditorID, name, actor value, [governing stat](#fallout-governing-stats), the Skyrim skills the converted content exercises with it, and whether the game shows it |
| `classes` | each `CLAS`: tag skills (named through the `AVIF`s, a dependent's through its master's), S.P.E.C.I.A.L., playable |
| `races` | each `RACE`'s skill bonuses (none in either master) and whether it is playable |
| `perks` | each `PERK`: trait or perk, minimum level, ranks, playable, hidden, its requirement conditions (raw), and each effect: quest and stage, ability, or entry point, function and value, with its condition tabs |
| `reputations` | each `REPU` and its value |
| `settings` | the XP rules' settings, over the engine's defaults read from the game's GECK when masterless: XP base and bump, the level cap, perks per level, skill points per level, the tag bonus, Health, carry weight and action point formulas, karma thresholds, every `iXPReward*` and `iXPLevel*` tier, and every `fAVDSkill*` (each skill's base and the stat and Luck multipliers) |
| `player` | the class of the player's own `NPC_` (`00000007`), whose S.P.E.C.I.A.L. a new character starts with: New Vegas's "Vault Dweller", 5 in every stat |
| `standings` | Karma, which Skyrim has no counterpart for |

An actor value's index is not stored anywhere in an `AVIF`; it follows from
the record's FormID block, which both masters use identically:
S.P.E.C.I.A.L. from `0x3E8` (5-11), derived stats from `0x44C` (12-31), skills
from `0x4B0` (32-45), the AI values from `0x514` (0-4), and the rest from
`0x5DC` (46 on). It matches every actor value a Fallout condition names.
Index 44 is Throwing in Fallout 3 and Survival in New Vegas (both `AVThrowing`),
and New Vegas keeps Big Guns as "Big Guns - OBSOLETE". Each game shows 13
skills: its engine hides one, Fallout 3 its cut Throwing and New Vegas Big
Guns, with nothing in the record to say so (the two `AVIF`s differ from the
shown ones only in their text), so each is marked `playable: false` by game.

Counts over the masters: New Vegas 14 skills, 74 classes (3 playable), 176
perks (10 traits, 101 playable; 212 effects: 143 entry point, 49 ability, 20
quest stage), 13 reputations, 60 settings; Fallout 3 14 skills, 53 classes (3
playable), 87 perks (61 playable; 118 effects), 57 settings.

### <a id="fallout-governing-stats"></a>The governing stats are not in the data

Which S.P.E.C.I.A.L. stat governs a skill is fixed in the engine, not stored
in any record, so `GOVERNING` is a table by `AVIF` EditorID, read from
`Fallout3.exe`. The Steam Fallout 3 GOTY exe is not encrypted (`.text` entropy
6.58, no `.bind` section; `FalloutNV.exe` is, 8.0), and its skill-value
routine `0x57dec0` reads two tables indexed by actor value: the governing stat
at `0x10fa194` and the skill's base setting at `0x10f91b0`. The skill is then
base + `fAVDSkillPrimaryBonusMult` × stat, rounded down, + `fAVDSkillLuckBonusMult`
× Luck, rounded up (`0x57e020`), which with the masters' 2, 2 and 0.5 is the
familiar 2 + 2 × stat + Luck / 2. The table: Barter and Speech Charisma;
Energy Weapons, Explosives and Lockpick Perception; Medicine, Repair and
Science Intelligence; Melee Weapons Strength; Small Guns (Guns) and Sneak
Agility; Big Guns and Unarmed Endurance; and actor value 44, Fallout 3's cut
Throwing, Intelligence. New Vegas's exe cannot be read, so its Survival, which
took over 44, is Endurance as the game shows it, and the other twelve are
taken as Fallout 3's (fallout.wiki's New Vegas Intelligence page agrees on
Medicine, Repair and Science).
