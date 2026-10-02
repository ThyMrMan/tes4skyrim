#include "hits.h"

#include <cstdint>

#include "addresses.h"
#include "engine.h"
#include "hook.h"
#include "ids.h"
#include "log.h"

namespace tesruntime {

namespace {

constexpr std::size_t kHitAggressor = 0x18;   // handle
constexpr std::size_t kHitWeapon    = 0x30;   // TESObjectWEAP*
constexpr std::size_t kHitDamage    = 0x50;   // floats: total, physical, limb, blocked share
constexpr std::uint32_t kPlayerRef  = 0x14;

using ApplyHitFn = void (*)(void* actor, void* hitData);
using LookupByHandleFn = void* (*)(std::uint32_t* handle, void** out);

ApplyHitFn       g_originalApplyHit = nullptr;
LookupByHandleFn g_lookupByHandle = nullptr;
FatalHitFn       g_onFatal = nullptr;

float Health(void* actor) {
    void* owner = static_cast<char*>(actor) + kActorValueOwner;
    return VCall<float (*)(void*, int)>(owner, 1)(owner, kActorValueHealth);
}

std::uint32_t AttackerId(void* hitData) {
    std::uint32_t handle = At<std::uint32_t>(hitData, kHitAggressor);
    void* attacker = nullptr;
    if (g_lookupByHandle) g_lookupByHandle(&handle, &attacker);
    if (!attacker) return 0;
    const std::uint32_t id = At<std::uint32_t>(attacker, kFormID);
    ReleaseRef(attacker);
    return id;
}

void LogHit(void* hitData, void* actor, float before) {
    const std::uint32_t by = AttackerId(hitData);
    const std::uint32_t target = At<std::uint32_t>(actor, kFormID);
    if (by != kPlayerRef && target != kPlayerRef) return;
    void* weapon = At<void*>(hitData, kHitWeapon);
    const float* dmg = &At<float>(hitData, kHitDamage);
    Log("hit: %08X by %08X weapon %08X total %.1f physical %.1f limb %.1f blocked %.2f "
        "health %.1f -> %.1f", target, by, weapon ? At<std::uint32_t>(weapon, kFormID) : 0,
        dmg[0], dmg[1], dmg[2], dmg[3], before, Health(actor));
}

void ApplyHitHook(void* actor, void* hitData) {
    const bool actorLike = actor && At<std::uint8_t>(actor, kFormType) == kFormTypeActor;
    const float before = actorLike ? Health(actor) : 0.0f;
    g_originalApplyHit(actor, hitData);
    if (!actorLike || !hitData) return;
    LogHit(hitData, actor, before);
    if (g_onFatal && before > 0.0f && Health(actor) <= 0.0f) g_onFatal(hitData, actor);
}

}  // namespace

bool InstallHitLog() {
    const std::uintptr_t applyHit = Resolve("Actor::ApplyHit", ids::kApplyHit, nullptr);
    if (!applyHit) {
        Log("hits: Actor::ApplyHit unresolved; hit log disabled");
        return false;
    }
    g_originalApplyHit = reinterpret_cast<ApplyHitFn>(applyHit);
    g_lookupByHandle = reinterpret_cast<LookupByHandleFn>(
        Resolve("LookupReferenceByHandle", ids::kLookupByHandle, nullptr));
    return PatchAllCalls(applyHit, reinterpret_cast<void*>(&ApplyHitHook), "ApplyHit") > 0;
}

void SetFatalHitHandler(FatalHitFn fn) { g_onFatal = fn; }

}  // namespace tesruntime
