"""A force greet's line that sets the stage its own package waits on runs its End script only in the dialogue menu.

A Skyrim force greet that starts as another talk closes says its line before
the menu opens. FO3's Amata ("Butch is such an idiot", `000319BB`, `setstage
CG02 32`) did: the stage ended her Dialogue package `CG02AmataFindPlayer`
(CG02 32 not done), so the menu never opened. Such a line's End script (its
condition `GetIsCurrentPackage(<package>) == 1`, the package asking that a
stage the line sets is not yet set) is wrapped in `UI.IsMenuOpen("Dialogue
Menu")`: an early bark leaves the package running, and the line said again
in the menu sets the stage as the source did.

See: docs/commentary/tes5_import_dialogue.md#force-greet-menu-stage
"""

import re
import struct

#: GetIsCurrentPackage, GetStage and GetStageDone (one numbering in TES4, FO3, FNV and TES5).
_FUNC_CURRENT_PACKAGE, _FUNC_GET_STAGE, _FUNC_GET_STAGE_DONE = 161, 58, 59

#: CTDA type byte: operator bits, "==" and "<".
_OP_MASK, _OP_EQUAL, _OP_LESS = 0xE0, 0x00, 0x80

#: A `setstage <quest> <stage>` statement anywhere in a script.
_SETSTAGE = re.compile(r'^\s*setstage\s+(\w+)\s+(\d+)', re.IGNORECASE | re.MULTILINE)


def _tests(rec: dict) -> list:
    """(operator, value, function, param 1, param 2, run on subject) of each source condition."""
    out = []
    for i in range(int(rec.get('ConditionCount') or 0)):
        raw = bytes.fromhex(rec.get(f'Condition[{i}].Raw') or '')
        if len(raw) >= 20:
            value, = struct.unpack_from('<f', raw, 4)
            func, = struct.unpack_from('<H', raw, 8)
            p1, p2 = struct.unpack_from('<II', raw, 12)
            subject = len(raw) < 24 or not struct.unpack_from('<I', raw, 20)[0]
            out.append((raw[0] & _OP_MASK, value, func, p1, p2, subject))
    return out


def _stages_set(rec: dict, quest_fids: dict) -> set:
    """{(quest FormID, stage)} the INFO's result scripts set."""
    text = '\n'.join(rec.get(k) or '' for k in ('ResultScript', 'ResultScriptEnd'))
    return {(quest_fids[m.group(1).lower()], int(m.group(2)))
            for m in _SETSTAGE.finditer(text) if m.group(1).lower() in quest_fids}


def _awaits(test: tuple, sets: set) -> bool:
    """Whether a package condition holds only until a stage in `sets` is set."""
    op, value, func, p1, p2, _subject = test
    return ((func == _FUNC_GET_STAGE_DONE and op == _OP_EQUAL and not value and (p1, p2) in sets)
            or (func == _FUNC_GET_STAGE and op == _OP_LESS and (p1, int(value)) in sets))


def menu_only_infos(by_type: dict) -> set:
    """Upper-hex FormIDs of the INFOs whose End script must wait for the dialogue menu."""
    packs = {int(r['FormID'], 16): _tests(r) for r in by_type.get('PACK', ()) if r.get('FormID')}
    quest_fids = {(r.get('EditorID') or '').lower(): int(r['FormID'], 16)
                  for r in by_type.get('QUST', ()) if r.get('FormID')}
    out = set()
    for rec in by_type.get('INFO', ()):
        named = [t[3] for t in _tests(rec)
                 if t[2] == _FUNC_CURRENT_PACKAGE and t[0] == _OP_EQUAL and t[1] == 1.0 and t[5]]
        sets = _stages_set(rec, quest_fids) if named else set()
        if any(_awaits(t, sets) for pack in named for t in packs.get(pack, ())):
            out.add(rec['FormID'].upper())
    return out


def in_menu_only(lines: list) -> list:
    """End fragment lines wrapped to run only while the dialogue menu is open."""
    return ['  If UI.IsMenuOpen("Dialogue Menu")'] + ['  ' + line for line in lines] + ['  EndIf']
