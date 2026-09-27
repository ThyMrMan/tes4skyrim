ScriptName TES4Rules_Player extends ReferenceAlias
{On the player: tells the character rules about every load, and about the
weapons, books and spells whose use decides which source skill an increase
belongs to. See docs/commentary/character_rules.md}

TES4Rules_Main Property Rules Auto

Event OnPlayerLoadGame()
	Rules.Loaded()
EndEvent

Event OnObjectEquipped(Form akBaseObject, ObjectReference akReference)
	Rules.NoteEquipped(akBaseObject)
EndEvent

Event OnSpellCast(Form akSpell)
	Rules.NoteCast(akSpell)
EndEvent
