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
Message Property SpecialMenu Auto           ; raise a stat, "Lower a stat", "Done"
Message Property SpecialLowerMenu Auto      ; lower a stat, "Raise a stat", "Done"
Message Property TagMenu Auto               ; the skill pages again, for choosing tags
Message Property TagMenuMore Auto
Perk[] Property PerkForms Auto              ; the level-up perks by level, then the traits
String[] Property PerkNames Auto
String[] Property PerkTexts Auto
Int[] Property PerkLevel Auto
Int[] Property PerkRanks Auto
Int[] Property PerkReqStart Auto            ; each perk's requirements: the first row in the Req columns
Int[] Property PerkReqCount Auto            ; and how many rows
Int[] Property ReqKind Auto                 ; 0 a stat, 1 a skill, 2 the level, 3 the sex, 4 a perk
Int[] Property ReqIndex Auto                ; which stat, skill, sex or perk
Int[] Property ReqOp Auto                   ; 0 ==, 1 !=, 2 >, 3 >=, 4 <, 5 <=
Float[] Property ReqValue Auto
Int[] Property ReqOr Auto                   ; 1: OR with the next row
Int Property FirstTrait Auto                ; PerkForms from here on are traits
Message Property PerkConfirm Auto           ; "Take it" or "Back", after the perk's description
Message[] Property PerkPages Auto           ; eight perks a page, then More and Back
Message[] Property TraitPages Auto          ; the same, then Done
GlobalVariable[] Property PickSlots Auto    ; a page's perk button shows while its slot is 1
GlobalVariable Property PickMore Auto
GlobalVariable Property PickBack Auto
Int Property LevelsPerPerk Auto             ; a perk every this many levels
Int Property MaxTraits Auto
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
Int Property IntelligenceCap Auto           ; Intelligence counts up to this, 0 for no cap
Int Property EvenLevelPoint Auto            ; 1: one more point on an even level when Intelligence is odd
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
GlobalVariable Property Karma Auto          ; the converted game's karma
FormList Property VeryEvilActors Auto       ; actor bases by the alignment their karma gives
FormList Property EvilActors Auto
FormList Property GoodActors Auto
FormList Property VeryGoodActors Auto
FormList Property CrimeFactions Auto        ; factions that track crime
FormList Property EvilFactions Auto         ; stealing from these costs no karma
FormList[] Property Reputations Auto        ; each New Vegas reputation
FormList[] Property ReputationFactions Auto ; and the crime-tracking factions that answer to it
Float[] Property KillKarmaClaimed Auto      ; a kill's karma by alignment when a crime-tracking faction claims the victim
Float[] Property KillKarmaUnclaimed Auto    ; and when none does
Int[] Property KillMurders Auto             ; 1: that alignment's kill is murder, the person or creature amount
Float Property KarmaMurderNPC Auto
Float Property KarmaMurderCreature Auto
Float Property KarmaTheft Auto
Float Property KarmaMin Auto
Float Property KarmaMax Auto
Float Property InfamyMajor Auto             ; a reported murder
Float Property InfamyMinor Auto             ; a reported theft or pickpocketing, or a kill in a fight

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
String Property MENU_EVENT = "TESCharacterMenu" AutoReadOnly
Int Property SPECIAL_MIN = 1 AutoReadOnly
Int Property SPECIAL_MAX = 10 AutoReadOnly
Int Property PAGE = 8 AutoReadOnly                    ; perks on a menu page
Int Property CRIME_REPORTED = 2 AutoReadOnly          ; a kill's crime status once someone saw it
Int Property CRIME_STEAL = 0 AutoReadOnly             ; the crime gold event's steal and pickpocket
Int Property CRIME_PICKPOCKET = 1 AutoReadOnly
Int Property INFAMY = 0 AutoReadOnly                  ; TES4_Reputation's kind for infamy
Int Property NEUTRAL = 0 AutoReadOnly                 ; alignments, as KillKarma* index them
Int Property EVIL = 1 AutoReadOnly
Int Property VERY_EVIL = 2 AutoReadOnly
Int Property GOOD = 3 AutoReadOnly
Int Property VERY_GOOD = 4 AutoReadOnly
String Property STOLEN_STAT = "Items Stolen" AutoReadOnly

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
Int[] tags                  ; the tag skills: the class's, then the player's choice
Bool levelling = False
Int kills = 0               ; the player's kills the rules heard of, beside the game's own count
Int locks = 0               ; the same for picked locks
Int[] taken                 ; ranks taken of each perk and trait
Int stolen = -1             ; the game's Items Stolen when last looked at, -1 before the first look

