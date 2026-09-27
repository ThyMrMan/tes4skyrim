// The pure half of a converted game's character rules: the character data
// file read into what the runtime needs, and Skyrim's skill rates recomputed
// from it. No engine access, so character_rates_test.cpp runs it headless.
// See: docs/commentary/tes_runtime_character.md#skill-rates

#pragma once

#include <array>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "json.h"

namespace tesruntime {

// Skyrim's 18 skills are actor values 6 (OneHanded) to 23 (Enchanting).
constexpr int kFirstSkill = 6;
constexpr int kSkillCount = 18;

// The level at which a recomputed skill needs exactly what Skyrim's own rates
// ask for: where an Oblivion character's major skills start.
constexpr float kAnchorLevel = 25.0f;

// A skill's four AVSK numbers, in the record's order.
struct SkillRates {
    float useMult = 0.0f;
    float useOffset = 0.0f;
    float improveMult = 0.0f;
    float improveOffset = 0.0f;
};

// A source skill credited from a Skyrim skill.
struct SourceSkill {
    std::string name;
    std::string specialization;
};

struct CharacterClass {
    std::string specialization;
    std::set<std::string> major;
};

// One converted game's rules, from its masterless plugin's file plus every
// file's classes.
struct CharacterRules {
    std::map<std::string, float> settings;
    std::array<std::vector<SourceSkill>, kSkillCount> sources;
    std::map<std::string, CharacterClass> classes;
    // An XP game (Fallout): its skills rise only by points, never by use.
    bool xp = false;

    // Reads a file's settings and skills; false unless it is a skill-use or XP file.
    bool Load(const Json& doc);
    // Adds a file's classes, by EditorID; a later file replaces an earlier one.
    void AddClasses(const Json& doc);
    // A setting, or `fallback` when the file does not carry it.
    float Setting(const char* name, float fallback) const;
};

// A Skyrim skill's index from its actor value name ("OneHanded"), or -1.
int SkyrimSkillIndex(const std::string& name);

// The source game's skill-XP multiplier for `skill` under `cls`: its major or
// minor setting times its specialization setting, the most favorable of the
// source skills credited from it. 1 without a class or a source skill.
float ClassMultiplier(const CharacterRules& rules, const CharacterClass* cls, int skill);

// XP for the next skill level at `level`: improveMult * level^curve + offset.
float Threshold(const SkillRates& rates, float curve, float level);

// `vanilla` rewritten to follow `sourceCurve` scaled by `multiplier`, needing
// exactly what `vanilla` needs at kAnchorLevel when the multiplier is 1. The
// use rates, Skyrim's per-action currency, are kept.
SkillRates SourceRates(const SkillRates& vanilla, float vanillaCurve,
                       float sourceCurve, float multiplier);

// `vanilla` with no skill XP per use, for an XP game: the level curve is kept.
SkillRates XpRates(const SkillRates& vanilla);

}  // namespace tesruntime
