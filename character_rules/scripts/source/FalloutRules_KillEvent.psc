ScriptName FalloutRules_KillEvent extends Quest
{Started by the Story Manager on a kill while this character's rules are on.
It stops first, so the next kill finds it free, then hands the kill to the
rules; the node lists several of these for kills close together.
See docs/commentary/character_rules.md#fallout}

FalloutRules_Main Property Rules Auto

Event OnStoryKillActor(ObjectReference akVictim, ObjectReference akKiller, Location akLocation, Int aiCrimeStatus, Int aiRelationshipRank)
	Stop()
	Rules.NoteKill(akVictim as Actor, akKiller as Actor)
EndEvent
