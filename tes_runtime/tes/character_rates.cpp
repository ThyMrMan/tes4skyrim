#include "character_rates.h"

#include <algorithm>
#include <cmath>

namespace tesruntime {

namespace {

// Skyrim's skill actor value names, from kFirstSkill.
constexpr const char* kSkyrimSkills[kSkillCount] = {
    "OneHanded", "TwoHanded", "Marksman", "Block", "Smithing", "HeavyArmor",
    "LightArmor", "Pickpocket", "Lockpicking", "Sneak", "Alchemy", "Speechcraft",
    "Alteration", "Conjuration", "Destruction", "Illusion", "Restoration",
    "Enchanting",
};

}  // namespace

int SkyrimSkillIndex(const std::string& name) {
    for (int i = 0; i < kSkillCount; ++i) {
        if (name == kSkyrimSkills[i]) return i;
    }
    return -1;
}

bool CharacterRules::Load(const Json& doc) {
    if (doc["rules"].asString() != "skill-use") return false;
    for (const auto& [name, value] : doc["settings"].fields()) {
        settings[name] = static_cast<float>(value.asNumber());
    }
    for (const Json& skill : doc["skills"].items()) {
        const SourceSkill source{skill["name"].asString(),
                                 skill["specialization"].asString()};
        for (const Json& skyrim : skill["skyrim"].items()) {
            const int index = SkyrimSkillIndex(skyrim.asString());
            if (index >= 0) sources[index].push_back(source);
        }
    }
    return true;
}

void CharacterRules::AddClasses(const Json& doc) {
    for (const Json& entry : doc["classes"].items()) {
        CharacterClass cls;
        cls.specialization = entry["specialization"].asString();
        for (const Json& skill : entry["major"].items()) cls.major.insert(skill.asString());
        classes[entry["id"].asString()] = cls;
    }
}

float CharacterRules::Setting(const char* name, float fallback) const {
    auto it = settings.find(name);
    return it == settings.end() ? fallback : it->second;
}

float ClassMultiplier(const CharacterRules& rules, const CharacterClass* cls, int skill) {
    if (!cls || skill < 0 || skill >= kSkillCount || rules.sources[skill].empty()) {
        return 1.0f;
    }
    const float major = rules.Setting("fSkillUseMajorMult", 1.0f);
    const float minor = rules.Setting("fSkillUseMinorMult", 1.0f);
    const float spec = rules.Setting("fSkillUseSpecMult", 1.0f);
    float best = 0.0f;
    for (const SourceSkill& source : rules.sources[skill]) {
        float m = cls->major.count(source.name) ? major : minor;
        if (source.specialization == cls->specialization) m *= spec;
        best = best == 0.0f ? m : (std::min)(best, m);
    }
    return best;
}

float Threshold(const SkillRates& rates, float curve, float level) {
    return rates.improveMult * std::pow(level, curve) + rates.improveOffset;
}

SkillRates SourceRates(const SkillRates& vanilla, float vanillaCurve,
                       float sourceCurve, float multiplier) {
    SkillRates out = vanilla;
    out.improveMult = Threshold(vanilla, vanillaCurve, kAnchorLevel) * multiplier /
                      std::pow(kAnchorLevel, sourceCurve);
    out.improveOffset = 0.0f;
    return out;
}

}  // namespace tesruntime
