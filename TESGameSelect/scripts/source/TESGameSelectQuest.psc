ScriptName TESGameSelectQuest extends Quest Conditional
{Threads of Prophecy — detects the installed games, asks which one a new game
begins, and starts a game on request: from the MQ101 takeover on a new game,
or from the Elder Scroll's travel menu later.

Every foreign form is resolved at runtime with Game.GetFormFromFile(), so this
plugin masters only Skyrim.esm and ships to users with any subset of the
converted games installed, in any load order. A game whose plugin is absent
never appears in a menu.
See docs/commentary/tesgameselect.md}

; ---------------------------------------------------------------------------
; Plugin file names. Properties rather than literals so a repack for a renamed
; or translated plugin needs no recompile — just an xEdit property edit.
; ---------------------------------------------------------------------------
String Property OblivionPlugin     = "Oblivion.esm"         Auto
String Property MorrowindPlugin    = "Morrowind.esm"        Auto
String Property MorroblivionPlugin = "Morrowind_ob.esm"     Auto
String Property NehrimPlugin       = "Nehrim.esm"           Auto
String Property ArktwendPlugin     = "Arktwend_English.esm" Auto
String Property FalloutNVPlugin    = "FalloutNV.esm"        Auto
String Property Fallout3Plugin     = "Fallout3.esm"         Auto

; ---------------------------------------------------------------------------
; Per-game entry points. GetFormFromFile takes a form's ID *within its own
; file*, so only the low 24 bits matter and the load order can be anything.
;
;   Oblivion      Charactergen 0002466E — stage 5 is the whole start: sets
;                 in-chargen, starts MQ01 at stage 5, and moves the player to
;                 CGPlayerStartMarker 00032AB5 in the Imperial Prison.
;   Nehrim        Charactergen 0002466E — stage 5 moves the player to
;                 PlayerMarkerStartCell 00000D33. MQ00 00000811 is the real
;                 intro driver and stops Charactergen once controls return.
;   Morroblivion  fbmwChargen 00F0A28C — stage 1 opens the prison-ship
;                 sequence; mwCGPlayerStartMarker 00F0A278 is the wake-up spot
;                 (the stage-1 fragment does NOT move the player itself).
; ---------------------------------------------------------------------------
Int Property OblivionChargenID     = 0x0002466E Auto
Int Property OblivionStartMarkerID = 0x00032AB5 Auto
Int Property OblivionChargenStage  = 5          Auto

Int Property NehrimChargenID       = 0x0002466E Auto
Int Property NehrimStartMarkerID   = 0x00000D33 Auto
Int Property NehrimMainQuestID     = 0x00000811 Auto
Int Property NehrimChargenStage    = 5          Auto
Int Property NehrimMainQuestStage  = 1          Auto
; TES4PlayerScripts, the converter's quest hosting Nehrim's player scripts. Its
; GlobalplayerScript polls every tenth of a second and starts MQ00 at stage 1
; the first time it runs, so it waits with the opening.
Int Property NehrimPlayerScriptsID = 0x0083563B Auto

Int Property MorroChargenID        = 0x00F0A28C Auto
Int Property MorroStartMarkerID    = 0x00F0A278 Auto
Int Property MorroChargenStage     = 1          Auto

; FalloutNV  VCG00 00102037 — stage 0 IS the whole opening: it moves the player
;            to VCG01PlayerStartMarkerREF 00103E6B, sets the hour, forces the
;            cemetery weather, plays the intro and advances itself to stage 90,
;            which reaches Doc Mitchell's house.
Int Property FalloutNVChargenID     = 0x00102037 Auto
Int Property FalloutNVStartMarkerID = 0x00103E6B Auto
Int Property FalloutNVChargenStage  = 0          Auto

; Fallout3   CG00 0001F388 — stage 0 IS the whole opening, as VCG00's is: it
;            moves the parents and Doctor Li to their marks, sets itself to
;            stage 5 (the birth) and moves the player to CG00PlayerStartMarker
;            00039562.
Int Property Fallout3ChargenID     = 0x0001F388 Auto
Int Property Fallout3StartMarkerID = 0x00039562 Auto
Int Property Fallout3ChargenStage  = 0          Auto

