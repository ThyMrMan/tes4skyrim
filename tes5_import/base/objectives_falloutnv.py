"""FO3/FNV quest-objective conditions, mirrored in globals Skyrim can test.

Skyrim's GetObjectiveCompleted and GetObjectiveDisplayed are script-only, so
each objective state a FO3/FNV condition tests gets a global
(`TES4ObjDone_<quest>_<n>`, `TES4ObjShown_<quest>_<n>`). The condition reads
the global; every converted SetObjectiveCompleted / SetObjectiveDisplayed on
that objective sets it. Only objectives of this plugin's own quests are
mirrored.

See: docs/commentary/tes5_import_conditions.md#fallout-objective-conditions
"""

import struct

from .conditions_falloutnv import OBJECTIVE_FUNCS, OBJECTIVE_GLOBALS
from .owned_records import emit_global
from ..record_types.world_falloutnv import is_fallout_source, register_fallout_source

#: Record types whose conditions can test an objective.
_CONDITION_SIGS = ('INFO', 'PACK', 'QUST')


def objective_global_name(quest_edid: str, index: int, state: str) -> str:
    """The mirror global's EditorID for one objective state."""
    return f'TES4Obj{state}_{quest_edid}_{index}'


def _tests(by_type: dict) -> set:
    """{(quest FormID low 24, objective index, state)} every objective condition tests."""
    out = set()
    for sig in _CONDITION_SIGS:
        for rec in by_type.get(sig, ()):
            for key, raw in rec.items():
                if not key.endswith('.Raw') or 'Condition' not in key or len(raw) < 40:
                    continue
                data = bytes.fromhex(raw)
                state = OBJECTIVE_FUNCS.get(struct.unpack_from('<H', data, 8)[0])
                if state:
                    quest, index = struct.unpack_from('<II', data, 12)
                    out.add((quest & 0xFFFFFF, index, state))
    return out


def _mirrored(by_type: dict) -> list:
    """[(quest FormID low 24, quest EditorID, index, state)] for this plugin's own quests."""
    edids = {int(q['FormID'], 16) & 0xFFFFFF: q['EditorID'] for q in by_type.get('QUST', ())
             if q.get('FormID') and q.get('EditorID')}
    return [(q, edids[q], index, state) for q, index, state in sorted(_tests(by_type)) if q in edids]


def objective_script_globals(by_type: dict) -> dict:
    """{(quest EditorID lower, objective index): {state: global name}} for the script converter."""
    out = {}
    for _q, edid, index, state in _mirrored(by_type):
        out.setdefault((edid.lower(), index), {})[state] = objective_global_name(edid, index, state)
    return out


def create_objective_globals(writer, by_type: dict, converter_cls) -> None:
    """Write every mirror global, bound by name; fill OBJECTIVE_GLOBALS and the converter's map.

    Runs before any condition or script VMAD is built; a no-op for other games.
    """
    OBJECTIVE_GLOBALS.clear()
    register_fallout_source(by_type)
    if not is_fallout_source():
        return
    for q, edid, index, state in _mirrored(by_type):
        OBJECTIVE_GLOBALS[(q, index, state)] = emit_global(
            writer, objective_global_name(edid, index, state), 's')
    converter_cls.objective_globals = objective_script_globals(by_type)
    print(f"  Objective globals: {len(OBJECTIVE_GLOBALS)} objective states FO3/FNV conditions test")
