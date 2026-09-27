ScriptName FalloutRules_Player extends ReferenceAlias
{On the player: tells a Fallout game's character rules about every load.
See docs/commentary/character_rules.md#fallout}

FalloutRules_Main Property Rules Auto

Event OnPlayerLoadGame()
	Rules.Loaded()
EndEvent
