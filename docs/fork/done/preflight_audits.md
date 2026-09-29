# Preflight audits: find stuck quests and broken content before play

**Built** (kept as the design record; open gaps are in the [roadmap](../ROADMAP.md#stability)). All nine audits are built as `python -m tools.validate.preflight`
(audit 9 as `--audit logs`),
with a review ledger for findings the audit cannot judge
([commentary](../../commentary/tools_preflight.md#overview)). Known gaps:
- audit 1 doesn't check stage-item conditions or Say Once lines;
- audit 2 doesn't evaluate condition-filled aliases, and marks required ones
  for review;
- audit 4 uses the quest audit's dialogue models rather than the two
  emulators;
- audit 6 doesn't check that quest actors have a package bringing them to
  their scenes.

Written 2026-09-28 after a run of Fallout 3
play-tests where each blocker (Andy's package, Amata's greeting, the red
error marker) took a session to trace. Each one followed a pattern a static
check over the built plugin could have flagged.

The goal is one command, run after every import, that prints a short report
for each game and compares it against the last build. Anything new in that
report is a regression found on the day it lands. Every play-test diagnosis
becomes a rule, so it is then checked across all five games.

## Principles

- **Source against converted.** Where possible, a check computes the same
  thing from the source export and from the built plugin. It flags what the
  conversion lost rather than guessing at what should work. The dialogue
  emulators already work this way.
- **Baselines.** Each audit saves its findings per game. The report shows
  only what changed since the last saved run, with the full list on request.
- **Rules from play-tests.** When a play-test finds a new engine behavior,
  it becomes a rule in the matching audit before the fix ships.
- **Static only.** None of these needs the game running.

## 1. Quest progression audit (highest value)

For every quest stage, list everything that sets it:
- quest stage scripts;
- dialogue result scripts and the "when this line finishes" fragments;
- package start, end and change fragments;
- object and magic effect scripts;
- trigger boxes and activators.

It builds this once from the source export and once from the built plugin,
then flags any stage the source can reach but the conversion cannot. It
follows each setter back to how it runs in Skyrim.

Rules from the setters diagnosed so far:
- A package change fragment that sets a stage runs only when the actor
  leaves the package. Flag it when the package never ends
  (the CG02 Andy case, [package fold](../../commentary/script_convert.md#run-once-package-change)).
- A greeting line whose replies survive must open as a Blocking branch, or
  its replies never show
  ([Blocking greeting](../../commentary/tes5_import_dialogue.md#greeting-choices-block)).
- A line with no speaker who can pass its conditions: GetIsID or voice
  type gates that no placed actor satisfies.
- A Say Once line that gates a stage, flagged as a warning because a save
  made after it can never reach the stage.
- A stage set only by a script that failed to compile, or by a command
  that converted to an inert `;NE: TODO`.
- A stage whose condition needs an item the player never gets: the item
  has no placed ref, container, leveled list or script that adds it.

Output: for each quest, the stages unreachable after conversion and the
setter that broke. Also, a count of the quests whose last stage is
reachable, as a single progress number for each game.

## 2. Quest start and alias fill audit

A Skyrim quest with a required alias that can't be filled never starts, and
nothing reports it. Checks:
- Unique Actor and Forced Reference aliases that point at a ref that isn't
  placed, is deleted or starts disabled with no enabler.
- Required aliases whose fill conditions no placed ref passes.
- Start Game Enabled quests whose startup stage fragment failed to compile.
- Quests that only start from a command nothing reachable runs.

## 3. Asset load audit over everything placed

This joins the scratch model check and `nif_block_type_audit.py` into one
pass:
- every model path on every base record that is placed, worn or held
  exists in a BSA or loose (MODL through MOD5; ARMA, not ARMO);
- every such NIF passes the block type check, so every block has Skyrim RTTI
  (the [convex list](../../commentary/asset_convert_collision.md#convex-list-shapes)
  case);
- every texture those NIFs name exists;
- embedded weapons have their NNAM node in the actor's skeleton.

The output is a list of red error markers, with the ref, cell and missing
piece for each.

## 4. Dialogue loss report

Run `dialog_emulator.py` and `oblivion_dialog_emulator.py` for every named
NPC, in every game, and rank the NPCs by lines lost. Add the
one-bark-topic-per-quest rule the emulator doesn't yet model. A quest NPC
who loses most of their lines is the first thing to look at.

## 5. Script and property audit

- The compile summary for each game, with the failures grouped by cause.
- A count of `;NE:` markers for each quest, with markers inside stage
  setters listed first.
- `vmad_property_typecheck.py` and `property_type_audit.py` on every build.
  These catch the "property cannot be bound" errors before launch.
- Properties that point at a FormID the plugin doesn't contain
  (`dangling_ref_check.py`).

## 6. Package and AI audit

- Package targets and locations that point at a missing ref or a cell
  that doesn't exist.
- Packages whose schedule never matches, or whose conditions no actor can
  pass.
- Quest actors with no package that brings them to where their scene or
  dialogue happens.
- Package destinations with no navmesh under them, once navmesh ships.

## 7. World linkage audit

- Every teleport door has a linked door, and the destination ref exists
  in a cell that exists.
- Interiors with no teleport door out.
- Map markers and quest targets that point at missing refs.

## 8. Build diff

A record count for each type, compared against the baseline, and FormIDs
added, removed or moved, using `stable_id_check.py`. This is the generalized
form of the scratch `verify5.py` and `verify6.py` diffs. Any removed or
moved FormID stops the report, because FormID drift needs the user's
approval before it ships.

## 9. Log triage (after a play-test)

These tools help after a play-test, but they never need one:
- A Papyrus log classifier that groups errors (binding, None refs, stack
  dumps) and compares them against the previous session's log.
- A flight recorder summary that prints, for every quest touched, its last
  stage and the setters audit 1 lists for the next stage.

## Order

1, 3 and 8 first: they cover most of the recent blockers and the drift
rule. Then 2 and 5, then 4, 6 and 7. Log triage can land at any time.
