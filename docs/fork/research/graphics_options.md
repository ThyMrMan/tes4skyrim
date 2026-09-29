# Graphics: what limits converted content and what could improve it

Research notes from 2026-09-28, not a plan; nothing here is built or measured unless stated. Revisit when the project is more mature.

**Provenance.** Sections marked (docs) come from this repo's own measurements. Sections marked (web) come from
searches made 2026-09-28 and were not independently verified. Everything else is general engine
knowledge, and specific claims in it should be checked before anyone builds on them.

## 1. Where the ceiling is

Converted content is limited by four things, in rough order of how fixable they are:

1. **Missing source data.** Oblivion never authored roughness, metalness, environment maps or PBR. Nothing
   converts what was never made. Fixing it means new content, hand-made or generated.
2. **Skyrim's renderer.** DX11 with per-pixel shader types and fixed texture slots. Its lighting model
   differs from the fixed-function look the content was made for.
3. **CPU-bound submission.** Skyrim issues most draw work from one main thread, so many small shapes and
   shadowed lights hit the CPU before the GPU.
4. **The interior/exterior boundary.** Lighting, simulation, weather and rules are all per cell.

## 2. What the converter already does (docs)

Source: `docs/commentary/asset_convert_shader.md`. Measured on Oblivion/Nehrim.

Transfers cleanly:
- Diffuse and normal maps. The normal map's alpha is the specular mask in both engines.
- The `_n` and `_g` name-derivation rules, including the base-name fallback.
- Double-sided, emissive, vertex-color effects.

Rewritten or replaced:
- Glossiness is never copied. Oblivion's median is 10 (authoring default, 59% of materials), which is
  hair-like in Skyrim. It is written as 80, vanilla's mode.
- Specular strength is uniform; where no mask exists a constant 64/255 is baked into the normal alpha so a
  later real mask overrides it.
- `APPLY_HILIGHT2` diffuse alpha (a height field in Oblivion) is detected, since Skyrim reads it as
  transparency.
- `NiFlipController` is rebuilt as a frame-strip atlas; FX get a soft-particle depth fade.

Known gaps:
- Actor shader types (skin, hair, face, eye) are all written as type 0.
- Glow maps: 588 `_g` textures exist, mostly unnamed in the NIF.
- Trees: leaf animation needs a record, a root node type and flags; skinned branches can crash.
- No `_e` cubemaps exist in the Nehrim sample, so environment reflections cannot be rebuilt.
- Baked lighting in diffuse textures and low-poly silhouettes are not addressed by any conversion.

## 3. Draw calls and culling

**What a draw call costs in Skyrim.** Roughly one per shape per pass (shadow passes redraw). The cost is
mostly CPU driver work, so many small draws leave the GPU idle. Actors are expensive: several shapes each,
again in shadow passes.

**Skyrim's culling layers.**
1. Loaded cell grid (`uGridsToLoad`), LOD beyond it.
2. Frustum culling over node bounds.
3. Distance and size fade.
4. Hand-placed occlusion planes and boxes.
5. Rooms and portals (interiors), built on multibound nodes.

There is no general automatic occlusion. Coverage depends on authored data.

**Comparison points.**
- FO4 precombines merge static references offline, previs bakes cell-to-cell visibility. Fast, but any edit
  to a merged reference invalidates the cell.
- FO3/FNV use the same plane and portal scheme as Skyrim.
- Oblivion likely has little of it (unverified).

