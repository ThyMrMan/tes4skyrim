ScriptName TES4_StagePackageAlias extends ReferenceAlias Hidden
{A converted quest alias carrying the quest's AI packages. Oblivion re-checked
an actor's packages on its own once a stage it was gated on was set; Skyrim
only does on EvaluatePackage. TES4Polyfill.StageSet sends this quest's event
after every converted SetStage, and each alias re-checks its own actor on its
own thread, so the caller never waits. The re-check waits until no
conversation has been open for about a second, as the source games paused the
world for one: a package switched mid-talk walks its speaker out of it, and a
force greet opened as another talk closes spends its line outside the menu. A run-once package that finishes adds
the actor to its faction, which its condition tests, so the next package runs.
See docs/commentary/script_convert.md#setstage-re-evaluates-alias-packages
See docs/commentary/tes5_import_package.md#run-once-quest-packages}

Form[] Property RunOncePackages Auto
Form[] Property RunOnceFactions Auto

Event OnInit()
  RegisterForModEvent(TES4Polyfill.StageEventName(GetOwningQuest()), "OnTES4StageSet")
EndEvent

Event OnTES4StageSet(String asEventName, String asArg, Float afArg, Form akSender)
  Recheck()
EndEvent

Event OnPackageEnd(Package akOldPackage)
  If !RunOncePackages
    Return
  EndIf
  Int i = RunOncePackages.Find(akOldPackage)
  Actor who = GetActorReference()
  If i >= 0 && who
    who.AddToFaction(RunOnceFactions[i] as Faction)
    Recheck()
  EndIf
EndEvent

Function Recheck()
  Actor who = GetActorReference()
  Int quiet = 0
  While who && quiet < 2
    If who.IsInDialogueWithPlayer() || UI.IsMenuOpen("Dialogue Menu")
      quiet = 0
    Else
      quiet += 1
    EndIf
    Utility.Wait(0.5)
  EndWhile
  If who
    who.EvaluatePackage()
  EndIf
EndFunction
