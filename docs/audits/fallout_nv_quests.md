# Quest completability audit — FalloutNV.esm

**Date:** 2026-09-27 · **Branch:** `standalone` working copy (after the
Travel-to-furniture and Fallout begin-script fixes) · **Scope:** all 436 QUST
records in FalloutNV.esm

## How it was run

```
python tools/dialog/quest_walkthrough.py --export export/FalloutNV.esm \
    --esm output/FalloutNV.esm/FalloutNV.esm --scripts output/FalloutNV.esm/scripts \
    --seq output/FalloutNV.esm/seq/FalloutNV.seq --start VCG00 --md <report.md>
```

The walkthrough ([quest.md](quest.md)) had only been run on Oblivion. Its first
New Vegas run reported 36 broken and 69 degraded quests, nearly all of them the
tool misreading Fallout output. Fixed in the tool:

| Tool gap | Effect on the first run |
|---|---|
| Script names were built in the `TES4_` namespace; New Vegas's are `FALLOUTNV_` | 407 "psc not generated" |
| `X.TES4SetStage(Q as X, n)` and `X.TES4Start(Q as X)`, the converter's stage helpers, were not edges (1,536 and 247 call sites) | most of the 132 "SetStage call missing" |
| The baseline read only an INFO's `ResultScript`, never FO3/FNV's End script | lost baseline edges, e.g. VCG01 stage 85 |
| `TACT` and `TERM` were not script-carrying types in the baseline | missed baseline edges |
| `Self.SetStage` in a quest's own script was skipped | missed edges |
| TESGameSelect starts New Vegas's opening, so `VCG00` is not start-game-enabled in the conversion; new `--start VCG00` | the whole opening chain unreachable |

**Result: 4 broken, 11 degraded** (from 36 and 69). The same tool on the
`local` Oblivion build (older code): 1 broken, 15 degraded.

The walkthrough proves only that a stage-setting call survives and can fire.
Engine behavior it cannot see: the two bugs found in game the same day
(Doc Mitchell's Travel-to-chair package, and Begin scripts run at the end of
the line) both passed it.

## Findings

Each class was checked against the export and the converted scripts; counts
are over FalloutNV.esm.

### 1. Menu-mode blocks commented out — real, 4 quests

