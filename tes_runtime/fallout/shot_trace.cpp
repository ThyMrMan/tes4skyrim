#include "shot_trace.h"

#include <windows.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <vector>

#include "addresses.h"
#include "engine.h"
#include "hook.h"
#include "ids.h"
#include "log.h"

namespace tesruntime {

namespace {

constexpr std::size_t kLaunchOrigin = 0x08;
constexpr std::size_t kLaunchBase = 0x20;
constexpr std::size_t kLaunchShooter = 0x28;
constexpr std::size_t kLaunchHeading = 0x48;
constexpr std::size_t kLaunchPitch = 0x4c;
constexpr std::size_t kLaunchTarget = 0x58;
constexpr std::size_t kRefAngle = 0x48;           // OBJ_REFR angle x, y, z (radians)
constexpr std::size_t kRefPosition = 0x54;        // OBJ_REFR location
constexpr std::size_t kCameraRoot = 0x20;         // TESCamera::cameraRoot
constexpr std::size_t kWorldRotate = 0x7c;        // NiAVObject world rotation, row-major
constexpr float kDegrees = 57.29578f;
constexpr int kPollMs = 16;
constexpr int kStillPolls = 3;                    // a round unmoved this many polls has stopped
constexpr unsigned long kMaxFlightMs = 3000;

using LaunchFn = void* (*)(std::uint32_t* handleOut, void* data);
using LookupByHandleFn = void* (*)(std::uint32_t* handle, void** out);

struct Round {
    std::uint32_t handle;
    unsigned long launched;
    float origin[3];
    float last[3];
    int still;
};

LaunchFn         g_origLaunch = nullptr;
LookupByHandleFn g_lookup = nullptr;
void**           g_player = nullptr;
void**           g_camera = nullptr;
std::vector<Round> g_rounds;
std::mutex       g_mutex;

bool IsPlayer(void* actor) {
    return g_player && actor && actor == *g_player;
}

// Local time to the millisecond, as the flight recorder stamps its events.
void Stamp(char* out, std::size_t n) {
    SYSTEMTIME t;
    GetLocalTime(&t);
    std::snprintf(out, n, "%02u:%02u:%02u.%03u", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
}

float Distance(const float* a, const float* b) {
    const float dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

void LogCameraAndPlayer(const char* stamp) {
    void* camera = g_camera ? *g_camera : nullptr;
    void* root = camera ? At<void*>(camera, kCameraRoot) : nullptr;
    if (root) {
        const float* p = &At<float>(root, kWorldTranslate);
        const float* m = &At<float>(root, kWorldRotate);
        Log("shot %s   camera at (%.0f %.0f %.0f) pitch %.1f heading %.1f", stamp, p[0], p[1], p[2],
            -std::asin(m[7]) * kDegrees, std::atan2(m[1], m[4]) * kDegrees);
    }
    void* player = g_player ? *g_player : nullptr;
    if (player) {
        const float* p = &At<float>(player, kRefPosition);
        const float* a = &At<float>(player, kRefAngle);
        Log("shot %s   player at (%.0f %.0f %.0f) pitch %.1f heading %.1f", stamp, p[0], p[1], p[2],
            a[0] * kDegrees, a[2] * kDegrees);
    }
}

void* LaunchHook(std::uint32_t* handleOut, void* data) {
    void* result = g_origLaunch(handleOut, data);
    if (!data || !IsPlayer(At<void*>(data, kLaunchShooter))) return result;
    char stamp[16];
    Stamp(stamp, sizeof(stamp));
    const float* o = &At<float>(data, kLaunchOrigin);
    void* base = At<void*>(data, kLaunchBase);
    void* target = At<void*>(data, kLaunchTarget);
    Log("shot %s launch %08X from (%.0f %.0f %.0f) pitch %.1f heading %.1f target %08X handle %08X",
        stamp, base ? At<std::uint32_t>(base, kFormID) : 0, o[0], o[1], o[2],
        At<float>(data, kLaunchPitch) * kDegrees, At<float>(data, kLaunchHeading) * kDegrees,
        target ? At<std::uint32_t>(target, kFormID) : 0, handleOut ? *handleOut : 0);
    LogCameraAndPlayer(stamp);
    if (handleOut && *handleOut) {
        Round r{*handleOut, GetTickCount(), {o[0], o[1], o[2]}, {o[0], o[1], o[2]}, 0};
        std::lock_guard<std::mutex> lk(g_mutex);
        g_rounds.push_back(r);
    }
    return result;
}

void Landed(const Round& r, const char* why) {
    char stamp[16];
    Stamp(stamp, sizeof(stamp));
    Log("shot %s round %08X stopped (%s) at (%.0f %.0f %.0f), %.0f units from launch, %lu ms",
        stamp, r.handle, why, r.last[0], r.last[1], r.last[2], Distance(r.last, r.origin),
        GetTickCount() - r.launched);
}

// Every frame: each tracked round's position; the last one seen is where it stopped.
void PollRounds() {
    std::lock_guard<std::mutex> lk(g_mutex);
    for (std::size_t i = 0; i < g_rounds.size();) {
        Round& r = g_rounds[i];
        std::uint32_t handle = r.handle;
        void* ref = nullptr;
        if (g_lookup) g_lookup(&handle, &ref);
        const char* done = nullptr;
        if (!ref) {
            done = "gone";
        } else {
            const float* p = &At<float>(ref, kRefPosition);
            r.still = (Distance(p, r.last) < 1.0f) ? r.still + 1 : 0;
            r.last[0] = p[0];
            r.last[1] = p[1];
            r.last[2] = p[2];
            ReleaseRef(ref);
            if (r.still >= kStillPolls) done = "still";
            else if (GetTickCount() - r.launched > kMaxFlightMs) done = "timeout";
        }
        if (done) {
            Landed(r, done);
            g_rounds.erase(g_rounds.begin() + static_cast<std::ptrdiff_t>(i));
        } else {
            ++i;
        }
    }
}

}  // namespace

bool InstallShotTrace(void** player, void** playerCamera) {
    g_player = player;
    g_camera = playerCamera;
    const std::uintptr_t launch = Resolve("Projectile::Launch", ids::kProjectileLaunch, nullptr);
    g_lookup = reinterpret_cast<LookupByHandleFn>(
        Resolve("LookupReferenceByHandle", ids::kLookupByHandle, nullptr));
    if (!launch || !g_lookup) return false;
    g_origLaunch = reinterpret_cast<LaunchFn>(launch);
    if (PatchAllCalls(launch, reinterpret_cast<void*>(&LaunchHook), "Projectile::Launch") <= 0) return false;
    return StartMainThreadTick(kPollMs, &PollRounds);
}

void TraceAnimEvent(void* actor, const char* tag, void* graph) {
    if (!IsPlayer(actor) || !tag) return;
    char stamp[16];
    Stamp(stamp, sizeof(stamp));
    Log("shot %s event %s (graph %p)", stamp, tag, graph);
}

void TraceStep(void* actor, const char* what) {
    if (!IsPlayer(actor)) return;
    char stamp[16];
    Stamp(stamp, sizeof(stamp));
    Log("shot %s step %s", stamp, what);
}

}  // namespace tesruntime
