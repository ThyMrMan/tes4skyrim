ScriptName TESGameSelectTravel extends Quest Conditional
{Threads of Prophecy — travel between the games with the Elder Scroll.

Reading the scroll offers every installed game but the current one: "Begin"
for a game not yet started, which runs that game's normal start, and "Return
to" for one already started, which puts the player back where they left it.

Returning is Morrowind's Mark and Recall in plain Papyrus: a heading marker
dropped at the player holds the cell or worldspace, position and facing, and
MoveTo brings the player back to it. One marker is kept per started game.
See docs/commentary/tesgameselect.md#travel-scroll}

TESGameSelectQuest Property Selector Auto
Quest Property MQ101 Auto

; The travel menu variants: entry [startedMask] labels each started game
; "Return to" and every other one "Begin". See #menu-variants.
FormList Property Menus Auto

; Mirrors CurrentGame for the buttons' conditions, which hide the current game.
GlobalVariable Property CurrentGameGlobal Auto

; XMarkerHeading: a return point keeps the facing as well as the spot.
Static Property ReturnMarker Auto

; Vanilla's own Elder Scroll reading, the forms ElderScrollScript binds on
; DA04ElderScroll: the scroll held in the hand (ElderScrollHandAttachArmor),
; the reading idle (IdleReadElderScroll), IdleStop, the reading visual
; (FXReadElderScrollEffect), the blinding (FXReadScrollsBlindImod) and its
; two sounds (OBJElderScrollBlindIn2D / Out2D).
Armor Property ScrollInHand Auto
Idle Property ReadIdle Auto
Idle Property StopIdle Auto
VisualEffect Property ReadEffect Auto
ImageSpaceModifier Property BlindImod Auto
Sound Property BlindIn Auto
Sound Property BlindOut Auto

; The game the player is in, as a GAME_* id; -1 until the first one begins.
Int Property CurrentGame = -1 Auto Conditional

; 🛑 Never compare an array to None: the compiler emits `cast None -> Bool[]`,
; which the VM rejects ("Cannot cast from None to Bool[]"), and the array
; creation after it then fails too. The flag says whether they exist.
Bool[] started
ObjectReference[] returnPoints
Bool arraysMade = false
Bool busy = false

Event OnInit()
  Sync()
EndEvent

; Bring an older save up to date: renumber its game ids, and count the game it
; began with as started and current. Also run from the Player alias on load.
; Until Nehrim is begun its self-starting opening stays held, which also
; repairs a save whose opening slipped past the new-game hold.
Function Sync()
  If Selector == None
    Return
  EndIf
  Selector.MigrateIds()
  EnsureArrays()
  If CurrentGame < 0 && Selector.HasRun && !Selector.Selecting
    Arrive(Selector.ChosenGame)
  EndIf
  If CurrentGame >= 0 && !started[Selector.GAME_NEHRIM]
    Selector.HoldSelfStartingOpenings()
  EndIf
EndFunction

; One slot per game. A save made before a game was added holds shorter arrays,
; which are copied into full-size ones. `new` takes only a literal, so this
; must equal TESGameSelectQuest.GAME_COUNT.
Int Property GAME_SLOTS = 8 AutoReadOnly

Function EnsureArrays()
  If arraysMade && started.Length >= GAME_SLOTS
    Return
  EndIf
  Bool[] grownStarted = new Bool[8]
  ObjectReference[] grownPoints = new ObjectReference[8]
  If arraysMade
    Int i = 0
    While i < started.Length
      grownStarted[i] = started[i]
      grownPoints[i] = returnPoints[i]
      i += 1
    EndWhile
  EndIf
  started = grownStarted
  returnPoints = grownPoints
  arraysMade = true
EndFunction

; The player is now in `game`, which counts as started from here on.
Function Arrive(Int game)
  EnsureArrays()
  If game < 0 || game >= started.Length
    Return
  EndIf
  started[game] = true
  CurrentGame = game
  If CurrentGameGlobal != None
    CurrentGameGlobal.SetValue(game)
  EndIf
EndFunction

; Bit N set when game N has been started: the travel menu variant to show.
Int Function StartedMask()
  EnsureArrays()
  Int mask = 0
  Int bit = 1
  Int game = 0
  While game < started.Length
    If started[game]
      mask += bit
    EndIf
    bit *= 2
    game += 1
  EndWhile
  Return mask
EndFunction

; ---------------------------------------------------------------------------
; Called by the scroll's OnEquipped (reading a book equips it), as vanilla
; ElderScrollScript is. Utility.Wait does not elapse while a menu is open, so
; the reading plays once the book and inventory have closed.
; ---------------------------------------------------------------------------
Function Open()
  If busy
    Return
  EndIf
  busy = true
  Sync()
  If CanTravel()
    Int pick = ReadScroll()
    If pick >= 0 && pick < Selector.GAME_COUNT && pick != CurrentGame
      TravelTo(pick)
    EndIf
  EndIf
  busy = false
EndFunction

; Vanilla ElderScrollScript.OnEquipped's reading away from the Time-Wound,
; step for step (disassembled from the LE Skyrim - Misc.bsa copy), with the
; travel menu shown where vanilla's reading ends, before IdleStop. Only the
; menu controls are disabled, and only a standing reader is put in first
; person with the scroll in hand.
Int Function ReadScroll()
  Actor player = Game.GetPlayer()
  Game.DisablePlayerControls(false, false, false, false, false, true, false, false, 0)
  If player.GetSitState() == 0
    Game.ForceFirstPerson()
  EndIf
  If player.GetSitState() == 0
    player.EquipItem(ScrollInHand, false, true)
    player.PlayIdle(ReadIdle)
    Utility.Wait(1.05)
  EndIf
  BlindIn.Play(player)
  Utility.Wait(0.5)
  Game.ShakeCamera(None, 0.5, 1.5)
  ReadEffect.Play(player, 8.1)
  BlindImod.Apply(1.0)
  Utility.Wait(1.0)
  Utility.Wait(2.0)

  Selector.DetectInstalledGames()
  CurrentGameGlobal.SetValue(CurrentGame)
  Int pick = (Menus.GetAt(StartedMask()) as Message).Show()

  If player.GetSitState() == 0
    player.PlayIdle(StopIdle)
    player.RemoveItem(ScrollInHand, 1, true)
  EndIf
  Game.EnablePlayerControls(false, false, false, false, false, true, false, false, 0)
  Utility.Wait(1.9)
  BlindOut.Play(player)
  Return pick
EndFunction

; Refused before any game has begun, in combat, and while movement controls
; are off — which also covers every game's opening sequence.
Bool Function CanTravel()
  If CurrentGame < 0
    Return false
  EndIf
  Actor player = Game.GetPlayer()
  If player.IsInCombat() || !Game.IsMovementControlsEnabled()
    Debug.Notification("The threads will not answer now.")
    Return false
  EndIf
  Return true
EndFunction

Function TravelTo(Int game)
  EnsureArrays()
  Actor player = Game.GetPlayer()
  ObjectReference leaving = player.PlaceAtMe(ReturnMarker, 1, true)
  If started[game]
    ObjectReference back = returnPoints[game]
    If back == None
      leaving.Delete()
      Debug.Notification("That thread has no end to return to.")
      Return
    EndIf
    KeepReturnPoint(leaving)
    returnPoints[game] = None
    player.MoveTo(back)
    back.Delete()
  ElseIf BeginGame(game)
    KeepReturnPoint(leaving)
  Else
    leaving.Delete()
    Debug.Notification("That world could not be begun.")
    Return
  EndIf
  Arrive(game)
EndFunction

; The spot the player is leaving becomes the current game's return point.
Function KeepReturnPoint(ObjectReference mark)
  ObjectReference old = returnPoints[CurrentGame]
  If old != None && old != mark
    old.Delete()
  EndIf
  returnPoints[CurrentGame] = mark
EndFunction

; Skyrim begins through MQ101's own opening; every other game through its
; normal start, without the race menu (the character already exists).
Bool Function BeginGame(Int game)
  If game == Selector.GAME_SKYRIM
    TESGameSelectMQ101 opening = MQ101 as TESGameSelectMQ101
    If opening == None
      Return false
    EndIf
    Return opening.BeginSkyrim()
  EndIf
  Return Selector.BeginGame(game)
EndFunction
