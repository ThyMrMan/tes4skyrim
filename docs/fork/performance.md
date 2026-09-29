# Performance: runtime cost and culling

Design only; status is in the [roadmap](ROADMAP.md#performance).

- [Rules every new system follows](#rules)
- [Papyrus runtime cost](#papyrus)
- [FO3/FNV occlusion data](#occlusion)

## <a id="rules"></a>Rules every new system follows

The DLL side is cheap when it is event-driven. Measured so far: the Morrowind
tick costs 0.03 ms over the real Morrowind, Tribunal and Bloodmoon sidecars
(10,640 placements), about 0.015 ms per frame at 60 fps. The one fps incident
was a timer that re-ran the tick back to back after about 156 hours of uptime
([whole milliseconds](../commentary/morrowind_runtime.md#the-tick-sleeps-whole-milliseconds)),
not the tick's own work.

Papyrus is the bigger risk: `Oblivion.esm`'s scripts carry 1,327 `GameMode`
blocks (Fallout 3 524, New Vegas 663, [counted](research/character_findings.md#checked)), each converted
into an `OnUpdate` poll ([scope](../commentary/script_convert.md#scope)). The systems layer
therefore never polls from Papyrus: its Papyrus runs only when a Story Manager
event fires, and anything that needs more lives in C++. Either way it:

1. reacts to engine events (skill increases, kills, casts, locks, sales)
   rather than polling; any poll in C++ runs at most every 33 ms and does
   nothing unless something changed;
2. precomputes tables at import and resolves FormIDs once per load;
3. applies effects when values change, never per frame;
4. writes a GLOB only when its value changes;
5. keeps a custom menu's per-frame callback trivial;
6. does nothing when its game's plugin is not loaded;
7. sleeps in whole milliseconds with at most one tick queued
   ([one queued tick](../commentary/morrowind_runtime.md#one-queued-tick));
8. records a headless benchmark and an in-game frame-time comparison, DLL on
   and off, in each piece's commentary doc.

## <a id="papyrus"></a>Papyrus runtime cost: polls and dialogue helpers that run all game

Unbuilt. This comes from a review on 2026-09-28 of the
fixes made while play-testing Fallout 3 and New Vegas. The counts were measured
from the generated scripts in `output/<game>/scripts/source`. None of it has
been profiled in game.

### What is already in its best form

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

### 1. Quest scripts poll far more often than the source games did

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

### 2. Object and actor GameMode loops pay extra on every tick

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

### 3. Dialogue state lives in actor values read many times per second

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

### 4. Patrol points check for arrivals every 0.5 s

`patrol_scripts._WATCH` runs `Game.FindClosestActorFromRef` twice a second
on each loaded patrol marker; New Vegas generates 101 of these scripts.

**Better design:** a trigger volume around each marker makes arrival an
`OnTriggerEnter` event. A cheaper middle step is to watch only while an
actor holding one of the marker's patrol packages is in the cell. This is
the lowest priority of the four.

### Order

1. Item 2: safest, entirely in the converter.
2. Item 1, after the Creation Kit check. The largest saving, and it fixes the
   `fQuestDelayTime` bug.
3. Item 3.
4. Item 4.

Items 1 and 2 need `--scripts-only` for each game; item 3 rebuilds every
game's scripts together.

## <a id="occlusion"></a>FO3/FNV occlusion planes, rooms and portals

Noted 2026-09-28 as a possible follow-up, not started. Nothing below is measured.

### The observation

FO3/FNV cull with hand-placed occlusion planes (exteriors) and rooms and portals
(interiors). Skyrim uses the same scheme. A code search found no stage that carries
any of it across:

- `XORD`, `XPOD`, `XRMR`, `XLRM` are never read by `tes4_export/` nor written by
  `tes5_import/`.
- `RoomMarker` (679 REFRs in FalloutNV.esm) and `MultiBoundMarker` (2) are swapped
  for an invisible `XMarker` (`tes5_import/record_types/world_falloutnv.py`). That hides
  the marker and drops what it stood for.
- `XPRM` primitives are copied raw, but only as trigger volumes
  (`world.py`, `_refr_head`).
- `nif_converter.py` has no `BSMultiBoundNode` handling. Only `lod/terrain_nif.py`
  builds them, for generated LOD.

Oblivion has no such data, so it loses nothing.

### Guess to test

Converted FO3/FNV interiors draw everything in the frustum, and converted
exterior cities lose their occlusion planes. The cost in play is unmeasured.

### Steps if pursued

1. Extend the export to dump `XORD`, `XPOD`, `XRMR`, `XLRM` and `XMBR` from FO3/FNV
   cells and refs (raw hex, as `XPRM.Raw` does).
2. Count them from the dump: cells and refs affected.
3. Compare the layouts against Skyrim's in `references/xEdit`, then census
   Skyrim.esm for how vanilla writes them. Byte-copy only if they match.
4. Check whether converted NIFs keep or drop `BSMultiBoundNode`; room and portal
   refs point at multibound nodes.
5. Measure in game or by frame capture before and after on one dense interior.
6. Add a preflight check: rooms, portals and planes in the source cell against the
   converted cell (see [preflight_audits.md](done/preflight_audits.md)).

### Open questions

- Whether Oblivion interiors would benefit from generated portals. Nothing authored to convert.
- Whether the room bound refs need their multibound base objects in the output.