; Vanilla Morrowind has NO chargen quest and NO start marker to move to: the
; opening is object scripts, set running by the TES3 global CharGenState. The
; `Main` start script polls `CharGenState == 1` and launches `CharGen`, which
; positions the player itself (`PositionCell ... "Imperial Prison Ship"`).
; See: docs/commentary/morrowind_runtime.md#vanilla-morrowind-chargen
;
; 🛑 The probe must be a BASE record, like every other game's chargen quest —
; MWJ_A1_1_FindSpymaster, the main quest's opening journal. GetFormFromFile
; resolves a non-persistent REFR only while its cell is loaded, and the
; selector runs from Skyrim's holding cell, so a placed reference answers None
; however the load order looks and the game is never offered.
Int Property MorrowindProbeID        = 0x00192940 Auto
Int Property MorrowindChargenStateID = 0x006472DD Auto

; Arktwend is a TES3 total conversion and starts the same way: its own `Main`
; polls its own CharGenState, and its `CharGen` moves the player to
; "Melee, Monastery". The GLOB is a base record, so it is the probe as well.
Int Property ArktwendChargenStateID  = 0x006472DD Auto

; ---------------------------------------------------------------------------
; Starting equipment: what each game's own player record carried, added and
; worn. The inventory is never cleared.
; See: docs/commentary/tesgameselect.md#starting-equipment
;
;   Oblivion      WristIrons + the Sack Cloth shirt/pants/sandals
;                 (Oblivion.esm NPC_ 00000007).
;   Nehrim        Flickweste / Geschnürte Lederhose / Jägermokassins worn,
;                 plus torch, Tagebuch and the anonymous MQ00 note carried
;                 (Nehrim.esm NPC_ 00000007).
;   Morroblivion  Morrowind_ob.esm does not override the player record, so a
;                 TES4 Morroblivion prisoner inherited Oblivion's set.
;   Morrowind     common shirt / pants / shoes (Morrowind.esm `Player`).
;   Arktwend      the same three plus common_robe_02_rr (Arktwend's own
;                 `Player`); the robe is put on last so it is the one worn.
;   FalloutNV     nothing: VCG00 stage 0 removes the Pip-Boy, the only item
;                 its player record carries.
;   Fallout3      nothing: the player is born, and the CG quests hand out the
;                 vault suit and Pip-Boy as the years pass.
; ---------------------------------------------------------------------------
Int Property OblivionWristIronsID  = 0x000BE335 Auto
Int Property OblivionShirtID       = 0x00027319 Auto
Int Property OblivionPantsID       = 0x00027318 Auto
Int Property OblivionShoesID       = 0x0002731A Auto

Int Property NehrimShirtID         = 0x0002ECAD Auto
Int Property NehrimPantsID         = 0x000229AB Auto
Int Property NehrimShoesID         = 0x0001C82B Auto
Int Property NehrimTorchID         = 0x00000D49 Auto
Int Property NehrimDiaryID         = 0x00000B96 Auto
Int Property NehrimNoteID          = 0x00000AED Auto

Int Property MorrowindShirtID      = 0x007E3DE2 Auto
Int Property MorrowindPantsID      = 0x00A5FBF7 Auto
Int Property MorrowindShoesID      = 0x00C73369 Auto

Int Property ArktwendShirtID       = 0x007E3DE2 Auto
Int Property ArktwendPantsID       = 0x00A5FBF7 Auto
Int Property ArktwendShoesID       = 0x00C73369 Auto
Int Property ArktwendRobeID        = 0x00B75B56 Auto

; ---------------------------------------------------------------------------
; The new-game prompt. A MESG's buttons are fixed at authoring time, so each
; converted game's button carries a GetGlobalValue(<its Has global>) == 1
; condition (vanilla dunMiddenNamesMenuMSG does exactly this). Hidden buttons
; do NOT renumber the rest — Show() returns the button's own index — so the
; returned index is the GAME_* id. The DESC prologue cannot be conditioned, so
; there is one variant per installed set: entry [installedMask] of Menus.
; ---------------------------------------------------------------------------
FormList Property Menus Auto

