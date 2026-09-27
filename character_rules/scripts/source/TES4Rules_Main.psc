ScriptName TES4Rules_Main extends Quest
{A converted TES4 game's character rules for the player: attributes, skill-use
leveling and the level-up at rest, for a character who started in that game.
Generic across TES4 games: every number and text is a property the rules
plugin's builder fills from the game's character data.
See docs/commentary/character_rules.md}

; ---------------------------------------------------------------------------
; Filled by tools/release/make_character_rules_esp.py
; ---------------------------------------------------------------------------

String Property Plugin Auto                 ; the converted game's plugin, e.g. Oblivion.esm
Int Property GameId Auto                    ; TESGameSelectQuest's id for that game
GlobalVariable Property Active Auto         ; 1 while this character plays by these rules
GlobalVariable Property ClassChoice Auto    ; the converted chargen's class menu index + 1
FormList Property BluntWeapons Auto
FormList Property MysticismSpells Auto
FormList Property SkillBooks Auto           ; a FormList of books per source skill
FormList Property Races Auto                ; Skyrim races, in the race arrays' order
FormList Property PickedGlobals Auto        ; eight GLOBs; 1 hides that attribute's button
Message Property LevelUpMenu Auto           ; eight attribute buttons, bonuses as %.0f
String[] Property SkyrimSkillNames Auto     ; Skyrim's 18 skill actor values
String[] Property SkillNames Auto           ; the source game's skills
Int[] Property SkillAttribute Auto          ; governing attribute, 0-7
Int[] Property SkillSpecialization Auto     ; 0-2
Int[] Property SkyrimPrimary Auto           ; per Skyrim skill: the source skill it credits, or -1
Int[] Property SkyrimFold Auto              ; per Skyrim skill: a folded source skill, or -1
String[] Property ClassIds Auto             ; by chargen menu index
Int[] Property ClassMajors Auto             ; a bit per source skill
Int[] Property ClassSpecialization Auto
Int[] Property ClassFavored1 Auto
Int[] Property ClassFavored2 Auto
Int[] Property RaceMale Auto                ; eight base attributes per race
Int[] Property RaceFemale Auto
Int[] Property RaceBonusSkill Auto          ; seven per race, -1 for none
Int[] Property RaceBonusValue Auto
Int[] Property LevelUpMults Auto            ; attribute bonus by increases, 0-10
String[] Property LevelUpTexts Auto         ; the passage shown on reaching level 2-20
String Property MeditateText Auto
Int Property SkillsPerLevel Auto
Int Property MinorSkillStart Auto
Int Property MajorSkillStart Auto
Int Property SpecializationBonus Auto
Float Property FavoredBonus1 Auto
Float Property FavoredBonus2 Auto
Float Property HealthMult Auto               ; fPCBaseHealthMult: Health per Endurance
Float Property MagickaMult Auto              ; fPCBaseMagickaMult: Magicka per Intelligence, plus one
Float Property EncumbranceMult Auto          ; fActorStrengthEncumbranceMult: carry weight per Strength

Int Property ATTRIBUTES = 8 AutoReadOnly
Int Property STRENGTH = 0 AutoReadOnly
Int Property INTELLIGENCE = 1 AutoReadOnly
Int Property ENDURANCE = 5 AutoReadOnly
Int Property LUCK = 7 AutoReadOnly
Int Property PICKS = 3 AutoReadOnly
Float Property ATTRIBUTE_CAP = 100.0 AutoReadOnly
Float Property HEALTH_PER_LEVEL = 0.1 AutoReadOnly    ; of Endurance, at each level-up
Float Property POLL_SECONDS = 2.0 AutoReadOnly       ; while the game or class is still being chosen
Int Property SELECTOR_QUEST = 0xA00 AutoReadOnly       ; TESGameSelectQuest in TESGameSelect.esp
Int Property PLAYER_ATTRIBUTES = 0xAF0 AutoReadOnly    ; TESGS_PlayerStrength, then the other seven
String Property SELECTOR = "TESGameSelect.esp" AutoReadOnly

; ---------------------------------------------------------------------------
; Kept with the character
; ---------------------------------------------------------------------------

Bool started = False
Bool settled = False        ; this session: the game is decided and it is not ours
Bool on = False             ; this session: TESRuntime has these rules on
String lastSeen = ""        ; the last TESGameSelect state traced
Int classIndex = -1
Int[] sourceLevels
Int[] attributeIncreases
Int majorIncreases = 0
Float[] snapshot
Form lastWeapon
Form lastSpell
Bool bartering = False
Int pendingBook = -1
Bool busy = False
Bool again = False
Bool announced = False

; ---------------------------------------------------------------------------
; Which character plays by these rules
; ---------------------------------------------------------------------------