; ---------------------------------------------------------------------------
; Which character plays by these rules
; ---------------------------------------------------------------------------

Event OnInit()
	Log("rules quest started")
	CheckCharacter()
EndEvent

; Every load starts over: TESRuntime has the rules off, SKSE has dropped the
; mod event registration, and the game is read again from TESGameSelect.
Function Loaded()
	Log("game loaded")
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
		Log("no TESGameSelect quest")
		Return -2
	EndIf
	String seen = "TESGameSelect HasRun " + gameSelect.HasRun + ", Selecting " + gameSelect.Selecting + ", ChosenGame " + gameSelect.ChosenGame + ", ids " + gameSelect.IdVersion + ", from load " + fromLoad
	If seen != lastSeen
		lastSeen = seen
		Log(seen)
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
	Log("game " + game + " chosen, not this one; Skyrim's rules")
	settled = True
	If on
		SendModEvent("TESCharacterRules", "", 0.0)
		on = False
	EndIf
	Active.SetValue(0)
	UnregisterForModEvent(XP_EVENT)
	UnregisterForModEvent(MENU_EVENT)
EndFunction

; Every load: hand Skyrim's own leveling to TESRuntime and listen again.
Function TurnOn()
	Log("this game's character; Skyrim's leveling handed to TESRuntime")
	on = True
	Active.SetValue(1)
	RegisterForModEvent(XP_EVENT, "OnRewardXP")
	RegisterForModEvent(MENU_EVENT, "OnCharacterMenu")
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
	tags = TagSkills
	level = Game.GetPlayer().GetLevel()
	xp = XPForLevel(level)
	StartSkills()
	stolen = Game.QueryStat(STOLEN_STAT)
	started = True
	Log("level " + level + ", " + xp + " XP; the rules begin")
	Log(SpecialLine())
	Log(SkillLine())
	Log(SkyrimLine())
EndFunction

; A skill's start is its base, plus its stat times the primary multiplier,
; plus Luck times the luck multiplier rounded up, plus the tag bonus. At the
; rules' start a Skyrim skill already higher than every source it carries
; raises them; during character creation the menus decide alone.
Function StartSkills(Bool keepSkyrim = True)
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
	While s < tags.Length
		skills[tags[s]] = skills[tags[s]] + TagSkillBonus
		s += 1
	EndWhile
	Actor player = Game.GetPlayer()
	Int k = 0
	While k < SkyrimSkillNames.Length
		Float current = player.GetBaseActorValue(SkyrimSkillNames[k])
		If keepSkyrim && BestSource(k) >= 0 && current > BestSource(k)
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

; Converted SetSPECIALPoints / ShowLoveTesterMenuParams send "special" with
; the points to spread; SetTagSkills sends "tags" with how many to choose;
; ShowTraitMenu sends "traits". Each choice sets the starting skills again,
; as the game's own menus do during character creation.
Event OnCharacterMenu(String eventName, String strArg, Float numArg, Form sender)
	If !started || settled
		Return
	EndIf
	If strArg == "special"
		PickSpecial(numArg as Int)
	ElseIf strArg == "tags"
		PickTags(numArg as Int)
	ElseIf strArg == "traits"
		PickTraits(MaxTraits)
	Else
		Log(strArg + " menu: not one the rules know")
		Return
	EndIf
	StartSkills(False)
	Log(SkillLine())
	Log(SkyrimLine())
EndEvent

