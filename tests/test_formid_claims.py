"""Claimed derived FormIDs derive before any generator, so an older record keeps its slot."""

from tes5_import.base.formid_claims import CLAIMS, claim_existing
from tes5_import.base.writer import PluginWriter


def test_claimed_key_keeps_its_slot_against_a_later_collider():
    """A key claimed first owns the slot; a colliding key asking later rehashes elsewhere."""
    writer = PluginWriter([])
    writer.reserve_source_ids(set())
    claims = claim_existing(writer, 'export/FalloutNV.esm')
    site, key = CLAIMS['falloutnv.esm'][0]
    claimed = writer.derive_formid(site, key)
    assert claims == len(CLAIMS['falloutnv.esm'])
    assert writer.derive_formid('TEST_SITE', 'late') != claimed


def test_plugins_without_claims_derive_nothing():
    """A plugin with no entry claims nothing, whatever the folder's case."""
    assert claim_existing(PluginWriter([]), 'export/Oblivion.esm') == 0