GlobalVariable Property HasSkyrim       Auto
GlobalVariable Property HasOblivion     Auto
GlobalVariable Property HasMorrowind    Auto
GlobalVariable Property HasMorroblivion Auto
GlobalVariable Property HasNehrim       Auto
GlobalVariable Property HasArktwend     Auto
GlobalVariable Property HasFalloutNV    Auto
GlobalVariable Property HasFallout3     Auto

; Set true the moment the prompt has been shown, so a second entry (quest
; restart, re-add on an existing save, a stray SetStage) can never re-ask.
Bool Property HasRun = false Auto Conditional

; The game the new game began with, as a GAME_* id.
Int Property ChosenGame = 0 Auto Conditional

; True from the moment the prompt is shown until the takeover has started the
; chosen game. ChosenGame reads Skyrim (0) meanwhile, so nothing may take it
; as the answer yet.
Bool Property Selecting = false Auto

; Game identifiers, in the button order the MESGs declare.
Int Property GAME_SKYRIM       = 0 AutoReadOnly
Int Property GAME_OBLIVION     = 1 AutoReadOnly
Int Property GAME_MORROWIND    = 2 AutoReadOnly
Int Property GAME_MORROBLIVION = 3 AutoReadOnly
Int Property GAME_NEHRIM       = 4 AutoReadOnly
Int Property GAME_ARKTWEND     = 5 AutoReadOnly
Int Property GAME_FALLOUTNV    = 6 AutoReadOnly
Int Property GAME_FALLOUT3     = 7 AutoReadOnly
Int Property GAME_COUNT        = 8 AutoReadOnly

; The GAME_* numbering this save was written with. Saves from before the
; reorder load with 0 and are renumbered once by MigrateIds().
; See: docs/commentary/tesgameselect.md#id-migration
Int Property IdVersion  = 0 Auto
Int Property ID_VERSION = 1 AutoReadOnly

; Number of games offered, counting Skyrim. 1 means "Skyrim only" — no prompt.
Int gameCount

; Bitmask of the installed gated games: bit 0 Oblivion, 1 Morrowind,
; 2 Morroblivion, 3 Nehrim, 4 Arktwend, 5 FalloutNV, 6 Fallout3.
Int installedMask

; ---------------------------------------------------------------------------
; Selection: show the prompt and record the choice. Called ONLY from the MQ101
; stage-0 takeover, which runs exactly once per new game.
; ---------------------------------------------------------------------------
Function RunSelection()
  If HasRun
    Return
  EndIf
  HasRun = true
  Selecting = true
  IdVersion = ID_VERSION

  DetectInstalledGames()
  If gameCount <= 1
    ChosenGame = GAME_SKYRIM
    Return
  EndIf

  Int game = (Menus.GetAt(installedMask) as Message).Show()
  ; A mod-added button or a cancelled menu is treated as Skyrim, the safe
  ; direction: it leaves the vanilla start intact.
  If game < GAME_OBLIVION || game >= GAME_COUNT
    game = GAME_SKYRIM
  EndIf
  ChosenGame = game
EndFunction

Bool Function ChoseSkyrim()
  Return ChosenGame == GAME_SKYRIM
EndFunction

; Renumber a save written before the reorder (Oblivion 1, Morroblivion 2,
; Nehrim 3, FalloutNV 4, Morrowind 5, Arktwend 6).
Function MigrateIds()
  If IdVersion == ID_VERSION
    Return
  EndIf
  If HasRun
    Int[] renumbered = new Int[7]
    renumbered[0] = GAME_SKYRIM
    renumbered[1] = GAME_OBLIVION
    renumbered[2] = GAME_MORROBLIVION
    renumbered[3] = GAME_NEHRIM
    renumbered[4] = GAME_FALLOUTNV
    renumbered[5] = GAME_MORROWIND
    renumbered[6] = GAME_ARKTWEND
    If ChosenGame >= 0 && ChosenGame < GAME_COUNT
      ChosenGame = renumbered[ChosenGame]
    EndIf
  EndIf
  IdVersion = ID_VERSION
EndFunction

; ---------------------------------------------------------------------------
; Openings that start themselves. Skyrim starts every Start-Game-Enabled quest
; of every loaded plugin on every new game, and Nehrim marks its opening that
; way: Charactergen moves the player into Nehrim's start cave within about half
; a second, and Nehrim's player script starts MQ00 at stage 1. The player
; script quest is held first — stopping a quest cancels its aliases' polling —
; so nothing restarts MQ00 once it is reset. BeginNehrim restarts all three.
; See: docs/commentary/tesgameselect.md#opening-hold
; ---------------------------------------------------------------------------