**Converter gap.** FO3/FNV occlusion planes, rooms and portals are dropped. Details and follow-up steps:
[fnv_occlusion_data.md](../performance.md#occlusion).

**Cheap wins with no engine work.**
- Fewer shapes per static, shared materials.
- Check that converted interiors carry rooms and portals.

## 4. Runtime culling and reduced simulation

Two tiers of state change:
- **Cheap, reversible:** node visibility, animation update skipping, AI process level, Havok sleeping,
  script throttling.
- **Expensive, hitchy:** loading or unloading 3D, attaching or detaching a cell.

So the workable model is three states: hidden and suspended, loaded but idle, fully active. Real-time
culling moves things between them and never in and out of memory.

Render side: runtime occlusion (depth pre-pass with hierarchical Z, or GPU queries; one-frame lag, pop-in)
or baked visibility (previs-like, needs a build step and goes stale).

Simulation side is a correctness problem, not a speed one. An actor in a hidden room can still see, hear or
chase the player, and quests and followers need it live. Suspend only what cannot affect the player.

## 5. Open houses (seamless interiors)

Draw calls are a factor, but not the main barrier. In order:
1. Lighting is per cell, with no blend of interior and weather lighting in one space.
2. Everything in a loaded cell is live, so all interiors would always simulate.
3. Culling data is authored for exteriors or interiors, not both.
4. Weather, reverb, and cell flags (wait, sleep, public, trespass) assume the boundary.
5. Interiors and exteriors were built at different scales in unrelated coordinates.

Section 4 is the mechanism that would make it viable. Unproven; large.

## 6. Upscaling and texture quality

**Textures — mature (web + general).**
- ESRGAN-family and transformer upscalers, with community game-texture models on OpenModelDB. chaiNNer
  chains them.
- Diffusion upscalers give more detail but hallucinate and are inconsistent across tiling neighbors.
- PBR map generation from diffuse is available but is a plausible guess, not the artist's intent.

**Skyrim-specific pitfalls.**
- Normal maps must be regenerated from height or upscaled with a dedicated model, then renormalized.
- Alpha, cutouts and tiling seams need separate handling.
- Baked shadows in diffuse get sharper, not fixed.
- 4x upscale is 16x the pixels: scale by visible size, compress to BC7 after.
- Roughness and metalness would need conversion to Skyrim's specular and complex-material slots.

**Models — immature.**
- Learned mesh upscaling is research-grade, not production.
- Procedural options are practical: raise segment counts on round objects, smooth silhouettes, bake detail
  into normals.
- Generative 3D makes new props, not faithful upgrades.
- Characters and creatures are hardest (skinning, animation compatibility).

**Where it would run.** On the user's machine, as an optional cached stage. ONNX Runtime with DirectML covers
NVIDIA, AMD and Intel. Ship the tool and model weights (each license checked), never the outputs, which is
consistent with the no-redistribution constraint.

## 7. Handcrafted mod lists

- Asset-only mods already work: `--import-mod`, then `-f <mod name>` (`docs/reference/pipeline.md`).
- Conversion time is unmeasured for replacer mods. Full pipeline for one large plugin is ~30 min on 32
  cores (docs/commentary/performance.md); a full mesh rebuild is ~20,000 meshes.
- Better fidelity than AI, but mods inherit original-engine authoring assumptions (old shading model, low-poly
  silhouettes, script-extender dependencies).
- A list should be a manifest (names, links, order, flags) the user downloads themselves, never a bundle.
- Needs an order, tested combinations, an optional downscale, and re-testing per converter version. The
  preflight audits ([preflight_audits.md](../done/preflight_audits.md)) are the natural home for that.
- Handcrafted first, AI upscale only for what is left.

## 8. RTX Remix (web)

- Remix is a DX9 replacer needing a fixed-function pipeline; best on 2000-2005 games. DX9.0c and shader-based
  games mostly do not work. Skyrim (DX11) is out.
- Known limits: shader-based games, animated mesh replacement, particles and special effects, per-game
  configuration, heavy path-tracing cost.
- Texture workflow: AI batch conversion (PBRFusion, Remix's own tools, PBRify_Remix), then human review.
  Painkiller RTX reports ~80% of repetitive work saved but hand-made metals, glass, skin and hero materials.
  Known model failures: texture atlases, roughness accuracy, baked shadows.
- Model workflow: replacement by artists, no automatic upgrade.
- Morrowind: a fan project (GokuwasHere) covers Seyda Neen, the Mages Guild and Balmora; unreleased, and
  I found no detail on which assets it replaces.
- PBRify_Remix is CC0 and trained on CC0 ambientCG content. That is a candidate for an optional upscale stage
  if the claim and license check out.

Sources: [compatibility wiki](https://github.com/NVIDIAGameWorks/rtx-remix/wiki/Compatibility),
[Painkiller RTX](https://developer.nvidia.com/blog/how-painkiller-rtx-uses-generative-ai-to-modernize-game-assets-at-scale),
[PBRify_Remix](https://github.com/Kim2091/PBRify_Remix),
[Morrowind Remix news](https://www.thefpsreview.com/2026/08/27/morrowind-is-getting-the-rtx-remix-treatment-24-years-after-bethesda-shipped-it/),
[TweakTown](https://www.tweaktown.com/news/113207/morrowind-rtx-remasters-the-iconic-the-elder-scrolls-game-with-full-path-traced-visuals/index.html).

## 9. Backporting FO4/F76 features (context)

Cost tiers for DLL work in Skyrim:
1. Cheap: rules, data, UI on existing hooks (perks, survival, dialogue wheel, companion affinity).
2. Medium: crafting with runtime mesh attachment, power armor, VATS-style targeting, settlement building.
3. Heavy: renderer features, new animation or physics or AI subsystems.
4. Out of reach: new record types, core class layout changes, F76 server features.

Tests for whether it is worth it: is there a Skyrim primitive to hang it on, is it a system or content, does
it survive runtime updates, does it need assets Skyrim lacks. A custom engine (OpenMW-style) buys
architectural freedom and stability at multi-year cost, mostly spent on bug-for-bug compatibility.

## 10. OpenMW and the later games (web, checked 2026-09-29)

**What works (0.49.0, July 2025).**
- Reads TES4-format plugins from Oblivion, FO3, FNV and Skyrim; reads FO4/FO76 BA2 archives; parses every
  official NIF from Oblivion, Skyrim, FO3/NV, FO4 and FO76.
- World loading, terrain heightmaps, statics, lights, items, doors, containers, flora. Diffuse, normal and
  glow maps. Basic book and door interaction. Limited NPC rendering (Oblivion and 2011 Skyrim only).
- Enabled by loading the game's files as "mods" in the launcher plus `load unsupported nif files = true` in
  `settings.cfg`.
- The ESM reader came from UESP research (0.48) and was extended to FO4 from xEdit research (0.49).

**What is missing.** Skinned geometry for Skyrim SE, particles, animations, SpeedTree, FaceGen, Havok,
collision generation for Skyrim SE and FO4/76, and every gameplay system (firearms, AI, dialogue, quests,
inventory, physics, VATS, scripted events).

**Direction.** Framed as early "walking simulator" prototyping with Morrowind staying primary. 0.51.0 (June
2026) says nothing about the other games, so visible progress since 0.49 looks slow (unreleased work is
possible). Older forum posts say the team will not port Skywind; an earlier developer (cc9cii) ported
Oblivion and FO3/FNV loading in a fork, whose current state was not checked.

**Read for this project.** The cheap layer (formats, world loading, basic rendering) works. The hard layer
(skeletal animation, physics, AI, scripting, dialogue) is untouched, and that is what this repo's converter
already solves inside Skyrim. Two things to watch: skinned-mesh and animation support, and the physics
approach. Not verified: the forum thread on later-game work was blocked, so developer activity is inferred
from release notes.

Sources: [0.49.0](https://openmw.org/2025/openmw-0-49-0-released/),
[0.51.0](https://openmw.org/2026/openmw-0-51-0-released/),
[GamingOnLinux on 0.49](https://www.gamingonlinux.com/2025/07/openmw-0-49-arrives-to-enhanced-morrowind-and-theyre-looking-to-support-later-bethesda-games/),
[GenerationAmiga on FNV](https://www.generationamiga.com/2026/07/24/fallout-new-vegas-could-escape-its-old-engine-with-openmw/),
[forum thread](https://forum.openmw.org/viewtopic.php?t=3017&start=440).

## 11. Havok alternatives and work-arounds (general knowledge, unverified)

Havok is three things: rigid-body physics and collision, ragdolls and constraints, and animation with
behavior graphs. Skyrim also uses Havok cloth.

**Engines.** Bullet (zlib, mature; OpenMW uses it, and the HDT-SMP mods run it inside Skyrim beside Havok),
Jolt (MIT, modern, multithreaded), PhysX (BSD in recent versions, strong character controller), Rapier, ODE,
Newton. Havok itself is proprietary and Microsoft-owned; a free SDK is not believed to exist now.

**Work-arounds.**
- Convert the data, not the engine: read Havok collision shapes from NIFs and HKX, rebuild them as the new
  engine's shapes, map collision layers and materials to its filter groups, rebuild ragdoll constraints from
  the joint limits. This repo already does the Havok-native version (collision extraction, 64-bit HKX
  conversion).
- Behavior graphs are the hard half: a state machine plus blending and animation compression, not physics.
  Community tools read and generate them (Pandora, Haviour) but a full replacement runtime is a large project.
- Expect behavior differences (stacking, friction, sleeping, ragdoll settling) and quirk-dependent gameplay
  to change.

| Path | Covers | Cost |
|---|---|---|
| Stay on Havok (Skyrim engine) | Everything | None, engine limits stay |
| Bullet beside Havok, as HDT-SMP does | Cloth, hair, extra bodies | Small to medium |
| Replace collision only, in a new engine | Statics, props, triggers | Medium |
| Replace ragdolls and character controller | Actor physics | Large |
| Replace behavior graphs and animation | Actor movement and combat | Very large |

Only matters if the project leaves Skyrim's engine. Collision is the tractable part there; animation and
behavior is where the time would go.

## 12. Suggested order when this is picked up

1. Measure first: a frame capture (RenderDoc) of a heavy scene showing draw count, and whether it is CPU or
   GPU bound.
2. Cheap converter fixes from section 2's gaps: glow, actor shader types.
3. FO3/FNV occlusion data ([fnv_occlusion_data.md](../performance.md#occlusion)).
4. Optional cached texture upscale stage, with per-category handling for diffuse, normal and alpha.
5. Procedural mesh smoothing before any AI mesh work.
6. Curated mod-list manifests once the asset-only import path is proven on real packs.
7. Runtime culling or seamless interiors only if measurements point there.