; Spread `total` points over S.P.E.C.I.A.L., each stat between the game's
; limits; "Done" closes the menu once every point is placed.
Function PickSpecial(Int total)
	Bool lowering = False
	While True
		Int left = total - SpecialSum()
		Int choice = ShowSpecial(lowering, left)
		If choice >= 0 && choice < SpecialGlobals.Length
			GlobalVariable stat = SpecialGlobal(choice)
			If lowering && stat.GetValue() > SPECIAL_MIN
				stat.SetValue(stat.GetValue() - 1)
			ElseIf !lowering && left > 0 && stat.GetValue() < SPECIAL_MAX
				stat.SetValue(stat.GetValue() + 1)
			EndIf
		ElseIf choice == SpecialGlobals.Length
			lowering = !lowering
		ElseIf left == 0
			Log("chosen: " + SpecialLine())
			Return
		EndIf
	EndWhile
EndFunction

Int Function ShowSpecial(Bool lowering, Int left)
	Message menu = SpecialMenu
	If lowering
		menu = SpecialLowerMenu
	EndIf
	Return menu.Show(left, StatAt(0), StatAt(1), StatAt(2), StatAt(3), StatAt(4), StatAt(5), StatAt(6))
EndFunction

Float Function StatAt(Int stat)
	Return SpecialGlobal(stat).GetValue()
EndFunction

Int Function SpecialSum()
	Int sum = 0
	Int s = 0
	While s < SpecialGlobals.Length
		sum += StatAt(s) as Int
		s += 1
	EndWhile
	Return sum
EndFunction

; Choose `count` tag skills on the skill pages; choosing a tagged skill again
; untags it. The values shown already carry the tag bonus.
Function PickTags(Int count)
	Bool[] tagged = Utility.CreateBoolArray(SkillNames.Length)
	Int chosen = 0
	tags = Utility.CreateIntArray(0)
	StartSkills(False)
	Bool second = False
	While chosen < count
		Int choice
		If second
			Int f = FirstPageSkills
			choice = TagMenuMore.Show(count - chosen, SkillAt(f), SkillAt(f + 1), SkillAt(f + 2), SkillAt(f + 3), SkillAt(f + 4), SkillAt(f + 5), SkillAt(f + 6), SkillAt(f + 7))
			choice += FirstPageSkills
		Else
			choice = TagMenu.Show(count - chosen, SkillAt(0), SkillAt(1), SkillAt(2), SkillAt(3), SkillAt(4), SkillAt(5), SkillAt(6), SkillAt(7))
		EndIf
		If !second && choice == FirstPageSkills
			second = True
		ElseIf second && choice >= SkillNames.Length
			second = False
		ElseIf choice >= 0 && choice < SkillNames.Length
			tagged[choice] = !tagged[choice]
			If tagged[choice]
				chosen += 1
			Else
				chosen -= 1
			EndIf
			tags = TaggedIndices(tagged, chosen)
			StartSkills(False)
		EndIf
	EndWhile
	Log("tag skills chosen: " + chosen)
EndFunction

Int[] Function TaggedIndices(Bool[] tagged, Int chosen)
	Int[] out = Utility.CreateIntArray(chosen)
	Int n = 0
	Int s = 0
	While s < tagged.Length
		If tagged[s]
			out[n] = s
			n += 1
		EndIf
		s += 1
	EndWhile
	Return out
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
; Every kill heard of is logged; the player's are counted beside the game's
; own kill stats, so a kill that never arrived shows as the counts parting.
Function NoteKill(Actor victim, Actor killer, Int crimeStatus)
	If !started || settled || !victim
		Return
	EndIf
	Bool person = victim.HasKeyword(ActorTypeNPC)
	String seen = "kill: " + NameOf(victim) + ", level " + victim.GetLevel() + ", by " + NameOf(killer)
	If killer == Game.GetPlayer()
		kills += 1
		Log(seen + "; player kill " + kills + ", the game counts " + GameKills() + ", crime status " + crimeStatus)
		ScoreKill(victim, crimeStatus)
	ElseIf TeammateKills == 1 && killer && killer.IsPlayerTeammate()
		Log(seen + "; a companion's, counted")
	Else
		Log(seen + "; not the player's")
		Return
	EndIf
	If person
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
	locks += 1
	Log("lock: level " + lockObject.GetLockLevel() + ", tier " + tier + "; lock " + locks + ", the game counts " + Game.QueryStat("Locks Picked"))
	AddXP(Reward(LevelPickLock, RewardPickLock, tier))
EndFunction