; Before the choice: only what would move the player. MQ00 is left alone, as
; stopping a quest already in the journal shows it failing, and Nehrim may
; well be the choice.
Function HoldOpeningMovers()
  HoldQuest(NehrimPlayerScriptsID, NehrimPlugin, false)
  HoldQuest(NehrimChargenID, NehrimPlugin, true)
EndFunction

; Nehrim is not being played: its whole opening waits, MQ00 included. Run once
; another game is chosen, and on every load until Nehrim is begun.
Function HoldSelfStartingOpenings()
  HoldOpeningMovers()
  HoldQuest(NehrimMainQuestID, NehrimPlugin, true)
EndFunction

; After the choice: the movers again (a quest started after MQ101 was not yet
; running the first time), and MQ00 too unless Nehrim is the game begun.
Function HoldOpeningsFor(Int game)
  If game == GAME_NEHRIM
    HoldOpeningMovers()
  Else
    HoldSelfStartingOpenings()
  EndIf
EndFunction

; Reset() before Stop(): Reset does nothing on a quest that is already stopped.
; Resetting undoes whatever stage already ran, journal entries included; the
; player-script quest has no stages and is only stopped.
Function HoldQuest(Int formID, String plugin, Bool reset)
  Quest q = GetQuestFrom(formID, plugin)
  If q != None && q.IsRunning()
    If reset
      q.Reset()
    EndIf
    q.Stop()
    Debug.Trace("[TESGameSelect] held " + q + " from " + plugin + " until chosen")
  EndIf
EndFunction

