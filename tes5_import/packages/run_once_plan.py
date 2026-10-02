"""Pick the run-once quest packages and write the faction marking each done (fills `run_once.RUN_ONCE_FACTION`).

See: docs/commentary/tes5_import_package.md#run-once-quest-packages
"""

import struct

from ..base.writer import pack_record, pack_string_subrecord, pack_subrecord
from ..record_types.common import get_formid, get_int, get_str
from .converter import T4_ONCE_PER_DAY, is_force_greet
from .run_once import RUN_ONCE_FACTION
from .scripts_falloutnv import folds_change
from .types_falloutnv import FNV_PATROL

#: PSDT.Time of a package with no schedule.
_ANY_TIME = -1

#: FACT DATA flag Hidden From PC.
_HIDDEN = 0x1


def _one_pass_patrol(rec: dict) -> bool:
    """A FO3/FNV Patrol that walks its route once (PKPT not Repeatable)."""
    return get_int(rec, 'PKDT.Type', -1) == FNV_PATROL and get_int(rec, 'PKPT.Repeatable', 1) == 0


def _runs_once(rec: dict, plan) -> bool:
    """An unscheduled quest package the source left once it completed (no stage fold, no force greet)."""
    return (get_formid(rec, 'FormID') in plan.owner_quest
            and (bool(get_int(rec, 'PKDT.Flags') & T4_ONCE_PER_DAY) or _one_pass_patrol(rec))
            and get_int(rec, 'PSDT.Time', _ANY_TIME) == _ANY_TIME
            and not folds_change(rec)
            and not is_force_greet(rec, get_int(rec, 'PKDT.Type', -1)))


def plan_run_once(by_type: dict, writer, plan) -> int:
    """Write a hidden faction for each of this plugin's run-once quest packages; returns the count."""
    RUN_ONCE_FACTION.clear()
    for rec in by_type.get('PACK', []):
        if not _runs_once(rec, plan):
            continue
        fid = writer.derive_formid('RUN_ONCE_FACTION', rec['FormID'])
        subs = pack_string_subrecord('EDID', f"TES4RunOnce_{get_str(rec, 'EditorID') or rec['FormID']}")
        subs += pack_subrecord('DATA', struct.pack('<I', _HIDDEN))
        writer.add_record('FACT', pack_record('FACT', fid, 0, subs))
        RUN_ONCE_FACTION[get_formid(rec, 'FormID')] = fid
    return len(RUN_ONCE_FACTION)
