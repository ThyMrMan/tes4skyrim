// Headless gate for the character data reader and the skill rate math: every
// expected number is worked by hand from Oblivion's settings and Skyrim's own
// One-Handed rates (6.3 / 0 / 2 / 0, fSkillUseCurve 1.95).
// See: docs/commentary/tes_runtime_character.md#skill-rates

#include <cmath>
#include <cstdio>

#include "character_rates.h"

using namespace tesruntime;

namespace {

int g_failures = 0;

void Check(bool ok, const char* what) {
    std::printf("  [%s] %s\n", ok ? "ok" : "FAIL", what);
    if (!ok) ++g_failures;
}

bool Near(float a, float b) { return std::fabs(a - b) <= 1e-3f * (std::fabs(b) + 1.0f); }

// Oblivion.esm's file, trimmed to the parts the rules read.
const char* kOblivion = R"({
  "version": 1, "plugin": "Oblivion.esm", "rules": "skill-use",
  "skills": [
    {"name": "Blade", "specialization": "Combat", "skyrim": ["OneHanded", "TwoHanded"]},
    {"name": "Blunt", "specialization": "Combat", "skyrim": ["OneHanded", "TwoHanded"]},
    {"name": "Mercantile", "specialization": "Stealth", "skyrim": ["Speechcraft"]},
    {"name": "Speechcraft", "specialization": "Stealth", "skyrim": ["Speechcraft"]},
    {"name": "Athletics", "specialization": "Combat", "skyrim": []}
  ],
  "settings": {"fSkillUseExp": 1.5, "fSkillUseFactor": 0.35,
               "fSkillUseMajorMult": 0.75, "fSkillUseMinorMult": 1.25,
               "fSkillUseSpecMult": 0.75},
  "classes": [
    {"id": "Knight", "specialization": "Combat", "major": ["Blade", "Speechcraft"]},
    {"id": "Thief", "specialization": "Stealth", "major": ["Sneak"]}
  ]
})";

// A dependent plugin that changes the Thief.
const char* kExpansion = R"({
  "version": 1, "plugin": "Knights.esp", "rules": "skill-use",
  "classes": [{"id": "Thief", "specialization": "Stealth", "major": ["Mercantile"]}]
})";

const int kOneHanded = 0;
const int kSpeech = 11;
const int kEnchanting = 17;

CharacterRules Rules() {
    CharacterRules rules;
    const Json doc = Json::Parse(kOblivion);
    rules.Load(doc);
    rules.AddClasses(doc);
    rules.AddClasses(Json::Parse(kExpansion));
    return rules;
}

void TestReader() {
    std::printf("reader\n");
    const CharacterRules rules = Rules();
    Check(rules.sources[kOneHanded].size() == 2, "One-Handed is credited to Blade and Blunt");
    Check(rules.sources[kSpeech].size() == 2, "Speech is credited to Mercantile and Speechcraft");
    Check(rules.sources[kEnchanting].empty(), "Enchanting is credited to nothing");
    Check(Near(rules.Setting("fSkillUseExp", 0.0f), 1.5f), "settings are read");
    Check(Near(rules.Setting("fMissing", 7.0f), 7.0f), "a missing setting falls back");
    Check(rules.classes.at("Thief").major.count("Mercantile") == 1,
          "a later file's class replaces an earlier one");
    CharacterRules other;
    Check(!other.Load(Json::Parse(R"({"rules": "xp"})")), "a non-skill-use file is refused");
    Check(SkyrimSkillIndex("Enchanting") == kEnchanting && SkyrimSkillIndex("Blade") == -1,
          "Skyrim skill names map to their index");
}

void TestClassMultiplier() {
    std::printf("class multiplier\n");
    const CharacterRules rules = Rules();
    const CharacterClass* knight = &rules.classes.at("Knight");
    const CharacterClass* thief = &rules.classes.at("Thief");
    Check(Near(ClassMultiplier(rules, knight, kOneHanded), 0.75f * 0.75f),
          "a major Combat skill of a Combat class: major times specialization");
    Check(Near(ClassMultiplier(rules, knight, kSpeech), 0.75f),
          "a major skill outside the specialization: major alone");
    Check(Near(ClassMultiplier(rules, thief, kOneHanded), 1.25f),
          "a minor skill outside the specialization: minor alone");
    Check(Near(ClassMultiplier(rules, thief, kSpeech), 0.75f * 0.75f),
          "the most favorable of the folded skills wins");
    Check(Near(ClassMultiplier(rules, knight, kEnchanting), 1.0f),
          "a skill credited to nothing keeps 1");
    Check(Near(ClassMultiplier(rules, nullptr, kOneHanded), 1.0f), "no class keeps 1");
}

void TestSourceRates() {
    std::printf("source rates\n");
    const SkillRates oneHanded{6.3f, 0.0f, 2.0f, 0.0f};
    const float vanillaAt25 = 2.0f * std::pow(25.0f, 1.95f);
    const SkillRates same = SourceRates(oneHanded, 1.95f, 1.5f, 1.0f);
    Check(Near(Threshold(same, 1.5f, kAnchorLevel), vanillaAt25),
          "at the anchor level the skill needs what Skyrim asks");
    Check(Near(Threshold(same, 1.5f, 100.0f) / Threshold(same, 1.5f, 25.0f), 8.0f),
          "the threshold grows by Oblivion's exponent: 4^1.5 from 25 to 100");
    Check(same.useMult == 6.3f && same.useOffset == 0.0f, "the use rates are Skyrim's");
    const SkillRates major = SourceRates(oneHanded, 1.95f, 1.5f, 0.5625f);
    Check(Near(Threshold(major, 1.5f, 50.0f), 0.5625f * Threshold(same, 1.5f, 50.0f)),
          "the class multiplier scales every level");
    const SkillRates offset = SourceRates({1.0f, 0.0f, 0.25f, 300.0f}, 1.95f, 1.5f, 1.0f);
    Check(Near(Threshold(offset, 1.5f, kAnchorLevel), 0.25f * std::pow(25.0f, 1.95f) + 300.0f),
          "Smithing's improve offset folds into the anchor");
}

}  // namespace

int main() {
    TestReader();
    TestClassMultiplier();
    TestSourceRates();
    std::printf("%s (%d failure%s)\n", g_failures ? "FAILED" : "passed", g_failures,
                g_failures == 1 ? "" : "s");
    return g_failures ? 1 : 0;
}
