"""FO3/FNV PERK conversion: effects Skyrim has carry over, the rest are left out.

See: docs/commentary/tes5_import_character_data.md#fallout-perks
"""
import struct

import pytest

from tes4_export.record_types.character_falloutnv import export_PERK
from tes4_export.tes4_reader import Record, Subrecord
from tes5_import.record_types import world_falloutnv
from tes5_import.record_types.perk_falloutnv import convert_PERK

GET_IS_SEX, GET_WEAPON_SKILL_TYPE, GUNS = 70, 109, 0x29


def _ctda(function, param=0):
    """A 28-byte Fallout condition: `function(param) == 1` on the subject."""
    return struct.pack('<B3xfHxxIIII', 0, 1.0, function, param, 0, 0, 0)


def _entry_point(entry_point, condition):
    """An entry point effect multiplying by 1.5, with one tab holding `condition`."""
    return [('PRKE', bytes([2, 0, 0])), ('DATA', bytes([entry_point, 3, 1])), ('PRKC', b'\x00'),
            ('CTDA', condition), ('EPFT', b'\x01'), ('EPFD', struct.pack('<f', 1.5)), ('PRKF', b'')]


def _convert(*effects):
    """convert_PERK over the export of a perk with these effects, as (subrecord, data) pairs."""
    subs = [('EDID', b'Sample\0'), ('FULL', b'Sample\0'), ('DESC', b'Text\0'), ('DATA', bytes([0, 4, 2, 1, 0]))]
    lines = export_PERK(Record('PERK', 0, 0, 0x31DE0, [Subrecord(t, d) for t, d in subs + list(effects)]))
    rec = dict(line.split('=', 1) for line in lines)
    rec['FormID'] = '00031DE0'
    out = convert_PERK(rec)
    pairs, pos = [], 24
    while pos < len(out):
        size = struct.unpack_from('<H', out, pos + 4)[0]
        pairs.append((out[pos:pos + 4].decode(), out[pos + 6:pos + 6 + size]))
        pos += 6 + size
    return pairs


@pytest.fixture(autouse=True)
def _fallout_source():
    """Conditions read as Fallout's while a test runs."""
    world_falloutnv.register_fallout_source({'TERM': [1]})
    yield
    world_falloutnv._IS_FALLOUT_SOURCE.clear()


def test_quest_stage_and_ability_effects_carry_over():
    """Both kinds keep their data, each closed by PRKF; the perk's DATA is Skyrim's five bytes."""
    pairs = _convert(('PRKE', bytes([0, 0, 0])), ('DATA', struct.pack('<IH2x', 0x0101, 20)), ('PRKF', b''),
                     ('PRKE', bytes([1, 1, 0])), ('DATA', struct.pack('<I', 0x0202)), ('PRKF', b''))
    assert ('DATA', bytes([0, 4, 2, 1, 0])) in pairs
    effects = [data for sig, data in pairs if sig == 'PRKE']
    assert effects == [bytes([0, 0, 0]), bytes([1, 1, 0])]
    assert ('DATA', struct.pack('<IHH', 0x0101, 20, 0)) in pairs and ('DATA', struct.pack('<I', 0x0202)) in pairs
    assert [sig for sig, _ in pairs].count('PRKF') == 2


def test_an_entry_point_skyrim_has_is_renumbered():
    """Fallout's Calculate Mine Explode Chance (4) is Skyrim's 3; its tab, condition and value follow."""
    pairs = _convert(*_entry_point(4, _ctda(GET_IS_SEX)))
    assert ('DATA', bytes([3, 3, 1])) in pairs
    assert ('PRKC', b'\x00') in pairs and ('EPFD', struct.pack('<f', 1.5)) in pairs
    assert len([data for sig, data in pairs if sig == 'CTDA']) == 1


def test_a_fallout_only_entry_point_is_left_out():
    """Action Point Cost (40) has no Skyrim counterpart: no effect is written."""
    assert not [sig for sig, _ in _convert(*_entry_point(40, _ctda(GET_IS_SEX))) if sig == 'PRKE']


def test_an_effect_whose_condition_drops_is_left_out():
    """A weapon-skill test Skyrim lacks would widen the bonus: the effect goes."""
    pairs = _convert(*_entry_point(0, _ctda(GET_WEAPON_SKILL_TYPE, GUNS)))
    assert not [sig for sig, _ in pairs if sig == 'PRKE']
