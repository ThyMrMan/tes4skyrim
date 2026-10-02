"""Run-once quest packages: a hidden faction per package marks each actor done with it.

Once Per Day made a source actor leave an unscheduled package as soon as it
completed, so the next package on its list ran: FO3's Dad walks to the speech
marker, then talks to Jonas on the intercom under the same stage condition.
The importer drops that flag from quest packages (Skyrim's daily latch may be
spent already), so the actor would stay. Instead each such package tests
`GetInFaction(<its faction>) == 0`, and `TES4_StagePackageAlias` adds its actor
to the faction on OnPackageEnd. The table is filled before QUST and PACK convert
(`run_once_plan.plan_run_once`).

See: docs/commentary/tes5_import_package.md#run-once-quest-packages
"""

import struct

from ..base.writer import pack_subrecord

#: Source PACK FormID -> the FACT marking an actor done with it.
RUN_ONCE_FACTION: dict = {}

#: TES5 GetInFaction.
_FUNC_GET_IN_FACTION = 71

#: The alias script's parallel arrays: a package, and the faction its end adds.
PACKAGES_PROPERTY = 'RunOncePackages'
FACTIONS_PROPERTY = 'RunOnceFactions'


def run_once_guard(pack_fid: int) -> bytes:
    """`GetInFaction(<the package's faction>) == 0` on the subject, or b'' for another package."""
    faction = RUN_ONCE_FACTION.get(pack_fid)
    if not faction:
        return b''
    return pack_subrecord('CTDA', struct.pack('<B3xfHHIIII I', 0, 0.0, _FUNC_GET_IN_FACTION, 0,
                                              faction, 0, 0, 0, 0xFFFFFFFF))


def alias_run_once(pack_fids) -> dict:
    """The alias script's run-once array properties for an alias's packages, {} for none."""
    pairs = [(p, RUN_ONCE_FACTION[p]) for p in pack_fids if p in RUN_ONCE_FACTION]
    if not pairs:
        return {}
    return {PACKAGES_PROPERTY: ('objects', [p for p, _f in pairs]),
            FACTIONS_PROPERTY: ('objects', [f for _p, f in pairs])}
