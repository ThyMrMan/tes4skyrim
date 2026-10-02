# tes5_import/packages/converter.py - AI packages

**Code:** `tes5_import/packages/converter.py`, `tes5_import/packages/actor_wiring.py`, `tes5_import/dialogue/converter.py`, `tes5_import/base/conditions.py`

## Contents

- [PACK Conversion Plan (TES4 → TES5)](#pack-conversion-plan)
- [1. Ground truth (verified, not assumed)](#1-ground-truth)
- [2. What we have on the TES4 side](#2-what-we-have-tes4)
- [3. Design](#3-design)
- [4. Implementation order](#4-implementation-order)
- [5. Verification](#5-verification)
- [6. Risks](#6-risks)
- [7. GetVMScriptVariable package gates need the script on the PLACED ref (2026-07-20)](#7-getvmscriptvariable-package-gates-need)
- [8. PLDT alias locations must be type 8, not type 9 (2026-07-20)](#8-pldt-alias-locations-must)
- [9. QUST.DNAM.Priority must stay in the engine's 0-100 band (2026-07-20)](#9-qustdnampriority-must-stay-engines)
- [10. What the engine actually does with a PACK (disassembly, 2026-07-20)](#10-what-engine-actually-does)
- [PACK conversion: the 2026-08-17 fix pass](#pack-conversion)
- [Status after the 2026-08-17 fix pass](#status-after)
- [PACK conversion: verified-correct behaviour](#pack-conversion-2)
- [Verified correct — do NOT "fix" these](#section)
- [Shop doors: Unlock Doors At Location becomes Unlock At Start](#shop-doors-unlock-at-location)
- [A Travel that ends at furniture sits in it](#travel-to-furniture)

## PACK Conversion Plan (TES4 → TES5)
<a id="pack-conversion-plan"></a>

Goal: **Oblivion-equivalent AI behavior expressed in Skyrim syntax.** Not
"records that load" — actors must keep their schedules, walk their routes,
follow, escort, flee, and ambush the way they did in Oblivion.

> **Status: IMPLEMENTED (updated 2026-07-26).** This document is the design plan
> that the implementation followed; the ground-truth sections below are still the
> reference for how Skyrim's package model works. The status text that used to
> head this file described the pre-implementation state and is preserved at the
> bottom under "Historical: pre-implementation status" so its dated claims are not
> mistaken for current behavior.
>
> Current reality:
> - `PACK` is **NOT** in `SKIP_TYPES` — it is converted.
> - `convert_PACK` lives in [tes5_import/packages/converter.py](../../tes5_import/packages/converter.py)
>   (with templates in [pack_templates.py](../../tes5_import/packages/templates.py)), not
>   in `record_types/dialog_misc.py`, and is live code.
> - PACK is written in its **own phase (import_main Phase 3b2), after QUST**,
>   because quest packages need the aliases to exist first — it is deliberately
>   not in the generic dispatch table.
> - For the verified engine contracts that came out of this work (PTDA distance,
>   Ambush→approach, force-greet topic binding, template data inputs), see
>   [package_ai_contracts.md](../reference/package_ai_contracts.md).

---

## 1. Ground truth (verified, not assumed)
<a id="1-ground-truth"></a>

Sources: `references/xEdit/Core/wbDefinitionsTES5.pas` (PACK at line 11182) and a
census of all 5,961 `PACK` records in `references/Skyrim.esm/PACK.txt`.

### 1.1 The template model — this is the whole architecture

Skyrim packages come in two kinds, and the census settles which one we build:

| Kind | `PKDT.Type` | Has Procedure Tree (`PRCB`) | Count in Skyrim.esm |
|---|---|---|---|
| Template **root** | **19** (`0x13`) | yes | 104 |
| Package **instance** | **18** (`0x12`) | no | 5,758 |

**96.6% of vanilla packages are instances that carry no procedure tree at all.**
They point `PKCU.PackageTemplate` at a root and supply *data inputs*. The root
owns the behavior; the instance owns the customization (destination, target,
radius, schedule, conditions, owner quest).

> `PKDT.Type` is **not** the behavior selector. It only says "I am a template" (19)
> or "I am a package" (18). Behavior lives in the template you point at. Any plan
> that tries to map TES4 `PKDT.Type` onto `PKDT.Type` is building the wrong thing.

**Therefore: we never author procedure trees.** We emit Type-18 instances that
point at stock Skyrim.esm template roots (master index 0, no remapping needed) and
fill in their data inputs. This is exactly what the CK does.

### 1.2 The data-input contract

A template root declares its public inputs as an ordered `UNAM`/`BNAM`/`PNAM`
list. An instance must supply values in a parallel `ANAM`(+`CNAM`/`PLDT`/`PTDA`)
list, then repeat the same `UNAM` index list, then `XNAM`.

Verified instance — `WERoad02Follow` (`0010F589`), a Follow instance.
**⚠ WERoad02 is a HORSEBACK world encounter — its `Ride Horse?=1` /
`Prefer Preferred Path?=1` values are the exception, not the norm (root and
41/44 vanilla Escort instances, 121/124 Follow instances use 0). Freezing
those values as converter defaults made every converted escort/follow NPC
stand still (a horseless actor with Ride Horse?=1 never moves — Pinarus
Inventius in FGC01Rats). Defaults now mirror the template ROOT; the TES4
Use-Horse flag (PKDT 0x00800000, 65 packages) sets `ride_horse` explicitly
in `pack_converter._choose()`. Fixed 2026-07-19.**

```
PKDT.hex = 00000000 12 00 02 82 FFFF 0000   ; Type=18 (instance)
CTDA     = <condition>
QNAM     = 001027A5                          ; owner quest
PKCU.hex = 06000000 2C9B0100 04000000        ; 6 inputs, template=00019B2C (Follow), version=4
ANAM=SingleRef  PTDA = Type 4 (RefAlias), alias 0x29, count 0
ANAM=Float      CNAM = 256.0     ; Min Radius
ANAM=Float      CNAM = 512.0     ; Max Radius
ANAM=Bool       CNAM = 1         ; Accompany?
ANAM=Bool       CNAM = 1         ; Ride Horse?
ANAM=Bool       CNAM = 0         ; Need LOS?
UNAM=0 UNAM=1 UNAM=2 UNAM=4 UNAM=6 UNAM=8
XNAM=9
POBA/INAM/PDTO  POEA/INAM/PDTO  POCA/INAM/PDTO
```

The `UNAM` index list and `XNAM` value are **copied verbatim from the template
root** — they are the root's public-input signature, not something we compute.
`XNAM` is the root's marker byte-count value (`9` for Follow, `5` for Travel,
`32` for Sandbox, `20` for EscortPlayerWhenNear).

`PKCU` = `DataInputCount:u32`, `PackageTemplate:formid`, `VersionCounter:u32`.
`DataInputCount` is the number of `ANAM` value entries (6 above), which equals the
number of `UNAM` entries.

### 1.3 Template roots we will target (all vanilla Skyrim.esm, master index 0)

Skyrim ships a **dedicated template for nearly every Oblivion package type**. This
is the crux of the whole plan: we are not approximating Oblivion behavior with
generic Skyrim sandboxing — we are mapping each Oblivion type onto the Skyrim
template that implements *the same procedure*.

| FormID | EditorID | Procedures in its tree | Key inputs |
|---|---|---|---|
| `00016FAA` | `Travel` | Travel | Place to Travel *(Location)*, Ride Horse, Prefer Preferred Path |
| `0001C254` | `Sandbox` | Travel → UnlockDoors → Sandbox | Location, + 10 booleans (Eating/Sleeping/Conversation/IdleMarkers/Sitting/Wandering/SpecialFurniture…), Energy |
| `00019714` | **`Eat`** | Travel → UnlockDoors → Find → Sandbox → **Acquire** → Find | **Eat Location**, **Food Criteria**, NumFoodItems, Chair Target, Wait Time |
| `00019717` | **`Sleep`** | Travel → **LockDoors** → Find → Sandbox → **Sleep** | **Sleep Location**, **Search Criteria** (bed), Warn Before Locking, Lock Doors |
| `00017723` | **`Patrol`** | Patrol | Patrol Start, Patrol Radius, Repeatable?, Start At Nearest?, Static Pathing? |
| `000503D0` | **`HoldPosition`** | HoldPosition | Hold Position Location, Radius, Center |
| `000A9277` | **`SitTarget`** | Sit → Wait | Sit Location, Search Criteria, **Chairs** *(ObjectList)*, Wait Time |
| `00019B2C` | `Follow` | Follow | Target to Follow *(SingleRef)*, Min/Max Radius, **Accompany?**, Ride Horse?, Need LOS? |
| `00069665` | `EscortPlayerWhenNear` | Escort → Travel | Target to Escort *(SingleRef)*, Destination *(Location)*, Distance to Wait for Player, Follower Min/Max Distance, Run if Behind |
| `000C7039` | **`FleeTo`** | Flee | Distance to Flee, **Flee To Location**, **Flee From Target**, Goal Radius, Quiet? |
| `0003C1C4` | `ForceGreet` | Travel → ForceGreet → Sandbox | Target, Location, **Topic**, Forcegreet Distance, Trigger Radius |
| `000F5842` | `UseMagicRepeat` | (dump before use) | — |

Note `Eat` and `Sleep` are *not* Sandbox-with-a-boolean — they are their own trees
with an `Acquire` procedure (go get food) and a `Sleep`+`LockDoors` procedure
respectively. Using them instead of Sandbox is what makes an Oblivion innkeeper's
"eat at 8pm in the tavern" actually read as eating rather than milling around.

**Step 0 of implementation is still to dump every root we intend to use and freeze
its exact `UNAM`/`BNAM` signature** (`tools/esm/pack_template_dump.py`). The tables in
this document are a design aid, not the source of truth — inputs are positional.

### 1.4 Substructures

`PKDT` (12 bytes): `GeneralFlags:u32`, `Type:u8`, `InterruptOverride:u8`,
`PreferredSpeed:u8` (0 Walk/1 Jog/2 Run/3 FastWalk), `pad:u8`,
`InterruptFlags:u16`, `pad:u16`.

`PSDT` (12 bytes): `Month:s8`, `DayOfWeek:s8`, `Date:u8`, `Hour:s8`, `Minute:s8`,
`unused[3]`, `Duration:s32` **in minutes**. TES4 `PSDT.Duration` is in *hours* —
multiply by 60. TES4 `PSDT.Time` is an hour → `Hour`, `Minute=0`. `-1` = Any.

`PLDT` (12 bytes): `Type:s32`, `Value:4`, `Radius:s32`. Types: 0 Reference,
1 Cell, 2 Near Package Start Loc, 3 Near Editor Loc, 4 Object ID, 5 Object Type,
6 Keyword, **8 Alias**, **9 Reference (alias)**.

`PTDA` (12 bytes): `Type:s32`, `Target:4`, `Count/Distance:s32`. Types:
0 Specific Reference, 1 Object ID, 2 Object Type, 3 Linked Reference,
**4 Ref Alias**, 6 Self.

### 1.5 PKDT General Flags (TES5)

`0x1` Offers Services · `0x4` Must complete · `0x8` Maintain Speed at Goal ·
`0x40` Unlock doors at start · `0x80` Unlock doors at end · `0x200` Continue if PC
Near · `0x400` Once per day · `0x2000` Preferred Speed · `0x20000` Always Sneak ·
`0x40000` Allow Swimming · `0x100000` Ignore Combat · `0x200000` Weapons
Unequipped · `0x800000` Weapon Drawn · `0x8000000` No Combat Alert.

### 1.6 How a package reaches an actor

Two routes, and vanilla uses both:

- **`PKID` on the actor** — the actor's own standing package list (schedules).
- **`ALPC` on a quest reference alias** — quest packages. Vanilla Skyrim.esm has
  **4,125 `ALPC` entries**. Alias packages outrank the actor's base list while the
  quest is running, which is precisely how Oblivion's "quest package with a
  `GetStage` condition sitting at the top of the NPC's list" behaves.

Our `convert_QUST` ([tes5_import/dialogue/converter.py:379](../../tes5_import/dialogue/converter.py#L379))
currently emits **no aliases at all**. That is a hard prerequisite for quest
packages.

---

## 2. What we have on the TES4 side
<a id="2-what-we-have-tes4"></a>

`export/Oblivion.esm/PACK.txt` — 7,209 records, and the exporter already emits
every field we need (`PKDT.Flags/Type/Format`, `PSDT.*`, `PLDT.Type/Location/Radius`,
`PTDT.Type/Target/Count`, `Condition[N].Raw`).

| TES4 Type | Count | Target template | Fidelity |
|---|---:|---|---|
| 6 Travel | 1,924 | `Travel` / `SitTarget` | **exact** — same procedure; one ending at furniture sits in it ([§](#travel-to-furniture)) |
| 5 Wander | 1,820 | `Sandbox` | **exact** — TES4 Wander = wander/sit/idle in a radius, which is what Sandbox does |
| 3 Eat | 829 | `Eat` | **exact** — dedicated tree w/ Acquire+Find-chair |
| 8 UseItemAt | 751 | `SitTarget` / `Activate` / `Travel` | **partial** — see §2.1, §3.2 |
| 0 Find | 741 | `Activate` / `ForceGreet` / `Sandbox` | **partial** — see §2.1, §3.2 |
| 4 Sleep | 725 | `Sleep` | **exact** — dedicated tree w/ bed-find + LockDoors |
| 1 Follow | 208 | `Follow` | **exact** |
| 9 Ambush | 80 | `HoldPosition` + Weapon Drawn / No Combat Alert | **close** |
| **2 Escort** | **75** | `TES4EscortWhenNear` (converter-owned root) | **exact** ← *fgc01rats*; see [§ escort restarts](#escort-restarts-when-the-target-returns) |
| 7 Accompany | 40 | `Follow` w/ `Accompany?=1` | **exact** — Skyrim models Accompany as a Follow input |
| 10 FleeNotCombat | 11 | `FleeTo` | **exact** |
| 11 CastMagic | 5 | `UseMagicRepeat` | **close** |

3,874 have conditions, 6,576 have `PLDT`, 1,776 have `PTDT`.

### 2.1 Fidelity analysis — where Oblivion behavior does and doesn't survive

**Locations carry over almost exactly.** TES4 `PLDT` types and TES5 `PLDT` types
are the same enum for 0–5, and vanilla Skyrim *uses* the ones we need:

| TES4 PLDT type | Uses | TES5 support |
|---|---:|---|
| 0 Near Reference | 4,647 | type 0 — used 4,048× in vanilla |
| 3 Near Editor Location | 856 | type 3 — used 605× |
| 1 In Cell | 746 | type 1 — **used 448× in vanilla**, so cell-scoped Eat/Sleep survive |
| 2 Near Current Location | 237 | type 2 — used 341× |
| 4/5 Object ID / Type | 14 | types 4/5 exist |

So "sleep in *this* bed", "eat in *this* cell", "wander within radius R of *this*
marker" all translate 1:1. This is the single biggest reason the schedules survive:
**the spatial data is not being approximated, it is being copied.**

**Schedules carry over exactly.** `PSDT` is month/day-of-week/date/hour/duration in
both games. The only conversion is hours → minutes on Duration. An NPC who ate at
20:00 for 2 hours still does.

**Conditions carry over** via the existing CTDA translator, which is what preserves
the *activation logic* (`GetStage`, `GetDayOfWeek`, disposition checks).

**Where it degrades — be honest about these:**

1. **UseItemAt (751)** — TES4's target is an *object type* (336) or *object ID*
   (318) more often than a specific ref (97): "use any chair", "use any bed".
   Skyrim's `SitTarget` takes a `Chairs` ObjectList input, which covers the common
   furniture cases, but TES4 UseItemAt could point at arbitrary activators. Plan:
   route furniture-ish targets to `SitTarget`, everything else to `Travel` +
   Sandbox-with-special-furniture at the location. Some "use this specific device"
   packages will read as "go there and idle." Accept, document, revisit.

2. **Find (741)** — TES4 Find = travel to a location *and locate an object/actor
   there*, with the object in `PTDT` (464 specific refs, 84 object types). Skyrim's
   `Eat` template has a `Find` procedure but there is no standalone generic Find
   root. Plan: `Travel` to the `PLDT` + Sandbox at the destination. The travel and
   the destination — the parts a player observes — are exact; the "locate this
   object" tail is dropped.

3. **Ambush (80)** — Skyrim has no Ambush procedure. `HoldPosition` + `Weapon
   Drawn` + `No Combat Alert` reproduces "wait hidden, weapon out, don't call for
   help," which is behaviorally most of it, but the trigger-on-detection nuance is
   the combat AI's, not the package's.

4. **PKDT flag bits without TES5 equivalents.** TES4 "Once per day" → TES5 `0x400`
   (same concept, different bit). TES4 "Always run" → `PreferredSpeed=Run` +
   `0x2000`, not a flag. Bits with no counterpart are dropped, not guessed. **Do
   not map a TES4 flag onto a TES5 "Unknown NN" bit** — the old `convert_PACK`
   docstring proposed exactly that ("0x2000 Always run → 0x02000000 Unknown 26"),
   which would set random engine behavior.

**Net:** ~6,300 of 7,209 packages (87%) map onto a Skyrim template that runs the
same procedure with the same location, the same schedule, and the same conditions.
The rest degrade to travel-and-sandbox, which is strictly better than today's
"everything is one sandbox and nobody moves."

---

## 3. Design
<a id="3-design"></a>

### 3.1 New module: `tes5_import/packages/converter.py`

Own file (CLAUDE.md: keep files < ~1000 lines; `dialog_misc.py` is already large).
Delete `convert_PACK` from `dialog_misc.py`.

```
TEMPLATES = {...}                  # dumped from Skyrim.esm, §1.3 — the input signatures
build_package(rec, ctx) -> bytes   # one TES4 PACK → one TES5 PACK instance
```

The core is a **template-instance emitter**:

```
emit_instance(template, inputs, flags, speed, schedule, conditions, owner_quest)
  PKDT  <- flags | Type=18 | preferred speed | interrupt flags
  PSDT  <- schedule (hours→minutes)
  CTDA* <- translated conditions
  QNAM  <- owner quest (quest packages only)
  PKCU  <- (len(inputs), template.formid, version)
  ANAM/CNAM/PLDT/PTDA per input, in the template's declared order
  UNAM* <- template.unam_indices  (verbatim)
  XNAM  <- template.xnam          (verbatim)
  POBA/INAM/PDTO  POEA/...  POCA/...   (all three required)
```

Everything else is a per-TES4-type function deciding *which template* and *what
inputs*. That keeps the type-specific logic small and declarative.

### 3.2 Type mapping (behavior-first)

Each rule below preserves the TES4 `PLDT` (location, **including its type and
radius**), the `PSDT` schedule, and the conditions. Only the *procedure* is
re-expressed in Skyrim's vocabulary.

- **Travel (6)** → `Travel`, or `SitTarget` when `PLDT` is a furniture
  reference ([travel to furniture](#travel-to-furniture)). `PLDT` → *Place to Travel*. TES4 "always run" →
  `PreferredSpeed=Run` + `0x2000`.
- **Wander (5)** → `Sandbox` at `PLDT`, radius preserved. Booleans:
  Wandering/Sitting/IdleMarkers/Conversation on.
- **Eat (3)** → `Eat` template. `PLDT` → *Eat Location*. The template's own
  Find→Acquire→Sandbox chain does the food-seeking; `PSDT` carries the mealtime.
- **Sleep (4)** → `Sleep` template. `PLDT` → *Sleep Location*. Template finds the
  bed and locks doors; `PSDT` carries bedtime and duration.
- **Find (0)** → `Activate` when `PTDT` names a specific **ACTI/DOOR/CONT** ref
  (see "operate the thing" below); `ForceGreet` when it names the player;
  otherwise `Travel` to `PLDT`, then Sandbox at destination. (Object-location
  tail is dropped — see §2.1.)
- **UseItemAt (8)** → `SitTarget` when the `PTDT` target is furniture (chair/bed/
  bench, incl. object-type targets → *Chairs* ObjectList); `Activate` for any
  other specific ref; otherwise `Travel` + Sandbox with Special Furniture
  allowed.

#### "Operate the thing": Find/UseItemAt at an activator

Both TES4 types are *seek-then-use* procedures, and Skyrim has no standalone
equivalent — the seek half looks like Travel, but the **use** half is the whole
point, because the target object's `OnActivate` script is what advances the
quest. Routing these to Sandbox leaves the actor standing inert beside the
object forever; worse, this idiom usually carries **no `PLDT` at all**, so the
Sandbox gets an empty location and the actor does not even walk over.

Skyrim expresses exactly this with the **`Activate` template (`00019B2D`)** —
24 vanilla instances, e.g. `MQ101HadvarOpenGate2`, `MS02BorkulOpenDoorPackage`,
`TG08AKarliahOpenGatePackage`, `MQ203DelphineLightRightSconce`.

`pack_converter._operate_target()` is the single decision point for both types:
target must be `PTDT.Type == 0` (specific ref), not the player, and the base
signature decides — UseItemAt takes anything **non-furniture**, Find takes
`ACTI`/`DOOR`/`CONT` only. It also drives the PKDT choice (vanilla speed +
`0xFFFF` interrupts), so the actor can break off its schedule to do the job.

Census of Oblivion's 741 Find packages by target: 230 `NPC_` (a greet — must
stay Sandbox), 123 no `PTDT`, 101 `STAT` (markers — Sandbox), 84+70 object-type
targets, 73 player (ForceGreet), and **24 `ACTI`/`DOOR`/`CONT`** — the operate
set. Getting this wrong stalls scripted sequences with no error and no log
line: `CGRatAmbushAPushBricks` (rat → `CGCrumbleWall01REF`) meant the
CharacterGen wall never crumbled, `setstage MQ01 24` never ran, and the
tutorial rats never turned hostile no matter how long the player waited.
- **Follow (1)** → `Follow`, `PTDA` = target, `Accompany?=0`.
- **Accompany (7)** → `Follow`, `Accompany?=1` — Skyrim models Accompany as a
  Follow input, so this is exact, not an approximation.
- **Escort (2)** → `TES4EscortWhenNear`, the converter's own root
  ([§ escort restarts](#escort-restarts-when-the-target-returns)). `PTDT` →
  *Target to Escort*, `PLDT` → *Destination*.
- **FleeNotCombat (10)** → `FleeTo`. `PLDT` → *Flee To Location*, `PTDT` →
  *Flee From Target*.
- **Ambush (9)** → `HoldPosition` at `PLDT` + `Weapon Drawn` + `No Combat Alert`.
- **CastMagic (11)** → `UseMagicRepeat`.

### 3.3 Reference targets → aliases

`PTDT.Target = 0x00000014` is the **player**. In Skyrim a package can't name the
player as a raw FormID target in a base-actor package; targets resolve through
`PTDA` Type 4 (Ref Alias) on a quest, or Type 0 against a persistent ref.

Rule:
- Package is quest-owned (has a `GetStage`/`GetQuestVariable` condition, or is
  referenced only from a quest context) → emit as **alias package**: create the
  reference alias on the owning QUST, set `QNAM`, use `PTDA` Type 4 / `PLDT`
  Type 8-9 pointing at alias indices, and attach via `ALPC`.
- Otherwise → base actor `PKID`, `PTDA` Type 0 against the persistent ref.

### 3.4 QUST aliases (prerequisite, `dialog_converter.py`)

Extend `convert_QUST` to emit reference aliases:
`ANAM` (next alias id) then, per alias: `ALST`, `ALID`, `FNAM`, `ALFR` (forced ref)
or `ALUA` (unique actor), `ALPC`* , `ALED`.

Sources for aliases:
1. Every actor named by a quest package's `PTDT`/`PLDT` (e.g. `PinarusInventiusREF`).
2. The player — a `Player` alias (`ALFR = 0x00000014`) for escort/follow targets.
3. TES4 `QSTA` quest targets we already parse.

Aliases must be **stable and idempotent** (index by EditorID) because the Papyrus
`Package Property` bindings and existing quest fragments reference them by name.

### 3.5 Conditions

TES4 `Condition[N].Raw` → TES5 `CTDA` via the **existing** translator in
[tes5_import/base/conditions.py](../../tes5_import/base/conditions.py) — do not
write a second one. Quest packages' `GetStage FGC01Rats == 50` conditions are the
entire activation mechanism, so this must be reused, not approximated.

### 3.6 Actor wiring — retire the substitution shim

[tes5_import/packages/actor_wiring.py](../../tes5_import/packages/actor_wiring.py) currently *drops* types
{1,2,7,8,9,10} and collapses everything else to one sandbox. Once real packages
exist:

- `PKID` = the actor's converted packages, **in TES4 order** (Skyrim, like
  Oblivion, takes the first package whose conditions pass — order is behavior).
- Keep `DPLT` (`DefaultMasterPackageList`) as the fallback beneath them.
- Creatures get the same list, with `DefaultMasterPackageCreature` appended as
  the fallback. Dropping their authored packages stranded scripted creatures
  ([why](tes5_import_actors.md#creature-class-and-package)).
- `packages.py` shrinks to the creature default + a fallback for actors whose
  packages all failed to convert.

---

## 4. Implementation order
<a id="4-implementation-order"></a>

Each step is independently testable; **do not batch them**.

0. **Dump the template roots.** Write `tools/esm/pack_template_dump.py` — given a
   template EditorID/FormID, print its `UNAM`/`BNAM`/`PNAM` signature, `XNAM`, and
   procedure tree from `references/Skyrim.esm/PACK.txt`. Freeze the results into
   `TEMPLATES` in `pack_converter.py`. **No table in this plan is a substitute for
   this step.**

1. **Emitter + Travel.** `pack_converter.py`, `emit_instance`, and TES4 Travel →
   `Travel`. Remove `PACK` from `SKIP_TYPES`. Byte-compare one emitted record
   against a vanilla Travel instance (`MQ303OdahviingWaitToFlyAlias` structure).
   Ship it and check NPCs actually walk their routes.

2. **Routine family** — Wander → `Sandbox`, Eat → `Eat`, Sleep → `Sleep`
   (3,374 records, 47% of the corpus). This is what restores daily routines across
   the whole game, and it is the step where "is this really Oblivion behavior?"
   gets answered empirically: pick an NPC with a known Oblivion schedule (e.g. an
   Anvil innkeeper), and watch a full 24h day at high timescale. They should eat,
   sleep, and open shop at the same hours, in the same rooms, as in Oblivion.

3. **QUST reference aliases** in `convert_QUST` (player alias + actor aliases +
   `ALPC`). No behavior change yet; verify in SSEEdit that aliases resolve.

4. **Escort + Follow + Accompany**, routed through aliases. **This is the
   fgc01rats fix.** The script side already works: `TES4_QF_FGC01Rats.psc` already
   emits `PinarusInventiusRef.EvaluatePackage()` at stage 50, and
   `TES4_FGC01PiranusScript.psc` already emits
   `Event OnPackageEnd(...) If akOldPackage == FGC01PinarusEscort`. Both are
   currently calling into a package record that does not exist. Creating
   `FGC01PinarusEscort` as a real PACK is the *only* missing piece — the
   `Package Property` VMAD binding will then resolve instead of reading `None`.

5. **Find / UseItemAt** (1,492 records — sitting, eating at inns, using furniture).

6. **Ambush / Flee / CastMagic** (96 records — long tail).

7. **Delete the substitution shim** from `packages.py`; wire real `PKID` lists in
   TES4 order.

## 5. Verification
<a id="5-verification"></a>

- **Structural:** SSEEdit loads output with no PACK errors; `tools/` script
  byte-compares a converted instance against its vanilla analogue (per CLAUDE.md:
  verify against **both** the xEdit def and a real Skyrim.esm dump).
- **Behavioral, per stage:** load a save, `tc` off, watch an NPC. Step 1 = NPCs
  travel. Step 2 = NPCs eat/sleep/wander on schedule. Step 4 = **Pinarus follows
  the player after stage 50, and starts the wrap-up conversation when the escort
  ends** (proves `PKID` order, alias resolution, `CTDA` translation, `ALPC`
  priority, `EvaluatePackage()`, and `OnPackageEnd` all line up).

## 6. Risks
<a id="6-risks"></a>

- **`PKDT.Type=19` roots must never be emitted.** Writing a template root as an
  actor's package gives an actor a package with no instance data. Always 18.
- **Input order is positional.** The `ANAM` value list must match the template's
  `UNAM` order exactly; a swapped Float feeds "max radius" into "min radius".
  Drive both lists from one frozen `TEMPLATES` entry so they cannot drift.
- **`PSDT` duration unit.** Hours (TES4) vs minutes (TES5). A 6-hour package
  becomes 6 minutes if missed.
- **Alias index churn.** If alias IDs shift between runs, Papyrus property
  bindings and `ALPC` links break. Assign deterministically.
- **Package order is behavior.** Preserve TES4 `AIPackage[N]` order in `PKID`.
- Old `convert_PACK` docstring is actively misleading (wrong `PKDT.Type` semantics,
  invented template FormIDs like "DefaultTravelToRef 0x000D6B8C"). **Delete it
  with the function**; do not mine it for tables.

## 7. `GetVMScriptVariable` package gates need the script on the PLACED ref (2026-07-20)
<a id="7-getvmscriptvariable-package-gates-need"></a>

Symptom: quest NPCs don't move when they should — Arielle (MG04Restore) never
walks to her rented room, Pinarus (FGC01Rats) never hunts the mountain lions.
Their quest packages (travel / escort / find) are gated by a translated
`GetScriptVariable(ActorRef, packageVAR)==N` → `GetVMScriptVariable(630)` with the
variable name in a `CIS2 ::packageVAR_var` (see the legacy-var-condition note in
docs/commentary/tes5_import_dialogue.md). Everything downstream was correct — the
package was detected as quest-owned, an `ALPC` hung it off the actor's QUST
reference alias, `packageVAR` was declared `Auto Conditional`, and the reveal
INFO's TIF fragment set `ActorRef.packageVAR = N; ActorRef.EvaluatePackage()`.

**The break:** `GetVMScriptVariable(ref, "::var_var")` reads the property off a
script attached to the **reference named in param1 (the ACHR)** — NOT the base
actor. The converter attached the actor script to the base `NPC_`/`CREA`
(object_scripts.SCRIPTABLE_TYPES), and the placed `ACHR` had no VMAD of its own.
A base-attached script propagates to instances for property *access* (the
fragment write works), but the condition *read* fails, so the gate never passes,
the package never wins arbitration, and the actor stays put. Verified against
Skyrim.esm: **100% of vanilla func-630 (`GetVMScriptVariable`) package conditions
name a REFR that carries its own VMAD** holding the variable (RatwayDrawbridgeRef
`::isOpen_var`, ResourceObject `::ResourceState_var`, MG02DraugrAmbushTrigger
`::DoOnce_var`). Every vanilla p1 is a REFR (object) — Bethesda never stores this
on an actor, so the actor case is novel, but the VM contract is identical.

**Fix (`object_scripts._relocate_actor_scripts_to_refs`):** for each `ACHR`/`ACRE`
read by a `GetVMScriptVariable` package condition, relocate the actor's script
VMAD from the base record onto the placed ref (`convert_ACHR` now splices it in as
`EDID VMAD NAME …`). The script is *moved* (base entry removed) so there is one
instance both the write and the read resolve to — unless the base has >1
placement (SI victims, Sheogorath's sheep: 3 bases), where the base keeps its
script and the read ref gains its own copy. Scope: 94 actors relocated across
~142 gated refs. Scripts `extends Actor`, which attaches fine to a placed actor
reference. Regression: `test_actor_script_relocated_to_placed_ref`,
`test_shared_base_keeps_script_and_adds_ref`.

## 8. `PLDT` alias locations must be type 8, not type 9 (2026-07-20)
<a id="player-target-is-the-reference"></a>
### A player package target is the REFERENCE, never the base NPC_

"The player", however TES4 spelled it, is the specific reference `PlayerRef`.
Oblivion routinely writes it as Object-ID plus the player's base `NPC_`
(0x07), but Skyrim's escort/follow procedures need a *reference* to act on,
and vanilla is emphatic about which one: **Skyrim.esm names the player as a
package target 543x as (type 0, 0x14) against just 6x as (type 1, 0x07)**.
Left as an Object-ID the engine holds a base form rather than an actor to
follow, so the package is SELECTED but its procedure never engages —
**Morroblivion's chargen guard said "follow me" and stood still**.

`resolve_target` normalizes to the reference FIRST, before the alias lookup,
so the lookup sees 0x14 and a quest package still routes the player through
its quest reference alias (`PTDA` type 4). That aliasing is what lets the
package outrank the actor's standing schedule, so it must not be
short-circuited.

<a id="8-pldt-alias-locations-must"></a>

The fix in §7 was necessary but not sufficient — after it, `sv` on Pinarus showed
`TES4_FGC01PiranusScript` attached to the ACHR, `packageVAR` = 1, the package
property bound, and the quest at stage 50 with every alias filled. He **stood up
out of his chair and then went nowhere**. That symptom is diagnostic: the package
won arbitration and its procedure started, so the fault is in the package's own
data inputs, not the gate.

`build_alias_location` emitted **`PLDT` type 9**. Per xEdit `wbLocationEnum`
(`wbDefinitionsTES5.pas:2620`):

| Type | Meaning |
|---|---|
| 8 | **Alias (reference)** — a REFERENCE alias ✅ what a quest package needs |
| 9 | Alias (location) — an LCTN-type **location** alias |

We were handing a *reference*-alias index to the *location*-alias slot, so the
destination resolved to nothing. Census of Skyrim.esm confirms 9 is a dead end:

```
vanilla PLDT types: {0: 4048, 1: 448, 2: 341, 3: 605, 6: 416, 8: 585, 9: 1, 12: 394}
```

**Type 9 appears once in 6,838 packages; type 8 appears 585 times.** Vanilla
attestation: `WERoad11EscortNoHorse` = `PLDT` type 8 alias 0x22 + `PTDA` type 4.
`PTDA` type 4 ('Ref Alias', 236 vanilla uses) was already correct — only the
LOCATION side was wrong, which is why the escort *target* (the player) was fine
and only the destination was dead.

Fixed to type 8; **85 quest packages** corrected, zero type-9 PLDTs remain.
Regressions: `test_alias_location_uses_reference_alias_type_8`,
`test_quest_escort_location_routes_through_alias_as_type_8`.

Independently confirmed against the engine's own reverse-engineered layout —
CommonLibSSE-NG `RE/P/PackageLocation.h` `PackageLocation::Type`:

```
kNone(-1) kNearReference(0) kInCell(1) kNearPackageStartLocation(2)
kNearEditorLocation(3) kObjectID(4) kObjectType(5) kNearLinkedReference(6)
kAtPackagelocation(7) kAlias_Reference(8) kAlias_Location(9) kNearSelf(12)
```

`SkyrimSE.exe` RTTI also carries `BGSLocAlias` as a class distinct from
`BGSBaseAlias`, corroborating that 8 and 9 resolve through different alias kinds.

**Debug lesson:** `sv` on a selected actor is the fastest way to split this class
of bug — it shows attached scripts, their variable values, and bound properties
in one shot. It cleared the entire condition/alias/script layer and localized the
fault to the package inputs.

## 9. QUST.DNAM.Priority must stay in the engine's 0-100 band (2026-07-20)
<a id="9-qustdnampriority-must-stay-engines"></a>

Third bug on the same symptom, and the systemic one. `FGC01Rats` was written with
**DNAM.Priority = 161**. Census of Skyrim.esm: **391 quests, max priority exactly
100, ZERO above it** — the CK field is 0-100. Our output had **265 of 391 (68%)
over 100**, up to 191.

Cause: `compute_quest_priorities` boosted every staged quest by a raw additive
offset so staged quests would outrank stage-less "conversation container" quests
in dialogue arbitration (§ dialogue notes). TES4 priority 60 + offset 101 = 161.
The boost solved the dialogue-ordering problem and silently created an AI one:
**DNAM.Priority is not only a dialogue tiebreak — it arbitrates a quest ALIAS
PACKAGE against the actor's standing schedule.** Out-of-band priority is why a
converted escort could pass its condition and start (the actor visibly stands up)
and still never travel.

Fix: keep the two-band design but **rescale** each band into the valid range
instead of adding an offset — zero-stage quests → `0..ZERO_STAGE_TOP` (49),
staged quests → `50..QUEST_PRIORITY_MAX` (100). Relative order within each group
is preserved (a linear map, not a rank remap), and the staged band still
universally outranks the container band.

Result: priorities now span 0-100 with **zero** out-of-band; staged 50-100 (n=265),
zero-stage 0-49 (n=125). `FGC01Rats` and `MG04Restore` both land at **83 — the
same priority vanilla gives MQ203**, its own escort-package quest.

Regression: `test_quest_priority_never_exceeds_engine_max` (asserts the range,
the written byte, and that the two-band ordering survives the clamp).

**Lesson:** when a derived value is written into a field the engine reads for
MORE than one subsystem, bound it to the range the engine documents for that
field, not to the storage type's range (U8 0-255). The old code clamped to 255.

## 10. What the engine actually does with a PACK (disassembly, 2026-07-20)
<a id="10-what-engine-actually-does"></a>

Settled by disassembling the **GOG** (unencrypted) `SkyrimSE.exe` 1.6.659 — the
Steam copy is Steam-DRM packed (`.text` entropy 8.00) and cannot be read
statically. Use `tools/disasm/skyrim_disasm.py --exe "D:/Other Games/Skyrim Anniversary
Edition/SkyrimSE.exe"`.

Key RVAs:

| RVA | What |
|---|---|
| `0x451990` | `TESPackage::LoadBuffer` (TESForm vtable slot 6) |
| `0x451a00` | its main subrecord dispatch loop |
| `0x4507d0` | package-type setter; types 18/19 both dispatch via `0x450c68` |
| `0x457cd0` | PKCU handler → builds the package-data object |
| `0x404710` | **the data-input reader** — driven by `PKCU.DataInputCount` |
| `0x4432e0` | single-ANAM fallback reader (only when `Template == 0`) |
| `0x4154d0` | `GetPackageData(slot)` |
| `0x404e10` | slot resolver: searches the **UNAM index-byte array** |
| `0x359c9f` | alias `ALPC` handler |

Subrecords `LoadBuffer` reads: `PKDT PSDT PLDT PTDT PTDA PKCU PKPT PLD2 PTD2
PKE2 PKW3 PKDD PKFD PT2A CTDA IDLA-F POBA POEA POCA EDID OBND VMAD`. `CNAM`/`QNAM`
are package-level u32s (`0x45217d`); `ANAM`/`UNAM`/`XNAM` are consumed by the
data-input reader, not this switch.

**Two contracts that matter for conversion:**

1. **`PKCU.DataInputCount` drives the read.** `0x404710` loops exactly that many
   times consuming `ANAM` entries — regardless of `PKCU.Template`. If the count
   disagrees with the number of `ANAM`s emitted, inputs are lost or the reader
   over-runs into following subrecords.
2. **Procedures address inputs by UNAM byte, not by position.** `0x404e10` walks
   a parallel index-byte array (the `UNAM` list) and returns the entry whose byte
   equals the requested slot. So the `UNAM` list must match the template root's
   exactly; a positional-but-wrong UNAM silently feeds a procedure the wrong
   value.

**A misread worth recording:** `0x457d59`'s `test eax,eax / jne` on
`PKCU.Template` looks like "skip the data inputs when a template is set". It is
not — the real reader (`0x404710`) already ran at `0x457d54`; the branch only
skips building the no-template fallback. Data confirms it: vanilla instances
carry `PLDT` values that differ from their root (Esbern type 0 ref `0x0010ff08`;
root type 3 value 0). **Never zero `PKCU.Template`.**

**Validator:** `tools/esm/pack_validate.py` encodes all of the above.

```bash
python tools/esm/pack_validate.py output/Oblivion.esm/Oblivion.esm \
       --ref "<SSE>/Data/Skyrim.esm" --summary
```

It checks PKDT type/size, PKCU size, count-vs-ANAM agreement, UNAM presence and
length, PLDT/PTDA type legality (rejecting the type-9 bug from §8), and — with
`--ref` — full agreement with the template root on input count, PKCU version,
UNAM order and ANAM type names. It flags the §8 bug on a synthetic pre-fix
record, so a clean run is meaningful. **Current state: all 7,209 converted PACKs
clean.**


## PACK conversion: the 2026-08-17 fix pass
<a id="pack-conversion"></a>

What changed after the audit, including two findings the audit got wrong.

## Status after the 2026-08-17 fix pass
<a id="status-after"></a>

Everything below was measured with `python tools/esm/pack_audit.py --detail`
(which now builds the import's own context via `tes5_import.pack_indexes`).
Oblivion routing before → after, Find/UseItemAt only:

```
Find      Sandbox 513 → 194   Travel 236 → 337   Acquire 0 → 72   Sit 0 → 16
          SitTarget 0 → 17    ForceGreet 79      Activate 26
UseItemAt Sandbox 662 → 656   Activate 87        Sit 0 → 6        SitTarget 2
```

### Fixed

* **Gap 1 (Object-ID / Object-Type targets).**
  `pack_converter._find_object_criteria` + `object_criteria_kind`:
  * actor base with **one** placement → the Object ID *is* that ref → Travel
    near it (alias-routed like any specific ref);
  * actor base with several placements (FGC06Goblin ×9, FGD08Goblin ×11,
    FGC01 lions/rats) → a **chain of Follow packages, one per placed target,
    nearest the hunter first**, each gated on the source's conditions +
    `GetInSameCell(target)`, `GetDisabled==0` and `GetDead==0` on the target,
    ahead of the source in the alias ALPC / PKID list; the source itself
    (a wander-only in-cell Sandbox) is the tail. FormIDs are derived from
    (source PACK, target ref). **Measured live 2026-08-18** (game bridge, FGC06
    at stage 30): with the Sandbox alone all three fighters were RUNNING their
    hunt package (`getiscurrentpackage`) yet stayed within ~300 units of spawn
    — the Sandbox wander is local; a PLDT type-4 "Object ID" location patched
    into the live package left the fighter standing (type 4/5 are dead in the
    engine); the mine's navmesh is one component (`tools/navmesh/reach.py`).
    Oblivion: 6 hunts → 46 seek links;
  * item base/type (WEAP/INGR/MISC/ALCH/BOOK/… incl. `SEBruscusDannusFind*`,
    `HeroLoot`, the goblins' totem staffs) → **Acquire** with the same
    criteria and `PTDT.Count` as num-to-acquire (vanilla
    `MQ101RalofGetDoorKey` type 1, `MS09Stage25JonAcquireNote` type 0);
  * furniture base/type → **Sit** with the criteria (vanilla
    `MG06Stage99MirabelleGetIntoFurniture` type 1, `DA14StartSamSit` type 2),
    also for UseItemAt "any furniture" (6);
  * a specific STAT/other ref (`SEBlackrootFindPrisonerNNTarget`, 101) →
    Travel near it; a specific FURN ref → SitTarget; a specific item ref →
    Acquire.
  * **The TES4 and TES5 object-TYPE enums differ** (Apparatus/Clothing/
    NPCs/Creatures/Soul Gems exist only in TES4, everything after Activators is
    shifted). `TES4_TO_TES5_OBJECT_TYPE` translates every PTDT type-2 target
    and PLDT type-5 location; before, the value was parsed as hex and
    load-order-shifted (TES4 "Furniture" 12 → written as 0x0100000C).
  * A PLDT type-4 (Object ID) location whose base has one placement is
    written as the type-0 reference (4,048 vanilla uses vs 0 for type 4).
* **Gap 2.** `_base_sig` now covers every placeable signature
  (`pack_indexes.PLACEABLE_BASE_SIGS`), so MS39's APPA mortar resolves;
  UseItemAt at a carriable item ref falls to the sandbox (Activate would pick
  it up), STAT stays Activate. `FURNITURE_SIGS = {FURN}`.
* **Gap 4, func 53.** `build_script_var_map` was blind to scripted
  WEAP/MISC/… bases (21 PACK + 13 INFO conditions, e.g. the goblin
  `CreatureGoblinLeaderFindHead*` totem gates). Beyond that, an unresolvable
  script variable is now emitted against `::TES4NoSuchVariable_var` — reads
  0, exactly TES4's value for a missing variable — instead of being dropped
  (fail-open). SE08's five Xedilian victims no longer force-greet/flee
  unconditionally. Func 171 `IsPlayerInJail` stays dropped: Skyrim has no
  equivalent function (`GetArrestedState` is the arrest, not the sentence).
* **AddScriptPackage** (not in the original audit): packages forced on by
  script and gated on a quest are attached to the actor's alias as ALPCs
  (`pack_aliases.build_script_assigned_packages`; 15 Oblivion / 4 Nehrim,
  incl. `MQ12MartinPlaceWelkyndStone`, `MQ14MartinPlaceSigilStone`,
  `MQ15MartinOpenPortal`, `MQ00CalebroPackage04`). Unconditioned forced
  packages (52 / 20) are NOT attached — with no gate they would run whenever
  the quest runs — and remain the known `AddScriptPackage → EvaluatePackage`
  gap.

### The audit was wrong about

* **Gap 3** — `PackagePlan.build` and the base-signature indexes already take
  `master_export` (checked in HEAD before this pass).
* **Gap 5** — Escort's arrival radius IS the destination location's radius,
  which `build_location` preserves (CGEmperorToMarkerB writes PLDT type 8
  radius 70 in the built ESM). Slots 3/4/5 are follower spacing, which TES4
  does not author.

### Still open (measured)

* UseItemAt with an object-type/token criteria — 232 `aaaObeisanceToken` /
  `aaaPreachToken` / Hoe / Rake / PaintBrush MISC tokens, 79 "read any book",
  55 "any melee weapon" drills, 142 "None" — keep the sandbox at the location.
  Oblivion drives these through IDLE records conditioned on the used item;
  Skyrim's equivalent is a placed IdleMarker/furniture + UseIdleMarker/
  UseWeapon-with-a-dummy, i.e. synthesised references, not a template choice.
* Find at a container/door/activator *type* (SE12 gnarl chests ×6, obelisk,
  cathedral doors) and at "any NPC" (ImpEx couriers ×35): sandbox in the
  authored cell. `ActivateAfterFinding` exists as a root but has 0 instances.
* Unconditioned script-forced packages (above).


## PACK conversion: verified-correct behaviour
<a id="pack-conversion-2"></a>

Binary layouts and behaviours confirmed against vanilla. Do not re-litigate.

## Verified correct — do NOT "fix" these
<a id="section"></a>

Recorded so a later session does not re-litigate them.

| Area | Verification |
|---|---|
| PKDT flag re-derivation | Matches xEdit `wbPackageFlags` (`wbDefinitionsCommon.pas:7635`) bit for bit. Both collisions handled: TES4 bit 3 `Lock Doors At Package Start` vs TES5 `Maintain Speed At Goal`; TES4 bit 20 `Armor Unequipped` vs TES5 `Ignore Combat`. |
| PKDT dual format | `export_PACK` emits `PKDT.Format`, matching `wbPACKPKDTDecider` (4-byte subrecord = U16 flags + U8 type; 8-byte = U32 + U8). Measured: **561** old-format Oblivion packages, **zero** with any flag bit above 16 — so no flag is misread. Nehrim is 100% new-format. |
| PSDT layout | 12 bytes `<bbBbb3xi>`, Duration hours→minutes, `minute=-1`. Confirmed against all **5,961** vanilla PSDTs. The nonzero bytes at `[5:8]` in some vanilla records are uninitialised garbage (`ababab`, ASCII fragments), not a field. |
| PSDT DayOfWeek | `wbPackageScheduleDayOfWeekEnum` is a **shared** enum — identical 0..10 values incl. `Weekdays (MTWTF)`, `Weekends (SS)`, `Monday, Wednesday, Friday`. Oblivion's 306 day-scheduled packages copy through correctly. |
| PSDT Date | Non-issue: 7,134/7,209 Oblivion and 1,900/1,900 Nehrim packages write 0, and all 5,961 vanilla records write 0. |
| PTDA slot 3 = 0 | Re-confirmed: all **3,740** vanilla PTDA records write 0 across every target type. |
| Speed byte | Vanilla honours `PKDT` speed only when flag `0x2000` (Preferred Speed) is set — **4,386** vanilla records carry an inert `speed=2` with the flag clear. Writing walk-unflagged is inert, not a defect. |
| PKDT byte layout | `<IBBBBHH>` confirmed: `[4]`=Type (18 ×5,857 / 19 ×104), `[5]`=interrupt override, `[6]`=speed, `[10:12]`=interrupt flags. |
| Reused CTDA indices | `_FUNC_DROP` correctly catches the index collisions, incl. **365 = `GetPlayerInSEWorld` (TES4) → `IsChild` (TES5)**, 249 `GetPCFame` → `IsInDialogueWithPlayer`, 224, 227, 258, 259, 264. |
| Structural contract | `tools/esm/pack_validate.py output/Oblivion.esm/Oblivion.esm` → **clean, 7,209 records**. Every defect below is *semantic*, which is exactly why the structural validator passes. |

---

## Shop doors: Unlock Doors At Location becomes Unlock At Start
<a id="shop-doors-unlock-at-location"></a>

Oblivion opens a shop through the owner's daytime package flag `0x100` Unlock
Doors At Location; the door itself is authored locked (Edgar's Discount Spells:
inside door `0002C243`, lock 50, owned by `EdgarVautrine`). His
`aaaServicesEditorLoc8x12LockAtEnd` is a Travel to his editor location with flags
`0x311`. TES5 bit 8 is Request Block Idles, so the bit was dropped, and the Travel
template has no UnlockDoors procedure: the door stayed locked all day, and a
player who got in anyway was a trespasser, so the owner asked them to leave
instead of trading. Confirmed fixed in-game.

The TES4 bit now maps to TES5 `0x40` Unlock Doors At Package Start, which is how
vanilla writes shop hours (`MarkarthGeneralStoreVendor8x16xPackage` `0xC1`,
`LucanValeriusTraderServices7x13` `0x251`; 35 of 5,961 vanilla packages set
`0x40`). Oblivion.esm has 165 packages with `0x100`.

Still dropped: TES4 Lock Doors At Package End (`0x10`, 92 packages) and At
Location (`0x20`, 141). TES5 has no named flag for either (the vanilla bits
`0x10`/`0x20` appear on 33/2 packages but are unnamed in xEdit and the CK).
Relocking comes from the Sleep template's LockDoors procedure, so a shop whose
owner sleeps elsewhere stays unlocked overnight.

---

## Escorts restart when the target returns
<a id="escort-restarts-when-the-target-returns"></a>

**Code:** `packages/escort_when_near.py`; created in
`base/owned_records.py::create_tes4_special_records`, adopted by dependent
plugins in `base/adopted_records.py`. Confirmed in-game (SE02).

Symptom: Jayred Ice-Veins (SE02 "Through the Fringe of Madness") led the player,
but once the player got far enough away he froze for good, even with the player
standing next to him. His "Follow me" line (`set LeadToGardens to 1` + `evp`) did
nothing; "Wait, let's do this later" then "Lead on" revived him.

Cause, from the 1.6.1170 exe and the live game:

- The escort package stayed current (`GetIsCurrentPackage` 1) while its
  procedure was dead (`GetCurrentAIProcedure` −1). `EvaluatePackage` re-picks
  the same package and does **not** restart it, so `evp` cannot revive it. The
  toggle works because the package genuinely changes (conditions go false,
  then true), which starts a fresh `BGSProcedureEscortExecState`.
- `BGSProcedureEscort`'s per-frame update (RVA `0x45E360`) keeps a waiting
  byte and path state that only a fresh start resets. The follower check
  (`0x6ED6D0`) waits once the follower is past the package's *Distance to Wait*
  (or `fAIEscortWaitDistanceInterior` 512 / exterior 2.0 × max(200, …) when the
  package has none) and resumes inside 2/3 of it (factor 0.444 = (2/3)² at
  `0x18A39C8`), with `fAIEscortHysteresisWidth` 50. Oblivion ships the same two
  wait defaults (2.0 and 512).
- `ResetAI` from the console also revives it; Papyrus has no equivalent.

Vanilla's answer is `EscortPlayerWhenNear` (`00069665`): a Stacked tree whose
Escort branch is gated on `GetWithinDistance(input 11, input 15) == 1` (CTDA
flag 0x08, both parameters package inputs), falling through to Travel. When the
player leaves the radius the Escort procedure ends; when they return it starts
fresh. Its Travel walks the escorter to the goal alone, which Oblivion never
did (Jayred would reach the gardens and fire FindBones without the player).

`TES4EscortWhenNear` is that root byte for byte except:

| | EscortPlayerWhenNear | TES4EscortWhenNear |
|---|---|---|
| fallback | Travel (inputs 3, 13, 17), FNAM 1 | **Wait** (inputs 20 ActualSeconds = 0, 21 StopMovement = 1), **FNAM 0** — vanilla `StayAtCurrentLocation`'s stay-put Wait |
| inputs / XNAM | 10 / 20 | 12 / 22 |
| defaults | wait 300, radius 500, preferred path 1 | wait 512, radius **1500**, preferred path 0 (the converter's existing Escort values) |

FNAM bit 0 is "success completes the package": the Escort keeps it (arriving
ends the package) and the Wait must not. The 1500 radius is MQ102
Hadvar/Ralof's (open-terrain player escorts; vanilla spans 300–5000). Every
converted escort uses it — TES4 Escort, a TES4 Follow rerouted to Escort, and
Morrowind `AIEscort` — and falls back to vanilla `Escort` only when no root is
installed (a master built before this change). Adding the root moved no
FormID (1,187,406 records before, the same plus one after). Test:
`tests/test_escort_when_near.py`.

## <a id="travel-to-furniture"></a>A Travel that ends at furniture sits in it

In Oblivion, Fallout 3 and New Vegas a Travel package whose location is a
specific furniture reference (`PLDT` type 0 on a `FURN` placement) uses that
furniture on arrival. Skyrim's `Travel` only walks there, so the converter
emits `SitTarget` on that reference instead (a quest alias when the package's
quest has one), the same template a Find or UseItemAt aimed at a specific
chair already gets.

Authored evidence: New Vegas's opening quest `VCG01` sends Doc Mitchell to his
chair with `VCG01DocMitchellTravelToExamSpot` (Travel, `PLDT` 0 on
`DocMitchellChairREF`, from stage 80), and nothing else seats him; the couch
and chair triggers (`VCG01DocMitchellCouchTriggerSCRIPT`,
`VCG01DocMitchellChairTriggerSCRIPT`) start the psych test only once
`DocMitchellREF.IsCurrentFurnitureRef DocMitchellChairREF`. Converted as a
Travel, Doc stood by the chair and the scene stalled. The same shape is
common: Travel packages ending at a furniture reference number 154 in
Oblivion (`SE04SheogorthSit`, the `SE*Worship` packages), 131 in Fallout 3
(`MS09MidnightMeetingStayBench*`) and 111 in New Vegas (`NVCCSleep*`).

`SitTarget`'s wait time is 0, as in all 276 vanilla instances: sit until the
package is conditioned out. It was 300, which stood a sitter up after five
minutes. Tests: `tests/test_packages.py`
(`test_travel_to_furniture_sits_in_it`,
`test_sit_target_waits_until_conditioned_out`).

### <a id="seated-chat"></a>A topicless chat held at a chair sits in it (built 2026-09-30, untested in game)

**Code:** `types_falloutnv.pick_dialogue`, `converter.travel_seat`.

FO3's Butch chats with Paul and Wally from his chair: `CG02ButchTalkToWally`
and `CG02ButchTalkToPaul` are Dialogue packages (Conversation, no topic) whose
location is `CG02ButchChairREF`, cycling with `CG02ButchSit` through the
`TSWally`/`TSPaul` variables their OnBegin scripts set. No line names Paul or
Wally as listener, so the source talk said nothing authored. Converted to
Skyrim's `Say` (a Travel to the location, then the topic, here HELLO), each
switch stood him up, walked him to the chair and had him say a generic Skyrim
Hello; the play-test recorder shows a stand and sit every 2 to 15 s through
the party. A topicless NPC-to-NPC Dialogue package whose location is a
furniture reference is now `SitTarget` on it, as a Travel ending at furniture
is ([above](#travel-to-furniture)); its conditions and OnBegin script still
drive the cycle.

### <a id="fallout-object-types"></a>FO3/FNV object types read in their own numbering (built 2026-09-30, untested in game)

**Code:** `types_falloutnv.tes4_object_type`, used by `object_criteria_kind`,
`build_location` (type 5) and `build_target` (type 2).

A package's object-type target or location is an enum that differs between
the games (xEdit `wbObjectTypeEnum`): FO3/FNV drop TES4's Apparatus (2) and
Soul Gems (17), reorder the weapon kinds, and add Actors: Any (29). The
converter read FO3/FNV values with TES4's table, so FO3 Furniture (11) was
TES4 Flora and FO3 Food (18) TES4 Keys. CG03's classroom packages ("find any
furniture within 350 of the class marker") became Sandbox with eating,
conversation and wandering on: in the 2026-09-30 play-test students ate at
their desks, and at the G.O.A.T. they stood up and wandered off, some stuck
pathing. Each FO3/FNV value is now translated to the TES4 value of the same
kind first, so those packages sit in a chair (Skyrim's Sit template with a
furniture criteria).

### <a id="greet-at-place"></a>A force greet waits at its package's place (built 2026-10-01, untested in game)

**Code:** `types_falloutnv._greet_at_place`, `trigger_location`;
`tes4_export/record_types/package_falloutnv.py` `_trigger_location_lines`.

A FO3/FNV Dialogue package to the player can carry two locations: `PLDT`,
where the actor waits, and `PLD2`, the area the player must enter before the
actor greets (GECK: Wait Location and Trigger Location). CG03's
`CG03MrBrotchDialoguePlayer` waits at `CG03MrBrotchMarker` and triggers
within 250 of it. Butch's force greet waits at his alias and triggers within
900 of a marker. With only the template's defaults Brotch went looking for
the player and was found outside Dad's office (2026-10-01 play-test).

The export now writes `PLD2.Type/Location/Radius` (384 FO3, 210 FNV
packages). The converted ForceGreet takes `PLDT` as its NPC wait location
(template slot 1) and `PLD2` as its target trigger location (slot 2).
Vanilla's C03Skjor and MG03Faralda fill the slots in that order. A first
build had them swapped, so the player had to stand on the wait marker and
neither Butch nor Brotch ever greeted. A package without `PLD2` sets no
trigger, and the actor walks to the player as FO3's does.

### <a id="say-to-reach"></a>A SayTo the player waits for its trigger location (built 2026-10-01, untested in game)

**Code:** `types_falloutnv.say_to_reach`, added by `converter._guards`.

A FO3/FNV SayTo aimed at the player speaks once the player enters its
trigger location (`PLD2`), then walks within `PTDT.Count` to say it.
Skyrim's `Say` has no trigger and speaks as soon as it runs. CG04's
`CG04Security02Ambush` (Officer Kendall) said "There she is! Hold it right
there!" two seconds into the escape, through the walls. That line sets CG04
12, which enabled the radroaches outside the door and ended Amata's wake-up
package early.

The package now carries the trigger as a condition:

- `PLD2` type 0 (a reference): `GetDistance(<reference>) <= radius`, run on
  the player. Kendall's is `0002D4C4` within 500.
- `PLD2` types 2 and 3: `GetDistance(player) <= radius`, run on the actor.
- otherwise, no condition.

The Say location is the player, within `PTDT.Count`, so the actor walks
over before speaking. A first build gated on 1000 units plus line of sight.
The line of sight test failed at Kendall's post, so his package was skipped
and he fell through to the next one.

### <a id="detected-target"></a>An empty GetDetected target is the player (built 2026-10-01, untested in game)

**Code:** `types_falloutnv.detected_target`, used by `converter._source_conditions`.

FO3/FNV packages ask `GetDetected` (function 45) with an empty reference to
mean "has detected the player". Gomez's force greet in Vault 101 is one.
Converted as written, the condition asked about no reference and never
passed, so he never greeted. An empty `GetDetected` parameter now becomes
the player (`00000014`), in 5 FO3 and 3 FNV packages.

### <a id="run-on-target"></a>A Run On Target condition runs on the package's target (built 2026-10-01, untested in game)

**Code:** `packages/converter.py` `_condition_target`, `_source_conditions`.

FO3/FNV packages ask Run On Target conditions of their own target: Lucas
Simms' `MS11LucasForceGreet` asks `GetInWorldspace` of the player it greets,
Gomez's force greet asks `IsInCombat` of the player. Skyrim.esm has none: of
its 4,699 package CTDAs, 4,273 run on the subject, 238 on a reference and
none on Target, so a Target condition on a package found nothing and failed,
and the force greet never ran (Lucas walked up, said his hello and went on to
patrol; 2026-10-01 play-test). A package whose target is one reference (PTDT
type 0, or the player as Object ID + the player's base) now runs those
conditions on that reference (Run On Reference), as `convert_ctda` already
does for a say topic's listener; identity tests (`GetIsID`) on it drop. A
package with no single target keeps them as before. 56 FO3 and 13 FNV
packages carry one.

## <a id="fallout-package-types"></a>FO3/FNV package types 12-16

**Code:** `tes5_import/packages/types_falloutnv.py`, `record_types/world.py`
`linked_ref_subrecord`, `tes4_export/record_types/package_falloutnv.py`.

FO3/FNV numbers its package types as Oblivion does up to 10, then adds
Sandbox 12, Patrol 13, Guard 14, Dialogue 15 and Use Weapon 16. `_choose`
knew only Oblivion's, so every other type sandboxed at its location: in
FalloutNV.esm, Sandbox 753 (right), Patrol 505, Dialogue 332, Guard 175 and
Use Weapon 82. Each now picks the vanilla template doing the same thing,
with inputs taken from real Skyrim.esm instances:

| FO3/FNV | Skyrim template | Inputs |
|---|---|---|
| Patrol | `Patrol` (00017723) | start: the PLDT's near-reference marker, else the actor's linked ref (PTDA type 3) with Start At Nearest; `PKPT` Repeatable; PLDT radius |
| Guard | `GuardPost` (0001C9FF) | wait at the package location; restricted area the same location, radius 500 when unset |
| Dialogue, to the player | `ForceGreet` | the `PKDD` topic; GREETING/HELLO leave the 0 placeholder so `patch_forcegreet_topics` opens the quest's own greeting; `PTDT.Count` as the forcegreet distance |
| Dialogue, SayTo or to an NPC | `Say` (0001CCB6) | the `PKDD` topic (HELLO when none), the target, the location when authored |
| Use Weapon | `UseWeapon` (0001C338) | the second target (`PTD2`) to shoot and trigger on, the weapon (`PTDT` Object ID), `PKW3` Always Hit / Do No Damage / Crouch / Hold Fire, bursts (Number of Bursts ends the package after N), volley pauses and shots |

A Dialogue package's topic counts as script-driven (`dialogue_source` reads it
as `SayTo <target> <topic>`), so the NPC-to-NPC drop keeps it and its
target conditions retarget onto that target. A player conversation is also a
force greet for `convert_PACK`'s speed and interrupt rules (`_is_force_greet`,
which also covers Oblivion's idiom: an Ambush or Find aimed at the player is
a scripted approach, not a hostile ambush).

Two shared pieces had to widen for these. PLDT location types 6 (near linked
reference) and 7 (at package location) are the same numbers in Skyrim, and
`build_location` used to null them. And a patrol walks the markers' linked
refs, which were never written: `linked_ref_subrecord` now writes the authored
`XLKR` on REFR and ACHR (the export gained it for ACHR/ACRE: 1,164 and 242),
winning over Oblivion's enable-parent mirror.

Not yet carried: a patrol marker's idle time (`XPRD`), idle and embedded
script, `PTDT` Object Type values (FO3/FNV's object-type enum is not TES4's),
and a Dialogue package's `PKDD` flags.

## <a id="patrol-points"></a>FO3/FNV patrol points

**Code:** `tes5_import/packages/patrol_falloutnv.py`,
`script_convert/patrol_scripts.py`, `record_types/world.py` (`convert_REFR`).

A FO3/FNV patrol point is a REFR on a Patrol package's linked chain, carrying
an idle time, an idle, an embedded script and a topic
([export](tes4_export_falloutnv.md#patrol-points)): FalloutNV.esm has 1,347,
106 with a script, 14 with a topic, none with an idle. The actor that reaches
one waits, runs the script on itself (`moveto`, `Say`, `AddItem`, quest
variables) and says the topic. The REPCON HQ tour, Pete's murals and General
Oliver's emergency are built this way.

Skyrim's REFR keeps most of it natively. 3,179 vanilla patrol markers (the
same `XMarkerHeading` base) carry `XPRD` idle time, the empty `XPPA` Patrol
Script Marker, `INAM` idle (0 on all of them) and a `PDTO` topic (one vanilla
marker sets it). A patrol point is written that way: its idle time, `XPPA`,
idle 0 (a FO3/FNV IDLE names no Skyrim animation) and the topic as a Topic
Ref `PDTO`. Patrol topics and scripts feed the say-topic scans, so a topic
only a marker says is kept.

The script has no Skyrim home: Skyrim's REFR keeps only unused leftovers of
the embedded script, and no Papyrus event reports a patroller's arrival. A
marker with a script therefore gets `<NS>_PM__<FormID> extends
ObjectReference`. While its cell is attached it polls every 0.5 s. The
closest actor within 128 units, not the player, whose current package is one
of `TES4PatrolPackages`, runs the converted body once (`akSpeakerRef` is that
actor, as in a package fragment). It can arrive again after moving 256 units
away. `TES4PatrolPackages` (a Form-array VMAD property) is every package that
brings an actor to the marker. A Patrol walks the XLKR chain from the marker
its PLDT names, else from each of its actors' own linked reference; any other
package arrives at the marker its PLDT names. FO3/FNV runs the script for
those too: VMS21's Joana escaping, the Legion snipers and the Strip
securitrons are Travel packages to scripted markers, and two Legion tent
guards are Guard packages. A marker nothing is known to reach gets no VMAD,
so it never runs for a passer-by.

## Every placed copy gets its quest package
<a id="every-placed-copy-gets-its-quest-package"></a>

Oblivion runs a base actor's AI packages on every copy placed from it. A
quest-gated package reaches a Skyrim actor only through a quest alias, and an
alias fills one reference, so `PackagePlan._build_base_to_refs`
(`packages/aliases.py`) maps each base to **all** its placements and each one
gets its own alias carrying the package. It used to keep only the first
placement, so the other copies never ran the package.

Nehrim's mine-exit trolls are the visible case: `MQ00TrollTravel`, the march
into the fire at MQ00 stage 35, is authored on the shared base
`MQ00troll01Ausgang` placed twelve times, and only `MQ00TrollA01` got it
(MQ00 went from 13 to 24 aliases). The same fix reached 15 Nehrim quests (the
largest, the tower-defense wave quest NQ15W02, gained 177 aliases) and 20
Oblivion quests (DASheogorath's sheep, SE08Xed's knights, Charactergen's
ambush assassins). Confirmed in game on the Nehrim exit and Charactergen.

A script's `AddScriptPackage` on a BASE still goes to its first placement.
Quests that gained aliases renumber existing ones, so a save made midway
through one may hold a stale alias fill. Test:
`tests/test_packages.py::test_every_placed_copy_gets_its_quest_package`.

## Quest-only actors hold in place
<a id="quest-only-actors-hold-in-place"></a>

**Code:** `default_package_list` in `packages/actor_wiring.py`

When none of an actor's packages is valid, Oblivion leaves it standing where it
is (UESP: Kiara "never moves because she has no AI packages"; the Blackwood
Company guards "stand in place when not engaged in combat"). Skyrim instead runs
the NPC's Default Package List (`DPLT`), and every converted NPC carried
vanilla's `DefaultMasterPackageList`, which sandboxes. A sandboxing actor is
placed at a sandbox spot when its cell loads, so an actor authored to stand on
one spot turned up somewhere else each time.

Nehrim's nightmare shows it. `Celebro02`'s only packages are MQ00's
(`MQ00Cel02ZumTroll` and the `AddScriptPackage`d `MQ00CalebroPackage04`, both
`GetStage MQ00 == 20`), so before stage 20 he had nothing valid. In game he
loaded 257 units to the left of his placement, once in the entrance doorway,
instead of in front of the player where the scene expects him.

An NPC whose every authored package is quest-owned (it reaches the actor through
a quest alias, so the author gave it AI only for quest moments) now carries
vanilla's `DefaultHoldPositionCurrentLoc64List` (Skyrim.esm `000A6853`, holding
`DefaultHoldPositionCurrentLoc64`: HoldPosition, "near package start location",
radius 64) instead. It holds wherever the actor is when the fallback takes
over, so it neither pulls back an actor a script `MoveTo`'d nor lets one wander.
Other NPCs keep `DefaultMasterPackageList`. Creatures are unchanged, since their
PKID always ends in vanilla's always-valid `DefaultMasterPackageCreature`.

## Run-once quest packages end when they complete (built 2026-09-30, untested in game)
<a id="run-once-quest-packages"></a>

**Code:** `packages/run_once.py`, `packages/run_once_plan.py`,
`static_scripts/TES4_StagePackageAlias.psc` (`OnPackageEnd`)

Once Per Day made a source actor leave an unscheduled package as soon as it
completed, so the next valid package on its list ran. FO3's CG02 depends on it:
at stage 35 Dad's `CG02DadToIntercom` (Travel to `CG02OverseerSpeechMarker`,
radius 50) comes before `CG02DadTalkToJonasOnIntercom` (Dialogue to the
intercom), both `GetStage CG02 >= 35`. `convert_flags` drops Once Per Day from
quest packages, since Skyrim's daily latch can already be spent on a
persistent actor (CharacterGen's Renault). So Dad reached the marker by the
booths and held there, and the intercom talk never ran. Skyrim has no
condition for "this package completed".

Each unscheduled (`PSDT.Time == -1`) quest-owned package with source Once Per
Day, other than a force greet or a package whose OnChange stage already ends it
([run-once fold](script_convert.md#run-once-package-change)), gets a hidden
faction `TES4RunOnce_<package>` and the condition `GetInFaction(<it>) == 0`.
The package's alias script lists its packages and factions
(`RunOncePackages` / `RunOnceFactions`); on `OnPackageEnd` (the CK wiki: "when
the actor finishes a package") it adds the actor to that package's faction
and re-checks, so the next package takes over. Scheduled packages (Bruma's
daily worship) keep the old behavior.

A FO3/FNV Patrol whose `PKPT` is not Repeatable walks its route once and gives
way; Skyrim's Patrol template reads `repeatable = false` but re-runs a package
that is still valid after it completes, so FO3's `CG04PatrolHannon`
(`CG04Security01StartPatrol`, stages CG04 33 to 200) walked his route over and
over instead of stopping at the vault door. Such a patrol is marked run-once
the same way.

## <a id="locked-door-gates"></a>FO3/FNV packages wait behind a locked door (2026-09-30, untested in game)

**Code:** `tes5_import/packages/door_gates_falloutnv.py` (`plan_door_gates`,
`door_gate`), planned before PACK converts.

Fallout's AI stops at a locked door it holds no key for, and quests use that to
hold actors back. CG04 stage 145 unlocks `Vault101ExitDoor` "so guards can come
in". Skyrim's AI walks up to such a door, sticks, and its failsafe warp moves it
past. The engine registers a movement handler named "FailSafe Warp" (string at
SkyrimSE 1.6.1170 `0x18b4120`). In the 2026-09-30 play-test, guards 07 and 08
started `CG04GuardsToEntrance` at stage 140 and completed it 17–18 s later, on
the far side of the locked door, without activating any door.

So a package waits on `GetLocked == 0` (function 5, run on the door
reference) for each door it would have to cross when all of the following
hold:
- its destination is a placed reference (PLDT type 0);
- every actor holding it (an ACHR whose base lists it) is placed in the
  destination's cell;
- every navmesh route from each such actor to the destination crosses a
  locked door that actor can't open (no key in its inventory, and it doesn't
  own the door, itself or by faction).

While the door is locked, the actor runs its next package; once a script
unlocks the door, it goes.

**Finding a door's triangles.** A load door has an NVDP door link, and
Door-flagged triangles (`0x400`) exist only for linked doors. An in-cell door
like `Vault101ExitDoor` has neither: the navmesh runs straight under it (its
cell's only Door-flagged triangles are the 3 linked doors'). So a door also
covers every triangle whose centroid lies inside its footprint. The footprint
is the base's OBND, turned by the reference's Z rotation and widened by
32 units, and taken symmetrically so the rotation's sign doesn't matter. For
the exit door that's triangles 58 and 102. Shutting them leaves the guards no
route, and opening them gives a 20-triangle route.

The routes are breadth-first over the cell's NAVMs, joined by their edge links.
An actor's start is its placed position; the triangle used is the one whose
centroid is nearest the point.

Gated packages, FO3 (16):
- CG04's three guard packages (`CG04GuardsToEntrance`, `CG04PatrolEntrance`,
  `CG04GuardEntrance`) and Tom Holden's death run;
- CG02's five target-range packages for Dad and Jonas. The door is unlocked by
  a CG02 stage (`CG02TargetRangeDoorNEW.unlock`), as Fallout ordered it;
- MQ08's guards and Sid;
- MS09's Robert;
- Moriarty's sleep package.

Not judged:
- packages whose holders start in another cell;
- alias and template holders;
- destinations that are not a placed reference.
