ScriptName FalloutRules_Main extends Quest
{A converted Fallout game's character rules for the player: S.P.E.C.I.A.L.,
experience from kills, picked locks and quest rewards, and the level-up with
skill points, for a character who started in that game. Generic across
Fallout games: every number is a property the rules plugin's builder fills
from the game's character data. See docs/commentary/character_rules.md#fallout}

; ---------------------------------------------------------------------------
; Filled by tools/release/make_character_rules_esp.py
; ---------------------------------------------------------------------------

String Property Plugin Auto                 ; the converted game's plugin, e.g. FalloutNV.esm
Int Property GameId Auto                    ; TESGameSelectQuest's id for that game
GlobalVariable Property Active Auto         ; 1 while this character plays by these rules
Keyword Property ActorTypeNPC Auto          ; a person's kill reads the NPC table, anything else the creature one
Message Property SkillMenu Auto             ; the first skills, then "More skills"
Message Property SkillMenuMore Auto         ; the rest, then "Back"
Int Property FirstPageSkills Auto
String[] Property SkyrimSkillNames Auto     ; Skyrim's 18 skill actor values
Int[] Property SkyrimSources Auto           ; per Skyrim skill, three source skills or -1
String[] Property SkillNames Auto           ; the source game's skills
Int[] Property SkillAttribute Auto          ; governing S.P.E.C.I.A.L., 0-6
Float[] Property SkillBase Auto
Int[] Property SpecialGlobals Auto          ; per S.P.E.C.I.A.L. stat, its global in TESGameSelect.esp
Int[] Property SpecialStart Auto            ; the player record's class
Int[] Property TagSkills Auto
Float Property TagSkillBonus Auto
Float Property PrimaryBonusMult Auto        ; a skill gains this per point of its stat
Float Property LuckBonusMult Auto           ; and this per point of Luck, rounded up
Int Property XPBase Auto                    ; XP from level 1 to 2
Int Property XPBumpBase Auto                ; each later level asks this much more
Int Property MaxLevel Auto
Float Property SkillPointsOffset Auto       ; skill points per level: this plus the next times Intelligence
Float Property SkillPointsPerIntelligence Auto
Float Property HealthPerLevel Auto
Int Property TeammateKills Auto             ; 1: a companion's kill counts as the player's
Int[] Property LevelKillCreature Auto       ; each reward table: the tier levels, then the XP per tier
Int[] Property RewardKillCreature Auto
Int[] Property LevelKillNPC Auto
Int[] Property RewardKillNPC Auto
Int[] Property LevelPickLock Auto
Int[] Property RewardPickLock Auto
String Property XPText Auto
String Property LevelText Auto

Int Property INTELLIGENCE = 4 AutoReadOnly
Int Property LUCK = 6 AutoReadOnly
Int Property SOURCES = 3 AutoReadOnly
Int Property LOCK_TIER_STEP = 25 AutoReadOnly         ; Skyrim's lock levels run 1, 25, 50, 75, 100
Float Property SKILL_CAP = 100.0 AutoReadOnly
Float Property POLL_SECONDS = 2.0 AutoReadOnly        ; while the game is still being chosen
Float Property BUSY_SECONDS = 5.0 AutoReadOnly        ; a level-up waits out combat and menus
Int Property SELECTOR_QUEST = 0xA00 AutoReadOnly      ; TESGameSelectQuest in TESGameSelect.esp
String Property SELECTOR = "TESGameSelect.esp" AutoReadOnly
String Property XP_EVENT = "TESCharacterXP" AutoReadOnly

; ---------------------------------------------------------------------------
; Kept with the character
; ---------------------------------------------------------------------------

Bool started = False
Bool settled = False        ; this session: the game is decided and it is not ours
Bool on = False             ; this session: TESRuntime has these rules on
String lastSeen = ""        ; the last TESGameSelect state traced
Int xp = 0
Int level = 1
Float[] skills
Float carry = 0.0           ; a part skill point, kept for the next level
Bool levelling = False

; ---------------------------------------------------------------------------
; Which character plays by these rules
; ---------------------------------------------------------------------------

Event OnInit()
	Debug.Trace("[FalloutRules] " + Plugin + ": rules quest started")
	CheckCharacter()
EndEvent

; Every load starts over: TESRuntime has the rules off, SKSE has dropped the
; mod event registration, and the game is read again from TESGameSelect.
Function Loaded()
	Debug.Trace("[FalloutRules] " + Plugin + ": game loaded")
	settled = False
	on = False
	CheckCharacter(True)
EndFunction

; Whether this character plays by these rules. Until the game is known this
; looks again every few seconds; once the rules run, an update means a
; level-up waited for combat or a menu to end.
Function CheckCharacter(Bool fromLoad = False)
	If settled
		Return
	EndIf
	Int game = ChosenGame(fromLoad)
	If game == -1
		RegisterForSingleUpdate(POLL_SECONDS)
		Return
	ElseIf game != GameId
		Settle(game)
		Return
	EndIf
	If !on
		TurnOn()
	EndIf
	If !started
		Begin()
	EndIf
	CheckLevel()
EndFunction

Event OnUpdate()
	CheckCharacter()
EndEvent

; The game this character began in, or -1 until it is final, or -2 for
; Skyrim's own rules; the same answer TES4Rules_Main.ChosenGame gives.
Int Function ChosenGame(Bool fromLoad)
	TESGameSelectQuest gameSelect = Game.GetFormFromFile(SELECTOR_QUEST, SELECTOR) as TESGameSelectQuest
	If !gameSelect
		Debug.Trace("[FalloutRules] " + Plugin + ": no TESGameSelect quest")
		Return -2
	EndIf
	String seen = "TESGameSelect HasRun " + gameSelect.HasRun + ", Selecting " + gameSelect.Selecting + ", ChosenGame " + gameSelect.ChosenGame + ", ids " + gameSelect.IdVersion + ", from load " + fromLoad
	If seen != lastSeen
		lastSeen = seen
		Debug.Trace("[FalloutRules] " + Plugin + ": " + seen)
	EndIf
	If gameSelect.HasRun && !gameSelect.Selecting && gameSelect.IdVersion == gameSelect.ID_VERSION
		Return gameSelect.ChosenGame
	ElseIf fromLoad && !gameSelect.HasRun
		Return -2
	EndIf
	Return -1
EndFunction

; Not this game's character: Skyrim's own rules, and nothing more to listen for.
Function Settle(Int game)
	Debug.Trace("[FalloutRules] " + Plugin + ": game " + game + " chosen, not this one; Skyrim's rules")
	settled = True
	If on
		SendModEvent("TESCharacterRules", "", 0.0)
		on = False
	EndIf
	Active.SetValue(0)
	UnregisterForModEvent(XP_EVENT)
EndFunction

; Every load: hand Skyrim's own leveling to TESRuntime and listen again.
Function TurnOn()
	Debug.Trace("[FalloutRules] " + Plugin + ": this game's character; Skyrim's leveling handed to TESRuntime")
	on = True
	Active.SetValue(1)
	RegisterForModEvent(XP_EVENT, "OnRewardXP")
	SendModEvent("TESCharacterRules", Plugin, 1.0)
EndFunction

; ---------------------------------------------------------------------------
; Character creation: S.P.E.C.I.A.L. and skills
; ---------------------------------------------------------------------------

; S.P.E.C.I.A.L. from the player record's class, each skill from its stat and
; Luck, tag skills raised, and experience at the player's current level.
Function Begin()
	Int s = 0
	While s < SpecialStart.Length
		SpecialGlobal(s).SetValue(SpecialStart[s])
		s += 1
	EndWhile
	level = Game.GetPlayer().GetLevel()
	xp = XPForLevel(level)
	StartSkills()
	started = True
	Debug.Trace("[FalloutRules] " + Plugin + ": level " + level + ", " + xp + " XP; the rules begin")
EndFunction

; A skill's start is its base, plus its stat times the primary multiplier,
; plus Luck times the luck multiplier rounded up, plus the tag bonus. A
; Skyrim skill already higher than every source it carries raises them.
Function StartSkills()
	skills = Utility.CreateFloatArray(SkillNames.Length)
	Float luckBonus = Math.Ceiling(LuckBonusMult * SpecialGlobal(LUCK).GetValue())
	Int s = 0
	While s < SkillNames.Length
		skills[s] = SkillBase[s] + luckBonus
		If SkillAttribute[s] >= 0
			skills[s] = skills[s] + Math.Floor(PrimaryBonusMult * SpecialGlobal(SkillAttribute[s]).GetValue())
		EndIf
		s += 1
	EndWhile
	s = 0
	While s < TagSkills.Length
		skills[TagSkills[s]] = skills[TagSkills[s]] + TagSkillBonus
		s += 1
	EndWhile
	Actor player = Game.GetPlayer()
	Int k = 0
	While k < SkyrimSkillNames.Length
		Float current = player.GetBaseActorValue(SkyrimSkillNames[k])
		If BestSource(k) >= 0 && current > BestSource(k)
			RaiseSources(k, current)
		EndIf
		k += 1
	EndWhile
	PushSkills()
EndFunction

; The highest of the source skills a Skyrim skill carries, or -1 for none.
Float Function BestSource(Int skyrimSkill)
	Float best = -1.0
	Int i = skyrimSkill * SOURCES
	While i < skyrimSkill * SOURCES + SOURCES
		If SkyrimSources[i] >= 0 && skills[SkyrimSources[i]] > best
			best = skills[SkyrimSources[i]]
		EndIf
		i += 1
	EndWhile
	Return best
EndFunction

Function RaiseSources(Int skyrimSkill, Float value)
	Int i = skyrimSkill * SOURCES
	While i < skyrimSkill * SOURCES + SOURCES
		If SkyrimSources[i] >= 0 && skills[SkyrimSources[i]] < value
			skills[SkyrimSources[i]] = value
		EndIf
		i += 1
	EndWhile
EndFunction

; Each Skyrim skill carries the best of its source skills: TESRuntime keeps
; it from rising by use, so this is the only thing that moves it.
Function PushSkills()
	Actor player = Game.GetPlayer()
	Int k = 0
	While k < SkyrimSkillNames.Length
		Float best = BestSource(k)
		If best >= 0.0
			player.SetActorValue(SkyrimSkillNames[k], best)
		EndIf
		k += 1
	EndWhile
EndFunction

GlobalVariable Function SpecialGlobal(Int stat)
	Return Game.GetFormFromFile(SpecialGlobals[stat], SELECTOR) as GlobalVariable
EndFunction

; ---------------------------------------------------------------------------
; Experience: quest rewards, kills and picked locks
; ---------------------------------------------------------------------------

; Converted RewardXP sends TESCharacterXP with the amount.
Event OnRewardXP(String eventName, String strArg, Float numArg, Form sender)
	AddXP(numArg as Int)
EndEvent

; A kill by the player, or by a companion where the game counts those: the
; victim's level picks the tier, from the NPC table for a person.
Function NoteKill(Actor victim, Actor killer)
	If !started || settled || !victim
		Return
	EndIf
	If killer != Game.GetPlayer() && !(TeammateKills == 1 && killer && killer.IsPlayerTeammate())
		Return
	EndIf
	If victim.HasKeyword(ActorTypeNPC)
		AddXP(Reward(LevelKillNPC, RewardKillNPC, victim.GetLevel()))
	Else
		AddXP(Reward(LevelKillCreature, RewardKillCreature, victim.GetLevel()))
	EndIf
EndFunction

; A lock the player picked: its tier, 0 for Novice to 4 for Master.
Function NotePickLock(ObjectReference picker, ObjectReference lockObject)
	If !started || settled || picker != Game.GetPlayer() || !lockObject
		Return
	EndIf
	Int tier = lockObject.GetLockLevel() / LOCK_TIER_STEP
	If tier > LevelPickLock.Length - 1
		tier = LevelPickLock.Length - 1
	EndIf
	AddXP(Reward(LevelPickLock, RewardPickLock, tier))
EndFunction

; The engine's lookup: the reward of the first tier whose level the value
; does not pass, or the last tier's.
Int Function Reward(Int[] tierLevels, Int[] rewards, Int value)
	Int i = 0
	While i < tierLevels.Length
		If value <= tierLevels[i]
			Return rewards[i]
		EndIf
		i += 1
	EndWhile
	Return rewards[rewards.Length - 1]
EndFunction

Function AddXP(Int amount)
	If !started || settled || amount <= 0
		Return
	EndIf
	xp += amount
	Debug.Notification((amount as String) + " " + XPText)
	Debug.Trace("[FalloutRules] " + Plugin + ": +" + amount + " XP, " + xp + " of " + XPForLevel(level + 1))
	CheckLevel()
EndFunction

; The experience a character has on reaching a level.
Int Function XPForLevel(Int target)
	If target <= 1
		Return 0
	EndIf
	Int n = target - 1
	Return n * XPBase + XPBumpBase * n * (n - 1) / 2
EndFunction

; ---------------------------------------------------------------------------
; The level-up, out of combat and menus
; ---------------------------------------------------------------------------

Function CheckLevel()
	If !started || levelling || level >= MaxLevel || xp < XPForLevel(level + 1)
		Return
	EndIf
	If Game.GetPlayer().IsInCombat() || Utility.IsInMenuMode()
		RegisterForSingleUpdate(BUSY_SECONDS)
		Return
	EndIf
	levelling = True
	While level < MaxLevel && xp >= XPForLevel(level + 1)
		LevelUp()
	EndWhile
	levelling = False
EndFunction

Function LevelUp()
	level += 1
	Debug.Notification(LevelText + " " + level)
	Game.GetPlayer().ModActorValue("Health", HealthPerLevel)
	Float points = carry + SkillPointsOffset + SkillPointsPerIntelligence * SpecialGlobal(INTELLIGENCE).GetValue()
	Int whole = Math.Floor(points)
	carry = points - whole
	SpendPoints(whole)
	PushSkills()
	Debug.Trace("[FalloutRules] " + Plugin + ": level " + level + ", " + whole + " skill points")
	SendModEvent("TESCharacterLevel", "", level as Float)
EndFunction

; One point per button press, on two pages, until every point is spent or
; every skill is at its cap.
Function SpendPoints(Int points)
	Bool second = False
	While points > 0 && !AllCapped()
		Int choice = ShowSkills(second, points)
		Int skill = choice
		If second
			skill = FirstPageSkills + choice
		EndIf
		If !second && choice == FirstPageSkills
			second = True
		ElseIf second && skill >= SkillNames.Length
			second = False
		ElseIf skill >= 0 && skill < SkillNames.Length && skills[skill] < SKILL_CAP
			skills[skill] = skills[skill] + 1.0
			points -= 1
		EndIf
	EndWhile
EndFunction

Int Function ShowSkills(Bool second, Int points)
	If second
		Int f = FirstPageSkills
		Return SkillMenuMore.Show(points, SkillAt(f), SkillAt(f + 1), SkillAt(f + 2), SkillAt(f + 3), SkillAt(f + 4), SkillAt(f + 5), SkillAt(f + 6), SkillAt(f + 7))
	EndIf
	Return SkillMenu.Show(points, SkillAt(0), SkillAt(1), SkillAt(2), SkillAt(3), SkillAt(4), SkillAt(5), SkillAt(6), SkillAt(7))
EndFunction

Float Function SkillAt(Int skill)
	If skill < SkillNames.Length
		Return skills[skill]
	EndIf
	Return 0.0
EndFunction

Bool Function AllCapped()
	Int s = 0
	While s < SkillNames.Length
		If skills[s] < SKILL_CAP
			Return False
		EndIf
		s += 1
	EndWhile
	Return True
EndFunction