**1001 fixed the same day** ([menumode-message-box](../commentary/script_convert.md#menumode-message-box)):
all 21 scripts now run their 1001 body as their own box closes, and a re-run
reports **2 broken, 9 degraded**; VMS32, VMS51, VMS54 and VMS35 (stage 101, in
`FortCaesarScript`'s 1001 block) all complete. The tutorial's 1 and 1056
remain.

`begin MenuMode <id>` runs only while that menu is open. The converter maps an
id to a Skyrim menu close in `MENU_ID_NAMES` (`script_convert/constants.py`),
which today holds only 1036 (`RaceSex Menu`); every other id's body is kept as
a comment and never runs ([menumode-with-a-menu-id](../commentary/script_convert.md#menumode-with-a-menu-id)).

| Block | Scripts | Blocks |
|---|---:|---|
| `begin MenuMode 1001` (message box) | 21 | `FortHowitzerScript` (VMS32 30), `VMS51BottleCapPressScript` (VMS51 20), `SLRemnantsBunkerPanelScript` (VMS54 30) |
| `begin MenuMode 1` (Pip-Boy) | 2 | `VCGTutorialSCRIPT` (CGTutorial 52, 212) |
| `begin MenuMode 1056` (VATS) | 2 | `VCGTutorialSCRIPT` (CGTutorial 72) |
| 1012, 1008, 1009 | 6, 3, 1 | not traced |

1001 is New Vegas's message-box button idiom: `ShowMessage` in OnActivate, the
button read in `MenuMode 1001`. The converter already waits on `Message.Show()`
(`TES4_ShowMsg`) and keeps the pressed button, so the proposed fix runs the
1001 body once after `Show()` returns, not on a menu-close event that can race
it. The Pip-Boy block's nearest Skyrim menu is probably the Journal Menu
(unverified; the name comes from `SkyrimSE.exe`), and VATS has no Skyrim menu,
so that block needs another trigger. The walkthrough reports the
tutorial stages as "no TES4 source found", which hides this cause.

### 2. `begin SayToDone` blocks dropped — real, fixed

**Fixed the same day** ([saytodone](../commentary/script_convert.md#saytodone)).
FO3/FNV run a `SayToDone <topic>` block when the speaker finishes a line of
that topic, and none survived: `LilyScript`'s `SayToDone LilyToDoctorHenry03`
holds VMS41's only `SetStage VMS41 60`. All 133 blocks are now functions on
their scripts, called from 356 INFO End fragments. A re-run reports **2
broken, 6 degraded**, and VMS41 completes. The 12 chains whose first topic
is an engine-picked NPC-to-NPC conversation (the REPCON tour, Pete's murals,
General Oliver's emergency) still wait on those topics, which the importer
drops.

### 2b. "NPC-to-NPC conversation" topics — mostly not conversations

The importer drops 1,345 Conversation-type topics as NPC-to-NPC chatter. Read
against FalloutNV.esm itself (every record, not the export):

| Topics | What they are |
|---:|---|
| 1,162 | no INFO at all (Fallout 3 leftovers: `MegatonTalk1`, `SPELLHELP`...) |
| 80 | engine-picked idle lines nothing names; 77 are single, speaker-gated flavor lines with no quest effect |
| about 80 | choice-linked (`TCLT`, or `LinkFrom`/`TCLF`, which the export writes but the importer never reads) |
| about 16 | spoken by a package's OnBegin/OnEnd/OnChange script or topic |
| 10 | spoken by a patrol marker's embedded script (REPCON tour, Pete's murals, General Oliver) |
| 7 | the topic of a Dialogue package (`PKDD`) |
| 1 | a terminal script |

So the chains that matter start from records the exporter never wrote.
**Package scripts are fixed** ([package-fragments](../commentary/script_convert.md#package-fragments)):
480 section scripts, 171 of them quest-advancing, now run as package
fragments, and 28 more topics are kept. Still open:

- ~~New Vegas package types 12-16 are not converted~~ **fixed**
  ([fallout-package-types](../commentary/tes5_import_package.md#fallout-package-types)):
  Patrol 505 → Patrol, Guard 175 → GuardPost, Dialogue 332 → ForceGreet 277
  / Say 55, Use Weapon 82 → UseWeapon, and authored linked refs (the patrol
  chains) are written. Dialogue-package topics are kept: 6 more topics, 29
  INFOs.
- ~~Patrol markers~~ **fixed** ([patrol-points](../commentary/tes5_import_package.md#patrol-points)):
  all 1,347 patrol points keep Skyrim's own idle time and topic; 90 of the
  101 scripted ones run their script on the arriving actor (Patrol, Travel or
  Guard). The other 11 are reached by no package in the data, among them the
  REPCON 2nd-floor teleport chain and Pete's fourth mural marker.
- ~~`LinkFrom` links~~ **checked, not needed**
  ([fallout-topic-links](../commentary/tes5_import_dialogue.md#fallout-topic-links)):
  625 of 1,008 pairs repeat a Choice link, and the rest name HELLO chains,
  radio and `ANY`. Found alongside: the Top-level flag and the INFO prompt
  were never exported, so 14,067 reply-only topics were listed in the menu
  (Doc Mitchell's "PLAYER FIRE WEAPON", "<Doc Outro>"). Fixed.
- The 77 idle flavor lines stay dropped (the "better absent than wrong" rule
  the Oblivion conversation driver follows).

### 2c. Objective conditions and Follow Up links — real, fixed (found in game)

Doc Mitchell never finished VCG01 in game: at the door he repeated the
psych-test "have a seat" greeting, the house door stayed locked, and VMQ01
never started. Two causes, both invisible to the walkthrough:

- **Objective conditions were dropped.** Skyrim's GetObjectiveCompleted /
  GetObjectiveDisplayed are script-only, so 1,809 FNV conditions on them
  vanished, and the "have a seat" greeting passed again after the test. They
  now read mirror globals the converted objective commands set
  ([fallout-objective-conditions](../commentary/tes5_import_conditions.md#fallout-objective-conditions)).
- **Follow Up (TCFU) was never exported.** The farewell is a chain of 1,107
  INFOs' worth of follow-up links (the Pip-Boy, the vault suit, "talk to Sunny
  Smiles", whose End script opens the door and ends the quest). Each now
  continues unasked into a topic of shared copies
  ([fallout-follow-ups](../commentary/tes5_import_dialogue.md#fallout-follow-ups)).

### 3. Voice-type conditions on voice types never written — real, fixed

**Fixed the same day** ([authored-voice-types](../commentary/tes5_import_conditions.md#authored-voice-types)).
The first reading here was wrong: New Vegas authors 16,833 `GetIsVoiceType`
conditions itself, and the importer adds its own. 32,224 parameters named New
Vegas's source VTYP FormIDs, which the plugin writes at other ids; creatures
had lost their voice types in the exporter; and the injected voice gate
contradicted lines that state their own. Measured against the voice types
actors carry, INFOs no one can speak went from 2,147 to 18, all 18
contradictions New Vegas authors itself. A re-run reports **2 broken, 7
degraded**: VMS01 (stages 30, 40) and Doctors (stage 30) complete.

### 4. Terminals lose their menus — real, 344 terminals

`TERM.txt` holds only EditorID, FULL, model, bounds and SCRI: no menu entries,
body text, or per-entry result scripts. Terminals become plain activators
([tes4_export_falloutnv.md](../commentary/tes4_export_falloutnv.md)). Nothing
exported starts `VMQ04` or `VMQHouseLockdown`, and `Lucky38MainframeSCRIPT`
(on a TERM) is attached to nothing (vfreeformlucky38 stage 20); entry scripts
are the likely source of all three. Needs the exporter to decode TERM's menu
items first, then a terminal design (message-box pages are the obvious one).

### 5. `StartConversation player <topic>` topics — tool gap, not verified

VMS19 (`VFSKingSendsPlayerToNegotiate`, `VFSKingSendsPlayerAfterPacer`) and
VHDLegionBattle (`VHDLegateCongratulatesYou`) are reached through
`StartConversation player <topic>`, which the converter turns into a
`TES4ForceGreets` alias package; the walkthrough does not model that pool.
VMS29a and VMS45's "only reachable via TCLT from an unreachable INFO" chains
probably root in the same place. Next: teach the walkthrough the force-greet
pool, then re-check.

## Open issues from the first in-game runs (2026-09-27)

Not quest-walkthrough findings: what the intro run showed, plus what its
Papyrus log carried. None fixed yet unless marked.

| Issue | What is known |
|---|---|
| Special idles never play | IDLE is in the importer's skip list; 491 special-idle `.kf` clips, 87 package idles and 189 `PlayIdle` calls do nothing. The player starts standing beside Doc's bed instead of lying in it. Needs clip retarget + humanoid-graph states (the gun path has both). |
| Terminals are plain activators | See 4 above. |
| Reputation properties unbound | Every `RepNV*` (NCR, Legion, Freeside, Khans, ...) fails to bind in the Papyrus log; the REPU records do not seem to reach the plugin. Not traced. |
| NPC dark faces | No FaceGen data is generated (Oblivion too). |
| Hands, pistol, player hands | NPC hands do not match their clothing; the player's pistol and hands are broken. Not looked into. |
| A light blocks movement | In front of the Prospector Saloon, under the light beam `0016B5EB`. The beam, lamp and saloon lights have no collision; the saloon's matches FNV. Suspect: the `GSSaloonExitTrigger` box beside it. Trigger primitives now name L_TRIGGER ([trigger-primitives](../commentary/tes4_export_falloutnv.md#trigger-primitives)); unconfirmed in game. |
| Saloon porch floor drops the player | **Fixed, unconfirmed in game.** Half of each porch/deck floor quad faced down, and Skyrim collides one side only; the winding repair could not flip a face inside a plank ([round 4d](../commentary/asset_convert_collision.md#round-4d-a-face-under-a-floor-faces-up)). The same pattern was in 12 of the 33 Goodsprings buildings. |
| Wooden gate opens but blocks | **Fixed, unconfirmed in game.** The gate's collision moved onto the mesh root because the animation check read only the posts' collision ([every collision owner](../commentary/asset_convert_collision.md#every-collision-owner)); 42 New Vegas meshes and 54 Oblivion ones had that shape. |
| NPC sits beside a stool | **Fixed, unconfirmed in game.** Fallout's stool entry (marker 15) put the sitter 20.5 units off the stool's center ([stool entries](../commentary/asset_convert_falloutnv.md#stool-entries)). |
| `{Evil 2+}` in dialogue | **Fixed, unconfirmed in game.** Fallout's writers left notes in braces in 5,634 lines and 125 topic texts, which the Fallout engine hides and Skyrim showed ([brace notes](../commentary/tes5_import_dialogue.md#fallout-brace-notes)). |
| Sunny's first greeting offers only Goodbye | **Fixed, unconfirmed in game.** Her greeting kept one of its ten choice links, and in Skyrim a line's links replace the topic menu ([choice filter](../commentary/tes5_import_dialogue.md#info-tclt-choice-filter)). |
| Chet: no barter, then only "Hey there." | **Fixed, unconfirmed in game.** `ShowBarterMenu` was left as a TODO ([barter](../commentary/script_convert.md#fallout-barter)); and the half-hour lockout on his one repeatable greeting let the civilian Goodbye greeting win ([lockout](../commentary/tes5_import_dialogue.md#info-enam-reset-timer)). |
| Sunny never walks out (VCG02) | **Fixed, unconfirmed in game.** No NPC could path through any door: FNV navmesh door links kept the source FormIDs, so none of 1,108 teleport doors got XNDP ([renumbered](../commentary/tes5_import_navmesh.md#fallout-door-links-renumbered)). |
| 100 XP at the start of a new game | **Fixed, unconfirmed in game.** ED-E's completion reward: `GetQuestCompleted` was dropped from its `&&` chain ([quest completed](../commentary/script_convert.md#fallout-quest-completed)). |
| Kills pay 1 XP; corpses can be "killed" | **Fixed, unconfirmed in game.** Template stubs kept their placeholder level, AI data and health ([a claimed category is final](../commentary/tes5_import_falloutnv_actors.md#a-claimed-category-is-final)); corpse bases' dead flag was ignored ([starts dead](../commentary/tes5_import_actors.md#fallout-starts-dead)). |
| Sunny does not walk to the well (VCG02 stage 25) | **Fixed, unconfirmed in game.** NPCs could not cross exterior cell borders: FNV's authored navmesh edge links were dropped, 9% of exterior meshes linked, now 95% ([edge links](../commentary/tes5_import_navmesh.md#fallout-edge-links)). |
| Same-kind enemies fight each other (geckos, Powder Gangers, convicts) | **Fixed, unconfirmed in game.** Every FNV faction relation was imported Neutral, a faction's Ally to itself included ([faction relations](../commentary/tes5_import_actors.md#faction-relations)). |
| Voice and sound notes do not play (Beagle's journal) | **Fixed for voice notes, unconfirmed in game.** Listening is what advances VMQ01: the recording's line completes objectives 30-38 and shows 40. A voice note's book now plays its topic when read, as its speaker ([voice notes](../commentary/tes4_export_falloutnv.md#voice-notes-play-when-read)); 5 of 34 name a speaker placed once. Sound notes still do not play. |
| Sunny's bottles never count (VCG02) | **Fixed, unconfirmed in game.** The hit test compares `GetWeaponAnimType` to 4-8; it read Skyrim's item type, 12 for a converted rifle ([weapon anim type](../commentary/script_convert.md#fallout-weapon-anim-type)). |
| Taking Deputy Beagle's journal does not advance VMQ01 | **Fixed, unconfirmed in game.** Notes were activators and `GetHasNote` read 0; notes are now books and the note commands item operations ([notes are items](../commentary/tes4_export_falloutnv.md#notes-are-items)). |
| A wooden plank lets the player fall through | Ref `001568A5`, base `WoodPlanksGroup01` (`000039D0`), alone in the Mojave at (-59920, -53456). Its converted collision is a closed box matching the render mesh, with the same body, flags and layer as walkable decks; the reference, base and cell all check out. Fourth run: it bridges a hole in the broken overpass (`OverpassRoad02` `001568A4`) outside Primm, and stepping on it drops the player to the road below. In world space the converted collision of plank and overpass matches FNV's exactly (plank top z 5782 over the hole); the MOPP tree is valid and encloses the plank. Seventh run: the same base drops the player on the NCR Correctional Facility administration's second floor (`0008DEAE`). **Fixed, confirmed in game (2026-09-28).** Half of the box's top quad faced down: its centre lies over a gap between the render planks, so the winding repair had no skin to judge it by. It now takes the winding of its coplanar neighbour ([coplanar neighbours](../commentary/asset_convert_collision.md#coplanar-neighbours-agree)). |
| Johnson Nash's options never advance VMQ01 | **Fixed, unconfirmed in game.** "I'm a courier with the Mojave Express" is unlocked by the line that offers it; the unlock ran at the line's end, after the choice menu was built ([unlocks land when the line begins](../commentary/tes5_import_dialogue.md#unlocks-land-when-the-line-begins)). |
| Back in the Saddle never completes (VCG02) | It completes when you meet Trudy. After "[END TUTORIAL]", Sunny's follow-up lines set that objective and enable Trudy; the run closed the conversation 1 s into her reply (the exit bark played), so they never ran, and none of her later greetings offers them again. FNV could not be left mid-line. Fifth run: the reply played in full and the talk still closed, so leaving mid-line was not the cause; the resume topic also lost to her own greeting. **Second attempt, sixth run: works via the resume.** On a fresh start "Suit yourself" played in full, then her goodbye bark instead of the follow-up; talking to her again played the resume copy and the Trudy lines. The in-conversation continue still fails although its copy is built like Doc's working one and the resume copy with the same conditions passed; cause not found ([resume](../commentary/tes5_import_dialogue.md#fallout-follow-ups-resume)). |
| Fixing the radio | **Works** (sixth run): finished. |
| Dynamite is not thrown; attack reloads | Thrown weapons (anim types 10-13) are crossbows, which fire separate ammo; in FNV a thrown weapon is its own ammo. Not converted. |
| Gun fires several times per click, at random | Seen in the third run; not looked into. |
| Dust in the air glitches; a laser beam stays after the shot | Seen in the third run; not looked into. |
| Enemy AI glitchy | Seen in the third run. Two causes fixed above (stubs' AI data and level; corpses loading alive); anything left is untraced. Sixth run: still rough. |
| Sunny's path to the wells is rough | Sixth run: she crosses mountains and gets stuck on terrain; the player had to disable rocks. Not looked into. |
| Tutorial ending (VCG01) | **Works** (flight recorder, second run): the whole follow-up chain plays, VCG01 reaches 200, and VMQ01 10 and VCG02 5 start at the same moment. |
| Intro movie | [bink_movies.md](../plans/bink_movies.md). |
| Tutorial help text shows raw tokens | The top-left tutorial messages print FNV's key-name tokens verbatim: `&sUActnJump;`, `&sUActnGrab;`, the `&sXB...;` gamepad names (about 40 in MESG `DESC`). Fallout's engine swaps in the bound key; Skyrim needs its own key-name markup there, or the words ("the Jump key"). |
| Screen fades missing | ImageSpace-modifier properties never bind (IMAD not converted). |
| Log spam | Second run: 3,279 Papyrus error lines in 15 minutes (590 more dropped at startup), almost all `FALLOUTNV_LuckyNLightScript.GetAnimationVariableBool("bAnimPlaying")` on the Goodsprings lights. First run: about 400 errors from `Lucky38LightScript` (`bAnimPlaying`) and 260 from ammo and other inventory item scripts calling `GetParentCell` while in a container. |

## Suggested order

1. ~~Menu-mode 1001~~ (done); the tutorial's 1 / 1056.
2. ~~The voice-type condition mapping~~ (done).
3. ~~`SayToDone`~~, ~~package scripts~~, ~~package types~~, ~~patrol
   markers~~, ~~`LinkFrom`~~ (done; see 2b).
4. Terminals (exporter plus design; biggest).
5. Walkthrough: model the force-greet pool, and name the commented-out
   menu-mode block instead of "no TES4 source found".