; The game's own count of the player's kills, from its General Stats.
Int Function GameKills()
	Return Game.QueryStat("People Killed") + Game.QueryStat("Animals Killed") + Game.QueryStat("Creatures Killed") + Game.QueryStat("Undead Killed") + Game.QueryStat("Daedra Killed") + Game.QueryStat("Automatons Killed")
EndFunction

String Function NameOf(Actor someone)
	If !someone
		Return "nobody"
	EndIf
	Return someone.GetDisplayName()
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
	Log("+" + amount + " XP, " + xp + " of " + XPForLevel(level + 1))
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
; Karma and infamy: the player's kills and crimes
; ---------------------------------------------------------------------------

; A kill's karma, by the victim's alignment and whether a faction that tracks
; crime claims it, as the game's death handler scores it; a murder amount is
; the creature's or the person's. A reported murder costs the major infamy, a
; kill in a fight the minor one.
Function ScoreKill(Actor victim, Int crimeStatus)
	Int align = Alignment(victim.GetActorBase())
	Float change = KillKarmaUnclaimed[align]
	If InAny(victim, CrimeFactions)
		change = KillKarmaClaimed[align]
		If KillMurders[align] == 1 && victim.HasKeyword(ActorTypeNPC)
			change = KarmaMurderNPC
		ElseIf KillMurders[align] == 1
			change = KarmaMurderCreature
		EndIf
	EndIf
	ModKarma(change, "kill of " + NameOf(victim))
	If crimeStatus == CRIME_REPORTED
		AddInfamy(victim, InfamyMajor)
	ElseIf Game.GetPlayer().IsInCombat()
		AddInfamy(victim, InfamyMinor)
	EndIf
EndFunction

Int Function Alignment(Form base)
	If EvilActors.HasForm(base)
		Return EVIL
	ElseIf VeryEvilActors.HasForm(base)
		Return VERY_EVIL
	ElseIf GoodActors.HasForm(base)
		Return GOOD
	ElseIf VeryGoodActors.HasForm(base)
		Return VERY_GOOD
	EndIf
	Return NEUTRAL
EndFunction

; A reported crime: being caught stealing or pickpocketing costs the minor infamy.
Function NoteCrime(Actor victim, Actor criminal, Int crime)
	If !started || settled || !victim || criminal != Game.GetPlayer()
		Return
	EndIf
	Log("crime " + crime + " against " + NameOf(victim))
	If crime == CRIME_STEAL || crime == CRIME_PICKPOCKET
		AddInfamy(victim, InfamyMinor)
	EndIf
EndFunction

; An item the player took: a theft, seen or not, when the game's Items Stolen
; rose, and it costs karma unless its owner is evil.
Function NoteItem(ObjectReference source, ObjectReference item)
	If !started || settled
		Return
	EndIf
	Int now = Game.QueryStat(STOLEN_STAT)
	Int before = stolen
	stolen = now
	If before < 0 || now <= before
		Return
	EndIf
	Form owner = OwnerOf(source, item)
	If EvilFactions.HasForm(owner) || EvilActors.HasForm(owner) || VeryEvilActors.HasForm(owner)
		Log("theft from evil " + owner + ": no karma")
		Return
	EndIf
	ModKarma(KarmaTheft, "theft from " + owner)
EndFunction

; The item's owner: its container's, else its own, else the cell's.
Form Function OwnerOf(ObjectReference source, ObjectReference item)
	ObjectReference held = source
	If !held
		held = item
	EndIf
	If held && held.GetActorOwner()
		Return held.GetActorOwner()
	ElseIf held && held.GetFactionOwner()
		Return held.GetFactionOwner()
	EndIf
	Cell here = Game.GetPlayer().GetParentCell()
	If here.GetActorOwner()
		Return here.GetActorOwner()
	EndIf
	Return here.GetFactionOwner()
EndFunction

Function ModKarma(Float change, String why)
	If change == 0.0 || !Karma
		Return
	EndIf
	Float value = Karma.GetValue() + change
	If value > KarmaMax
		value = KarmaMax
	ElseIf value < KarmaMin
		value = KarmaMin
	EndIf
	Karma.SetValue(value)
	Log("karma " + change + " for " + why + ", now " + value)
EndFunction

