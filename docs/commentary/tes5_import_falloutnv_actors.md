# FO3/FNV actor templates

**Code:** `tes5_import/record_types/actors_falloutnv.py`

## The stub owns nothing

FO3/FNV actors inherit by category. A record carries a `TPLT` naming another
actor and an ACBS `TemplateFlags` word saying which categories come from it —
bit 6 is Model/Animation (`wbTemplateFlags`, wbDefinitionsCommon.pas:7715). A
spawn stub therefore has no MODL, no NIFZ, no race and no stats of its own.

`FalloutNV.esm` CREA `00156782` `VSpawnTier3GiantRadscorpionMed` is the whole
pattern in one record: EDID / OBND / EAMT / NIFT / ACBS / TPLT / AIDT / PKID ×2
/ DATA / RNAM / ZNAM / PNAM / TNAM / BNAM / WNAM / NAM4 / NAM5, TemplateFlags
`0x01DF` (Traits, Stats, Factions, Spell List, AI Data, **Model/Animation**,
Base Data, Inventory). Its mesh is two links away:

    00156782  (stub)      TPLT ─▶ 001567A0  LVLC VEncTier3GiantRadscorpionMed
    001567A0  Entry[0]         ─▶ 0014F401  CREA VCrTier3GiantRadscorpionMed
    0014F401             TPLT ─▶ 0001CF9E  CREA CrRadscorpion2Large
                                            MODL Creatures\Radscorpion\Skeleton.nif

So the chain passes through a leveled list, which is why the resolver follows
`Entry[i].FormID` as well as `TPLT.Template`.

## Why this became a Skyrim giant

`convert_CREA` picks a race in two steps: `get_creature_race(fid)` for a
generated creature race, else `resolve_creature_race(edid, full)`, which
keyword-matches the EditorID. A modelless stub gets no folder, so
`build_creature_races` never registers it and the first step returns None. The
second then matched the substring `giant` in `VSpawnTier3GiantRadscorpionMed`
and returned Skyrim's `GiantRace` (0x000131F9, `skyrim_overrides.py:186`).

