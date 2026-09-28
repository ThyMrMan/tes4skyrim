# Source-game movies (Bink 1) in Skyrim

Status: PLAN — parked 2026-09-27, not started. Nothing plays today.

## The problem

Scripted movies convert to nothing: `PlayBink` is a note-only row in
`script_convert/command_rows.py`, so the call is dropped and the script goes on.

Skyrim cannot play the source files anyway:

- The source movies are **Bink 1** (`FNVIntro.bik` starts `BIKi`).
- Skyrim SE links only **Bink 2** (the 1.6.1170 exe imports `bink2w64.dll`;
  its one movie is `BGS_Logo.bik`). Bink 2 does not decode Bink 1.
- Re-encoding to Bink 2 needs RAD's licensed encoder; no free one exists.
- Skyrim's engine command `PlayBink` (opcode 4372) exists, but Papyrus has no
  way to call it.

## Where it matters

Census of `PlayBink` in every export (SCPT, INFO, QUST, PACK), 2026-09-27:

| Plugin | Call | File on disk | Effect of the loss |
|---|---|---|---|
| FalloutNV.esm | VCG00 stage 0: `PlayBink "FNVIntro.bik" 1 1 0 1` | yes, 353 MB | **The opening cinematic** (Benny at the cemetery, the narration). The game goes straight to Doc Mitchell waking you. |
| FalloutNV.esm | VCG00 stages 7, 23: `FNVLogo1.bik`, `FNVLogo2.bik` | no | none: demo-only stages, files not shipped |
| FalloutNV.esm | `VEndingBinksSCRIPT`: `B01.bik`, `B02.bik` | no | none: commented out in the source |
| FalloutNV.esm | `CorporalBetsyScript`: `VB01.bik` | no | none: file not shipped, so FNV plays nothing either |
| Oblivion.esm | MQ16 stage 26: `OblivionOutro.bik` | not checked | **The main-quest ending movie** |

So two movies matter: New Vegas's intro and Oblivion's outro. A movie the
engine plays on its own, with no script (an intro started by the exe on New
Game, as Oblivion's likely is), would not appear in this census. That case
is not checked yet.

## Options

1. **Play the original file from the runtime DLL** (preferred). Decode Bink 1
   with a free decoder (ffmpeg's libavcodec reads it) and draw it full-screen
   with its audio. `PlayBink` converts to a native call. Reads the file from the
   source install, so no Bethesda asset ships. Makes movie playback depend on
   the DLL, which needs the user's go-ahead
   ([CLAUDE.md](../../CLAUDE.md#no-stopping)).
2. **Rebuild the FNV intro live** from VCG00's leftover stages. Needs
   special-idle animations (pistol whip, lying in the grave), and the stages
   are incomplete demo code, so it would only approximate the movie. No help
   for Oblivion's outro.

## Before starting

- Confirm how Oblivion (and Nehrim) start their intro movie, and list their
  `Data\Video` folders.
- Decide where the decoder lives (TESRuntime, shared by every game).