Bool Function InAny(Actor someone, FormList factions)
	Int i = factions.GetSize()
	While i > 0
		i -= 1
		If someone.IsInFaction(factions.GetAt(i) as Faction)
			Return True
		EndIf
	EndWhile
	Return False
EndFunction

; Infamy with a reputation for each of the victim's crime-tracking factions that answers to it.
Function AddInfamy(Actor victim, Float amount)
	If amount <= 0.0 || !Reputations
		Return
	EndIf
	Int i = 0
	While i < Reputations.Length
		Int f = ReputationFactions[i].GetSize()
		While f > 0
			f -= 1
			If victim.IsInFaction(ReputationFactions[i].GetAt(f) as Faction)
				TES4_Reputation.AddExact(Reputations[i], INFAMY, amount)
				Log("infamy " + amount + " with reputation " + Reputations[i].GetFormID() + " for " + NameOf(victim))
			EndIf
		EndWhile
		i += 1
	EndWhile
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
	Int smarts = SpecialGlobal(INTELLIGENCE).GetValueInt()
	If IntelligenceCap > 0 && smarts > IntelligenceCap
		smarts = IntelligenceCap
	EndIf
	Int whole = Math.Floor(SkillPointsOffset + SkillPointsPerIntelligence * smarts)
	If EvenLevelPoint == 1 && level % 2 == 0 && smarts % 2 == 1
		whole += 1
	EndIf
	Log("level " + level + ", " + whole + " skill points; Health +" + HealthPerLevel)
	SpendPoints(whole)
	PushSkills()
	Log(SkillLine())
	Log(SkyrimLine())
	If LevelsPerPerk > 0 && level % LevelsPerPerk == 0
		PickPerk()
	EndIf
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
			Log("point to " + SkillNames[skill] + ", now " + (skills[skill] as Int) + "; " + points + " left")
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

; ---------------------------------------------------------------------------
; Perks and traits
; ---------------------------------------------------------------------------

; Every LevelsPerPerk levels, one perk the character qualifies for.
Function PickPerk()
	Int entry = PickEntry(PerkPages, 0, FirstTrait, 0)
	If entry < 0
		Log("level " + level + ": no perk to choose")
		Return
	EndIf
	Take(entry)
EndFunction

; Up to `count` traits at character creation; Done ends it early.
Function PickTraits(Int count)
	Int chosen = 0
	Int entry = 0
	While chosen < count && entry >= 0
		entry = PickEntry(TraitPages, FirstTrait, PerkForms.Length - FirstTrait, count - chosen)
		If entry >= 0
			Take(entry)
			chosen += 1
		EndIf
	EndWhile
	Log("traits chosen: " + chosen)
EndFunction

; An entry from the pages over [first, first + count): only the ones the
; character can take show, More and Back skip pages with none, and a choice
; counts once its description is confirmed. -1 for Done or nothing to take.
Int Function PickEntry(Message[] pages, Int first, Int count, Int left)
	Int at = NextPage(first, count, -1, 1)
	While at >= 0
		Int base = first + at * PAGE
		Int onPage = PageSize(first, count, at)
		Int more = NextPage(first, count, at, 1)
		Int back = NextPage(first, count, at, -1)
		ShowSlots(base, onPage)
		PickMore.SetValue((more >= 0) as Int)
		PickBack.SetValue((back >= 0) as Int)
		Int choice = pages[at].Show(left)
		Log("perk page " + at + ": button " + choice)
		If choice >= 0 && choice < onPage
			If Described(base + choice)
				Return base + choice
			EndIf
		ElseIf choice == onPage
			at = more
		ElseIf choice == onPage + 1
			at = back
		Else
			Return -1
		EndIf
	EndWhile
	Return -1
EndFunction

Int Function PageSize(Int first, Int count, Int at)
	Int size = count - at * PAGE
	If size > PAGE
		Return PAGE
	EndIf
	Return size
EndFunction

; The next page from `at` in direction `step` with an entry the character
; can take, or -1.
Int Function NextPage(Int first, Int count, Int at, Int step)
	at += step
	While at >= 0 && at * PAGE < count
		Int e = first + at * PAGE
		Int last = e + PageSize(first, count, at)
		While e < last
			If Eligible(e)
				Return at
			EndIf
			e += 1
		EndWhile
		at += step
	EndWhile
	Return -1
