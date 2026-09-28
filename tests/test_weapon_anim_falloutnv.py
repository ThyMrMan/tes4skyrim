"""FO3/FNV GetWeaponAnimType reads the weapon's Fallout animation type, not Skyrim's weapon type.

See: docs/commentary/script_convert.md#fallout-weapon-anim-type
"""
import struct

from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph
from tes5_import.base.writer import PluginWriter
from tes5_import.record_types import world_falloutnv
from tes5_import.record_types.equipment_falloutnv import WEAPON_ANIM_LISTS, create_weapon_anim_lists

RIFLE_BALLISTIC = 5


def test_each_animation_type_lists_its_weapons():
    """The varmint rifle (type 5) is in TES4WeapAnimType5; every type gets a list, empty or not."""
    writer = PluginWriter(masters=['Skyrim.esm'])
    by_type = {'WEAP': [{'Signature': 'WEAP', 'FormID': '0007EA24', 'DNAM.FalloutAnimType': str(RIFLE_BALLISTIC)}]}
    world_falloutnv.register_fallout_source({'TERM': [1]})
    try:
        lists = create_weapon_anim_lists(by_type, writer)
    finally:
        world_falloutnv._IS_FALLOUT_SOURCE.clear()
    assert sorted(lists) == sorted(WEAPON_ANIM_LISTS.values())
    group = b''.join(writer._top_groups['FLST'])
    rifles = group[group.index(b'TES4WeapAnimType5\0'):]
    assert rifles[18:28] == b'LNAM\x04\x00' + struct.pack('<I', 0x0007EA24)


def test_other_games_write_no_lists():
    """Only a Fallout source has animation types to list."""
    assert create_weapon_anim_lists({'WEAP': []}, PluginWriter(masters=['Skyrim.esm'])) == {}


def test_a_rifle_check_reads_the_fallout_type():
    """Sunny's bottles accept types 4-8; a converted rifle is a Skyrim crossbow, so Skyrim's type cannot say."""
    src = ('scn T\nbegin OnHitWith\n  if Player.GetWeaponAnimType > 3 && Player.GetWeaponAnimType < 9\n'
           '    return\n  endif\nend\n')
    out = ScriptConverter(CrossRefGraph()).convert_standalone('T', src, 'ObjectReference', 'T')
    assert 'FormList Property TES4WeapAnimType5 Auto' in out
    assert '5 * (TES4WeapAnimType5.HasForm((Game.GetPlayer() as Actor).GetEquippedWeapon()) as Int)' in out
    assert 'GetEquippedItemType' not in out
