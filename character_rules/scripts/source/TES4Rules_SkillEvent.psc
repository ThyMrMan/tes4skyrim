ScriptName TES4Rules_SkillEvent extends Quest
{Started by the Story Manager on each skill increase while this character's
rules are on. It counts nothing itself: the rules compare every skill with
their snapshot, because one event can carry several levels and an increase
that arrives while this quest runs gets no event. Then it stops, so the next
increase can start it again. See docs/commentary/character_rules.md}

TES4Rules_Main Property Rules Auto

Event OnStoryIncreaseSkill(String asSkill)
	Rules.Recount()
	Stop()
EndEvent
