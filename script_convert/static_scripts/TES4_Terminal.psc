ScriptName TES4_Terminal extends ObjectReference Hidden
{A converted FO3/FNV terminal. Each menu page is a message whose buttons are
its items (conditions hide the ones the source hid) and whose last button
leaves it. The terminal's generated script extends this one and runs the item
picked (TES4Pick). A locked terminal opens with its password note, or when
the player's Lockpicking reaches 25 per step of hacking difficulty.
See: docs/commentary/script_convert.md#terminals}

Message[] Property TES4Pages Auto        ; every menu page, the terminal's own first
Book Property TES4Password Auto          ; the note that unlocks it (PNAM)
Int Property TES4Difficulty Auto         ; 0 Very Easy to 4 Very Hard; 5 opens only with the password
Bool Property TES4Locked Auto            ; the source terminal starts locked

Bool TES4Opened                          ; this reference was unlocked in play

Event OnActivate(ObjectReference akActionRef)
  If !IsActivationBlocked()
    TES4Open(akActionRef)
  EndIf
EndEvent

Function TES4Open(ObjectReference akActionRef)
  If akActionRef == Game.GetPlayer() && TES4Unlock()
    TES4Run(0)
  EndIf
EndFunction

Bool Function TES4Unlock()
  If !TES4Locked || TES4Opened
    Return true
  EndIf
  Actor player = Game.GetPlayer()
  If TES4Password && player.GetItemCount(TES4Password) > 0
    TES4Opened = true
    Debug.Notification("Password accepted.")
  ElseIf TES4Difficulty < 5 && player.GetActorValue("Lockpicking") >= TES4Difficulty * 25
    TES4Opened = true
    Debug.Notification("Terminal unlocked.")
  ElseIf TES4Difficulty < 5
    Debug.MessageBox("This terminal is locked. Opening it takes its password, or Lockpicking " + TES4Difficulty * 25 + ".")
  Else
    Debug.MessageBox("This terminal is locked. Opening it takes its password.")
  EndIf
  Return TES4Opened
EndFunction

; Show a page until its last button leaves it; an item may open another page (a sub-menu or the next page).
Function TES4Run(Int page)
  Int next = TES4Pick(page, TES4Pages[page].Show())
  While next != -1
    If next >= 0
      TES4Run(next)
    EndIf
    next = TES4Pick(page, TES4Pages[page].Show())
  EndWhile
EndFunction

; The item on `page` the player picked: -1 leaves the page, -2 shows it again, 0 or more opens that page.
Int Function TES4Pick(Int page, Int button)
  Return -1
EndFunction

; Open a note (a book) for reading as the terminal shows it, adding it to the player first when the item says so.
Function TES4Read(Book akNote, Bool abAdd)
  Actor player = Game.GetPlayer()
  If abAdd && player.GetItemCount(akNote) == 0
    player.AddItem(akNote, 1, true)
  EndIf
  Int had = player.GetItemCount(akNote)
  ObjectReference page = player.PlaceAtMe(akNote)
  page.Activate(player)
  Int tries = 0
  While !UI.IsMenuOpen("Book Menu") && tries < 20
    Utility.WaitMenuMode(0.05)
    tries += 1
  EndWhile
  Utility.Wait(0.1)
  If player.GetItemCount(akNote) == had
    page.Delete()
  EndIf
EndFunction
