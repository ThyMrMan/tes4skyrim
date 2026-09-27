#include "character_rules.h"

#include <windows.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <functional>
#include <string>
#include <utility>
#include <vector>

#include "addresses.h"
#include "character_rates.h"
#include "engine.h"
#include "engine_ids.h"
#include "hook.h"
#include "ids.h"
#include "json.h"
#include "log.h"

namespace tesruntime {

namespace {

constexpr const char* kRulesEvent = "TESCharacterRules";
constexpr const char* kClassEvent = "TESCharacterClass";
constexpr const char* kLevelEvent = "TESCharacterLevel";

// fXPLevelUpBase while the rules are on: no experience reaches it, so the
// "Level up available" message never shows.
constexpr float kWithheldLevelUpBase = 1.0e30f;

// A skill's rates match GetSkillUsage's to this much, or the layout is wrong.
constexpr float kLayoutTolerance = 1.0e-6f;

// SKSEModCallbackEvent, as spin.cpp reads it.
struct ModEvent {
    const char* eventName;
    const char* strArg;
    float numArg;
    void* sender;
};

class RulesSink {
public:
    virtual ~RulesSink() = default;
    virtual int ReceiveEvent(const ModEvent* event, void* dispatcher);
};

class Task : public TaskDelegate {
public:
    explicit Task(std::function<void()> fn) : fn_(std::move(fn)) {}
    void Run() override { fn_(); }
    void Dispose() override { delete this; }

private:
    std::function<void()> fn_;
};

using AddEventSinkFn = void (*)(void* dispatcher, void* sink);
using CanLevelUpFn = bool (*)(void* skills);
using SetLevelFn = void (*)(void* skills, std::uint32_t level);
using SkillUsageFn = bool (*)(int value, float* useMult, float* useOffset,
                              float* improveMult, float* improveOffset);

RulesSink g_sink;
CanLevelUpFn g_canLevelUp = nullptr;
SetLevelFn g_setLevel = nullptr;
SkillUsageFn g_skillUsage = nullptr;
void** g_playerSlot = nullptr;
void** g_valueListSlot = nullptr;
float* g_skillUseCurve = nullptr;
float* g_levelUpBase = nullptr;
bool g_ratesReady = false;

// Every character.json, parsed at install: rules by plugin, and every class.
std::vector<std::pair<std::string, Json>> g_files;

// Game thread only, apart from g_withhold, which the level-up check reads.
std::atomic<bool> g_withhold{false};
bool g_on = false;
CharacterRules g_rules;
std::string g_class;
std::array<SkillRates, kSkillCount> g_vanilla{};
float g_vanillaCurve = 0.0f;
float g_vanillaLevelUpBase = 0.0f;

template <typename T>
bool Bind(T& slot, const char* name, std::uint64_t id) {
    const std::uintptr_t address = Resolve(name, id, nullptr);
    slot = reinterpret_cast<T>(address);
    return address != 0;
}

bool CanLevelUpHook(void* skills) {
    return !g_withhold.load() && g_canLevelUp(skills);
}

// The live AVSK of Skyrim skill `index`, or null.
SkillRates* LiveRates(int index) {
    void* list = *g_valueListSlot;
    if (!list) return nullptr;
    void* info = At<void*>(list, ids::kOffActorValueEntries +
                                     (kFirstSkill + index) * sizeof(void*));
    return info ? At<SkillRates*>(info, ids::kOffActorValueSkill) : nullptr;
}

// Every skill's AVSK where LiveRates finds it holds what GetSkillUsage reads.
bool LayoutMatches() {
    for (int i = 0; i < kSkillCount; ++i) {
        SkillRates expected;
        const SkillRates* live = LiveRates(i);
        if (!live || !g_skillUsage(kFirstSkill + i, &expected.useMult, &expected.useOffset,
                                   &expected.improveMult, &expected.improveOffset)) {
            return false;
        }
        const float diffs[] = {live->useMult - expected.useMult,
                               live->useOffset - expected.useOffset,
                               live->improveMult - expected.improveMult,
                               live->improveOffset - expected.improveOffset};
        for (float d : diffs) {
            if (d > kLayoutTolerance || d < -kLayoutTolerance) return false;
        }
    }
    return true;
}

const CharacterClass* PlayerClass() {
    auto it = g_rules.classes.find(g_class);
    return it == g_rules.classes.end() ? nullptr : &it->second;
}

// Writes the source game's rates over the captured vanilla ones: an XP game's
// skills gain nothing by use.
void ApplyRates() {
    if (!g_ratesReady) return;
    const float curve = g_rules.Setting("fSkillUseExp", g_vanillaCurve);
    const CharacterClass* cls = PlayerClass();
    for (int i = 0; i < kSkillCount; ++i) {
        SkillRates* live = LiveRates(i);
        if (!live) continue;
        *live = g_rules.xp ? XpRates(g_vanilla[i])
                           : SourceRates(g_vanilla[i], g_vanillaCurve, curve,
                                         ClassMultiplier(g_rules, cls, i));
    }
    *g_skillUseCurve = curve;
    if (g_rules.xp) {
        Log("character: skills rise only by points (XP rules)");
        return;
    }
    Log("character: skill rates follow curve %g, class '%s'%s", curve,
        g_class.c_str(), cls ? "" : " (no class: every multiplier 1)");
}

void CaptureVanilla() {
    for (int i = 0; i < kSkillCount && g_ratesReady; ++i) {
        const SkillRates* live = LiveRates(i);
        if (live) g_vanilla[i] = *live;
    }
    if (g_skillUseCurve) g_vanillaCurve = *g_skillUseCurve;
    if (g_levelUpBase) g_vanillaLevelUpBase = *g_levelUpBase;
}

// The rules for `plugin`, with every file's classes; false without its file.
bool LoadRules(const std::string& plugin) {
    CharacterRules rules;
    bool found = false;
    for (const auto& [name, doc] : g_files) {
        if (_stricmp(doc["plugin"].asString().c_str(), plugin.c_str()) == 0) {
            found = rules.Load(doc);
        }
        rules.AddClasses(doc);
    }
    if (found) g_rules = std::move(rules);
    return found;
}

void RulesOn(const std::string& plugin) {
    if (!LoadRules(plugin)) {
        Log("character: no skill-use or XP character data for '%s' -- rules stay off",
            plugin.c_str());
        return;
    }
    if (!g_on) CaptureVanilla();
    g_on = true;
    ApplyRates();
    if (g_levelUpBase) *g_levelUpBase = kWithheldLevelUpBase;
    g_withhold = g_canLevelUp != nullptr;
    Log("character: rules on for %s; Skyrim's level-up %s", plugin.c_str(),
        g_withhold ? "withheld" : "NOT withheld (no hook)");
}

void SetClass(const std::string& cls) {
    g_class = cls;
    if (g_on) ApplyRates();
}

// Sets the player's level with the real fXPLevelUpBase in place, so the
// threshold the bookkeeping stores is Skyrim's own.
void SetLevel(int level) {
    if (!g_on || !g_setLevel || !g_playerSlot || level < 1) return;
    void* player = *g_playerSlot;
    if (!player) return;
    if (g_levelUpBase) *g_levelUpBase = g_vanillaLevelUpBase;
    g_setLevel(At<void*>(player, PlayerField(ids::kOffPlayerSkills)),
               static_cast<std::uint32_t>(level));
    if (g_levelUpBase) *g_levelUpBase = kWithheldLevelUpBase;
    Log("character: player level set to %d", level);
}

int RulesSink::ReceiveEvent(const ModEvent* event, void*) {
    if (!event || !event->eventName) return 0;
    const std::string arg = event->strArg ? event->strArg : "";
    const float value = event->numArg;
    std::function<void()> fn;
    if (_strnicmp(event->eventName, "TESCharacter", 12) == 0) {
        Log("character: event %s '%s' %g", event->eventName, arg.c_str(), value);
    }
    if (_stricmp(event->eventName, kRulesEvent) == 0) {
        fn = value != 0.0f ? std::function<void()>([arg] { RulesOn(arg); })
                           : std::function<void()>(CharacterRulesOff);
    } else if (_stricmp(event->eventName, kClassEvent) == 0) {
        fn = [arg] { SetClass(arg); };
    } else if (_stricmp(event->eventName, kLevelEvent) == 0) {
        fn = [value] { SetLevel(static_cast<int>(value)); };
    }
    if (fn) RunOnMainThread(new Task(std::move(fn)));
    return 0;
}

void KeepFile(const std::string& name, const Json& doc) {
    g_files.emplace_back(name, doc);
}

// Hooks every call to the level-up check; false when none was patched.
bool HookLevelUp() {
    if (!g_canLevelUp) return false;
    const int patched = PatchAllCalls(reinterpret_cast<std::uintptr_t>(g_canLevelUp),
                                      reinterpret_cast<void*>(CanLevelUpHook),
                                      "CanLevelUp");
    Log("character: %d level-up check call(s) hooked", patched);
    if (patched == 0) g_canLevelUp = nullptr;
    return patched > 0;
}

bool ResolveAll() {
    bool ok = Bind(g_canLevelUp, "CanLevelUp", ids::kCanLevelUp);
    ok = Bind(g_setLevel, "SetPlayerLevel", ids::kSetPlayerLevel) && ok;
    ok = Bind(g_skillUsage, "GetSkillUsage", ids::kGetSkillUsage) && ok;
    ok = Bind(g_playerSlot, "PlayerCharacter singleton", ids::kPlayerSingleton) && ok;
    ok = Bind(g_valueListSlot, "ActorValueList singleton", ids::kActorValueList) && ok;
    ok = Bind(g_skillUseCurve, "fSkillUseCurve", ids::kSkillUseCurve) && ok;
    return Bind(g_levelUpBase, "fXPLevelUpBase", ids::kXPLevelUpBase) && ok;
}

}  // namespace

void CharacterRulesOff() {
    if (!g_on) return;
    g_on = false;
    g_withhold = false;
    for (int i = 0; i < kSkillCount && g_ratesReady; ++i) {
        SkillRates* live = LiveRates(i);
        if (live) *live = g_vanilla[i];
    }
    if (g_skillUseCurve) *g_skillUseCurve = g_vanillaCurve;
    if (g_levelUpBase) *g_levelUpBase = g_vanillaLevelUpBase;
    Log("character: rules off, Skyrim's own rates and leveling restored");
}

void CheckCharacterLayout() {
    g_ratesReady = g_skillUsage && g_valueListSlot && g_skillUseCurve && LayoutMatches();
    Log("character: skill rate layout %s", g_ratesReady ? "verified" : "NOT verified -- "
        "skill rates stay Skyrim's");
}

bool InstallCharacterRules(SKSEMessagingInterface* messaging) {
    ForEachSidecar("character.json", KeepFile);
    if (g_files.empty()) {
        Log("character: no character data staged -- NOT installed");
        return false;
    }
    const bool resolved = ResolveAll();
    const bool hooked = HookLevelUp();
    void* dispatcher = messaging ? messaging->GetEventDispatcher(
        SKSEMessagingInterface::kDispatcher_ModEvent) : nullptr;
    auto add = reinterpret_cast<AddEventSinkFn>(
        Resolve("BSTEventSource::AddEventSink", ids::kAddEventSink, nullptr));
    if (!dispatcher || !add) {
        Log("character: no mod-event dispatcher -- NOT installed");
        return false;
    }
    add(dispatcher, &g_sink);
    Log("character: %zu file(s); natives %s, level-up %s", g_files.size(),
        resolved ? "resolved" : "PARTLY resolved", hooked ? "hooked" : "NOT hooked");
    return true;
}

}  // namespace tesruntime