Event OnInit()
	Debug.Trace("[TES4Rules] " + Plugin + ": rules quest started")
	CheckCharacter()
EndEvent

; Every load starts over: TESRuntime has the rules off, and the game is read
; again from TESGameSelect, which keeps it with the save.
Function Loaded()
	Debug.Trace("[TES4Rules] " + Plugin + ": game loaded")
	settled = False
	on = False
	CheckCharacter(True)
EndFunction

; Whether this character plays by these rules. Skyrim's own leveling is handed
; over as soon as the game is chosen; the rules begin once the class is too.
; Until both are known this looks again every few seconds: an update survives
; the start of a new game, where a menu registration made in OnInit may not.
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
		If !Begin()
			RegisterForSingleUpdate(POLL_SECONDS)
			Return
		EndIf
		SendClass()
	EndIf
	Recount()
EndFunction

Event OnUpdate()
	CheckCharacter()
EndEvent

; The game this character began in (TESGameSelect's ChosenGame), or -1 until it
; is final: its menu still to show, open (Selecting), or the game not yet
; started, or an older save's ids not yet renumbered (MigrateIds). TESGameSelect's
; travel quest takes the same answer. -2 means Skyrim's own rules: no
; TESGameSelect, or a loaded save whose menu never ran (begun before it was
; installed). A new game's menu runs after this quest starts, so it waits.
Int Function ChosenGame(Bool fromLoad)
	TESGameSelectQuest gameSelect = Game.GetFormFromFile(SELECTOR_QUEST, SELECTOR) as TESGameSelectQuest
	If !gameSelect
		Debug.Trace("[TES4Rules] " + Plugin + ": no TESGameSelect quest")
		Return -2
	EndIf
	String seen = "TESGameSelect HasRun " + gameSelect.HasRun + ", Selecting " + gameSelect.Selecting + ", ChosenGame " + gameSelect.ChosenGame + ", ids " + gameSelect.IdVersion + ", from load " + fromLoad + ", class choice " + ClassChoice.GetValue()
	If seen != lastSeen
		lastSeen = seen
		Debug.Trace("[TES4Rules] " + Plugin + ": " + seen)
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
	Debug.Trace("[TES4Rules] " + Plugin + ": game " + game + " chosen, not this one; Skyrim's rules")
	settled = True
	If on
		SendModEvent("TESCharacterRules", "", 0.0)
		on = False
	EndIf
	Active.SetValue(0)
	UnregisterForAllMenus()
	UnregisterForSleep()
EndFunction

; ---------------------------------------------------------------------------
; Character creation: the class, race and sign are chosen
; ---------------------------------------------------------------------------

; False while no class is chosen yet.
Bool Function Begin()
	Int choice = ClassChoice.GetValue() as Int
	If choice < 1 || choice > ClassIds.Length
		Return False
	EndIf
	Actor player = Game.GetPlayer()
	classIndex = choice - 1
	Int race = Races.Find(player.GetRace())
	Bool female = player.GetActorBase().GetSex() == 1
	Int a = 0
	While a < ATTRIBUTES
		Float value = 40.0
		If race >= 0 && female
			value = RaceFemale[race * ATTRIBUTES + a]
		ElseIf race >= 0
			value = RaceMale[race * ATTRIBUTES + a]
		EndIf
		If a == ClassFavored1[classIndex]
			value += FavoredBonus1
		EndIf
		If a == ClassFavored2[classIndex]
			value += FavoredBonus2
		EndIf
		AttributeGlobal(a).SetValue(value)
		a += 1
	EndWhile
	StartSkills(race)
	attributeIncreases = Utility.CreateIntArray(ATTRIBUTES)
	majorIncreases = 0
	started = True
	Debug.Trace("[TES4Rules] " + Plugin + ": class " + ClassIds[classIndex] + ", race " + race + "; the rules begin")
	Return True
EndFunction

; Each source skill at its starting level, and each Skyrim skill raised to the
; best of the source skills credited from it, never lowered: on a character
; already played, a higher Skyrim level becomes its source skill's. Then the
; snapshot increases count from.
Function StartSkills(Int race)
	Int count = SkillNames.Length
	sourceLevels = Utility.CreateIntArray(count)
	Int s = 0
	While s < count
		Int level = MinorSkillStart
		If IsMajor(s)
			level = MajorSkillStart
		EndIf
		If SkillSpecialization[s] == ClassSpecialization[classIndex]
			level += SpecializationBonus
		EndIf
		sourceLevels[s] = level + RaceBonus(race, s)
		s += 1
	EndWhile
	Actor player = Game.GetPlayer()
	Int k = 0
	While k < SkyrimSkillNames.Length
		Int best = -1
		If SkyrimPrimary[k] >= 0
			best = sourceLevels[SkyrimPrimary[k]]
		EndIf
		If SkyrimFold[k] >= 0 && sourceLevels[SkyrimFold[k]] > best
			best = sourceLevels[SkyrimFold[k]]
		EndIf
		If best >= 0
			Int current = player.GetBaseActorValue(SkyrimSkillNames[k]) as Int
			If best > current
				player.SetActorValue(SkyrimSkillNames[k], best)
			ElseIf SkyrimPrimary[k] >= 0 && current > sourceLevels[SkyrimPrimary[k]]
				sourceLevels[SkyrimPrimary[k]] = current
			EndIf
		EndIf
		k += 1
	EndWhile
	TakeSnapshot()
EndFunction

Int Function RaceBonus(Int race, Int skill)
	If race < 0
		Return 0
	EndIf
	Int i = race * 7
	While i < race * 7 + 7
		If RaceBonusSkill[i] == skill
			Return RaceBonusValue[i]
		EndIf
		i += 1
	EndWhile
	Return 0
EndFunction

Bool Function IsMajor(Int skill)
	Return Math.LogicalAnd(ClassMajors[classIndex], Math.LeftShift(1, skill)) != 0
EndFunction

; ---------------------------------------------------------------------------
; Every load: hand Skyrim's own leveling to TESRuntime and listen again
; ---------------------------------------------------------------------------

Function TurnOn()
	Debug.Trace("[TES4Rules] " + Plugin + ": this game's character; Skyrim's leveling handed to TESRuntime")
	on = True
	Active.SetValue(1)
	RegisterForMenu("BarterMenu")
	RegisterForMenu("Book Menu")
	RegisterForMenu("Training Menu")
	RegisterForMenu("Crafting Menu")
	RegisterForMenu("Lockpicking Menu")
	RegisterForSleep()
	SendModEvent("TESCharacterRules", Plugin, 1.0)
	SendClass()
EndFunction

; Until a class is named, TESRuntime's skill rates use no class multiplier.
Function SendClass()
	If started
		SendModEvent("TESCharacterClass", ClassIds[classIndex], 0.0)
	EndIf
EndFunction

; ---------------------------------------------------------------------------
; Skill increases: compared with the last snapshot, never counted as events
; ---------------------------------------------------------------------------

Function TakeSnapshot()
	Actor player = Game.GetPlayer()
	snapshot = Utility.CreateFloatArray(SkyrimSkillNames.Length)
	Int k = 0
	While k < SkyrimSkillNames.Length
		snapshot[k] = player.GetBaseActorValue(SkyrimSkillNames[k])
		k += 1
	EndWhile
EndFunction

; Credits every Skyrim skill level gained since the snapshot. A call that
; arrives while one is running makes that one go round again.
Function Recount()
	If !started || settled
		Return
	EndIf
	again = True
	If busy
		Return
	EndIf
	busy = True
	While again
		again = False
		CountIncreases()
	EndWhile
	busy = False
EndFunction

Function CountIncreases()
	Actor player = Game.GetPlayer()
	Int k = 0
	While k < SkyrimSkillNames.Length
		Float now = player.GetBaseActorValue(SkyrimSkillNames[k])
		Int gained = (now - snapshot[k]) as Int
		If gained > 0
			Credit(k, gained)
		EndIf
		snapshot[k] = now
		k += 1
	EndWhile
	pendingBook = -1
EndFunction

; The source skill a Skyrim skill's increase belongs to: a skill book just
; read, the folded skill when what the player was doing names it, or the
; skill's own source.
Function Credit(Int skyrimSkill, Int gained)
	Int source = SkyrimPrimary[skyrimSkill]
	If pendingBook >= 0
		source = pendingBook
		pendingBook = -1
	ElseIf SkyrimFold[skyrimSkill] >= 0 && FoldApplies(SkyrimFold[skyrimSkill])
		source = SkyrimFold[skyrimSkill]
	EndIf
	If source >= 0
		Advance(source, gained)
	EndIf
EndFunction

Bool Function FoldApplies(Int source)
	String name = SkillNames[source]
	If name == "Blunt"
		Return BluntWeapons.HasForm(lastWeapon)
	ElseIf name == "Mysticism"
		Return MysticismSpells.HasForm(lastSpell)
	ElseIf name == "Mercantile"
		Return bartering
	EndIf
	Return False
EndFunction

Function Advance(Int source, Int gained)
	sourceLevels[source] = sourceLevels[source] + gained
	Int attribute = SkillAttribute[source]
	attributeIncreases[attribute] = attributeIncreases[attribute] + gained
	If IsMajor(source)
		majorIncreases += gained
	EndIf
	If majorIncreases >= SkillsPerLevel && !announced
		announced = True
		Debug.Notification(MeditateText)
	EndIf
EndFunction

; ---------------------------------------------------------------------------
; What the player was doing, for folded skills and skill books
; ---------------------------------------------------------------------------

Function NoteEquipped(Form item)
	If !started || settled
		Return
	ElseIf item as Weapon
		lastWeapon = item
	ElseIf item as Book
		pendingBook = BookSkill(item)
	EndIf
EndFunction

Function NoteCast(Form spell)
	If started && !settled
		lastSpell = spell
	EndIf
EndFunction

Int Function BookSkill(Form book)
	Int s = 0
	While s < SkillBooks.GetSize()
		FormList books = SkillBooks.GetAt(s) as FormList
		If books && books.HasForm(book)
			Return s
		EndIf
		s += 1
	EndWhile
	Return -1
EndFunction

Event OnMenuOpen(String menuName)
	If menuName == "BarterMenu"
		Recount()
		bartering = True
	EndIf
EndEvent

Event OnMenuClose(String menuName)
	Recount()
	If menuName == "BarterMenu"
		bartering = False
	EndIf
EndEvent

; ---------------------------------------------------------------------------
; The level-up, at rest, as in the source game
; ---------------------------------------------------------------------------

Event OnSleepStop(Bool abInterrupted)
	Recount()
	If started && !settled && majorIncreases >= SkillsPerLevel
		LevelUp()
	EndIf
EndEvent

Function LevelUp()
	Actor player = Game.GetPlayer()
	Int level = player.GetLevel() + 1
	Debug.MessageBox(LevelUpText(level))
	Float[] bonus = Utility.CreateFloatArray(ATTRIBUTES)
	Int a = 0
	While a < ATTRIBUTES
		bonus[a] = AttributeBonus(a)
		(PickedGlobals.GetAt(a) as GlobalVariable).SetValue(0)
		a += 1
	EndWhile
	Int picked = 0
	While picked < PICKS
		Int choice = LevelUpMenu.Show(bonus[0], bonus[1], bonus[2], bonus[3], bonus[4], bonus[5], bonus[6], bonus[7])
		If choice >= 0 && choice < ATTRIBUTES && (PickedGlobals.GetAt(choice) as GlobalVariable).GetValue() == 0
			(PickedGlobals.GetAt(choice) as GlobalVariable).SetValue(1)
			RaiseAttribute(choice, bonus[choice])
			picked += 1
		EndIf
	EndWhile
	player.ModActorValue("Health", AttributeGlobal(ENDURANCE).GetValue() * HEALTH_PER_LEVEL)
	majorIncreases -= SkillsPerLevel
	attributeIncreases = Utility.CreateIntArray(ATTRIBUTES)
	announced = majorIncreases >= SkillsPerLevel
	Debug.Trace("[TES4Rules] " + Plugin + ": level " + level)
	SendModEvent("TESCharacterLevel", "", level as Float)
EndFunction

String Function LevelUpText(Int level)
	Int index = level - 2
	If index >= LevelUpTexts.Length
		index = LevelUpTexts.Length - 1
	EndIf
	If index < 0
		Return ""
	EndIf
	Return LevelUpTexts[index]
EndFunction

; Luck is governed by no skill and always rises by one.
Float Function AttributeBonus(Int attribute)
	If attribute == LUCK
		Return 1.0
	EndIf
	Int increases = attributeIncreases[attribute]
	If increases >= LevelUpMults.Length
		increases = LevelUpMults.Length - 1
	EndIf
	Return LevelUpMults[increases]
EndFunction

; Raises an attribute to at most 100, and what it governs with it.
Function RaiseAttribute(Int attribute, Float amount)
	GlobalVariable value = AttributeGlobal(attribute)
	Float before = value.GetValue()
	Float after = before + amount
	If after > ATTRIBUTE_CAP
		after = ATTRIBUTE_CAP
	EndIf
	value.SetValue(after)
	Float change = after - before
	Actor player = Game.GetPlayer()
	If attribute == STRENGTH
		player.ModActorValue("CarryWeight", change * EncumbranceMult)
	ElseIf attribute == INTELLIGENCE
		player.ModActorValue("Magicka", change * (1.0 + MagickaMult))
	ElseIf attribute == ENDURANCE
		player.ModActorValue("Health", change * HealthMult)
	EndIf
EndFunction

GlobalVariable Function AttributeGlobal(Int attribute)
	Return Game.GetFormFromFile(PLAYER_ATTRIBUTES + attribute, SELECTOR) as GlobalVariable
EndFunction
