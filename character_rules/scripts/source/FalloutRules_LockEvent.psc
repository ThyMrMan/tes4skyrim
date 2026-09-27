ScriptName FalloutRules_LockEvent extends Quest
{Started by the Story Manager when a lock is picked while this character's
rules are on. It stops first, so the next lock finds it free, then hands the
lock to the rules. See docs/commentary/character_rules.md#fallout}

FalloutRules_Main Property Rules Auto

Event OnStoryPickLock(ObjectReference akActor, ObjectReference akLock)
	Stop()
	Rules.NotePickLock(akActor, akLock)
EndEvent
