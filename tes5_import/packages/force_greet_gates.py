"""A ForceGreet package's own conditions, standing in for GetIsCurrentPackage on its lines.

A source Dialogue package stays current through the conversation it opens and
keeps retrying, so its greeting asks `GetIsCurrentPackage(<package>) == 1`. A
Skyrim ForceGreet ends when its conversation starts and retires for the day, so
that test holds only at the instant it greets: a talk broken off can never be
reopened. The line instead asks what the package itself asks, less the
not-yet-set stages the line sets itself: the package held through its talk.

See: docs/commentary/tes5_import_dialogue.md#force-greet-package-gate
"""

import re
import struct

#: ForceGreet PACK FormID -> its converted conditions (packed CTDA/CIS2 subrecords).
FORCE_GREET_CONDITIONS: dict = {}

#: PACK FormIDs a script forces on (AddScriptPackage): their conditions do not say when they run.
SCRIPT_FORCED: set = set()


def note_script_forced(pack_fids) -> None:
    """Record the plugin's script-forced packages, replacing the last plugin's."""
    SCRIPT_FORCED.clear()
    SCRIPT_FORCED.update(pack_fids)


def gate_for(pack_fid: int, conditions: bytes) -> None:
    """Keep a ForceGreet's conditions as its lines' gate, unless it has none or a script forces it."""
    if conditions and pack_fid not in SCRIPT_FORCED:
        FORCE_GREET_CONDITIONS[pack_fid] = conditions

#: TES5 GetIsCurrentPackage; the CTDA OR flag and "==" operator bits.
_FUNC_GET_IS_CURRENT_PACKAGE = 161
_CTDA_OR = 0x01
_OP_MASK = 0xE0

#: TES5 GetStage and GetStageDone; the CTDA "<" operator bits.
_FUNC_GET_STAGE = 58
_FUNC_GET_STAGE_DONE = 59
_OP_LESS = 0x80

#: A `setstage <quest> <stage>` statement anywhere in a script.
_SETSTAGE = re.compile(r'^\s*setstage\s+(\w+)\s+(\d+)', re.IGNORECASE | re.MULTILINE)

#: A source INFO's result script fields.
_RESULT_SCRIPTS = ('ResultScript', 'ResultScriptEnd')


def stages_set(rec: dict, quest_fid_by_edid: dict) -> frozenset:
    """{(quest FormID, stage)} the `setstage` lines of an INFO's result scripts set."""
    scripts = '\n'.join(rec.get(k) or '' for k in _RESULT_SCRIPTS)
    return frozenset((quest_fid_by_edid[m.group(1).lower()], int(m.group(2)))
                     for m in _SETSTAGE.finditer(scripts)
                     if m.group(1).lower() in (quest_fid_by_edid or {}))


def _awaits(ctda: bytes, sets: frozenset) -> bool:
    """Whether `ctda` tests that a stage in `sets` is not yet set (GetStageDone == 0 or GetStage < it)."""
    value, = struct.unpack_from('<f', ctda, 4)
    func, _pad, quest = struct.unpack_from('<HHI', ctda, 8)
    op = ctda[0] & _OP_MASK
    return ((func == _FUNC_GET_STAGE_DONE and not op and not value
             and (quest, struct.unpack_from('<I', ctda, 16)[0]) in sets)
            or (func == _FUNC_GET_STAGE and op == _OP_LESS and (quest, int(value)) in sets))


def _package_test(ctda: bytes) -> int:
    """The ForceGreet FormID a subject `GetIsCurrentPackage(p) == 1` names, else 0."""
    func, _pad, package = struct.unpack_from('<HHI', ctda, 8)
    value, = struct.unpack_from('<f', ctda, 4)
    run_on, = struct.unpack_from('<I', ctda, 20)
    if (func != _FUNC_GET_IS_CURRENT_PACKAGE or ctda[0] & _OP_MASK or value != 1.0
            or run_on or package not in FORCE_GREET_CONDITIONS):
        return 0
    return package


def while_package_runs(pairs: list, unpack, sets: frozenset = frozenset()) -> list:
    """`pairs` of (CTDA, trailing subrecords), each lone ForceGreet test swapped for its package's conditions.

    A test inside an OR chain is kept; `unpack` turns packed conditions into
    pairs. A lone package test awaiting a stage in `sets` (the line's own
    SetStages) is left out, so the line outlives its own fragment.
    """
    out = []
    for i, (ctda, extra) in enumerate(pairs):
        chained = ctda[0] & _CTDA_OR or (i and pairs[i - 1][0][0] & _CTDA_OR)
        package = 0 if chained else _package_test(ctda)
        if not package:
            out.append((ctda, extra))
            continue
        tests = unpack(FORCE_GREET_CONDITIONS[package])
        out += [(c, x) for j, (c, x) in enumerate(tests)
                if not _awaits(c, sets) or c[0] & _CTDA_OR or (j and tests[j - 1][0][0] & _CTDA_OR)]
    return out
