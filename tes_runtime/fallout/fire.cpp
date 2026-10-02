#include "fire.h"

#include <windows.h>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "addresses.h"
#include "engine.h"
#include "guns.h"
#include "hook.h"
#include "hud.h"
#include "parts.h"
#include "shot_trace.h"
#include "ids.h"
#include "log.h"
#include "paths.h"
#include "zoom.h"

namespace tesruntime {

namespace {

// Actor layout the shot reads.
constexpr std::size_t kAnimSinkOffset = 0x30;     // BSTEventSink<BSAnimationGraphEvent>
constexpr std::size_t kGraphHolderOffset = 0x38;  // IAnimationGraphManagerHolder
constexpr std::size_t kActorProcess = 0xf8;       // AIProcess*
constexpr std::size_t kVtGetCurrentAmmo = 0x4f0 / 8;
constexpr std::size_t kVtNotifyGraph = 1;

constexpr std::size_t kNodeFlags = 0xf4;          // NiAVObject::flags; bit 0 = hidden
constexpr std::uint32_t kNodeHidden = 1;
constexpr std::size_t kEventTag = 0;              // BSAnimationGraphEvent::tag; holder at +8, payload +0x10
constexpr std::size_t kActionActor = 8;           // ActorActionData::actor
constexpr std::size_t kActionForm = 0x18;         // ActorActionData::action (BGSAction*)
constexpr std::size_t kActionEditorId = 0x20;     // BGSAction::formEditorID (BSFixedString)
constexpr int kDefaultReloadKey = 0x05;           // VK_XBUTTON1
constexpr unsigned long kEquipSettleMs = 1500;    // one swap per actor per interval
constexpr int kEventNotifyContinue = 0;
constexpr std::size_t kActorFlags = 0xc8;         // ActorState flags; attack state in bits 28-31
constexpr int kDefaultZoomKey = 0x02;             // VK_RBUTTON
constexpr std::size_t kRefAngleX = 0x48;          // OBJ_REFR angle.x: the look pitch, radians
constexpr float kDegreesPerRadian = 57.29578f;
constexpr unsigned long long kSamePressMs = 50;   // one click reached PerformAction twice in the same ms
constexpr std::size_t kCameraRoot = 0x20;         // TESCamera::cameraRoot (NiNode*)
constexpr std::size_t kCameraState = 0x28;        // TESCamera::currentState
constexpr std::size_t kFirstPersonState = 0xb8;   // the state 0x766130 compares it with
constexpr std::size_t kWorldRotate = 0x7c;        // NiAVObject world rotation, row-major

using FireFn = void (*)(void* weapon, void* shooter, void* ammo, void* poison, void* node);
using EquippedFn = void* (*)(void* process, bool left);
using ProcessEventFn = int (*)(void* sink, void* evn, void* src);
using NotifyGraphFn = bool (*)(void* holder, void* eventName);
using EquipFn = void (*)(void* vm, std::uint32_t stack, void* actor, void* form, bool a, bool b);
using CountFn = int (*)(void* vm, std::uint32_t stack, void* ref, void* form);
using ActionFn = std::int64_t (*)(void* a, void* action, std::int64_t c, std::int64_t d);
using ObjectByNameFn = void* (*)(void* root, void** name, bool recurse);
using FiringNodeFn = void* (*)(void* process, void** holder);
using AimAnglesFn = void (*)(void* actor, void* node, float* pitch, float* heading, float* origin);

// A resolved gun: the rounds it loads, its no-ammo sound, its sight FOV,
// its magazine size.
struct Gun {
    std::vector<void*> ammo;
    std::unique_ptr<FixedString> dry;
    float sightFov = 0.0f;
    int clipSize = 0;
};

// The event as the engine hands it to a sink.
struct GraphEvent {
    void* tag;
    void* holder;
    void* payload;
};

FireFn         g_fire = nullptr;
EquippedFn     g_equipped = nullptr;
EquipFn        g_equip = nullptr;
CountFn        g_count = nullptr;
ActionFn       g_origAction = nullptr;
ObjectByNameFn g_objectByName = nullptr;
FiringNodeFn   g_origFiringNode = nullptr;
void**         g_playerCamera = nullptr;
AimAnglesFn    g_origPlayerAim = nullptr;
void*          g_shooter = nullptr;                 // the actor inside our Fire call
std::unordered_map<void*, unsigned long long> g_lastPress;
ProcessEventFn g_origProcessEvent[2] = {nullptr, nullptr};
void**         g_player = nullptr;
std::unique_ptr<FixedString> g_shotTag, g_drawTag, g_equipTag, g_soundPlay, g_reloadEvent,
    g_fireEvent, g_fireRelease, g_quiverNode, g_reloadEndTag, g_fireEndTag, g_attackEndTag,
    g_projectileNode;
// Shots since each actor's last reload: the graph's iGunShots, the HUD magazine.
std::unordered_map<void*, int> g_shots;

// The actions a gun holder never hands the engine: the attack press and
// release become the graph's own fire events, the rest is dropped.
constexpr const char* kFireAction = "ActionRightAttack";
constexpr const char* kFireReleaseAction = "ActionRightRelease";
constexpr const char* kDroppedActions[] = {
    "ActionRightInterrupt", "ActionRightPowerAttack", "ActionLeftAttack",
    "ActionLeftRelease", "ActionLeftInterrupt", "ActionLeftPowerAttack",
    "ActionDualAttack", "ActionDualRelease", "ActionDualPowerAttack"};
std::unordered_map<void*, Gun> g_guns;
std::unordered_map<void*, unsigned long> g_lastEquip;
unsigned long g_lastLog = 0;

bool Throttled() {
    const unsigned long now = GetTickCount();
    if (now - g_lastLog < 1000) return true;
    g_lastLog = now;
    return false;
}

void* EquippedWeapon(void* actor) {
    void* process = At<void*>(actor, kActorProcess);
    if (!process) return nullptr;
    void* entry = g_equipped(process, false);
    void* form = entry ? At<void*>(entry, 0) : nullptr;
    if (!form || At<std::uint8_t>(form, kFormType) != kFormTypeWeapon) return nullptr;
    return form;
}

// The equipped gun, or null when the actor holds none.
const Gun* GunOf(void* actor, void** weapon) {
    *weapon = EquippedWeapon(actor);
    if (!*weapon) return nullptr;
    auto it = g_guns.find(*weapon);
    return it == g_guns.end() ? nullptr : &it->second;
}

bool Contains(const std::vector<void*>& list, void* form) {
    for (void* f : list) {
        if (f == form) return true;
    }
    return false;
}

// A round the gun loads: the current ammo when listed, else the first
// listed round the actor carries, equipped silently (once per settle
// interval: the equip lands on a later frame and raises reloadStart).
// Null when the actor carries none; a wrong round stays in hand so the
// engine's attack button keeps working and the dry fire answers it.
void* FindRound(void* actor, const Gun& gun) {
    void* current = VCall<void* (*)(void*)>(actor, kVtGetCurrentAmmo)(actor);
    if (gun.ammo.empty() || (current && Contains(gun.ammo, current))) return current;
    for (void* ammo : gun.ammo) {
        if (g_count(g_api.vm, 0, actor, ammo) <= 0) continue;
        const unsigned long now = GetTickCount();
        auto last = g_lastEquip.find(actor);
        if (last == g_lastEquip.end() || now - last->second >= kEquipSettleMs) {
            g_lastEquip[actor] = now;
            g_equip(g_api.vm, 0, actor, ammo, false, true);
            Log("fire: %p loaded %p (had %p)", actor, ammo, current);
        }
        return ammo;
    }
    return nullptr;
}

// Hands the engine an event as if the actor's graph had raised it.
void RaiseEngineEvent(void* actor, const FixedString& name, void* payload = nullptr) {
    GraphEvent evn{name.ptr, actor, payload};
    const int which = (g_player && actor == *g_player) ? 1 : 0;
    g_origProcessEvent[which](static_cast<char*>(actor) + kAnimSinkOffset, &evn, nullptr);
}

// The gun's no-ammo sound at the actor.
void DryFire(void* actor, const Gun& gun) {
    if (gun.dry) RaiseEngineEvent(actor, *g_soundPlay, gun.dry->ptr);
    if (!Throttled()) Log("fire: %p dry fire", actor);
}

bool IsPlayer(void* actor) {
    return g_player && actor == *g_player;
}

// The actor's magazine count, into every graph of the actor and the HUD.
void SetShots(void* actor, const Gun& gun, int shots) {
    g_shots[actor] = shots;
    SetActorGraphInt(actor, "iGunShots", shots);
    if (IsPlayer(actor)) HudSetMagazine(true, gun.clipSize - shots, gun.clipSize);
}

// The shot: false when the actor holds no gun (the event is the engine's).
bool OnShot(void* actor) {
    void* weapon = nullptr;
    const Gun* gun = GunOf(actor, &weapon);
    if (!gun) return false;
    void* round = FindRound(actor, *gun);
    if (!round) {
        DryFire(actor, *gun);
        return true;
    }
    TraceStep(actor, "Fire called");
    g_shooter = actor;
    g_fire(weapon, actor, round, nullptr, nullptr);
    g_shooter = nullptr;
    if (IsPlayer(actor)) {
        Log("fire: player fired %08X, pitch %.1f deg", At<std::uint32_t>(weapon, kFormID),
            At<float>(actor, kRefAngleX) * kDegreesPerRadian);
    } else if (!Throttled()) {
        Log("fire: %p fired %p", actor, weapon);
    }
    SetShots(actor, *gun, g_shots[actor] + 1);
    return true;
}

bool SendToGraph(void* actor, const FixedString& name);

// The press: the fire event when a round is there, the dry fire otherwise.
void Press(void* actor, const Gun& gun) {
    if (!FindRound(actor, gun)) {
        DryFire(actor, gun);
        return;
    }
    TraceStep(actor, "press: TES4GunFire sent");
    SendToGraph(actor, *g_fireEvent);
    if (IsPlayer(actor)) ZoomNoteFiring(true);
}

// True for a second attack press from `actor` within kSamePressMs: one click
// can reach PerformAction twice in the same millisecond, and each press
// queued its own attack, so the gun fired again 178 ms later.
bool RepeatedPress(void* actor) {
    const unsigned long long now = GetTickCount64();
    auto it = g_lastPress.find(actor);
    const bool repeat = it != g_lastPress.end() && now - it->second < kSamePressMs;
    if (!repeat) g_lastPress[actor] = now;
    return repeat;
}

int AttackState(void* actor) {
    return static_cast<int>(At<std::uint32_t>(actor, kActorFlags) >> 28);
}

// The engine's PerformAction. A gun holder's attack press becomes the
// graph's TES4GunFire (or the dry fire), the release its
// TES4GunFireRelease; the interrupt, the off-hand (bash/block) and the
// power attacks are dropped. None of them reaches the engine, so no
// attack state is ever written for a gun.
std::int64_t ActionHook(void* a, void* action, std::int64_t c, std::int64_t d) {
    void* actor = action ? At<void*>(action, kActionActor) : nullptr;
    void* form = actor ? At<void*>(action, kActionForm) : nullptr;
    const char* name = form ? At<const char*>(form, kActionEditorId) : nullptr;
    void* weapon = nullptr;
    const Gun* gun = actor ? GunOf(actor, &weapon) : nullptr;
    if (!gun || !name) return g_origAction(a, action, c, d);
    if (IsPlayer(actor)) {
        char step[128];
        std::snprintf(step, sizeof(step), "action %s, attackState %d", name, AttackState(actor));
        TraceStep(actor, step);
    }
    if (std::strcmp(name, kFireAction) == 0) {
        if (RepeatedPress(actor)) {
            TraceStep(actor, "press dropped: the same click again");
            return 0;
        }
        Press(actor, *gun);
        return 0;
    }
    if (std::strcmp(name, kFireReleaseAction) == 0) {
        TraceStep(actor, "release: TES4GunFireRelease sent");
        SendToGraph(actor, *g_fireRelease);
        return 0;
    }
    for (const char* dropped : kDroppedActions) {
        if (std::strcmp(name, dropped) == 0) return 0;
    }
    return g_origAction(a, action, c, d);
}

// The equipped ammo hangs off the actor's QUIVER node; a gun has no
// quiver, so the node is culled for a gun holder and shown otherwise, on
// both the third- and the first-person skeleton.
void ShowQuiver(void* actor, bool show) {
    void* roots[2] = {VCall<void* (*)(void*, bool)>(actor, kVtGet3DFirstPerson)(actor, false),
                      VCall<void* (*)(void*, bool)>(actor, kVtGet3DFirstPerson)(actor, true)};
    for (void* root : roots) {
        void* node = root ? g_objectByName(root, &g_quiverNode->ptr, true) : nullptr;
        if (IsPlayer(actor)) Log("quiver: %s on %p: %s", show ? "show" : "hide", root, node ? "node" : "no node");
        if (!node) continue;
        std::uint32_t& flags = At<std::uint32_t>(node, kNodeFlags);
        flags = show ? (flags & ~kNodeHidden) : (flags | kNodeHidden);
    }
}

void OnDraw(void* actor) {
    void* weapon = nullptr;
    const Gun* gun = GunOf(actor, &weapon);
    ShowQuiver(actor, gun == nullptr);
    if (gun) {
        FindRound(actor, *gun);
        SetShots(actor, *gun, g_shots[actor]);
    } else if (IsPlayer(actor)) {
        HudSetMagazine(false, 0, 0);
    }
}

// A finished reload: the magazine is full again.
void OnReloadEnd(void* actor) {
    void* weapon = nullptr;
    const Gun* gun = GunOf(actor, &weapon);
    if (gun) SetShots(actor, *gun, 0);
}

// The ammo check a frame after the engine's reloadStart (ammo equipped):
// a wrong round leaves the hand at once, so the engine's own no-ammo
// refusal covers the attack button.
struct EquipCheckTask : TaskDelegate {
    void* actor;
    explicit EquipCheckTask(void* a) : actor(a) {}
    void Run() override { OnDraw(actor); }
    void Dispose() override { delete this; }
};

// The engine's crossbow firing node ("NPC R MagicNode [RMag]"), except
// under a gun: the gun mesh's ProjectileNode, so the shot, the muzzle flash
// and the aim start at the barrel. No vanilla weapon mesh has that node.
void* FiringNodeHook(void* process, void** holder) {
    void* node = g_origFiringNode(process, holder);
    void* loaded = (node && holder) ? *holder : nullptr;
    void* root = loaded ? At<void*>(loaded, 8) : nullptr;
    void* barrel = root ? g_objectByName(root, &g_projectileNode->ptr, true) : nullptr;
    return barrel ? barrel : node;
}

// In first person the player's round starts at the camera and flies along its
// forward axis, so it lands on the crosshair: from the barrel, 40 units ahead
// and about 10 off the line of sight, a parallel round passed beside small
// targets (radroaches). Third person is left to the engine.
void PlayerAimHook(void* actor, void* node, float* pitch, float* heading, float* origin) {
    g_origPlayerAim(actor, node, pitch, heading, origin);
    void* camera = g_playerCamera ? *g_playerCamera : nullptr;
    if (actor != g_shooter || !camera || !pitch || !heading || !origin) return;
    if (At<void*>(camera, kCameraState) != At<void*>(camera, kFirstPersonState)) return;
    void* root = At<void*>(camera, kCameraRoot);
    if (!root) return;
    const float* m = &At<float>(root, kWorldRotate);
    *pitch = -std::asin(m[7]);
    *heading = std::atan2(m[1], m[4]);
    std::memcpy(origin, &At<float>(root, kWorldTranslate), 3 * sizeof(float));
}

int ProcessEventHook(int which, void* sink, void* evn, void* src) {
    if (evn && sink) {
        void* tag = At<void*>(evn, kEventTag);
        void* actor = static_cast<char*>(sink) - kAnimSinkOffset;
        void* weapon = nullptr;
        if (tag && GunOf(actor, &weapon)) TraceAnimEvent(actor, static_cast<const char*>(tag), src);
        if (tag && GunOf(actor, &weapon)) PlayPartSequence(actor, tag);
        if (tag == g_shotTag->ptr && OnShot(actor)) return kEventNotifyContinue;
        if (tag == g_drawTag->ptr) OnDraw(actor);
        if (tag == g_reloadEndTag->ptr) OnReloadEnd(actor);
        if (IsPlayer(actor) && (tag == g_fireEndTag->ptr || tag == g_attackEndTag->ptr ||
                                tag == g_reloadEndTag->ptr)) {
            ZoomNoteFiring(false);
        }
        if (tag == g_equipTag->ptr) RunOnMainThread(new EquipCheckTask(actor));
    }
    return g_origProcessEvent[which](sink, evn, src);
}

int CharacterProcessEvent(void* sink, void* evn, void* src) {
    return ProcessEventHook(0, sink, evn, src);
}

int PlayerProcessEvent(void* sink, void* evn, void* src) {
    return ProcessEventHook(1, sink, evn, src);
}

bool PatchSlot(int which, std::uint64_t id, const char* name, void* replacement) {
    auto* vt = reinterpret_cast<void**>(Resolve(name, id, nullptr));
    g_origProcessEvent[which] =
        reinterpret_cast<ProcessEventFn>(PatchVtableSlot(vt, 1, replacement, name));
    return g_origProcessEvent[which] != nullptr;
}

bool PatchPlayerAim() {
    auto* vt = reinterpret_cast<void**>(Resolve("PlayerCharacter vtable", ids::kPlayerVtable, nullptr));
    if (!vt) return false;
    g_origPlayerAim = reinterpret_cast<AimAnglesFn>(PatchVtableSlot(
        vt, ids::kVtAimAngles, reinterpret_cast<void*>(&PlayerAimHook), "PlayerCharacter aim"));
    return g_origPlayerAim != nullptr;
}

void* PlayerWithGun() {
    void* player = g_player ? *g_player : nullptr;
    void* weapon = nullptr;
    return (player && GunOf(player, &weapon)) ? player : nullptr;
}

bool SendToGraph(void* actor, const FixedString& name) {
    void* holder = static_cast<char*>(actor) + kGraphHolderOffset;
    void* p = name.ptr;
    return VCall<NotifyGraphFn>(holder, kVtNotifyGraph)(holder, &p);
}

// Sends TES4GunReloadRequest to the player's graph (the root enters the
// reload state on it; the fire machine takes it mid-burst); the dry fire
// when no round can be loaded.
struct ReloadTask : TaskDelegate {
    void Run() override {
        void* player = PlayerWithGun();
        if (!player) return;
        void* weapon = nullptr;
        const Gun* gun = GunOf(player, &weapon);
        if (FindRound(player, *gun)) SendToGraph(player, *g_reloadEvent);
        else DryFire(player, *gun);
    }
    void Dispose() override { delete this; }
};

// The zoom key's edge, then one blend frame per poll, on the main thread.
struct ZoomTask : TaskDelegate {
    bool zoomed, edge;
    ZoomTask(bool z, bool e) : zoomed(z), edge(e) {}
    void Run() override {
        if (edge) ZoomSet(zoomed);
        if (ZoomActive()) ZoomTick();
    }
    void Dispose() override { delete this; }
};

struct Keys {
    int reload, zoom;
};

DWORD WINAPI KeyThread(LPVOID param) {
    std::unique_ptr<Keys> keys(static_cast<Keys*>(param));
    bool reloadDown = false, zoomDown = false;
    for (;;) {
        Sleep(16);
        const bool r = (GetAsyncKeyState(keys->reload) & 0x8000) != 0;
        if (r && !reloadDown) RunOnMainThread(new ReloadTask());
        reloadDown = r;
        const bool z = (GetAsyncKeyState(keys->zoom) & 0x8000) != 0;
        if (z != zoomDown || ZoomActive()) RunOnMainThread(new ZoomTask(z, z != zoomDown));
        zoomDown = z;
    }
}

// FalloutRuntime.ini, else (DEPRECATED, to be removed) the pre-split
// TESRuntime\TESRuntime.ini a player may already have set keys in.
// See: docs/reference/tes_runtime_fragments.md#legacy-sidecar-paths
std::string IniPath() {
    const std::string ini = SidecarDir() + "FalloutRuntime.ini";
    const std::string legacy = PluginsDir() + "TESRuntime\\TESRuntime.ini";
    if (GetFileAttributesA(ini.c_str()) != INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesA(legacy.c_str()) == INVALID_FILE_ATTRIBUTES) {
        return ini;
    }
    Log("fire: DEPRECATED -- keys read from %s; move it to %s", legacy.c_str(), ini.c_str());
    return legacy;
}

int IniKey(const std::string& ini, const char* name, int fallback) {
    return static_cast<int>(GetPrivateProfileIntA("Guns", name, fallback, ini.c_str()));
}

}  // namespace

bool InstallFire() {
    const std::uintptr_t fire = Resolve("TESObjectWEAP::Fire", ids::kWeaponFire, nullptr);
    const std::uintptr_t equipped = Resolve("AIProcess::GetEquippedObject", ids::kProcessEquipped, nullptr);
    const std::uintptr_t equip = Resolve("Actor.EquipItem", ids::kEquipItemNative, nullptr);
    const std::uintptr_t count = Resolve("ObjectReference.GetItemCount", ids::kGetItemCountNative, nullptr);
    const std::uintptr_t action = Resolve("Actor::PerformAction", ids::kPerformAction, nullptr);
    const std::uintptr_t byName = Resolve("NiAVObject::GetObjectByName", ids::kObjectByName, nullptr);
    const std::uintptr_t firingNode = Resolve("CrossbowFiringNode", ids::kCrossbowFiringNode, nullptr);
    g_player = reinterpret_cast<void**>(Resolve("PlayerCharacter singleton", ids::kPlayerSingleton, nullptr));
    g_playerCamera = reinterpret_cast<void**>(Resolve("PlayerCamera singleton", ids::kPlayerCamera, nullptr));
    if (!fire || !equipped || !equip || !count || !action || !byName || !g_player || !InstallZoom()) {
        Log("fire: an address is unresolved; guns will not fire");
        return false;
    }
    g_fire = reinterpret_cast<FireFn>(fire);
    g_equipped = reinterpret_cast<EquippedFn>(equipped);
    g_equip = reinterpret_cast<EquipFn>(equip);
    g_count = reinterpret_cast<CountFn>(count);
    g_origAction = reinterpret_cast<ActionFn>(action);
    g_objectByName = reinterpret_cast<ObjectByNameFn>(byName);
    g_quiverNode.reset(new FixedString("QUIVER"));
    g_shotTag.reset(new FixedString("arrowRelease"));
    g_drawTag.reset(new FixedString("weaponDraw"));
    g_equipTag.reset(new FixedString("reloadStart"));
    g_soundPlay.reset(new FixedString("SoundPlay"));
    g_reloadEvent.reset(new FixedString("TES4GunReloadRequest"));
    g_fireEvent.reset(new FixedString("TES4GunFire"));
    g_fireRelease.reset(new FixedString("TES4GunFireRelease"));
    g_reloadEndTag.reset(new FixedString("TES4GunReloadEnd"));
    g_fireEndTag.reset(new FixedString("TES4GunFireEnd"));
    g_attackEndTag.reset(new FixedString("TES4GunAttackEnd"));
    if (!PatchSlot(0, ids::kCharacterAnimSinkVtable, "Character anim sink vtable",
                   reinterpret_cast<void*>(&CharacterProcessEvent)) ||
        !PatchSlot(1, ids::kPlayerAnimSinkVtable, "PlayerCharacter anim sink vtable",
                   reinterpret_cast<void*>(&PlayerProcessEvent))) {
        return false;
    }
    if (PatchAllCalls(action, reinterpret_cast<void*>(&ActionHook), "PerformAction") <= 0) return false;
    g_projectileNode.reset(new FixedString("ProjectileNode"));
    if (!InstallShotTrace(g_player, g_playerCamera)) Log("fire: shot trace not installed");
    if (!PatchPlayerAim()) Log("fire: first-person aim not patched; rounds start at the barrel");
    g_origFiringNode = reinterpret_cast<FiringNodeFn>(firingNode);
    if (!firingNode ||
        PatchAllCalls(firingNode, reinterpret_cast<void*>(&FiringNodeHook), "CrossbowFiringNode") <= 0) {
        Log("fire: firing node not patched; shots start at the hand");
    }
    Log("fire: HUD magazine counter disabled (hud.cpp kept, not installed)");
    if (!InstallParts()) Log("fire: gun part sequences not installed");
    const std::string ini = IniPath();
    auto* keys = new Keys{IniKey(ini, "ReloadKey", kDefaultReloadKey),
                          IniKey(ini, "ZoomKey", kDefaultZoomKey)};
    CreateThread(nullptr, 0, KeyThread, keys, 0, nullptr);
    Log("fire: shot hook installed; reload key 0x%02x, zoom key 0x%02x", keys->reload, keys->zoom);
    return true;
}

float PlayerGunSightFov() {
    void* weapon = nullptr;
    const Gun* gun = g_player && *g_player ? GunOf(*g_player, &weapon) : nullptr;
    return gun ? gun->sightFov : 0.0f;
}

void RegisterGunAmmo(void* weapon, std::vector<void*> ammo, const std::string& drySound,
                     float sightFov, int clipSize) {
    Gun& gun = g_guns[weapon];
    gun.ammo = std::move(ammo);
    gun.sightFov = sightFov;
    gun.clipSize = clipSize;
    if (!drySound.empty()) gun.dry.reset(new FixedString(drySound.c_str()));
}

}  // namespace tesruntime
