"""TES4 `ForceFlee [cell] [ref]` as a Flee package handed out through an alias pool.

Skyrim's ForceFlee is a console command Papyrus cannot reach; its Flee
procedure is a package. One start-game quest owns a pool of aliases per
destination: a FleeTo package to the named reference (else into the named
cell), or a FleeFrom package away from the actor's threats when none is named.
The converted call fills a free alias (`TES4Polyfill.FillPoolSlot`) and the
package's OnEnd fragment (`TES4_ForceGreetDone`) empties it once the actor has
fled, so nothing stays changed afterwards.

See: docs/commentary/script_convert.md#forceflee-is-a-package
"""

from script_convert.constants import FORCE_FLEE_QUEST
from .converter import Inputs, build_location, build_pkdt, SPEED_RUN
from .templates import FLEE_FROM, FLEE_TO
from ..base.text_reader import get_formid, get_str
from ..dialogue.force_greets import pool_package, pool_quest

#: derive_formid sites.
_QUEST_SITE, _PACK_SITE = 'FORCE_FLEE_QUST', 'FORCE_FLEE_PACK'

#: PKDT flags 0x2000 and interrupts of vanilla MQ303DragonFarengarFlee (FleeTo) and WEJS11SigarFlee (FleeFrom).
_PKDT_FLAGS, _FLEE_TO_INTERRUPT, _FLEE_FROM_INTERRUPT = 0x2000, 0xFC00, 0xFEFF

#: FleeFrom's Distance to Flee: Skyrim.esm fFleeDistanceExterior, as WEJS11SigarFlee writes it.
_FLEE_DISTANCE = 5000.0

#: A TES4 placed creature is an ACHR once converted.
_TES5_SIG = {'ACRE': 'ACHR'}

#: PLDT types: 0 near reference, 1 in cell.
_NEAR_REF, _IN_CELL = 0, 1


def _edid_index(by_type: dict, sigs: tuple) -> dict:
    """Lowercased EditorID -> output FormID for this plugin's own records of `sigs`."""
    return {get_str(r, 'EditorID').lower(): get_formid(r, 'FormID')
            for sig in sigs for r in by_type.get(sig, [])
            if get_str(r, 'EditorID')}


def _resolver(by_type: dict, master_index):
    """`(sigs, edid) -> FormID`: the plugin's own record first, then its masters'."""
    own = {sigs: _edid_index(by_type, sigs)
           for sigs in (('REFR', 'ACHR', 'ACRE'), ('CELL',))}

    def resolve(sigs: tuple, edid: str) -> int:
        """FormID of the record `edid` names, 0 when neither side has it."""
        fid = own[sigs].get(edid, 0)
        if fid or master_index is None:
            return fid
        for sig in sigs:
            fid = master_index.find_by_edid(_TES5_SIG.get(sig, sig).encode('ascii'), edid)
            if fid:
                return fid
        return 0
    return resolve


def _inputs(key: str, resolve) -> tuple:
    """(Inputs, interrupt flags) for one destination key."""
    cell, _, ref = key.partition('|')
    ref_fid = resolve(('REFR', 'ACHR', 'ACRE'), ref) if ref else 0
    cell_fid = resolve(('CELL',), cell) if cell and not ref_fid else 0
    if ref_fid or cell_fid:
        i = Inputs(FLEE_TO)
        i.set('location', build_location(_NEAR_REF, ref_fid, 0) if ref_fid
              else build_location(_IN_CELL, cell_fid, 0))
        return i, _FLEE_TO_INTERRUPT
    i = Inputs(FLEE_FROM)
    i.set('flee_distance', _FLEE_DISTANCE)
    return i, _FLEE_FROM_INTERRUPT


def write_force_flee_quest(writer, slots: dict, by_type: dict,
                           master_index=None) -> int:
    """Mint the TES4ForceFlees quest and one Flee PACK per alias of `slots`; 0 without call sites.

    `slots` is say_topics.build_force_flee_slots' {flee_key: (first alias, count)}.
    """
    if not slots:
        return 0
    resolve = _resolver(by_type, master_index)
    quest_fid = writer.derive_formid(_QUEST_SITE, FORCE_FLEE_QUEST)
    pack_fids = []
    for key, (first, count) in slots.items():
        inputs, interrupt = _inputs(key, resolve)
        pkdt = build_pkdt(_PKDT_FLAGS, SPEED_RUN, interrupt)
        for n in range(count):
            fid = writer.derive_formid(_PACK_SITE, (key, n))
            edid = f'TES4ForceFlee_{key.strip("|").replace("|", "_") or "Away"}_{n}'
            writer.add_record('PACK', pool_package(edid, fid, first + n,
                                                   quest_fid, inputs, pkdt))
            pack_fids.append(fid)
    writer.add_record('QUST', pool_quest(quest_fid, FORCE_FLEE_QUEST,
                                         'TES4 Force Flees', pack_fids))
    return quest_fid
