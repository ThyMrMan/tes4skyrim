"""FO3/FNV reputation and karma: FormLists of globals, commands on them, conditions reading them.

See: docs/commentary/tes5_import_character_data.md#fallout-reputation
"""
import struct

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
from tes5_import.base.conditions_falloutnv import mirrored_ctda
from tes5_import.record_types.reputation_falloutnv import create_reputation_records
from tes5_import.record_types.world_falloutnv import register_fallout_source

NCR = 0x0F2E8B


class _Writer:
    """Records by signature, derived ids counted up."""

    def __init__(self):
        self.records, self.next = [], 0x800

    def derive_formid(self, _site, _key):
        """A fresh id per call."""
        self.next += 1
        return self.next

    def add_record(self, sig, data):
        """Keep a written record."""
        self.records.append((sig, data))


def _build():
    """create_reputation_records over one NCR-like REPU (maximum 80)."""
    register_fallout_source({'TERM': [1]})
    writer = _Writer()
    props = create_reputation_records(
        {'REPU': [{'FormID': f'{NCR:08X}', 'EditorID': 'RepNVNCR', 'DATA.Value': '80.0'}]}, writer)
    return writer, props


def test_a_reputation_is_a_list_of_its_globals_at_its_own_formid():
    """FLST at the REPU's id, six LNAM globals; thresholds start Neutral (1), the maximum at 80."""
    writer, props = _build()
    flst = next(data for sig, data in writer.records if sig == 'FLST')
    assert struct.unpack_from('<I', flst, 12)[0] & 0xFFFFFF == NCR and props['RepNVNCR']
    globs = {struct.unpack_from('<I', d, 12)[0]: d for s, d in writer.records if s == 'GLOB'}
    members = [struct.unpack_from('<I', flst, i + 6)[0] for i in range(len(flst))
               if flst[i:i + 4] == b'LNAM']
    values = [struct.unpack('<f', globs[m][globs[m].index(b'FLTV') + 6:][:4])[0] for m in members]
    assert values == [0.0, 0.0, 1.0, 1.0, 1.0, 80.0] and 'TES4Karma' in props


def test_threshold_reputation_and_karma_conditions_read_globals():
    """GetReputationThreshold axis 1 reads the good global; player karma reads TES4Karma."""
    writer, props = _build()
    globs = [struct.unpack_from('<I', d, 12)[0] for s, d in writer.records if s == 'GLOB']
    good = mirrored_ctda(0x60, 0, 575, NCR, 1)
    assert struct.unpack_from('<HH I', good, 8)[0] == 74 and struct.unpack_from('<I', good, 12)[0] in globs
    fame = struct.unpack_from('<I', mirrored_ctda(0, 0, 573, NCR, 1), 12)[0]
    assert fame != struct.unpack_from('<I', good, 12)[0]
    karma = mirrored_ctda(0, 0, 14, 23, 0, on_player=True)
    assert struct.unpack_from('<I', karma, 12)[0] == props['TES4Karma']
    assert mirrored_ctda(0, 0, 14, 23, 0, on_player=False) is None


def test_reputation_and_karma_commands_call_the_globals():
    """Commands pass the REPU as a FormList to TES4_Reputation; karma is the TES4Karma global."""
    src = ('scn T\nbegin GameMode\n  AddReputation RepNVNCR 1 3\n'
           '  if GetReputationThreshold RepNVNCR 1 >= 4\n    RewardKarma -50\n  endif\n'
           '  if player.GetAV Karma > 250\n    SetReputation RepNVNCR 0 0\n  endif\nend\n')
    out = ScriptConverter(CrossRefGraph()).convert_standalone('T', src, 'Quest', 'T')
    assert 'FormList Property RepNVNCR Auto' in out
    assert 'TES4_Reputation.Add(RepNVNCR, 1, 3' in out
    assert 'TES4_Reputation.Threshold(RepNVNCR, 1) >= 4' in out
    assert 'TES4Karma.Mod(-50' in out and 'TES4Karma.GetValue() > 250' in out
    assert 'TES4_Reputation.Set(RepNVNCR, 0, 0' in out
