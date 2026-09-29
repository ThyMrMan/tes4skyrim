# Papyrus runtime cost: polls and dialogue helpers that run all game

**Status: PLAN, unimplemented.** This comes from a review on 2026-09-28 of the
fixes made while play-testing Fallout 3 and New Vegas. The counts were measured
from the generated scripts in `output/<game>/scripts/source`. None of it has
been profiled in game.

## What is already in its best form

These fixes are record changes the engine handles natively, so nothing runs
repeatedly. Leave them as they are:

| Fix | Why it's the right approach |
|---|---|
| A greeting with replies opens as a Blocking branch ([greeting choices](../commentary/tes5_import_dialogue.md#greeting-choices-block)) | Vanilla's own mechanism for a greeting that offers choices |
| A run-once package's OnChange folds into OnEnd, guarded by `GetStageDone == 0` ([package fold](../commentary/script_convert.md#run-once-package-change)) | The engine checks the condition only while choosing packages |
| `bhkConvexListShape` becomes `bhkListShape` ([convex list](../commentary/asset_convert_collision.md#convex-list-shapes)) | Build-time only |
| Embedded weapons keep the DNAM flag and NNAM ([embedded weapons](../commentary/tes4_export_falloutnv.md#embedded-weapons)) | An engine flag |
| `SayTo...Done` blocks become functions the line's End fragment calls | Event-driven, replacing a poll |
| Follow-ups (TCFU) become hidden topics reached with an invisible continue | Records only |
| The `TES4SetStage` wrapper | One `IsRunning()` per stage set |

## 1. Quest scripts poll far more often than the source games did

The biggest saving, and it also fixes a behavior bug.

**The source games.** A quest script ran only while its quest was running,
every 5 s by default, or at the quest's authored delay (FO3/FNV QUST
`DATA.Delay`; `fQuestDelayTime` in a script). 146 of Fallout 3's 162 quests
keep the default.

**The converter now.**
- `poll_interval.update_interval` treats "no authored delay" as 0.5 s. It
  uses 0.1 s for a script reading `GetSecondsPassed`, 0.15 s for a Say timer
  and 0.25 s for other timers.
- `assemble.poll` keeps a quest's poll ticking while the quest isn't running.
  The body returns after `If (!IsRunning())`, but the loop keeps re-arming.
- `converter._quest_delay` turns `set Q.fQuestDelayTime to N` into a single
  `RegisterForSingleUpdate(N)`. The next bottom re-arm returns to the fixed
  interval, so the delay lasts one tick instead of until it's changed.

**Measured quest polls:**

| Game | Polling quest scripts | By interval | Wake-ups per second, all game |
|---|---|---|---|
| Fallout 3 | 74 | 49 at 0.5 s, 21 at 0.1 s | about 300 |
| New Vegas | 207 | 120 at 0.5 s, 47 at 0.1 s, the rest authored | about 700 |
| Oblivion | 212 | 166 at 0.5 s, 42 at 0.1 s | about 760 |

The source games ran only the running quests, at 0.2 per second each.

**Better design:**
- Hold the delay in a quest-script variable (`TES4_Delay`), initialized to
  the authored delay or 5 s.
- Make `fQuestDelayTime` set that variable for good, with 0 or less meaning
  5 s, and arm from the variable.
- Stop re-arming while the quest isn't running, and start the poll when the
  quest starts: from `OnInit` if that fires on every start, else from
  `TES4Start`.
- Keep the 0.1 s floor for an authored delay.

**Before building:**
- Confirm from the Creation Kit docs when a quest script's `OnInit` fires
  (every start, reset, game start for Start Game Enabled quests).
- Play one timing-heavy quest, such as CG02's party failsafe timer or a
  scripted conversation. Say-timer pacing was tuned against the fast
  interval ([poll interval](../commentary/script_convert.md#poll-interval)),
  but the source quests that need speed set `fQuestDelayTime` themselves,
  which the variable now honors.

## 2. Object and actor GameMode loops pay extra on every tick

Safe, contained in `script_convert/assemble.py`, and it helps every game.

Polling reference scripts: about 530 in Fallout 3, 790 in New Vegas and
1,360 in Oblivion (quests included); only those in loaded cells tick.

**Now:**
- Every tick checks `TES4Polyfill.SafeGameModeGate(Self)` twice: once for the
  5 s insurance arm at the top, once for the real re-arm at the bottom
  ([why two arms](../commentary/script_convert.md#poll-lifecycle)). Each
  check calls up to three natives on the reference: `GetParentCell`,
  `Is3DLoaded` and `IsAttached`.
- Any script reading `GetSecondsPassed` polls at 0.1 s.

**Better design:**
- Replace the native gate with a flag set in `OnCellAttach`/`OnLoad` and
  cleared in `OnCellDetach`/`OnUnload`, as the patrol watcher already does
  (`patrol_scripts._WATCH`, `TES4Watching`). A carried object still needs the
  native holder check (`assemble._carried`). Keep both arms; with the flag
  they cost nothing.
- Poll a `GetSecondsPassed` script at 0.25 s. It already measures real
  elapsed time (`assemble._elapsed_prologue`), so its counted timers stay
  accurate. Keep 0.1 s only for `moves_in_poll`, the scripts that glide
  references.

## 3. Dialogue state lives in actor values read many times per second

**Now:**
- `TES4Polyfill.LineBegan`/`LineEnded` run on every spoken line.
- `PlayerIsInDialogue` runs on every tick of any polling script that speaks
  (`assemble._dialogue_gate`) and in the quest-timer pauses.
- They store the dialogue speaker and line timing in actor values:
  - the player's `Variable05`/`Variable06` hold the dialogue speaker's
    FormID, `Variable07` the game-wide "a line is playing until" time, and
    `Variable09` a talking activator's line length;
  - each speaker's `Variable06`/`Variable09` hold its own line start and
    length.

  So each check is several native calls, and those slots may be shared with
  anything else that uses them.

**Better design:** hold that state in variables on one small polyfill quest,
which the script engine reads directly without a native call.
`TES4Polyfill.psc` is in `script_convert/static_scripts/`, so this means
rebuilding the scripts of every game
([static scripts](../../CLAUDE.md#static-scripts-rebuild-all)).

## 4. Patrol points check for arrivals every 0.5 s

`patrol_scripts._WATCH` runs `Game.FindClosestActorFromRef` twice a second
on each loaded patrol marker; New Vegas generates 101 of these scripts.

**Better design:** a trigger volume around each marker makes arrival an
`OnTriggerEnter` event. A cheaper middle step is to watch only while an
actor holding one of the marker's patrol packages is in the cell. This is
the lowest priority of the four.

## Order

1. Item 2: safest, entirely in the converter.
2. Item 1, after the Creation Kit check. The largest saving, and it fixes the
   `fQuestDelayTime` bug.
3. Item 3.
4. Item 4.

Items 1 and 2 need `--scripts-only` for each game; item 3 rebuilds every
game's scripts together.
