"""A FO3/FNV Upper Body outfit claims the whole body the body-slot patch splits."""

from tes5_import.record_types import world_falloutnv
from tes5_import.record_types.equipment import armo_slots


def test_upper_body_claims_body_feet_and_lower_body():
    """Upper Body (bit 2) -> 32-Body, 37-Feet and 49, so the patched skin's legs stay hidden.

    See: docs/commentary/tes4_export_falloutnv.md#upper-body-covers-feet
    """
    world_falloutnv.register_fallout_source({'TERM': [1]})
    try:
        slots = armo_slots({'BMDT.BipedFlags': '4'})
    finally:
        world_falloutnv._IS_FALLOUT_SOURCE.clear()
    assert slots == (1 << 2) | (1 << 7) | (1 << 19)
