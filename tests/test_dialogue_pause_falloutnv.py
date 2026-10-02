"""FO3/FNV dialogue pause: a switched-on global and a PlayerRef-alias quest running TES4_DialoguePause.

See: docs/commentary/tes5_import_dialogue.md#fallout-dialogue-pause
"""
import struct

from tes5_import.base.writer import PluginWriter
from tes5_import.dialogue.dialogue_pause_falloutnv import build_dialogue_pause
from tes5_import.record_types import world_falloutnv


def _built(fallout: bool) -> tuple:
    """(quest FormID, {signature: [record bytes]}) of one build_dialogue_pause run."""
    world_falloutnv._IS_FALLOUT_SOURCE.clear()
    if fallout:
        world_falloutnv.register_fallout_source({'TERM': [1]})
    writer = PluginWriter(masters=['Skyrim.esm'], is_esm=True)
    try:
        return build_dialogue_pause(writer), writer._top_groups
    finally:
        world_falloutnv._IS_FALLOUT_SOURCE.clear()


def test_a_fallout_plugin_gets_the_switch_on_and_the_quest():
    """The global starts at 1 and the quest's alias runs the pause script."""
    fid, groups = _built(True)
    [glob], [quest] = groups['GLOB'], groups['QUST']
    assert struct.unpack('<f', glob[glob.index(b'FLTV') + 6:][:4])[0] == 1.0
    assert struct.unpack_from('<I', quest, 12)[0] == fid
    assert b'TES4_DialoguePause' in quest and b'TES4DialoguePause' in quest


def test_another_game_gets_nothing():
    """A plugin from another game gets no pause records."""
    fid, groups = _built(False)
    assert fid == 0 and not groups.get('QUST') and not groups.get('GLOB')
