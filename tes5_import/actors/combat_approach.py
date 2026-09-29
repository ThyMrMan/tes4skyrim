"""The alias pool TES4Polyfill.ForceCombatApproach puts a StartCombat attacker and its target in.

Oblivion's StartCombat attacker advances on its target until it can attack and
never hides or searches; Skyrim's combat does both. Vanilla steers where an
actor fights with a combat override package on its quest alias (the Civil War
finale's enemies close on the player, followers stay near them). Each attacker
alias carries one: vanilla's HoldPositionWithTravel on its paired target alias,
to Oblivion's ranged attack range when a bow, staff, spell or crossbow is in
hand, else to melee distance, then fight from there. Both give way once the target is dead.

See: docs/commentary/script_convert.md#startcombat-approaches-an-undetected-target
"""

import struct

from script_convert.constants import COMBAT_APPROACH_QUEST, COMBAT_QUEUE_SCRIPT
from script_convert.pipeline import build_vmad_quest_fragments
from ..base.conditions import build_ctda
from ..dialogue.force_greets import alias_quest
from ..packages.converter import ANY_TIME_PSDT, Inputs, package_markers
from ..packages.templates import HOLD_POSITION_TRAVEL_512, HOLD_POSITION_TRAVEL_1024
from ..record_types.common import (pack_formid_subrecord, pack_record,
                                   pack_string_subrecord, pack_subrecord)

#: Attacker/target alias pairs: attacker alias 2n, target alias 2n+1.
PAIRS = 32

#: derive_formid sites.
_QUEST_SITE, _PACK_SITE, _LIST_SITE = 'COMBAT_APPROACH_QUST', 'COMBAT_APPROACH_PACK', 'COMBAT_APPROACH_FLST'

#: PKDT of vanilla CWFinaleEnemyHoldPositionNearPlayer, which closes on its target: Weapon Drawn, Combat override, run.
_PKDT = bytes.fromhex('000080001204024F00000000')

#: Oblivion.exe 0x6142d0's default ranged maximum (fArrowMaxDistance is the same 2000).
_RANGED_RADIUS = 2000

#: Melee travel and hold radius: CWFinaleEnemyHoldPositionNearPlayer closes to 500 and fights from there.
_MELEE_RADIUS = 512

#: Travel in until 1024 of the target (Oblivion's optimal range, 1000) at range, 512 in melee.
_TEMPLATE = {True: HOLD_POSITION_TRAVEL_1024, False: HOLD_POSITION_TRAVEL_512}

#: The override applies only farther out than its travel stop; closer in, Skyrim's own combat fights.
_REACH = {True: 1024.0, False: 512.0}

#: PLDT type 8 and PTDA type 4: the reference an alias of the package's quest holds.
_ALIAS_REF, _PTDA_ALIAS = 8, 4

#: Condition functions: GetDistance, GetDead, GetEquippedItemType (0 left hand, 1 right).
_GET_DISTANCE, _GET_DEAD, _GET_EQUIPPED_ITEM_TYPE = 1, 46, 597

#: CTDA type bits: compare greater-than, parameters name quest aliases (vanilla: 230 GetDistance uses).
_GREATER, _USE_ALIASES = 0x40, 0x02

#: GetEquippedItemType values Oblivion fights at range with: bow, staff, spell, crossbow.
_RANGED_ITEMS = (7, 8, 9, 12)

#: CTDA run-on 5: the quest alias named in parameter 3.
_RUN_ON_ALIAS = 5


def _conditions(target_alias: int, ranged: bool) -> bytes:
    """Target alias alive and out of reach and, for the ranged package, a ranged item in either hand."""
    out = pack_subrecord('CTDA', build_ctda(_GET_DEAD, comp_value=0.0,
                                            run_on=_RUN_ON_ALIAS, param3=target_alias))
    out += pack_subrecord('CTDA', build_ctda(_GET_DISTANCE, target_alias, comp_value=_REACH[ranged],
                                             operator=_GREATER | _USE_ALIASES))
    if ranged:
        checks = [(hand, item) for hand in (0, 1) for item in _RANGED_ITEMS]
        for i, (hand, item) in enumerate(checks):
            out += pack_subrecord('CTDA', build_ctda(_GET_EQUIPPED_ITEM_TYPE, hand, comp_value=float(item),
                                                     is_or=i < len(checks) - 1))
    return out


def _package(fid: int, edid: str, quest_fid: int, target_alias: int, ranged: bool) -> bytes:
    """Travel to and hold near `target_alias`, a combat override instance of vanilla's template."""
    inputs = Inputs(_TEMPLATE[ranged])
    inputs.set('location', (_ALIAS_REF, target_alias, _RANGED_RADIUS if ranged else _MELEE_RADIUS))
    inputs.set('center', (_PTDA_ALIAS, target_alias, 0))
    subs = pack_string_subrecord('EDID', edid)
    subs += pack_subrecord('PKDT', _PKDT)
    subs += pack_subrecord('PSDT', ANY_TIME_PSDT)
    subs += _conditions(target_alias, ranged)
    subs += pack_formid_subrecord('QNAM', quest_fid)
    subs += pack_subrecord('PKCU', struct.pack('<III', len(inputs.t.inputs), inputs.t.formid, inputs.t.version))
    subs += inputs.emit()
    subs += package_markers()
    return pack_record('PACK', fid, 0, subs)


def _pair(writer, quest_fid: int, n: int) -> list:
    """Pair n's packages and FormList; its two alias bodies (attacker, target)."""
    list_fid = writer.derive_formid(_LIST_SITE, n)
    subs = pack_string_subrecord('EDID', f'TES4CombatApproachList{n}')
    for kind in ('Ranged', 'Melee'):
        fid = writer.derive_formid(_PACK_SITE, (n, kind))
        writer.add_record('PACK', _package(fid, f'TES4CombatApproach{n}{kind}', quest_fid,
                                           2 * n + 1, kind == 'Ranged'))
        subs += pack_formid_subrecord('LNAM', fid)
    writer.add_record('FLST', pack_record('FLST', list_fid, 0, subs))
    return [pack_formid_subrecord('ECOR', list_fid), b'']


def create_combat_approach(writer, master_index=None) -> dict:
    """The pool quest with its TES4_CombatQueue script, adopted from a master that has it; {EditorID: FormID}."""
    fid = master_index.find_by_edid(b'QUST', COMBAT_APPROACH_QUEST) if master_index is not None else 0
    if not fid:
        fid = writer.derive_formid(_QUEST_SITE, COMBAT_APPROACH_QUEST)
        bodies = [body for n in range(PAIRS) for body in _pair(writer, fid, n)]
        vmad = build_vmad_quest_fragments(COMBAT_APPROACH_QUEST, [], None,
                                          attached_script=(COMBAT_QUEUE_SCRIPT, {}), quest_fid=fid)
        writer.add_record('QUST', alias_quest(fid, COMBAT_APPROACH_QUEST, 'TES4 Combat Approaches',
                                              bodies, vmad))
    return {COMBAT_APPROACH_QUEST: fid}