The radscorpion's own race, meshes and animations were built correctly and sat
unused. Only the pointer from the placed spawn to that creature was missing —
first because `tes4_export` never emitted TPLT at all
([the export side](tes4_export_falloutnv.md#tplt-carries-the-whole-actor)), and
then because nothing here consumed it.

## Flatten rather than walk

Every pass in this package reads a CREA's own `Model.MODL`: the creature-race
builder derives the folder from it, the body-set lookup keys off `NIFZ`, and
creature voices key off the folder. Teaching each of them to walk a template
chain would be the same fix repeated in several places, and each would have to
agree about depth limits and cycles.

Copying the inherited model onto the stub once, before any of them run, fixes
all of them with no other change — the stub then looks like an ordinary actor
that happens to share a mesh with its template, which is what it is. Only the
categories the flags actually claim are copied.

## Flattening is the only channel

An early version of this note claimed the engine still resolves the remaining
categories through TPLT at spawn time, the way `tes5_import/actors/leveled_actors.py`
relies on for Oblivion's placed-LVLC shells. That is wrong, and measuring the
built ESM settles it: **0 of 5,394 output NPC_ records carry a TPLT**, because
neither `convert_CREA` nor `convert_NPC_` ever emits one — TPLT appeared only
inside a subrecord-order comment. The LVLNs are converted but orphaned; nothing
points at them.

So every category the flags claim is lost unless it is flattened here. Two
besides the model matter in-game, and both were measured against the shipped
`output/FalloutNV.esm`:

* **Base Data (bit 7) carries `FULL`.** 836 output NPC_ shipped with no name.
  The names are not missing at the source — of the 248 actors reachable from a
  leveled list, 247 have their own FULL — they are one link away, on the
  template.
* **AI Data (bit 4) carries `AIDT`.** 1,775 of the 1,880 placed refs whose base
  templates onto a leveled list set this bit, so the stub's own aggression and
  confidence are placeholders the engine would have overwritten.

Flattening all three categories takes the nameless count from **836 to 14**,
and the 14 that remain author no FULL anywhere in the chain (Player,
`AudioTemplate*`, `DocAATEMPLATE` and other placeholders). 879 stubs inherit at
least one category on a FalloutNV.esm run.

The chain must also index **LVLN**, not just LVLC: 258 of the stubs template
onto one, and until its entries were exported the walk dead-ended there. See
[the export side](tes4_export_falloutnv.md#lvln-is-a-native-type).

## <a id="every-category-flattens"></a>Every category flattens, not just three

The three categories above were the ones implemented first; the other seven
were dropped silently, because the reasoning that makes flattening the only
channel applies to all ten equally. Measured over FalloutNV.esm's **3,723
actors that carry a TPLT**:

| Bit | Category | Actors claiming it |
|---|---|---|
| 3 | Actor Effect List | 2,967 |
| 1 | Stats | 2,912 |
| 8 | **Inventory** | **2,886** |
| 2 | Factions | 2,853 |
| 9 | Script | 2,042 |
| 0 | Traits | 1,751 |
| 5 | AI Packages | 1,401 |

**1,310 of the inventory claimants own no items at all**, so they reached the
game naked — `vMONCRTrooper4` (`00145CFC`, templating onto the LVLN
`001543DF`) is one of them. The rest own a partial list and were missing
whatever the template held.

Factions matter as much and are less visible: an actor that inherits its
faction list and loses it has no allies, no enemies and no ownership, which
reads in-game as wrong aggression rather than as missing data.

Six of the categories are **counted arrays** (`ItemCount`/`Item[i]`,
`FactionCount`, `AIPackageCount`, `SpellCount`, `KFFZCount`,
`SoundTypeCount`), so they need a different copier than the scalar keys:
`_copy_array` takes every entry and rewrites the count, because a partial list
is worse than none — the engine reads the count and would index past what was
copied.

<a id="a-claimed-category-is-final"></a>**A claimed category is final.** The
copier first skipped a category whenever the stub already had its lead field,
so that "a stub that overrides it keeps its own". But a stub cannot override a
category it claims: the engine takes that category from the template, and the
CK hides the stub's fields for it. Several of those fields are always written
anyway: `ACBS.Level` and the `AIDT` block sit in fixed-size structs every
record carries. So Stats and AI Data never flattened: the second played run's
Goodsprings coyotes (`VSpawnTier1CoyoteMed`, templating through
`VEncTier1CoyoteMed` onto the level-3 `VCrTier1CoyoteMed`) reported level 1
and paid 1 XP. Each claimed category now comes whole from the nearest actor
down the chain that defines it itself, meaning it does not claim that bit from
a template of its own. Over FalloutNV.esm, stub values that had wrongly stayed:
level 1,127, aggression 717, confidence 854, aggro radius 191, health 543,
item lists 929, models 638, names 8. A chain through a leveled list with
several entries still takes the first entry, where the game picks one per
spawn.

The field-to-bit mapping is xEdit's own, read from the `wbActorTemplateUse*`
visibility predicates each subrecord declares in `wbDefinitionsFNV.pas:6830`
(NPC_) — that is what the CK hides when a bit is set, so it is exactly the set
the engine takes from the template.

## <a id="aggro-radius"></a>The aggro radius carries over (built 2026-10-01, untested in game)

**Code:** `actors_falloutnv.aggro_radius`, used by `actor_common.build_aidt`.

FO3/FNV's AI data has an Aggro Radius Behavior flag and one radius: an actor
with it attacks whoever comes inside, whatever its Aggression. FO3's base
radroach (`CrRadroach`) is Unaggressive (0) with the flag on and a 256-unit
radius, which is how radroaches attack the player in FO3. The converter wrote
Skyrim's flag off and its three radii 0, so Unaggressive creatures never
started a fight with the player (radroaches in FO3, the same in FNV; reported
2026-10-01). Skyrim's Aggro Radius Behavior (CK wiki, AI Data Tab) attacks a
Neutral or Enemy that enters the Attack radius, after a warning in the Warn
and Warn/Attack radii; the FO3/FNV radius now fills all three, so the actor
attacks on entry as the source did.

## <a id="npc-health"></a>NPC hit points follow FO3's formula (built 2026-10-01, untested in game)

**Code:** `actors_falloutnv.npc_health`, used by `npc.source_health`.

FO3/FNV computes an NPC's hit points from its Base Health, Endurance and
level: `Base Health + Endurance x fAVDNPCHealthEnduranceMult + (Level - 1) x
fAVDNPCHealthLevelMult`, both settings 5.0 in FO3 and FNV. The player's
version uses the same shape with 20 and 10 (the wiki's `90 + Endurance x 20
+ Level x 10`, base 100); the NPC level term starting at level 1 follows
that shape and is not read from the exe. A PC Level Mult NPC takes no level
term, since Skyrim adds its own. The result goes through the same offset
solver as TES4's `DATA.Health`
([health offset](tes5_import_actors.md#health-offset)), and a template's
Stats category passes `DATA.BaseHealth` along with the rest.

## <a id="assistance"></a>Assistance is already a tier (built 2026-10-01, untested in game)

**Code:** `actors_falloutnv.assistance`, used by `actor_common.build_aidt`.

FO3/FNV stores Assistance in the TES5 enum: helps nobody, helps allies,
helps friends and allies. The importer derived it from Responsibility as
for TES4 (helps allies at 30 or more), so most Fallout NPCs helped allies
whatever they were authored with. Allen and Gloria Mack (both 0) joined the
security officers' fight with the player in the Atrium (2026-10-01
play-test). The authored value now carries over.

## <a id="aggression-is-already-a-tier"></a>Aggression is already a tier

`build_aidt` in `record_types/actor_common.py` maps TES4's **0-100** scalar
onto TES5's 0-3 tier, and TES4's 0-100 confidence onto TES5's 0-4. That mapping
is correct for Oblivion and must stay.

FO3/FNV does not use scalars. Its Aggression is `wbAggressionEnum` (0-3) and
its Confidence is `wbConfidenceEnum` (0-4) — the *same* enums TES5 uses
(wbDefinitionsFNV.pas:4303, wbDefinitionsCommon.pas:6533). Running an enum
through a scalar bucketer collapses it: every FNV value fell into
`aggr <= 5 → tier 0` and `conf < 15 → tier 0`.

Measured on `FalloutNV.esm`, source against shipped output:

| | source distribution | shipped (before) | shipped (after) |
|---|---|---|---|
| Aggression | 1:2429, 0:1942, 2:1023 | **0 × 5394** | matches source |
| Confidence | 4:1704, 2:1645, 3:1291, 0:597, 1:157 | **0 × 5394** | matches source |

Tier 0 confidence is Cowardly, the one tier that flees on sight, and tier 0
aggression never initiates — which is exactly the reported symptom, leveled
creatures that only ever flee. The fix is a passthrough, not a remap: identical
enums need no translation.
