# TESGameSelect: the new-game menu and the travel scroll

**Code:** `tools/release/make_game_select_esp.py`,
`TESGameSelect/scripts/source/*.psc`, `tests/test_game_select_esp.py`.
User-facing description: [TESGameSelect/README.md](../../TESGameSelect/README.md).

## <a id="records"></a>Records and FormIDs

The plugin masters only Skyrim.esm. Every converted game's form is resolved at
runtime through `Game.GetFormFromFile`, which takes the id within that game's
own file (the low 24 bits), so any subset of games loads in any order.

Own FormIDs are hand-assigned constants, never derived, so adding records
never moves an existing one:

| Range | Records |
|---|---|
| `0x800`–`0x807` | GLOB: one "installed" flag per converted game, Skyrim's, and `TESGS_CurrentGame` |
| `0x80F` | FLST of the new-game prompt variants |
| `0x810`… | MESG: 2^(gated games) prompt variants — the block GROWS with each game |
| `0xA00`–`0xA02` | QUST selector, QUST travel, BOOK scroll |
| `0xAF0`–`0xAF7` | GLOB: the player's TES4 attributes, Strength to Luck, which the [character rules](character_rules.md#attributes) write and `TES4Polyfill` reads; Fallout's S.P.E.C.I.A.L. shares the five of the same name |
| `0xAF8`–`0xAF9` | GLOB: the player's Perception and Charisma, the S.P.E.C.I.A.L. stats with no TES4 attribute ([Fallout's rules](character_rules.md#fallout)) |
| `0xAFF` | FLST of the travel-menu variants |
| `0xB00`… | MESG: 2^(games) travel variants — also grows |

`test_no_two_records_share_a_formid` guards the growing blocks: going from four
gated games to five once ran the prompt block straight through the selector
quest.

## <a id="mq101-takeover"></a>The MQ101 takeover

The override is vanilla MQ101 read out of the installed Skyrim.esm, with our
script appended and two fragments retargeted. Nothing else changes: 54 aliases,
every other fragment and every log entry survive byte-identical.

- **Stage 0, entry 0** (`Fragment_2`, gated `GetGlobalValue(MQQuickstart) == 0`,
  the real new-game path) runs `RunTakeover`. An earlier build APPENDED an
  unconditional entry instead; it ran alongside `Fragment_2`, so stage 10 still
  fired — title credits, cart audio, and a tug-of-war over the player.
- **Stage 10, entry 0** (`Fragment_4`, the opening itself) runs `RunOpening`,
  which parks the player's items in a vanilla empty chest
  (`TreasChestSmallEMPTYNoRespawn`, `000F8478`) placed in the holding cell,
  calls vanilla `Fragment_4` itself, then gives everything back. Vanilla's
  `RemoveAllItems` there strips the player base record's items (16 entries in
  Skyrim.esm `NPC_ 00000007`: iron armor, potions, 140 gold — kept only by a
  main-menu `coc`), and a player who begins Skyrim from another game must not
  lose their gear to it. Worn items come back unequipped.
- **The new-game takeover strips those base-record items itself**
  (`RemoveAllItems`, which keeps quest items such as the Elder Scroll), whichever
  game is chosen: they are all the player has, and neither a converted game's
  start nor the stage-10 wrapper would otherwise remove them. The strip runs
  AFTER the load and the menu. Run before the load, it missed what the player
  put on while loading: the iron helmet and gauntlets survived into Nehrim.
