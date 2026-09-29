ScriptName TES4_ConfidenceFlee extends ActiveMagicEffect Hidden
{Effect of the TES4ConfidenceFlee ability. Each of its effects starts once the
owner's health falls under the line its flee margin (rank in
TES4FleeMarginFaction) sets and ends when the owner heals above it; either way
TES4Polyfill.ApplyConfidence re-reads margin and health and picks Cowardly or
Foolhardy. See docs/commentary/tes5_import_actors.md#flee-margin}

Faction Property TES4FleeMarginFaction Auto
GlobalVariable Property TES4FleeHealthScale Auto

Event OnEffectStart(Actor akTarget, Actor akCaster)
  TES4Polyfill.ApplyConfidence(akTarget, TES4FleeMarginFaction, TES4FleeHealthScale)
EndEvent

Event OnEffectFinish(Actor akTarget, Actor akCaster)
  TES4Polyfill.ApplyConfidence(akTarget, TES4FleeMarginFaction, TES4FleeHealthScale)
EndEvent
