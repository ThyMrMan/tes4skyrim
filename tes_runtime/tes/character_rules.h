// Skyrim's own skill rates and leveling while a converted game's character
// rules are on, all in memory and never in a record or the save:
//   * each skill's AVSK rates and fSkillUseCurve follow the source game's
//     curve and the player's class (character_rates.h);
//   * Skyrim's level-up, its screen and its perk point are withheld, and the
//     "Level up available" message stays quiet;
//   * the rules set the player's level, which leveled lists scale by.
//
// Off until a rules quest turns it on, and off again at every load or new
// game, so a character playing Skyrim's own rules is never touched. A rules
// quest talks to it with mod events (akSender any form):
//   SendModEvent("TESCharacterRules", "<plugin>", 1.0)  on, the plugin's file
//   SendModEvent("TESCharacterRules", "", 0.0)          off
//   SendModEvent("TESCharacterClass", "<class EditorID>", 0.0)
//   SendModEvent("TESCharacterLevel", "", <level>)
// See: docs/commentary/tes_runtime_character.md

#pragma once

#include "skse_abi.h"

namespace tesruntime {

// Reads every character.json sidecar, hooks the level-up check and registers
// the mod-event sink. False, logged, when a piece is missing; what did
// resolve still works.
bool InstallCharacterRules(SKSEMessagingInterface* messaging);

// Checks, once the game's data has loaded, that each skill's rates sit where
// they are written; without that, the rates stay Skyrim's.
void CheckCharacterLayout();

// Restores Skyrim's own rates and leveling: every load and new game.
void CharacterRulesOff();

}  // namespace tesruntime
