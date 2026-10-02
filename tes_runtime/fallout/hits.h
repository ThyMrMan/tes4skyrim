// FO3/FNV hit log: one line per hit the player gives or takes.
//
// Every melee and projectile hit is applied by one routine (id 38586,
// Actor* + HitData*). This module owns the hook on it: it logs the weapon,
// the engine's damage breakdown and the health the hit cost, so a gun that
// "does nothing" can be told apart as a miss (no line), a weightless hit
// (total 0) or a hit the target shrugs off (health unchanged). Limb severing
// rides the same hook through SetFatalHitHandler.
//
// HitData, as id 38586 reads it in 1.6.1170: aggressor handle +0x18, weapon
// +0x30, then floats total +0x50, physical +0x54, limb +0x58, blocked share
// +0x5c.
// See: docs/commentary/tes_runtime_guns.md#hit-log

#pragma once

namespace tesruntime {

// Called after a hit takes an actor from alive to dead.
using FatalHitFn = void (*)(void* hitData, void* actor);

// Resolves the routine and patches its call sites. False leaves the game
// untouched (the reason logged).
bool InstallHitLog();

void SetFatalHitHandler(FatalHitFn fn);

}  // namespace tesruntime