- 🛑 **MQ101 is never stopped.** It is Run Once (DNAM flags `0x0100`, bit 8 in
  xEdit's `wbDefinitionsTES5.pas`), so a stopped MQ101 can never be started
  again. An earlier build stopped it once another game was chosen, and the
  scroll's "Begin Skyrim" then did nothing. It stays running at stage 0, before
  the cart, until `BeginSkyrim` replays `Fragment_2`. A save from that build
  cannot begin Skyrim, and the scroll says so.
- **`Selecting`** is true from the prompt until the takeover has started the
  chosen game. `ChosenGame` reads Skyrim (0) meanwhile, and the travel quest's
  `Sync` adopted that as the current game once, so the menu offered "Return to
  Skyrim" in a game that began in Nehrim.

The menu is shown once, after the load: a `Message.Show()` issued during the
initial load is drawn over the main menu, bashed by the load screen and drawn
again — the "popup appears twice" bug. The selector is not Start Game Enabled
for the same reason: `OnInit` fires again on quest restart or when the plugin
is added to a save.

## <a id="opening-hold"></a>Openings that start themselves

Skyrim starts every Start-Game-Enabled quest of every loaded plugin on every
new game. Nehrim marks its opening that way (`Charactergen` 0002466E and `MQ00`
00000811, DATA.Flags 1): `CharGenQuest` sets its own stage 5 after five update
ticks, which moves the player into Nehrim's start cave, and Nehrim's
`GlobalplayerScript` sets `MQ00` stage 1 the first time it runs. Oblivion,
Morroblivion and FalloutNV leave their openings off the `.seq`; the TES3 games
wait for `CharGenState`.

The hold comes in two parts, because stopping a quest already in the journal
shows it failing:

- **`HoldOpeningMovers`**, before anything else: what would move the player.
  `Reset()` then `Stop()` on `Charactergen` (`Reset` does nothing on a stopped
  quest), and `Stop()` on the player-script quest below.
- **`HoldOpeningsFor(game)`**, once the prompt closes: the movers again (a quest
  the engine started after MQ101 was not yet running the first time), plus
  `MQ00` only when the choice is not Nehrim. Holding `MQ00` before the choice
  made "Schatten und Licht" start, fail and start again when Nehrim was picked.

Background quests keep running. `BeginNehrim` restarts all three and sets
`MQ00` stage 1 itself, because the player script sets it only once and may
have spent that before the hold. None of the three is Run Once (all DNAM
`0x11`), so a restart always works.

Resetting `MQ00` alone lost a race in game: Nehrim's `GlobalplayerScript` polls
every 0.1 s with no running check, and its one-shot `TES4SetStage(MQ00, 1)`
STARTS the quest, so a first tick after the hold brought "Schatten und Licht"
straight back. The hold therefore also stops Nehrim's `TES4PlayerScripts` quest
(`0083563B`, derived from its EditorID), and stopping a quest cancels its
aliases' update registrations (CK wiki, `RegisterForSingleUpdate`). The travel
quest repeats the hold on every load until Nehrim is begun, which also repairs
a save whose opening slipped through.

## <a id="starting-equipment"></a>Starting equipment

Starting a game adds and equips what that game's own player record carried,
and never clears the inventory; only the new-game takeover strips Skyrim's
base-record items (see [#mq101-takeover](#mq101-takeover)).

| Game | Items |
|---|---|
| Oblivion, Morroblivion | Oblivion.esm `NPC_ 00000007`: sack-cloth shirt/pants/sandals, wrist irons |
| Nehrim | Nehrim.esm `NPC_ 00000007`: vest, trousers, moccasins, torch, diary, MQ00 note |
| Morrowind | Morrowind.esm `Player`: `common_shirt_01`, `common_pants_01`, `common_shoes_01` |
| Arktwend | Arktwend's own `Player`: `common_robe_02_rr` plus the same three |
| FalloutNV | nothing: `VCG00` stage 0 removes the Pip-Boy, the only thing its record carries |

The TES3 exporter drops the `Player` NPC record, so these came from the source
files. Arktwend's ids were read from an authored-mode export (the only mode it
may be built in — see
[tes4_export_morrowind.md](tes4_export_morrowind.md#masters)); its clothing
records hash to the same ids as Morrowind.esm's. The robe is equipped last so it
is the one worn.

## <a id="travel-scroll"></a>The travel scroll

A BOOK carrying vanilla `DA04ElderScroll`'s bounds, model and inventory art
(read from Skyrim.esm at build time, so nothing ships but the ESP and scripts).
Its script opens the travel menu from `OnEquipped` for the player, the hook
vanilla `ElderScrollScript` uses (reading a book equips it). `Utility.Wait`
does not elapse while a menu is open, so the reading plays once the book and
inventory close.

`ReadScroll` is vanilla `ElderScrollScript.OnEquipped`'s reading away from the
Time-Wound, step for step, disassembled from the LE `Skyrim - Misc.bsa` copy:
menu controls off; if standing, `ForceFirstPerson`, `ElderScrollHandAttachArmor`
(`000F71DF`) worn, `IdleReadElderScroll` (`000EC9D0`), wait 1.05 s;
`OBJElderScrollBlindIn2D` (`0010A95A`), wait 0.5 s; `ShakeCamera(None, 0.5,
1.5)`; `FXReadElderScrollEffect` (`00044F20`) for 8.1 s;
`FXReadScrollsBlindImod` (`00044F3F`); wait 1 s and 2 s. The travel menu goes
here, where vanilla's reading ends, then `IdleStop` (`000E4242`), the hand
scroll removed, menu controls back, wait 1.9 s, `OBJElderScrollBlindOut2D`
(`0010A95B`). A first build forced third person and hooked `OnRead`, and the
idle never played. Controls return before any travel, so an opening that
disables them itself is not undone.

🛑 **Never compare a Papyrus array to `None`.** The bundled compiler emits
`cast ::temp, none` into an array-typed temp; the VM rejects it ("Cannot cast
from None to Bool[]") and the `array_create` into the same temp then fails
("Cannot create an array into a non-array variable"). That killed the first
build's travel menu before it opened. A Bool flag records whether the arrays
exist.

The travel quest is Start Game Enabled and listed in the `.seq`, so it also
starts on a save made before the scroll existed. Its alias `Scroll` creates the
book in alias `Player`'s inventory with the Quest Object flag (`FNAM 0x04`,
`ALCA 0x80000000 | alias`, as vanilla quest items are), so it cannot be dropped
or sold and survives `RemoveAllItems`.

Travel is Morrowind's Mark and Recall
([morrowind_runtime.md](morrowind_runtime.md#teleport-effects)) in plain
Papyrus, since the plugin must not need SKSE or the DLL: a heading marker
(`XMarkerHeading`, `00000034`) placed at the player holds the cell or
worldspace, position and facing, and `MoveTo` returns the player to it. One
marker is kept per started game and deleted once used. Beginning a game runs
that game's normal start without the race menu (the character already exists);
the game's own opening still runs, so a TES3 chargen or Doc Mitchell's
reflectron can still offer theirs. Travel is refused in combat and while
movement controls are off, which also covers every opening sequence.

## <a id="menu-variants"></a>Menu variants

A MESG button's text is fixed and `Message.Show()` returns only 0–9 (CK wiki),
so a menu holds at most 10 buttons. Two buttons per game ("Begin" and "Return
to") would need 15. Instead each game has one button and the whole menu comes
in one variant per started-game set (2^7 = 128), the script showing entry
`[startedMask]` of the FLST — the same device the new-game prompt uses for its
DESC, which carries no condition. Conditions still hide absent games and the
current one; a hidden button does not renumber the rest, so the returned index
is the game id and index 7 is "Stay".

## <a id="id-migration"></a>Game numbering

The button index IS the game id, in the order Skyrim, Cyrodiil, Vvardenfell
(vanilla Morrowind), Vvardenfell (Morroblivion), Nehrim, Arktwend, Mojave, with
Fallout 3 reserved next. Saves from the first numbering (Oblivion 1,
Morroblivion 2, Nehrim 3, FalloutNV 4, Morrowind 5, Arktwend 6) store
`ChosenGame` under it; `IdVersion` defaults to 0 on those saves and
`MigrateIds` renumbers once.
