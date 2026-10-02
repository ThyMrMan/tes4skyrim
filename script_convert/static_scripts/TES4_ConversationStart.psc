ScriptName TES4_ConversationStart extends Package Hidden
{Shared OnBegin fragment of a converted FO3/FNV conversation package: the
package that held its speaker through the conversation starts the scene
that plays the conversation lines (tes5_import/dialogue/conversation_scenes_falloutnv.py).
A scene already playing is left alone, so re-entering the package never
restarts the conversation mid-line. A cast alias left empty, as on a save made
before the scene existed (a running quest never fills a new alias), is filled
with its reference first.}

Scene Property ConversationScene Auto
Int Property SpeakerAlias = -1 Auto
Int Property TargetAlias = -1 Auto
ObjectReference Property SpeakerRef Auto
ObjectReference Property TargetRef Auto

Function Fragment_0(Actor akActor)
  If ConversationScene && !ConversationScene.IsPlaying()
    Quest owner = ConversationScene.GetOwningQuest()
    TES4Cast(owner, SpeakerAlias, SpeakerRef)
    TES4Cast(owner, TargetAlias, TargetRef)
    ConversationScene.Start()
  EndIf
EndFunction

; Fill one cast alias with its reference when it is empty.
Function TES4Cast(Quest akOwner, Int aiAlias, ObjectReference akRef)
  If aiAlias < 0 || !akRef
    Return
  EndIf
  ReferenceAlias cast = akOwner.GetAlias(aiAlias) as ReferenceAlias
  If cast && !cast.GetReference()
    cast.ForceRefTo(akRef)
  EndIf
EndFunction
