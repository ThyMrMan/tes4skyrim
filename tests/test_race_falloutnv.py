"""FO3/FNV children take Skyrim's child races, and so does the clothing they carry.

See: docs/commentary/tes4_export_falloutnv.md#humanoid-races
"""
import pytest

from tes5_import.record_types import race_falloutnv as R
from tes5_import.record_types import world_falloutnv


@pytest.fixture
def fallout():
    """Mark this run as a Fallout source for the test's duration."""
    world_falloutnv.register_fallout_source({'TERM': [1]})
    yield
    world_falloutnv._IS_FALLOUT_SOURCE.clear()
    R._CHILD_WORN.clear()


def test_a_child_takes_its_ethnicitys_child_race(fallout):
    """HispanicChild -> ImperialRaceChild; an adult race has no child race."""
    assert R.fallout_child_race(0x000042C4) == 0x0002C659
    assert R.fallout_child_race(0x000038E5) is None
    assert R.fallout_race_edid(0x000042C4) == 'Imperial'


def test_only_fallout_runs_have_children():
    """An Oblivion run never reads the Fallout race table."""
    assert R.fallout_child_race(0x000042C4) is None


def test_items_a_child_carries_fit_the_child_races(fallout):
    """Amata's vault suit is child clothing; an adult's item is not."""
    by_type = {'NPC_': [
        {'FormID': '000300E9', 'RNAM.Race': '000042C4', 'ItemCount': '1',
         'Item[0].FormID': '000340F2'},
        {'FormID': '000300EF', 'RNAM.Race': '00000019', 'ItemCount': '1',
         'Item[0].FormID': '0000431E'}]}
    assert R.register_child_wear(by_type) == 1
    assert R.child_wears({'FormID': '000340F2'})
    assert not R.child_wears({'FormID': '0000431E'})
