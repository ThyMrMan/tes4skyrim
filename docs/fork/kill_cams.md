# Kill cams and killmoves for converted weapons

Design only; status is in the [roadmap](ROADMAP.md#stability).

- [The problem](#problem)
- [Two features, two controls](#features)
- [Options](#options)
- [Suggested order](#order)

## <a id="problem"></a>The problem

Skyrim's finishing moves fire on converted weapons that were never made for
them. FO3/FNV's police baton converts as a one-handed sword, passes the sword
killmove conditions, and plays a blade animation that lines up badly with the
baton mesh. Kill cams also fire on Fallout guns and Oblivion weapons, which
the source games never did.

## <a id="features"></a>Two features, two controls

| Feature | What it is | Controlled by |
|---|---|---|
| Kill cam | The slow-motion camera on a killing blow (ranged, spell, sometimes melee) | Game settings: `fKillCamBaseOdds` (1.0), `fKillCamLevelBias` (0.01), `fKillCamLevelFactor` (0.5), `fKillCamLevelMaxBias` (0.1), `iKillCamLevelOffset` (4) |
| Killmove | The paired melee finishing animation | Vanilla IDLE records in `Skyrim.esm`, picked by their conditions (weapon type keywords among them); `fKillMoveMaxDuration` (10) and `fCombatKillMoveDamageMult` (10) only tune it |

Values are from the offline CK wiki's `Game_Settings.html`. Which setting, if
any, gates melee killmoves as a whole is **unverified**: check the CK wiki,
UESP and the 1.6.1170 exe before building.

Game settings are global. A GMST record in a converted plugin would apply to
every world in the all-worlds profile, so per-game control has to happen at
run time ([both profiles](ROADMAP.md); no base-game overrides).

## <a id="options"></a>Options

1. **Kill cam toggle at run time.** A player-alias script sets
   `fKillCamBaseOdds` to 0 with SKSE `Game.SetGameSettingFloat` while a
   converted weapon is equipped, and restores the saved value when it isn't
   (and on load). Keyed on the weapon's plugin, not the character, so
   Skyrim weapons keep Skyrim's behavior in every world. A per-game GLOB
   switch, like `TES4DialoguePause`
   ([dialogue pause](../commentary/tes5_import_dialogue.md#fallout-dialogue-pause)),
   lets a player turn it back on. Simple and well understood.
2. **Killmoves: make converted weapons fail the conditions.** If the vanilla
   killmove idles test `WeapType*` keywords, converted weapons could carry a
   fork keyword instead of `WeapTypeSword` and friends. Needs a census first
   of everything that reads those keywords (perks, animations, enchantment
   conditions, sheathing), since dropping them changes more than killmoves.
3. **Killmoves: suppress at run time.** The same watcher script blocks
   killmoves while a converted weapon is in hand, if Skyrim exposes a way to
   do it (a setting, an actor value, or the `NoKillmove`-style flags on
   actors). Engine check needed.
4. **Killmoves: a DLL hook** on killmove selection that refuses converted
   weapons. Last resort, per the fork's rules.

Rejected: editing the vanilla killmove IDLE conditions (a base-game override)
and a GMST record in the converted plugin (global, breaks the all-worlds
profile).

## <a id="order"></a>Suggested order

1. Census the conditions on the vanilla killmove idles (`Skyrim.esm` dump in
   `references/`) and the readers of the `WeapType*` keywords; decide between
   options 2 and 3.
2. Build option 1 (kill cam toggle), with a test of the restore path.
3. Build the chosen killmove option.