EndFunction

Function ShowSlots(Int base, Int onPage)
	Int k = 0
	While k < PickSlots.Length
		PickSlots[k].SetValue((k < onPage && Eligible(base + k)) as Int)
		k += 1
	EndWhile
EndFunction

; The level reached, a rank left, and every requirement met: consecutive
; rows joined by OR count as one, as the game groups its conditions.
Bool Function Eligible(Int e)
	If level < PerkLevel[e] || TakenRanks(e) >= PerkRanks[e]
		Return False
	EndIf
	Bool met = True
	Bool group = False
	Int r = PerkReqStart[e]
	Int last = r + PerkReqCount[e]
	While r < last
		group = group || RequirementMet(r)
		If ReqOr[r] == 0 || r == last - 1
			met = met && group
			group = False
		EndIf
		r += 1
	EndWhile
	Return met
EndFunction

Bool Function RequirementMet(Int r)
	Float have = RequirementValue(ReqKind[r], ReqIndex[r])
	Float want = ReqValue[r]
	Int op = ReqOp[r]
	If op == 0
		Return have == want
	ElseIf op == 1
		Return have != want
	ElseIf op == 2
		Return have > want
	ElseIf op == 3
		Return have >= want
	ElseIf op == 4
		Return have < want
	EndIf
	Return have <= want
EndFunction

Float Function RequirementValue(Int kind, Int index)
	Actor player = Game.GetPlayer()
	If kind == 0
		Return StatAt(index)
	ElseIf kind == 1
		Return SkillAt(index)
	ElseIf kind == 2
		Return level
	ElseIf kind == 3
		Return (player.GetActorBase().GetSex() == index) as Int
	EndIf
	Return player.HasPerk(PerkForms[index]) as Int
EndFunction

; The perk's name and description, then "Take it" or "Back".
Bool Function Described(Int e)
	Debug.MessageBox(PerkNames[e] + "\n\n" + PerkTexts[e])
	Return PerkConfirm.Show() == 0
EndFunction

Function Take(Int e)
	Actor player = Game.GetPlayer()
	EnsureTaken()
	player.AddPerk(PerkForms[e])
	taken[e] = taken[e] + 1
	Log("took " + PerkNames[e] + ", rank " + taken[e] + " of " + PerkRanks[e] + "; has it: " + player.HasPerk(PerkForms[e]))
EndFunction

Int Function TakenRanks(Int e)
	EnsureTaken()
	Return taken[e]
EndFunction

; A character from before the perks, or from a build with a different perk
; list, counts one rank of every perk it has.
Function EnsureTaken()
	If taken.Length == PerkForms.Length
		Return
	EndIf
	taken = Utility.CreateIntArray(PerkForms.Length)
	Actor player = Game.GetPlayer()
	Int e = 0
	While e < PerkForms.Length
		taken[e] = player.HasPerk(PerkForms[e]) as Int
		e += 1
	EndWhile
EndFunction

; ---------------------------------------------------------------------------
; The Papyrus log
; ---------------------------------------------------------------------------

Function Log(String text)
	Debug.Trace("[FalloutRules] " + Plugin + ": " + text)
EndFunction

String Function SpecialLine()
	String line = "S.P.E.C.I.A.L."
	Int s = 0
	While s < SpecialGlobals.Length
		line += " " + (SpecialGlobal(s).GetValue() as Int)
		s += 1
	EndWhile
	Return line
EndFunction

; The source game's skills as the rules keep them.
String Function SkillLine()
	String line = "skills:"
	Int s = 0
	While s < SkillNames.Length
		line += " " + SkillNames[s] + " " + (skills[s] as Int)
		s += 1
	EndWhile
	Return line
EndFunction

; Skyrim's skills as the player has them.
String Function SkyrimLine()
	Actor player = Game.GetPlayer()
	String line = "Skyrim skills:"
	Int k = 0
	While k < SkyrimSkillNames.Length
		line += " " + SkyrimSkillNames[k] + " " + (player.GetBaseActorValue(SkyrimSkillNames[k]) as Int)
		k += 1
	EndWhile
	Return line
EndFunction
