ScriptName FalloutRules_CrimeEvent extends Quest
{Started by the Story Manager when a crime is reported and bounty is added,
while this character's rules are on. It stops first, so the next crime finds
it free, then hands the crime to the rules. See
docs/commentary/character_rules.md#fallout-karma-and-infamy}

FalloutRules_Main Property Rules Auto

Event OnStoryCrimeGold(ObjectReference akVictim, ObjectReference akCriminal, Form akFaction, Int aiGoldAmount, Int aiCrime)
	Stop()
	Rules.NoteCrime(akVictim as Actor, akCriminal as Actor, aiCrime)
EndEvent
