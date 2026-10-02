ScriptName TES4_DialoguePause extends ReferenceAlias Hidden
{FO3/FNV dialogue paused the world; Skyrim's runs on. While the player talks to
one of this plugin's actors, every other living actor in the player's cell has
its AI turned off, so nobody walks up or attacks mid-conversation, and it is
turned back on when the menu closes, or at load if a save caught it frozen.
An actor whose AI was already off is left alone, and so is one running a force
greet, which must stay free to open its own talk. The speaker itself is held in
place (restrained, which still lets it talk; converted scripts restrain with
SetDontMove, so none of ours is restrained already) so a package change cannot
walk it off mid-line. TES4DialoguePause (1 = on)
switches it per game.
See: docs/commentary/tes5_import_dialogue.md#fallout-dialogue-pause}

GlobalVariable Property TES4DialoguePause Auto

Actor[] TES4Frozen
Int TES4FrozenCount
Actor TES4Held

Event OnInit()
  RegisterForMenu("Dialogue Menu")
EndEvent

Event OnPlayerLoadGame()
  TES4Thaw()
  RegisterForMenu("Dialogue Menu")
EndEvent

Event OnMenuOpen(String asMenuName)
  Int tries = 0
  While TES4DialoguePause.GetValue() > 0 && tries < 3 && !TES4Freeze()
    Utility.Wait(0.1)
    tries += 1
  EndWhile
EndEvent

Event OnMenuClose(String asMenuName)
  TES4Thaw()
EndEvent

; Whether `akForm` comes from the plugin that owns this quest.
Bool Function TES4Ours(Form akForm)
  Return akForm && Math.RightShift(akForm.GetFormID(), 24) == Math.RightShift(GetOwningQuest().GetFormID(), 24)
EndFunction

; Whether the actor is running a force greet (a package on Skyrim's ForceGreet template).
Bool Function TES4Greeting(Actor akActor)
  Package current = akActor.GetCurrentPackage()
  Return current && current.GetTemplate() == Game.GetForm(0x0003C1C4)
EndFunction

; Freeze the others once the speaker is known; False while no actor in the cell is talking yet.
Bool Function TES4Freeze()
  Actor player = Game.GetPlayer()
  Cell here = player.GetParentCell()
  If !here || !UI.IsMenuOpen("Dialogue Menu")
    Return true
  EndIf
  Actor[] found = new Actor[128]
  Actor speaker = None
  Int count = 0
  Int n = here.GetNumRefs(62)
  Int i = 0
  While i < n && count < 128
    Actor someone = here.GetNthRef(i, 62) as Actor
    If someone && someone != player
      If someone.IsInDialogueWithPlayer()
        speaker = someone
      ElseIf !someone.IsDead() && someone.IsAIEnabled() && !TES4Greeting(someone)
        found[count] = someone
        count += 1
      EndIf
    EndIf
    i += 1
  EndWhile
  If !speaker
    Return false
  ElseIf !(TES4Ours(speaker) || TES4Ours(speaker.GetActorBase()))
    Return true
  EndIf
  speaker.SetRestrained(true)
  TES4Held = speaker
  TES4Frozen = found
  TES4FrozenCount = count
  i = 0
  While i < count
    found[i].EnableAI(false)
    i += 1
  EndWhile
  ; The walk above spans frames: a menu closed meanwhile already ran its thaw.
  If !UI.IsMenuOpen("Dialogue Menu")
    TES4Thaw()
  EndIf
  Return true
EndFunction

Function TES4Thaw()
  If TES4Held
    TES4Held.SetRestrained(false)
    TES4Held = None
  EndIf
  Int i = 0
  While i < TES4FrozenCount
    If TES4Frozen[i]
      TES4Frozen[i].EnableAI(true)
    EndIf
    i += 1
  EndWhile
  TES4FrozenCount = 0
EndFunction