; ---------------------------------------------------------------------------
; Starting a game. BeginChosenGame is the new-game path: if the chosen game
; turns out broken it resets ChosenGame to Skyrim and the takeover runs the
; vanilla opening instead. BeginGame is shared with the travel scroll, which
; skips the race menu because the character already exists.
; ---------------------------------------------------------------------------
Function BeginChosenGame()
  If !BeginGame(ChosenGame)
    Debug.Trace("[TESGameSelect] game " + ChosenGame + " could not start; resuming Skyrim")
    ChosenGame = GAME_SKYRIM
    Return
  EndIf

  ; The TES4 engine popped the race menu (with the name prompt) on every new
  ; game; Skyrim's only shows it when a script asks. The Fallouts and the TES3
  ; games show their own from inside their openings (Doc Mitchell's
  ; reflectron, Doctor Li's gene projection, the census office), so asking
  ; here too would put one up before any of them had spoken.
  If ChosenGame == GAME_OBLIVION || ChosenGame == GAME_MORROBLIVION \
     || ChosenGame == GAME_NEHRIM
    Utility.Wait(0.5)
    Game.ShowRaceMenu()
  EndIf
EndFunction

; Start one converted game; false when its plugin or entry point is missing.
Bool Function BeginGame(Int game)
  If game == GAME_OBLIVION
    Return BeginOblivion()
  ElseIf game == GAME_MORROWIND
    Return BeginMorrowind()
  ElseIf game == GAME_MORROBLIVION
    Return BeginMorroblivion()
  ElseIf game == GAME_NEHRIM
    Return BeginNehrim()
  ElseIf game == GAME_ARKTWEND
    Return BeginArktwend()
  ElseIf game == GAME_FALLOUTNV
    Return BeginFalloutNV()
  ElseIf game == GAME_FALLOUT3
    Return BeginFallout3()
  EndIf
  Return false
EndFunction

; ---------------------------------------------------------------------------
; Detection
; ---------------------------------------------------------------------------
Function DetectInstalledGames()
  gameCount = 0
  installedMask = 0

  ; Skyrim is always available and owns no mask bit: its line is unconditional.
  SetGate(HasSkyrim, true, 0)
  SetGate(HasOblivion, IsPluginPresent(OblivionPlugin, OblivionChargenID), 1)
  SetGate(HasMorrowind, IsPluginPresent(MorrowindPlugin, MorrowindProbeID), 2)
  SetGate(HasMorroblivion, \
          IsPluginPresent(MorroblivionPlugin, MorroChargenID), 4)
  SetGate(HasNehrim, IsPluginPresent(NehrimPlugin, NehrimChargenID), 8)
  SetGate(HasArktwend, \
          IsPluginPresent(ArktwendPlugin, ArktwendChargenStateID), 16)
  SetGate(HasFalloutNV, \
          IsPluginPresent(FalloutNVPlugin, FalloutNVChargenID), 32)
  SetGate(HasFallout3, \
          IsPluginPresent(Fallout3Plugin, Fallout3ChargenID), 64)

  ; A menu that never appeared, or appeared with the wrong buttons, is ALWAYS
  ; this pass: gameCount 1 means nothing was detected.
  Debug.Trace("[TESGameSelect] detected " + gameCount + " game(s), mask " \
              + installedMask)
EndFunction

Function SetGate(GlobalVariable gate, Bool present, Int maskBit)
  ; The global drives that game's button conditions: 1 shows it, 0 hides it.
  If gate != None
    If present
      gate.SetValue(1.0)
    Else
      gate.SetValue(0.0)
    EndIf
  EndIf
  If present
    gameCount += 1
    installedMask += maskBit
  EndIf
EndFunction

Bool Function IsPluginPresent(String plugin, Int probeID)
  ; GetFormFromFile returns None when the file is not in the load order, so a
  ; successful lookup of a form we know that file defines proves it is loaded.
  Bool found = Game.GetFormFromFile(probeID, plugin) != None
  If !found
    Debug.Trace("[TESGameSelect] " + plugin + " not found (probe " \
                + probeID + ")")
  EndIf
  Return found
EndFunction

; ---------------------------------------------------------------------------
; Per-game handoff. Each converted game's opening owns itself: we dress the
; player, move them to that game's start marker, and set the stage its own
; author wrote as "the game begins here" — then get out of the way.
; ---------------------------------------------------------------------------
Bool Function BeginOblivion()
  Quest chargen = GetQuestFrom(OblivionChargenID, OblivionPlugin)
  If chargen == None
    Return false
  EndIf
  WearOblivionPrisonerSet()
  HandOff(chargen, OblivionChargenStage, \
          GetRefFrom(OblivionStartMarkerID, OblivionPlugin))
  Return true
EndFunction

Bool Function BeginMorroblivion()
  Quest chargen = GetQuestFrom(MorroChargenID, MorroblivionPlugin)
  If chargen == None
    Return false
  EndIf
  WearOblivionPrisonerSet()
  HandOff(chargen, MorroChargenStage, \
          GetRefFrom(MorroStartMarkerID, MorroblivionPlugin))
  Return true
EndFunction

Function WearOblivionPrisonerSet()
  WearFrom(OblivionPlugin, OblivionShirtID)
  WearFrom(OblivionPlugin, OblivionPantsID)
  WearFrom(OblivionPlugin, OblivionShoesID)
  WearFrom(OblivionPlugin, OblivionWristIronsID)
EndFunction

Bool Function BeginNehrim()
  Quest chargen = GetQuestFrom(NehrimChargenID, NehrimPlugin)
  If chargen == None
    Return false
  EndIf
  WearFrom(NehrimPlugin, NehrimShirtID)
  WearFrom(NehrimPlugin, NehrimPantsID)
  WearFrom(NehrimPlugin, NehrimShoesID)
  CarryFrom(NehrimPlugin, NehrimTorchID)
  CarryFrom(NehrimPlugin, NehrimDiaryID)
  CarryFrom(NehrimPlugin, NehrimNoteID)
  HandOff(chargen, NehrimChargenStage, \
          GetRefFrom(NehrimStartMarkerID, NehrimPlugin))

  ; MQ00 drives Nehrim's intro; its stage 2 stops Charactergen and hands the
  ; controls back. Nehrim's player script sets stage 1 only ONCE, and it may
  ; have spent that before HoldSelfStartingOpenings reset the quest, so the
  ; stage is set here. Setting a done stage again does nothing.
  Quest mq00 = GetQuestFrom(NehrimMainQuestID, NehrimPlugin)
  If mq00 != None
    If !mq00.IsRunning()
      mq00.Start()
    EndIf
    If mq00.GetStage() < NehrimMainQuestStage
      mq00.SetStage(NehrimMainQuestStage)
    EndIf
  EndIf
  Quest playerScripts = GetQuestFrom(NehrimPlayerScriptsID, NehrimPlugin)
  If playerScripts != None && !playerScripts.IsRunning()
    playerScripts.Start()
  EndIf
  Return true
EndFunction

Bool Function BeginFalloutNV()
  Quest chargen = GetQuestFrom(FalloutNVChargenID, FalloutNVPlugin)
  If chargen == None
    Return false
  EndIf
  HandOff(chargen, FalloutNVChargenStage, \
          GetRefFrom(FalloutNVStartMarkerID, FalloutNVPlugin))
  Return true
EndFunction

Bool Function BeginFallout3()
  Quest chargen = GetQuestFrom(Fallout3ChargenID, Fallout3Plugin)
  If chargen == None
    Return false
  EndIf
  HandOff(chargen, Fallout3ChargenStage, \
          GetRefFrom(Fallout3StartMarkerID, Fallout3Plugin))
  Return true
EndFunction

Bool Function BeginMorrowind()
  If !BeginTes3(MorrowindPlugin, MorrowindChargenStateID)
    Return false
  EndIf
  WearFrom(MorrowindPlugin, MorrowindShirtID)
  WearFrom(MorrowindPlugin, MorrowindPantsID)
  WearFrom(MorrowindPlugin, MorrowindShoesID)
  Return true
EndFunction

Bool Function BeginArktwend()
  If !BeginTes3(ArktwendPlugin, ArktwendChargenStateID)
    Return false
  EndIf
  WearFrom(ArktwendPlugin, ArktwendShirtID)
  WearFrom(ArktwendPlugin, ArktwendPantsID)
  WearFrom(ArktwendPlugin, ArktwendShoesID)
  WearFrom(ArktwendPlugin, ArktwendRobeID)
  Return true
EndFunction

; A TES3 game (vanilla Morrowind, Arktwend) has no chargen quest: setting its
; CharGenState global to 1 is the whole start. `Main` then launches `CharGen`,
; which positions the player itself, so no marker is moved to and no stage is
; set. MorrowindRuntime mirrors the GLOB back into its own global space each
; tick, so a write here reaches the scripts polling it.
; See: docs/commentary/morrowind_runtime.md#vanilla-morrowind-chargen
Bool Function BeginTes3(String plugin, Int chargenStateID)
  GlobalVariable chargen = \
      Game.GetFormFromFile(chargenStateID, plugin) as GlobalVariable
  If chargen == None
    Return false
  EndIf
  chargen.SetValue(1.0)
  Debug.Trace("[TESGameSelect] " + plugin + " CharGenState " + chargen \
              + " set to 1")
  Return true
EndFunction

Quest Function GetQuestFrom(Int formID, String plugin)
  Return Game.GetFormFromFile(formID, plugin) as Quest
EndFunction

ObjectReference Function GetRefFrom(Int formID, String plugin)
  Return Game.GetFormFromFile(formID, plugin) as ObjectReference
EndFunction

Function WearFrom(String plugin, Int formID)
  Form item = Game.GetFormFromFile(formID, plugin)
  If item != None
    Game.GetPlayer().AddItem(item, 1, true)
    Game.GetPlayer().EquipItem(item, false, true)
  EndIf
EndFunction

Function CarryFrom(String plugin, Int formID)
  Form item = Game.GetFormFromFile(formID, plugin)
  If item != None
    Game.GetPlayer().AddItem(item, 1, true)
  EndIf
EndFunction

Function HandOff(Quest chargen, Int stage, ObjectReference marker)
  ; Move first so the destination cell loads while the quest spins up. Some
  ; chargen stage scripts move the player to the same marker themselves — a
  ; redundant MoveTo is harmless — but Morroblivion's does not.
  Actor player = Game.GetPlayer()
  If marker != None
    player.MoveTo(marker)
  EndIf

  ; Let the arrival cell finish loading before the game's opening runs on it.
  Int guard = 0
  While !player.Is3DLoaded() && guard < 200
    Utility.Wait(0.1)
    guard += 1
  EndWhile

  If !chargen.IsRunning()
    chargen.Start()
  EndIf
  chargen.SetStage(stage)
EndFunction
