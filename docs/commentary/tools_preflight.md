# tools/validate/preflight — audits that run before a play-test

**Code:** `tools/validate/preflight/__main__.py`, `tools/validate/preflight/findings.py`, `tools/validate/preflight/plugin_index.py`, `tools/validate/preflight/quest_source.py`, `tools/validate/preflight/quest_converted.py`, `tools/validate/preflight/quest_progression.py`, `tools/validate/preflight/quest_start.py`, `tools/validate/preflight/dialogue_loss.py`, `tools/validate/preflight/script_health.py`, `tools/validate/preflight/package_ai.py`, `tools/validate/preflight/world_links.py`, `tools/validate/preflight/log_triage.py`, `tools/validate/preflight/asset_load.py`, `tools/validate/preflight/build_diff.py`, `tools/validate/vmad_property_typecheck.py`, `tools/validate/property_type_audit.py`, `tools/validate/dangling_ref_check.py`
**History:** [fork/done/preflight_audits.md](../fork/done/preflight_audits.md)

## Contents

- [Overview](#overview)
- [Running it](#running-it)
- [Findings and the review ledger](#findings-and-the-review-ledger)
- [The plugin index](#the-plugin-index)
- [Quest progression](#quest-progression)
- [Source setters](#source-setters)
- [Converted setters](#converted-setters)
- [Quest start and alias fill](#quest-start)
- [Dialogue loss](#dialogue-loss)
- [Script health](#script-health)
- [Property binding](#property-binding)
- [Packages and AI](#packages)
- [World links](#world-links)
- [Log triage](#log-triage)
- [Asset load](#asset-load)
- [Build diff](#build-diff)
- [Validation against earlier builds](#validation)
- [What the audits do not see](#blind-spots)

## Overview
<a id="overview"></a>
Eight static audits over a built game. They find the kinds of failure that
used to cost a play-test session each:

- **quest**: a stage that the source game can reach and the converted game can't;
- **start**: a quest the source game starts that the build never starts, and a
  quest alias that can never fill;
- **dialogue**: lines the source game can say and the build can't, ranked by
  the NPC who loses them, and quests with two topics of one bark subtype;
- **scripts**: scripts that don't compile, quest commands the converter left
  inert, properties that read None, and FormIDs that name no record;
- **packages**: AI packages that point at nothing, never run, or send an
  actor into a cell with no navmesh;
- **world**: doors that lead nowhere or have no door back, interiors with no
  way out, and quest targets or map markers that point at nothing;
- **assets**: a model or texture that would show as a red error marker or
  purple, or a mesh block the exe can't build;
- **build**: FormID drift since the last accepted build.

A ninth, **logs**, runs only when asked, after a play-test. It sorts the
session's Papyrus errors by cause and names where each touched quest stopped
([log triage](#log-triage)).

None of them needs the game running. Each game takes about 10 s for the quest,
start and dialogue audits together, 20 s for the scripts audit, a few seconds
each for packages and world, and 40 s for the asset audit (about 6,000 models
each in Fallout 3 and New Vegas).

## Running it
<a id="running-it"></a>
```
python -m tools.validate.preflight                         # every built game
python -m tools.validate.preflight --game Fallout3.esm --audit quest --audit start
                                                           # audits: quest start dialogue scripts
                                                           #         packages world assets build
python -m tools.validate.preflight --game Fallout3.esm --audit logs   # after a play-test
python -m tools.validate.preflight --full                  # print every finding
```

Games are the folders in `output/` that hold their plugin and have a matching
`export/` folder. The report prints the first 25 findings of each section.
The full report goes to `output/preflight/<game>/report.txt`. The exit code is
1 while any error is left that the ledger does not hide. The command runs under
both `python` (3.13) and `py -3.14`.

## Findings and the review ledger
<a id="findings-and-the-review-ledger"></a>
A finding has one of two severities:
- `error`: the audit is sure the build is broken.
- `review`: the audit could not tell, so a person decides.

Each finding has a stable key, such as `quest|Fallout3.esm|MS16|10` or
`assets|Fallout3.esm|missing|meshes\...`.

Decisions go in `tools/validate/preflight/review_ledger.json`. That file is
committed so every machine shares it.

```
python -m tools.validate.preflight --mark "quest|Fallout3.esm|MS16|10" --as ok --note "radio, planned"
python -m tools.validate.preflight --mark "assets|*|outside|*" --as skip
python -m tools.validate.preflight --unmark "assets|*|outside|*"
```

| Status | Meaning | Effect |
|---|---|---|
| `ok` | reviewed, works as intended | hidden |
| `skip` | don't check this | hidden |
| `bug` | confirmed broken | listed as an error with the note, whatever the audit said |

A key may be an `fnmatch` pattern. An exact key beats a pattern, and a longer
pattern beats a shorter one.

Each run saves its keys in `output/preflight/<game>/<audit>_last.json`. The
next report tags anything missing from that list as `[new]`, so a regression
shows up the day it lands.

## The plugin index
<a id="the-plugin-index"></a>
`plugin_index.load_plugin` reads the built plugin once, which takes about 4 s
for Fallout 3's 311 MB file. It indexes records by type and by FormID, and
keeps the plugin's master list so it can tell its own FormIDs from a master's.
It reads each VMAD's script list with every property, of every value type. From
that it records:
- which records every script is attached to;
- which property names each script has bound, whatever their type;
- which FormID each object property names.

A script attached with no properties at all still counts as attached. VMAD
fragment data after the script list isn't read.

`home_cell` gives the cell a placed reference really stands in. A worldspace's
persistent cell (record flag 0x400) holds its persistent references whatever
their position, and it carries XCLC (0,0) like an ordinary cell. So a reference
in it is mapped to the grid cell under its position, 4,096 units per side.
Without this, every persistent package destination looked like it had no
navmesh (595 in Fallout 3 before, 105 after).

## Quest progression
<a id="quest-progression"></a>
Every `SetStage` in the source becomes a site. Each site has a kind (a quest
stage result, a dialogue line, a package section or a script), an owner, the
quest and the stage.

A site is **live in the source** when its container runs there:
- a dialogue line needs a reachable topic and a placed actor who passes its
  GetIsID conditions;
- a script needs a record that uses it;
- a stage result needs its own stage reached;
- packages always count as live.

A site is **live in the build** when it is live in the source and also:
- the generated script that should hold it has a SetStage for the same quest
  and stage;
- that script compiled to a `.pex`;
- the script is attached to a record;
- the container runs in Skyrim terms (see [converted setters](#converted-setters)).

A fixed point over each side gives the stages it reaches. The build side is
computed twice: optimistically (review sites count) and strictly (only
confirmed sites count). Then:
- a stage the source reaches and the optimistic build doesn't is an **error**;
- a stage only the optimistic pass reaches is marked for **review**, listing
  the unconfirmed setters.

A quest that also has a SetStage with a computed stage number reports its
lost stages as review, not error, because that setter may reach them.

The model deliberately doesn't evaluate the `if` guards around a SetStage, and
assumes every quest is running. Both sides use the same assumptions, so what
remains is only what the conversion lost.

## Source setters
<a id="source-setters"></a>
`quest_source.SourceGame` reads the export's QUST, PACK, SCPT, DIAL, INFO,
ACHR and ACRE files:
- **Setters:** SetStage and StartQuest calls are found with comments stripped.
  A stage that isn't a literal is kept as None, and a StartQuest reaches the
  pseudo-stage `start`. A script setter also records the `Begin` block it sits
  in, so the report can name a block such as `OnFire` that the build drops.
- **Start Game Enabled:** QUST DATA.Flags 0x01.
- **Used scripts:** a script counts as used when its FormID appears as a value
  in any base-record export file. Placement, geometry, dialogue and SCPT files
  are skipped. This keeps unused scripts, such as FO3's `FFEDoctorSCRIPT`, from
  counting as losses.

A topic is reachable in the source when any of these holds:
- it isn't a plain Topic (DATA.Type ≠ 0);
- it is top-level (DATA.Flags 0x02);
- it is `GREETING`;
- it is named by an INFO's AddTopic, a package's PKDD.Topic, or a script's
  `AddTopic`, `Say`, `SayTo`, `StartConversation` or `ForceGreet`;
- a speakable line in a reachable topic offers it as a choice or links into it.

A line is **speakable** when a placed actor passes its GetIsID conditions
(`required_speakers`). The conditions are split into OR chains. Only a chain
made entirely of `GetIsID X == 1` on the subject binds the speaker, and several
such chains must all pass, so their bases intersect. A GetIsID OR'd with a
faction or voice test binds nothing, because anyone passing the other test may
speak.

Oblivion also teaches topics when they are heard in a response. The audit
doesn't model that, which only makes Oblivion's source side smaller, so it can
hide an Oblivion loss but never invent one.

## Converted setters
<a id="converted-setters"></a>
`quest_converted.load_scripts` reads every generated `.psc`. It records three
forms of SetStage, `X.TES4SetStage(Q as T, n)`, `Q.SetStage(n)` and a bare
`SetStage(n)`, and two forms of StartQuest: `Q.Start()` for a quest with no
script, and `X.TES4Start(Q as X)` for one with a script. Each call keeps the
function it sits in. It also records the calls that survive only in comments:
- a `;NE:` line;
- a line under a `; --- TES4 \`begin MenuMode 1\`` header, the converter's
  marker for a source block it keeps but never runs.

The report names the dead block.

A call's quest expression is resolved in this order:
1. the script's own quest, for `Self` or `GetOwningQuest()`;
2. the VMAD property's FormID;
3. a quest with the same EditorID.

An expression that none of these resolves makes the site a review.

The scope a source site's SetStage must sit in depends on its kind:
- a quest stage site needs a `Fragment_Stage_NNNN_*` function of its stage;
- a package site needs the fragment of its section, using the index order of
  `tes5_import.packages.scripts_falloutnv.package_sections`. A folded OnChange
  may sit in OnEnd
  ([run-once packages](script_convert.md#run-once-package-change)). One that
  survives only in the OnChange fragment is marked for review, because Skyrim
  runs OnChange only when the actor leaves the package.

A SetStage for the right quest and stage found in some other script also makes
the site a review ("setter moved").

Skyrim's dialogue model (`ConvertedDialogue`) treats these topics as
reachable:
- every topic whose SNAM isn't `CUST`;
- the start topic of a top-level or Blocking DLBR;
- a custom topic named by a scene, a package or a script property;
- a topic offered by a TCLT from a speakable line in a reachable topic that
  isn't a Hello topic.

That last rule is the one CG02 needed: a Hello line closes the conversation
before its replies show
([Blocking greeting](tes5_import_dialogue.md#greeting-choices-block)).

## Quest start and alias fill
<a id="quest-start"></a>
`quest_start.start_findings` reuses the quest progression graph. A quest counts
as **started** on a side when any of these holds there:
- it is Start Game Enabled (source QUST DATA.Flags 0x01, built DNAM 0x0001);
- one of its StartQuest sites is reached;
- one of its stages is reached, because a SetStage starts a stopped quest in
  both engines.

The Skyrim half of that last rule rests on the CK wiki's description of
`Quest.SetStage`; no offline copy of the wiki was at hand to cite.

A quest the source starts and even the optimistic build never starts is an
error. One that only the optimistic build starts is a review. Both list the
StartQuest sites and their verdicts, with the source `Begin` block for script
sites.

`quest_start.alias_findings` reads every QUST's reference aliases (ALST to
ALED) in the built plugin. A forced-reference alias (ALFR) can't fill when its
target is:
- missing from the plugin;
- not a placed reference;
- deleted;
- initially disabled while the alias lacks Allow Disabled (FNAM 0x80).

A unique-actor alias (ALUA) can't fill when no ACHR places its base. Targets in
a master's id space aren't judged.

| Alias | Finding |
|---|---|
| Required (FNAM lacks Optional, 0x02) and can't fill | error: the quest can't start |
| Optional, can't fill, has packages (ALPC) | error: the packages never run |
| Optional, can't fill, no packages | review |
| Required, filled by conditions, creation or another alias | review: the audit can't evaluate the fill |

The converter writes every alias as Optional + Allow Disabled + Allow Dead +
Allow Reserved (FNAM 0x292). On 2026-09-28, all 1,288 Fallout 3 forced-ref
aliases filled; 48 of those point at the player in Skyrim.esm. So today this
check is a guard against regressions and against other plugins' aliases.

## Dialogue loss
<a id="dialogue-loss"></a>
`dialogue_loss.audit` reuses the quest audit's two dialogue models instead of
`dialog_emulator.py` and `oblivion_dialog_emulator.py`. Those emulators answer
what an NPC offers in one game state, at game start by default, and the
Oblivion one numbers condition functions as Oblivion does. Paired on a
Fallout build, they would measure state and numbering differences rather than
what the conversion lost.

A line counts when the source can say it: its topic is reachable and a placed
actor can speak it (see [source setters](#source-setters)). It is lost when:
- the built INFO is missing;
- its built topic is unreachable in Skyrim;
- no placed actor passes its built GetIsID conditions.

Each reason names the source topic's type (Conversation, Radio, Topic and so
on). A lost line reached in the source only through LinkFrom (TCLF) says so;
the importer never reads LinkFrom.

Losses are grouped by speaker, one error each, most lines first:
- a line bound to named NPCs counts against each of them;
- a line anyone may say counts against its quest ("lines anyone may say in
  ConvMegaton").

**One bark topic per quest.** Skyrim honors only one topic of each bark
subtype per owning quest
([bark rule](tes5_import_dialogue.md#qust-records-journal)). The audit
reports every (quest, subtype) that owns two or more topics, for any subtype
other than CUST and SCEN. A census of vanilla Skyrim.esm found no quest owning
two topics of the same subtype, across all 70 such subtypes, which supports
applying the rule beyond Hello.

## Script health
<a id="script-health"></a>
`script_health.audit` groups its findings by cause, so each one is a converter
work item rather than a per-script list:
- **Compile:** each `.psc` with no `.pex`. Causes are read from the
  compiler's `scripts/compile_errors.log`, with names replaced by `#`, and a
  source missing from the log gets its own cause.
- **Inert quest commands (review):** a `;NE:` marker on a command that can
  leave a quest unfinishable (`FLOW_COMMANDS`: KillActor, SetPlayerTeammate,
  CompleteAllObjectives, PlaceLeveledActorAtMe, AddTopic, MoveTo and others),
  one finding per command naming the quests affected. SetStage and StartQuest
  are left to the quest audits. Other `;NE:` commands aren't reported.
- **Script attachment:** a script whose `extends` chain ends in an engine type
  that can only sit on one kind of record (`ATTACHABLE`) is attached to
  another kind. The engine logs "base types do not match" and runs nothing.
  Actor scripts need an ACHR or NPC_; Quest, TopicInfo, Package, Scene and
  ActiveMagicEffect scripts need their own record type. ObjectReference
  scripts may sit on any placeable base and aren't judged. A census of the
  Fallout 3 build found one mismatch: `FFER05LootBoxSCRIPT` extends Actor but
  sits on three CONT records and an ACTI.
- **Property binding:** see [property binding](#property-binding).
- **Dangling FormIDs:** `dangling_ref_check.dangling_refs`, one finding per
  record type, subrecord and the file expected to hold the target.

## Property binding
<a id="property-binding"></a>
A Papyrus property that can't bind reads None for the whole session, and the
first call on it aborts the enclosing function. The CharacterGen Emperor broke
this way when `Player` stopped being bound in 18 QF_ scripts, and the Imperial
City Arena announcer when its XMarkers were typed `Actor`.

`vmad_property_typecheck` and `property_type_audit` return data for the
preflight and still print as command-line tools. `vmad_property_typecheck`
reads VMADs through the plugin index. Its old byte scanner stopped at the
first property type it couldn't size, and skipped scripts attached with no
properties. On Fallout 3 the rewrite resolves 20,257 object properties
(20,190 before), and finds the same 196 name-pass and 140 FormID-pass
failures. It also newly finds scripts such as `DefaultActLinkWhenActSCRIPT` on
a DOOR whose VMAD binds none of its properties.

The preflight uses three checks:
- **FormID pass (`cross_master_problems`):** each bound object property's real
  FormID, resolved through the MAST list, must hold a record the declared type
  accepts. `Actor` accepts only an ACHR; a plain REFR is never an Actor in
  Skyrim. For targets in this plugin, a type-correct record must also pass
  three more rules. The Papyrus log proved each one, and all three are now
  checked before play:
  - A **script-typed** property (`FALLOUT3_MQ09EdenScript Property
    MQ09EdenRef`) binds only to a record carrying that script, on the
    reference or its base (`lacks_script`).
  - A property whose type is, or is a script extending, **Actor or
    ObjectReference** needs a placed reference, not a base record
    (`reference_problem`). An example is `CG04RadroachSpawn`, which names the
    NPC_ base.
  - That reference must be **persistent** (record flag 0x400). The engine
    can't bind a property to a temporary reference, and logs `<nullptr form>`,
    as for the `FFHamRadio` activators. The Creation Kit makes every
    property-referenced reference persistent. On 2026-09-28, 216 Fallout 3
    script-typed properties named a non-persistent reference, and none in New
    Vegas or Oblivion.

  Findings are grouped by (declared type, cause), where the cause is the record
  type found or which of these rules failed.
- **Unbound (`unbound_properties`):** a property declared `Auto` on an
  attached script and bound by no VMAD. It is reported only when its name
  matches a record in the plugin or an engine value (`Player`, `GameHour`),
  and the script uses it outside comments; other names are dead in the source
  game too. On Fallout 3, 836 declared properties are unbound; the naming
  rule leaves 406 property names, and the comment rule cuts those to 22, all
  `Cell` properties. Most were mentioned only inside `;NE:` lines. Groups use
  (declared type, named record type), and every converted-script type is one
  bucket.
- **Actor on a non-actor (`unbindable_actor_properties`):** an `Actor`
  property named after a placed reference whose base isn't an NPC_, CREA or
  LVLC.

The name pass (`type_mismatches`) stays in the command-line tool only, since
the FormID pass judges the same properties from their real binding.

## Packages and AI
<a id="packages"></a>
`package_ai.audit` reads the built PACK records and who holds them. A holder
is an NPC_ through PKID, or the forced reference of a quest alias through
ALPC. An NPC_ whose ACBS template flags (u16 at offset 18) carry 0x20 runs its
template's PKID list instead of its own. An alias with no forced reference in
the plugin holds its packages for an actor known only at runtime.

| Check | Finding |
|---|---|
| PLDT (near reference, in cell, object) or PTDA (specific reference, object) names a missing record, or one of the wrong kind | error |
| PLDT type 8 or PTDA type 4 names an alias the package's QNAM quest lacks | error |
| PSDT month, day of week, date, hour or minute outside -1..11, -1..10, 0..31, -1..23, -1..59 | error |
| An NPC_ or alias holds a package missing from the plugin | error |
| The package's GetIsID chains exclude every actor that holds it | review: the source package may be just as dead |
| A destination (near-reference PLDT, specific-reference PTDA, or in-cell PLDT) is in a cell with no NAVM | review, one per cell |

Day-of-week values 7 to 10 are day groups (weekdays, weekends, Mon/Wed/Fri,
Tue/Thu), not errors. The GetIsID check is a review because of New Vegas's
`VMS18WaiterCFPatrol`. It requires `VMS18WhiteGloveCF`, which holds no
packages in the source either, since its template flags (0x19E) don't take
AI packages. So that patrol is dead in both games.

## World links
<a id="world-links"></a>
`world_links.audit` checks four things:
- **Teleport doors:** a door (REFR XTEL) whose destination is missing, or has
  no door back, is an error. One whose destination leads back to a different
  door is a review.
- **Trapped interiors:** an interior that a door leads into, with no teleport
  door out, is a review, since a script may move the player out.
- **Quest targets:** an objective target (QSTA) naming an alias its quest
  lacks is an error.
- **Map markers:** those with no name (REFR XMRK with no FULL) are grouped
  into one review.

Measured on 2026-09-28:

| Game | Door pairs | Interiors entered | Trapped | Objective targets |
|---|---|---|---|---|
| Fallout 3 | 1,118 teleport doors, all reciprocal | 365 | 0 | 355, all naming real aliases |
| New Vegas | 1,108 teleport doors, 2 returning through a different door | 331 | 0 | 1,469, all naming real aliases |

So today these checks guard against regressions.

## Log triage
<a id="log-triage"></a>
`--audit logs` runs after a play-test, and never by default, since it reads
the last session rather than the build. It needs no game running:

```
python -m tools.validate.preflight --game Fallout3.esm --audit logs
```

**Papyrus errors.** The session's text is `Papyrus.0.log` plus every `papyrus`
event in the flight recorder's newest run that the log lacks. The log often
stops flushing mid-session; the recorder keeps going. Only lines naming this
game's generated scripts (its prefix, as `FALLOUT3_`) or the shared
`TES4Polyfill` and `TES4_` scripts are kept; other mods' lines are dropped.
Each line is filed under a cause:

| Cause | Log line | Finding |
|---|---|---|
| `binding` | `Property P on script S ... cannot be bound because [<nullptr form>] ...` | error, per script and property |
| `bind-script` | `Unable to bind script S to X because their base types do not match` | error |
| `missing-class` | `Cannot open store for class "S", missing file?` | error |
| `runtime` | an `error:` line followed by its stack; identifiers masked, grouped with the top frame's `Script.Function` | error |
| `stale` | `Property P ... cannot be initialized because the script no longer contains that property` | review: the save holds it |

A binding or attach error the static scripts audit already predicts folds into
one review ("N binding errors the scripts audit already reports"). Only the
ones it missed stand out, and each of those points at a rule the static audit
lacks. The same folding is applied to the previous session (`Papyrus.1.log`
and recorder run 1) to tag new causes and count the ones that are gone.

**Where each quest stopped.** For every quest in this plugin that the recorder
saw change stage, a review names:
- the last stage it reached;
- the next stage authored in the source;
- each source setter of that next stage, with the quest audit's verdict.

A setter that runs in a stage fragment is also marked when that stage never
ran this session. The recorder's quest ids are mapped to this plugin by
finding the load-order byte under which most of them are its quests.

**First run, 2026-09-28**, on the Fallout 3 session from that afternoon:
- 131 binding and attach errors. Before the rules above, 49 of their causes
  were ones the static audit didn't predict. Each rule the logs exposed was
  added: script-typed targets must carry the script, reference types need a
  persistent placed reference, Actor needs an ACHR, and scripts must attach to
  a record their engine type allows. Now all 131 are predicted.
- The quest report said "CG02 was left at stage 32; next is 34", with the
  stage 34 setters in the fragments of stages 20, 21 and 23, and "stage 21 did
  not run this session". Stage 21 is Amata's present, the blocker traced by
  hand that day.

## Asset load
<a id="asset-load"></a>
**What counts as seen:** every record placed as a REFR or ACHR, plus
everything reachable from those through:
- container and inventory entries (CNTO);
- default outfits (DOFT → OTFT INAM);
- leveled entries (LVLO);
- an ARMO's ARMA links.

Every model path on those records (MODL to MOD5) is checked:
- **Missing.** The model must exist loose under `output/<game>/` or in one of
  its BSAs (read with `tools/misc/bsa_list_names.py`). A missing path under the
  game's own folder (`meshes\fallout3\...`) is an error when the source export
  holds the file. When the source lacks it too, it's a review. A missing path
  outside the game's folder is grouped into one review per top folder, since
  vanilla Skyrim probably ships it.
- **Bad blocks.** Each shipped NIF's header block types are checked against the
  RTTI names in the played exe (`SkyrimSE.exe.unpacked.exe`, 1.6.1170). The
  check uses `nif_block_type_audit.rtti_names`, which reads the raw exe bytes,
  so it needs no `pefile`. A type with no RTTI is an error
  ([convex list shapes](asset_convert_collision.md#convex-list-shapes)).
- **Missing textures.** Every `.dds` path a shipped NIF names is checked the
  same way as a missing mesh.
- **Embedded weapons.** A WEAP whose DNAM flags carry 0x20 (Embedded) and that
  has no NNAM is an error
  ([embedded weapons](tes4_export_falloutnv.md#embedded-weapons)).

## Build diff
<a id="build-diff"></a>
A snapshot maps every FormID to `SIG|EditorID`. Compared with the baseline in
`output/preflight/<game>/build_baseline.json`, it reports three kinds of
drift, one finding per kind and signature:
- **moved**: an EditorID now sits on a new FormID;
- **removed**: a FormID vanished;
- **retyped**: a FormID now holds another signature.

The first run only saves a baseline. After that, the baseline advances by
itself while a build shows no drift. Once one does, it stays put until
`--accept-build`, because
[FormID drift](../../CLAUDE.md#formid-drift) needs the user's approval. Use
`--accept-build`, not the ledger, to approve drift: an `ok` on
`build|G|removed|INFO` would hide every later INFO removal too. Added records
are printed as a count per signature.

## Validation against earlier builds
<a id="validation"></a>
The quest audit was checked against the builds saved before the 2026-09-28
Blocking-greeting fix:

| Build | Fallout 3 stuck stages | New Vegas stuck stages |
|---|---|---|
| Before the Blocking fix | 18, including CG02 stage 21 (Amata's present) | 48 |
| Current | 6 | 4 |

The remaining findings were each checked by hand. All are real:
- CGTutorial 52, 72 and 212, in both games: their SetStages sit in `MenuMode`
  blocks the converter keeps only as comments.
- MQ09 stage 50: `MQ09PresidentEden`, a TACT, became an ACTI with no VMAD.
- MS16 stage 10 and MS18 stage 5: set only by FO3 radio lines (`RadioGoodbye`),
  and nothing in the build plays radio dialogue.
- vfreeformlucky38 stage 20: `Lucky38MainframeSCRIPT` is attached to no record.

The asset audit's four Fallout 3 errors are creature-folder meshes used as a
STAT, an ACTI or a WEAP: `alien.nif`, `haroldanimated.nif`,
`libertyprimeweapbomb.nif` and `misterhandystatic.nif`. The export holds all
four, but the build doesn't ship them.

The start audit's first run flagged 12 Fallout 3 quests. All 12 were the audit
missing the `TES4Start` form, which it now reads, and Fallout 3 is now clean.
New Vegas has one real finding: `VEuclidQuest` never starts, because its only
StartQuest sits in `EuclidsCFinderSCRIPT`'s `Begin OnFire` block, which the
converted script doesn't carry.

Script health, spot-checked against the data (2026-09-28):
- **Dangling FormIDs:** 577 + 197 Fallout 3 REFRs (851 + 71 in New Vegas) have
  a base of `01000020` or `01000017`. Their source bases `0x20` and `0x17` are
  engine-defined, so they aren't in the export, and the build shifted them into
  its own id space, where nothing defines them.
- **Topic properties:** 41 Fallout 3 Topic properties (137 in New Vegas) point
  at FormIDs the build doesn't hold. An example is
  `MQ05TaftEnclaveBark01Script.MQ05TaftDialogue`: the DIAL exists in the source
  export, but its FormID is absent from the built plugin.
- **Property FormID pass:** 55 Fallout 3 properties (81 in New Vegas) are
  typed ObjectReference but bound to an EXPL base record, which an
  ObjectReference can't hold.

**Oblivion (first run, 2026-09-28).** The game's own asset folder comes from
its script prefix (`TES4_` gives `meshes\tes4`), not its plugin name; using
the name had filed every missing Oblivion mesh as "maybe vanilla". Results:
- **quest:**
  - error: TG11Heist stage 135 is set only by `TG11TalkToMillona15`, a
    Conversation line whose built INFO is missing.
  - review: MQ01's tutorial stages are set only from `MenuMode` blocks, and the
    quest also has a computed SetStage.
- **dialogue:** 1,509 Conversation lines, 216 Service, 130 Persuasion and 28
  Topic lines are missing from the build. `conversations.py` drops flavor
  conversations by design ("better absent than wrong") and restores only
  quest-advancing chains. So the Conversation groups are intended and can be
  marked `ok`, except where a quest stage rides on a line, as in TG11.
- **scripts:**
  - 60 script-typed properties name a base record (ARMO, BOOK, KEYM, NPC_ and
    others) where a reference is needed;
  - 8 name a record lacking the script;
  - 191 `SetQuestObject` and 46 `AddTopic` calls are left inert.
- **assets:**
  - error: iron cuirass `meshes\tes4\armor\iron\{f,m}\cuirass.nif` is in the
    source export but not in the build;
  - error: `ungrdltraphingedoor.nif` holds a `bhkMeshShape` with no RTTI;
  - review: 15 assets are missing from both the build and the source export.
- **world:** one Kvatch lift door returns through a different door (review).
- **start, packages, build:** clean, except 8 navmesh reviews.

Dialogue loss (2026-09-28). A line with several named speakers counts once
for each, so the totals slightly overcount lines.

| Cause | Fallout 3 | New Vegas |
|---|---|---|
| Conversation topics missing from the build | 2,683 lines | 318 lines |
| Radio topics unreachable | 1,071 | 484 |
| Player-topic lines unreachable, almost all `SpeechChallengeFailure`, a topic the source reaches through LinkFrom | about 180 | 7 |
| No placed actor passes the built GetIsID | 145 | 44 |

The `SpeechChallengeFailure` losses were Fallout 3's speech challenges, which never failed; they now do ([speech challenges](tes5_import_dialogue.md#fallout-speech-challenges)), and the audit counts a line reached when a shared INFO (DNAM) in a reachable topic names it. Ten remain: lines linked only from topics with no challenge line, which Fallout 3 cannot reach either, since it looks for a failure line only after a lost roll. `decode_condition` also reads a short Fallout CTDA ([short CTDAs](tes5_import_conditions.md#fallout-short-ctda)) instead of zeros, so lines whose GetIsID sits in a 20-byte condition now name their speaker.

The Fallout 3 ambient conversations aren't in the build at all: for example,
`UnderworldTalkGretaDrink3` and its lines are absent, and the plugin holds 7
scenes. That is why Greta (64 lines), Ahzrukhal (55) and "lines anyone may say
in ConvMegaton" (206) head the list.

The GetIsID group includes converter-added speaker gates. The GenericRaider
battle cry INFO `000853C1` ("Yeaaaaaaaaah!") has no conditions in Fallout 3,
but the build adds `GetIsID 0x7 == 1` on the subject, which Skyrim.esm's
player base fills. So no raider can say it. New Vegas's package
`vHDNCRPlayerFollow` carries the same `GetIsID 0x7` requirement.

## What the audits do not see
<a id="blind-spots"></a>
- **Rules not yet learned.** Engine behavior nobody has hit yet isn't modeled.
  When a play-test finds some, add it as a rule here.
- **Guards and conditions.** SetStage `if` guards, stage-item conditions, and
  every INFO condition except the GetIsID speaker test.
- **Quest running state.** Stages are judged as if every quest runs. Quest
  starts are judged separately, and alias fill conditions aren't evaluated.
- **Inert commands other than the quest-moving list**, and whether a listed one
  actually blocks its quest; those are left for manual review.
- **Where quest actors need to be.** The plan's check for a quest actor with no
  package bringing it to its scene or dialogue isn't built. Nothing static says
  where a line must be spoken.
- **Package loss against the source.** The package audit reads only the build,
  so a dead package that was also dead in the source is marked for review
  rather than dropped.
- **Paths and animation.** Navmesh is checked only as "the destination cell
  has one", not whether a path exists.
- **Assets outside the game's folder.** They are only grouped for review,
  since vanilla Skyrim is never read.
