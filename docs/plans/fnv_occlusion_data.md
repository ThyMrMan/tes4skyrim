# FO3/FNV occlusion planes, rooms and portals

Status: PLAN — noted 2026-09-28 as a possible follow-up, not started. Nothing below is measured.

## The observation

FO3/FNV cull with hand-placed occlusion planes (exteriors) and rooms and portals
(interiors). Skyrim uses the same scheme. A code search found no stage that carries
any of it across:

- `XORD`, `XPOD`, `XRMR`, `XLRM` are never read by `tes4_export/` nor written by
  `tes5_import/`.
- `RoomMarker` (679 REFRs in FalloutNV.esm) and `MultiBoundMarker` (2) are swapped
  for an invisible `XMarker` (`tes5_import/record_types/world_falloutnv.py`). That hides
  the marker and drops what it stood for.
- `XPRM` primitives are copied raw, but only as trigger volumes
  (`world.py`, `_refr_head`).
- `nif_converter.py` has no `BSMultiBoundNode` handling. Only `lod/terrain_nif.py`
  builds them, for generated LOD.

Oblivion has no such data, so it loses nothing.

## Guess to test

Converted FO3/FNV interiors draw everything in the frustum, and converted
exterior cities lose their occlusion planes. The cost in play is unmeasured.

## Steps if pursued

1. Extend the export to dump `XORD`, `XPOD`, `XRMR`, `XLRM` and `XMBR` from FO3/FNV
   cells and refs (raw hex, as `XPRM.Raw` does).
2. Count them from the dump: cells and refs affected.
3. Compare the layouts against Skyrim's in `references/xEdit`, then census
   Skyrim.esm for how vanilla writes them. Byte-copy only if they match.
4. Check whether converted NIFs keep or drop `BSMultiBoundNode`; room and portal
   refs point at multibound nodes.
5. Measure in game or by frame capture before and after on one dense interior.
6. Add a preflight check: rooms, portals and planes in the source cell against the
   converted cell (see [preflight_audits.md](preflight_audits.md)).

## Open questions

- Whether Oblivion interiors would benefit from generated portals. Nothing authored to convert.
- Whether the room bound refs need their multibound base objects in the output.
