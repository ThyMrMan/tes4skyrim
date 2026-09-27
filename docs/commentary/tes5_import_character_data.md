# The character data file

**Code:** `tes5_import/character_data.py`, `tes4_export/record_types/actors.py`
(`export_SKIL`), `tools/disasm/oblivion_engine_extract.py` (`--settings`),
`tes4_export/oblivion_engine_tables.json` (`settings`).

**Nothing reads the file yet.** It is the data the classic character systems
work builds on: the runtime's in-memory skill rates and the player's leveling
rules both read it.

## <a id="the-character-data-file"></a>What it holds

Every TES4-format plugin that defines a skill, class, race, birthsign or
leveling setting writes `SKSE/Plugins/TESRuntime/<plugin>.character.json`,
beside the other TESRuntime sidecars, so the
[sidecar sweep](tes5_import_pipeline.md#stale-runtime-sidecars) removes it
when a rebuild stops writing it. TES3 and FO3/FNV sources write none yet:
their records differ (FO3/FNV keep S.P.E.C.I.A.L. and skills in `AVIF`, which
the exporter does not dump), and each gets its own reader when its rules are
built.

| Key | Holds |
|---|---|
| `version`, `plugin`, `rules` | schema version 1, the plugin, and the rule set: `skill-use` for TES4 |
| `skills` | each `SKIL`: name, actor value, governing attribute, specialization, its two use values, and the [Skyrim skills](#skyrim-skills) its increases can be credited from |
| `classes` | each `CLAS`: its two primary attributes, specialization, seven major skills, and whether chargen offers it |
| `races` | each `RACE`: skill bonuses, base attributes for each sex, the spells it grants, and whether chargen offers it |
| `signs` | each `BSGN` and the spells it grants |
| `settings` | the [leveling settings](#engine-defaults) |
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
