ScriptName TES4_TwoStateActivator extends ObjectReference Hidden
{A FO3/FNV activator whose model has Open and Close sequences: a vault gear
door, a switch, a radio. Fallout gave it a door's open state, so default
activation toggles it and GetOpenState/SetOpenState read and set it. Skyrim
does neither for an activator (vanilla scripts one, default2stateActivator), so
this script keeps the state and plays the sequences. The globals are what
converted Fallout scripts call in place of the natives; a terminal's default
activation opens its menu.
See: docs/commentary/script_convert.md#two-state-activators}

Bool Property TES4OpenByDefault = False Auto  ; the placement's Open By Default flag
Int TES4State                            ; GetOpenState numbering: 1 open, 3 closed; 0 not read yet

Event OnActivate(ObjectReference akActionRef)
  If !IsActivationBlocked()
    TES4SetOpen(TES4OpenState() != 1)
  EndIf
EndEvent

Int Function TES4OpenState()
  If TES4State == 0
    TES4State = 3
    If TES4OpenByDefault
      TES4State = 1
    EndIf
  EndIf
  Return TES4State
EndFunction

Function TES4SetOpen(Bool abOpen)
  TES4OpenState()
  If abOpen && TES4State != 1
    TES4State = 1
    PlayAnimation("Open")
  ElseIf !abOpen && TES4State != 3
    TES4State = 3
    PlayAnimation("Close")
  EndIf
EndFunction

; A converted `Activate` asking for default processing: a terminal opens its menu, a two-state activator toggles.
Function DefaultActivate(ObjectReference akTarget, ObjectReference akActionRef) Global
  TES4_Terminal term = akTarget as TES4_Terminal
  TES4_TwoStateActivator twoState = akTarget as TES4_TwoStateActivator
  If term
    term.TES4Open(akActionRef)
  ElseIf twoState
    twoState.TES4SetOpen(twoState.TES4OpenState() != 1)
  Else
    akTarget.Activate(akActionRef, true)
  EndIf
EndFunction

; A converted GetOpenState: the two-state activator's own state, else the native.
Int Function OpenState(ObjectReference akTarget) Global
  TES4_TwoStateActivator twoState = akTarget as TES4_TwoStateActivator
  If twoState
    Return twoState.TES4OpenState()
  EndIf
  Return akTarget.GetOpenState()
EndFunction

; A converted SetOpenState: the two-state activator plays its sequence, else the native.
Function SetOpenState(ObjectReference akTarget, Bool abOpen) Global
  TES4_TwoStateActivator twoState = akTarget as TES4_TwoStateActivator
  If twoState
    twoState.TES4SetOpen(abOpen)
  Else
    akTarget.SetOpen(abOpen)
  EndIf
EndFunction
