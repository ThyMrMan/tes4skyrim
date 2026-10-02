// FO3/FNV gun shot trace: a diagnostic, millisecond log of each player shot.
//
// Gun fixes guessed from second-resolution logs kept failing, so this records
// what the engine actually did, one line per step, stamped with the local
// time to the millisecond (the flight recorder's clock):
//
//   * every animation event the player's graphs raise while a gun is held,
//     with the graph that raised it (a double shot shows which clip and
//     state fired each round);
//   * each step FalloutRuntime takes (the press it sends, each Fire call);
//   * the launch data Fire hands Projectile::Launch (id 44108): origin,
//     heading, pitch and desired target, next to the camera's position and
//     forward axis and the player's position and look angles;
//   * where each round stopped, from its reference polled every frame.
//
// LaunchData, as Fire (id 18102) fills it in 1.6.1170: origin +0x08,
// projectile base +0x20, shooter +0x28, heading +0x48, pitch +0x4c,
// desired target +0x58.
// See: docs/commentary/tes_runtime_guns.md#shot-trace

#pragma once

namespace tesruntime {

// Hooks Projectile::Launch and starts the round poll. False leaves the game untouched.
bool InstallShotTrace(void** player, void** playerCamera);

// An animation event `tag` raised by `graph` on `actor` (logged for the player holding a gun).
void TraceAnimEvent(void* actor, const char* tag, void* graph);

// A FalloutRuntime step on `actor` (logged for the player).
void TraceStep(void* actor, const char* what);

}  // namespace tesruntime
