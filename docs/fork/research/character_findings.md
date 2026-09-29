# Character systems: findings

What was read from the games' files and executables, and checked in game, for
[the character plan](../character.md). Counts are as measured when written;
sections marked **Fixed** describe bugs that are no longer in `standalone`.

## <a id="checked"></a>Checked

Read from the installed Skyrim SE, Oblivion and New Vegas files:

- **Skill increases are an engine event.** `Skyrim.esm` has 24 Story Manager
  event nodes (`SMEN`), one of them `SKIL` (Skill Increase), beside `LEVL`,
  `KILL`, `LOCK`, `CAST`, `CRFT`, `BRIB`, `INTM` and `FLAT`. Skyrim's own
  `Quest.psc` declares the matching events, `OnStoryIncreaseSkill(string
  asSkill)` among them.
- **Skyrim's per-skill XP rates are records.** 20 of `Skyrim.esm`'s 149 `AVIF`
  records carry a 16-byte `AVSK`, in xEdit's order Skill Use Mult, Skill
  Offset Mult, Skill Improve Mult, Skill Improve Offset, one per skill plus two
  regeneration modifiers; for
  example One-Handed is 6.3 / 0 / 2 / 0 and Smithing 160 / 0 / 0.25 / 300. An
  override plugin could set them; the plan sets them in memory instead
  ([why](../character.md#no-base-overrides)). Skyrim's Illusion skill is the record named
  `AVMysticism`.
- **Oblivion's leveling table is engine defaults.** `Oblivion.esm` stores no
  leveling GMSTs; `Oblivion.exe` registers them with these defaults, read from
  the push before each name: `iLevelUpSkillCount` 10; `iLevelUp01Mult` to
  `iLevelUp04Mult` 2; `iLevelUp05Mult` to `iLevelUp07Mult` 3; `iLevelUp08Mult`
  and `iLevelUp09Mult` 4; `iLevelUp10Mult` 5. `Oblivion.esm` does carry the
  skill-use curve, `fSkillUseExp` 1.5 and `fSkillUseFactor` 0.35, and its 21
  `SKIL` records each give a governing attribute, a specialization and two use
  values (Athletics 0.03 / 0.04, Speechcraft 2.4 / 1).
- **Morrowind's leveling matches Oblivion's.** Unlike Oblivion, `Morrowind.esm`
  stores its leveling GMSTs: `iLevelupTotal` 10 and `iLevelUp01Mult` to
  `iLevelUp10Mult` 2, 2, 2, 2, 3, 3, 3, 4, 4, 5, the same table as Oblivion's
  engine defaults, plus skill XP modifiers by category (`fMajorSkillBonus`
  0.75, `fMinorSkillBonus` 1.0, `fMiscSkillBonus` 1.25, `fSpecialSkillBonus`
  0.8) and `fLevelUpHealthEndMult` 0.1. OpenMW's
  `apps/openmw/mwmechanics/npcstats.cpp` reads exactly these. One skill-use
  rule set with per-game settings covers both games.
- **Fallout perks share Skyrim's record structure, not its entry points.**
  `Fallout3.esm` has 87 `PERK` records, `FalloutNV.esm` 176, `Skyrim.esm` 375.
  All use `DATA`, `PRKE`, `PRKC`, `CTDA`, `EPFT`, `EPFD`, `PRKF`, `EPF2` and
  `EPF3`, with the same three entry kinds (quest stage, ability, entry point);
  New Vegas adds icons (169) and inline scripts on 5 perks, Skyrim adds
  `VMAD`, `NNAM` and `CIS2`. The entry points differ (xEdit's lists): Fallout
  3 has 37, New Vegas 74 (Fallout 3's list is its first 37), Skyrim 92. Only
  12 of New Vegas's exist in Skyrim by name, 3 at the same index. Counted over
  the actual perk entries, at least 99 of Fallout 3's 118 (84%) and 131 of New
  Vegas's 212 (62%) convert without new work: every quest-stage and ability
  entry, plus the entry points Skyrim has by name. The rest are Fallout-only:
  most-used are action point cost, VATS to-hit chance, gun spread and damage
  threshold.
- **New Vegas's XP rules are GMSTs.** `iLevelUpSkillPointsBase` 11,
  `iLevelUpSkillPointsInterval` 1, `fAVDTagSkillBonus` 15, `fBookPerkBonus` 3,
  `iTraitMenuMaxNumTraits` 2, and XP rewards per difficulty for kills,
  picked locks, hacked terminals, speech challenges and map markers
  (`iXPRewardKillOpponent*`, `iXPRewardPickLock*`, `iXPRewardHackComputer*`,
  `iXPLevelKill*`, `iXPRewardDiscoverMapMarker` 10). `Fallout3.esm` carries
  the same skill-point settings (11, 1).
- **Fallout's engine defaults, read from each game's GECK** (the editor shares
  the engine's setting table without the game exe's DRM; the method was
  checked against Oblivion.exe's known values first). New Vegas:
  `iLevelsPerPerk` 2, a perk every second level. Fallout 3 has no
  `iLevelsPerPerk` at all, so its one-perk-per-level schedule is fixed in
  code. Both: `iLevelUpSkillPointsBase` 7 and `iLevelUpSkillPointsInterval` 2,
  which both masters override to 11 and 1 (a plugin's GMST beats the engine
  default, as the data file assumes), and `iXPBase` 200.

How much converted content depends on these systems, counted over the
exports' scripts (`SCPT` text plus dialogue and quest-stage result scripts)
and their conditions:

| | Oblivion | Fallout 3 | New Vegas |
|---|---|---|---|
| Script bodies / `GameMode` blocks | 9,992 / 1,327 | 3,474 / 524 | 6,140 / 663 |
| Attribute or S.P.E.C.I.A.L. reads and writes in scripts | 54 in 14 scripts | 32 in 18 | 66 in 19 |
| Fame, infamy, karma in scripts | 244 in 212 (fame, infamy) | 67 in 43 (karma) | 43 in 42 (karma) |
| `RewardXP` | none | 60 in 58 scripts | 265 in 262 |
| Perks added, tested or removed in scripts | none | 44 in 16 | 256 in 107 |
| Reputation commands | none | none | 510 in 249 |
| Pip-Boy notes | none | 249 in 33 | 128 in 75 |
| Actor-value conditions (all values) | 120 | 869 | 1,481 |
| Biggest condition dependencies | class tests 114, `GetActorValue` on Illusion, fame and infamy | karma 277, `HasPerk` 115 | Speech 540, Barter 209, `GetReputationThreshold` 1,581, `HasPerk` 124 |

So for Oblivion, fame and infamy matter more than attributes; for Fallout,
dialogue skill checks, karma, reputation and perks dominate.

**Fixed (`fix/fallout-av-conditions`, upstream PR #69): Fallout actor-value
conditions were translated with Oblivion's table.**
`fallout_function` remaps a FO3/FNV condition's function, but its actor-value
parameter then goes through `_TES4_AV_TO_TES5` in `_convert_params`
(`tes5_import/base/conditions.py`), and Fallout numbers its actor values
differently. Run through `convert_ctda` on the exports' real conditions:

| Condition tests | New Vegas | Fallout 3 | Converts to |
|---|---|---|---|
| Karma | 42 | 275 | the player's Illusion skill |
| Charisma | 27 | 37 | Health |
| Intelligence | 42 | 38 | Magicka |
| Repair | 14 | 3 | Infamy |
| Speech | 540 | none | dropped (the check always passes) |
| Medicine, Science, Strength | 137 | 75 | dropped |
| Barter | 209 | 26 | Speech (correct by coincidence) |

The fix is independent of this plan and is written, on its own branch
(`fix/fallout-av-conditions`): a Fallout actor-value table in
`conditions_falloutnv.py` maps the 25 values Skyrim has with the same meaning
(Speech and Barter to Speech, Lockpick to Lockpicking, Repair to Smithing,
Sneak, Health, Carry Weight, the resistances and others) and drops the rest
until pieces D and E give them a GLOB to read. It also pads Fallout's older
20- and 24-byte conditions to 28 bytes, so they are read with Fallout's
function numbering instead of Oblivion's.

**Fixed (same branch): converted Fallout scripts passed most Fallout-only
actor values through as names Skyrim does not know.** Scripts translate by name, not index
(`script_convert/commands.py` `actor_value`), through Oblivion's
`ACTOR_VALUE_MAP`; a name missing from it is emitted unchanged. Skyrim's
actor-value names, read from `CreationKit.exe`'s name table, do not include
most of Fallout's, and an unknown name reads 0 and rejects writes
([script_convert.md](../../commentary/script_convert.md#skyrim-has-no-attributes)).
Counted over the exports' `SCPT` text and the result
scripts in `INFO`, `QUST`, `PACK`, `TERM`, `PERK` and `NOTE`:

| | Fallout 3 | New Vegas |
|---|---|---|
| Actor-value calls | 1,008 | 1,062 |
| Naming a value Skyrim does not know | 144 | 227 |
| Repair | 48 | 49 |
| Medicine, Science, Explosives | 32 | 97 |
| Karma | 32 | 4 |
| Perception, Charisma | 9 | 27 |
| Speech, Barter, Lockpick | 7 | 13 |
| Weapon skills, Survival, RadiationRads, ActionPoints, XP, BloodyMess | 16 | 37 |

Repair, Speech, Barter and Lockpick have a Skyrim value and should map the way
the condition fix maps them. Perception and Charisma also read 0, while
Strength, Endurance, Intelligence, Agility and Luck read 100, because
`TES4_ATTRIBUTES` lists Oblivion's attributes and five of them share a
name with S.P.E.C.I.A.L. stats: the same kind of gate falls open for one stat
and shut for another. The script-side fix is on the same branch: the four
renames, Perception and Charisma read as the other five stats do, and the
values Skyrim lacks become inert reads, which drop out of a comparison rather
than deciding it.

<a id="skill-source"></a>**A folded skill increase can be credited to its source
skill from authored data**, without a DLL. `OnStoryIncreaseSkill` names only
the Skyrim skill, so the rules keep the context themselves, on a player alias,
from vanilla events that fire only when the player acts:

- **Blade or Blunt** (One-Handed, Two-Handed): `OnObjectEquipped` records the
  weapon in hand. Import already knows each weapon's Oblivion type, so piece A
  writes Blade and Blunt weapons into two form lists and the rules test
  membership. This follows the authored skill rather than the Skyrim weapon
  type the conversion chose, so an Oblivion axe stays Blunt.
- **Mysticism** (Alteration): converted Mysticism effects are Alteration, or
  Conjuration for a few (`tes5_import/record_types/magic.py`
  `SCHOOL_TO_AV`); scripts and conditions read it as Alteration too since
  upstream's 2026-09-28 fix ([B3](../../plans/character_sheet.md#bug-mysticism)).
  `OnSpellCast` records the last spell cast; a form list of converted
  Mysticism spells credits the increase. The rules' own Mysticism GLOB then
  replaces the stand-in.
- **Mercantile or Speechcraft** (Speech): Speech gained while the barter menu
  is open is Mercantile. The rules take a Speech snapshot when the menu opens
  and credit the difference when it closes (SKSE's `RegisterForMenu`, which
  converted scripts already use), so the result does not depend on whether
  the story event arrives before or after the menu closes.
- **Skill books and trainers** raise a skill with no use to observe, and a
  Blunt book read with a sword equipped would be misread. Both records name
  their Oblivion skill (`BOOK` `DATA.Teaches`, read in `equipment.py`;
  trainers' `Teaches`, read in `actor_common.py`), so piece A records it and
  the rules credit it directly: for books, the equip event Skyrim sends when a
  book is read ([checked](#in-game-results)); for trainers, the training
  menu's snapshot.

<a id="in-game-results"></a>**Checked in game** with a probe plugin in a
near-vanilla profile: vanilla Papyrus only, a monitor polling the 18 skill
levels every 0.1 s, a player alias logging equips and casts, and a quest on the
`SKIL` event node logging what it sees at each event.

- **Outside menus the event is prompt.** Each of the 8 increases earned in
  game mode logged its event within 0.26 s of the level change, 6 of them
  before the poll noticed it. The quickest swap afterward took 0.9 s for a
  spell and 2.9 s for a weapon, and every event still saw the Iron Sword or
  Flames that earned it. Crediting by the last weapon or spell recorded holds.
- **One event can carry several levels.** Six events each covered a jump
  (One-Handed 1 to 3 and 3 to 5, Destruction 15 to 20, 20 to 23 and 23 to 26,
  Sneak 15 to 20), with the event already seeing the final level.
- **Increases inside a menu share one event, sent after the menu closes.**
  Reading five skill books (three One-Handed, one Sneak, one Destruction)
  raised three skills by five levels and produced one event, for Destruction,
  when the menu closed; One-Handed and Sneak got none. Selling to a merchant
  raised Speech from 1 to 17 and produced one event, also after the menu
  closed. Counting events would lose most of these, which is why the rules
  compare snapshots instead.
- **An increase that arrives while the event quest is still running gets no
  event.** Casting Flames on enemies from Destruction 1 raised it to 9 and
  produced 7 events: the one for level 3 is missing. It came within 0.3 s
  of level 2, while the quest was still logging level 2, and the next event
  jumped from 2 to 4. So the Story Manager skips an increase while its quest
  is running rather than queueing it, which the snapshot also covers.
- **Reading a book sends the equip event**, inside the menu and as it happens,
  with the book as the object, so a skill book is credited from its authored
  skill with a vanilla event. Alias events run inside menus in real time;
  only the story event waits.
- **Console `SetAV` changes a skill without an event**, in either direction,
  so the snapshot takes a decrease as a new starting point, never as credit.
- **The player's limb conditions start at 100**, current and base, all seven,
  so converted Fallout scripts that pass the limb names through read healthy
  limbs, and a crippled check (`<= 0`) does not fire.
- **`OnInit` ran twice** on the monitor quest's first start, so the rules
  quest's setup must be safe to repeat, as TESGameSelect's already is.

- **`OnSpellCast` fires once when a cast begins**, including for a
  concentration spell: three Flames casts were logged while Destruction rose
  eight levels, one per press of the button, not per second held. So the last
  spell cast is the one being channeled, which is what the Mysticism crediting
  needs.
- **The console's `IncPCS` sends the event.** The console is a menu, so two
  `incpcs sneak` in one sitting arrived as one event (Sneak 15 to 17) when it
  closed; each later one arrived on its own.

<a id="level-up-in-the-exe"></a>**Checked in the executable**, the unpacked
1.6.1170 build. Every Address Library id below resolves on all 14 shipped
versionlibs, 1.6.317 to 1.7.104 (`tools/validate/stable_id_check.py`):

| Id | 1.6.1170 RVA | What it does |
|---|---|---|
| 41561 | `0x77ae60` | Skill advance: adds skill experience, raises the skill while it passes the skill's threshold, sends the skill-increase event, and adds `level × fXPPerSkillRank` to the player's experience |
| 41565 | `0x77b400` | "Can level up": the player's experience (skill data `+0`) against the **stored** threshold (`+4`) |
| 41566 | `0x77b420` | Advance level: level plus one, the level-increase event |
| 41567 | `0x77b4d0` | Level-up bookkeeping: subtracts the threshold (or resets experience), stores the next threshold from `fXPLevelUpBase` + level × `fXPLevelUpMult`, restores Health, Magicka and Stamina |
| 51917 | `0x934700` | Level-up screen confirm: the chosen value plus `iAVDhmsLevelUp`, Carry Weight plus `fLevelUpCarryWeightMod` for Stamina, then the bookkeeping |
| 52538 | `0x9674c0` | Adds to the perk count (player `+0xb09`, a byte), or to the werewolf and Vampire Lord point global in those trees |
| 41563 | `0x77b350` | Set level (console `SetLevel` on the player): the new level, then the bookkeeping with experience reset; no screen, no perk point |
| 41560 | `0x77ae10` | Experience and a threshold computed from the settings, read by the "Level up available" message (`0x921207`) |
| 52510 | `0x95f710` | The Skills menu's message handler, holding the level-up branch |
| 403521 | `0x31874f8` | The player singleton, as the runtime already uses it |
| 374908, 374911 | `0x20058e0`, `0x20058f8` | The `fXPLevelUpBase` and `fXPLevelUpMult` values |

The whole natural level-up happens in the Skills menu (`0x9606b7` to
`0x96072f`): only when "can level up" is true does it advance the level, open
the level-up screen and add one perk point. The perk count is written in only
four places: reset to 0, that add, a Legendary skill's refund, and
`Game.AddPerkPoints`. So keeping the stored threshold out of reach withholds
the level, the screen and the perk point together, and the settings keep the
message quiet. SKSE's `SetPlayerExperience(0)` alone would leave a gap:
experience gained inside a menu, as from skill books, is only seen when the
menu closes, and going straight to the Skills menu would level up first. The
ids hold on every build; the field offsets (skill data at player `+0x9b8`,
the perk count at `+0xb09`, experience and threshold at `+0` and `+4`) are
read from 1.6.1170 only and need checking in another build's executable
before the runtime relies on them there.
