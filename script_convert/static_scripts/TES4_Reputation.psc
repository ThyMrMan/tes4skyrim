ScriptName TES4_Reputation Hidden
{FO3/FNV reputation. A reputation is a FormList of its globals: infamy (kind 0),
fame (kind 1), its mixed, good and bad threshold (axis 0-2 at 2 + axis), then
its maximum. Changing the points re-derives the title, which conditions read.
See: docs/commentary/tes5_import_character_data.md#fallout-reputation}

; A reputation's list slot for points of one kind: fame for 1, else infamy.
Int Function Slot(Int kind) global
  If kind == 1
    Return 1
  EndIf
  Return 0
EndFunction

; The points an AddReputation value gives: 1-5 are Fallout's bumps, anything else as written.
Float Function Bump(Float amount) global
  If amount == 1.0
    Return 1.0
  ElseIf amount == 2.0
    Return 2.0
  ElseIf amount == 3.0
    Return 4.0
  ElseIf amount == 4.0
    Return 7.0
  ElseIf amount == 5.0
    Return 12.0
  EndIf
  Return amount
EndFunction

Float Function Points(FormList rep, Int kind) global
  If !rep
    Return 0.0
  EndIf
  Return (rep.GetAt(Slot(kind)) as GlobalVariable).GetValue()
EndFunction

Float Function Pct(FormList rep, Int kind) global
  If !rep
    Return 0.0
  EndIf
  Float top = (rep.GetAt(5) as GlobalVariable).GetValue()
  If top <= 0.0
    Return 0.0
  EndIf
  Return Points(rep, kind) * 100.0 / top
EndFunction

Int Function Threshold(FormList rep, Int axis) global
  If !rep || axis < 0 || axis > 2
    Return 0
  EndIf
  Return (rep.GetAt(2 + axis) as GlobalVariable).GetValueInt()
EndFunction

Function Set(FormList rep, Int kind, Float value) global
  If !rep
    Return
  EndIf
  If value < 0.0
    value = 0.0
  EndIf
  (rep.GetAt(Slot(kind)) as GlobalVariable).SetValue(value)
  Refresh(rep)
EndFunction

Function Add(FormList rep, Int kind, Float amount) global
  Set(rep, kind, Points(rep, kind) + Bump(amount))
EndFunction

Function Remove(FormList rep, Int kind, Float amount) global
  Set(rep, kind, Points(rep, kind) - Bump(amount))
EndFunction

Function AddExact(FormList rep, Int kind, Float amount) global
  Set(rep, kind, Points(rep, kind) + amount)
EndFunction

Function RemoveExact(FormList rep, Int kind, Float amount) global
  Set(rep, kind, Points(rep, kind) - amount)
EndFunction

; A kind's range 0-3: below 15% of the maximum, below half, below the maximum, at or above it.
Int Function Range(Float points, Float top) global
  If points < Math.Ceiling(top * 0.15)
    Return 0
  ElseIf points < Math.Ceiling(top * 0.5)
    Return 1
  ElseIf points < top
    Return 2
  EndIf
  Return 3
EndFunction

; The title of a fame and an infamy range, as axis * 10 + threshold (axis 0 mixed, 1 good, 2 bad; 0 is Neutral).
Int Function Title(Int fame, Int infamy) global
  Int[] titles = new Int[16]
  titles[1] = 24
  titles[2] = 25
  titles[3] = 26
  titles[4] = 14
  titles[5] = 3
  titles[6] = 22
  titles[7] = 23
  titles[8] = 15
  titles[9] = 12
  titles[10] = 4
  titles[11] = 2
  titles[12] = 16
  titles[13] = 13
  titles[14] = 2
  titles[15] = 5
  Return titles[fame * 4 + infamy]
EndFunction

Function Refresh(FormList rep) global
  Float top = (rep.GetAt(5) as GlobalVariable).GetValue()
  Int title = Title(Range(Points(rep, 1), top), Range(Points(rep, 0), top))
  Int axis = 0
  While axis < 3
    Int value = 0
    If title == 0
      value = 1
    ElseIf title / 10 == axis
      value = title % 10
    EndIf
    (rep.GetAt(2 + axis) as GlobalVariable).SetValue(value as Float)
    axis += 1
  EndWhile
EndFunction
