"""A start-game quest whose one PlayerRef alias hosts scripts that run on the player.

See: docs/commentary/tes5_import_dialogue.md#script-driven-type-1-topics
"""

import struct

from ..base.writer import (pack_formid_subrecord, pack_record, pack_string_subrecord, pack_subrecord,
                           pack_uint32_subrecord)

#: QUST DNAM flags Start Game Enabled + Starts Enabled.
_START_ENABLED = 0x0011

#: Alias FNAM flags: Optional, Allow Disabled, Allow Dead, Allow Reserved (a fill failure keeps the quest).
_ALIAS_FLAGS = 0x00000292

#: The player's reference.
_PLAYER_REF = 0x00000014


def player_alias_quest(writer, fid: int, edid: str, name: str, scripts: list) -> None:
    """Write the quest `fid` with alias 0 forced to PlayerRef, `scripts` [(name, props)] attached to it.

    script_convert.pipeline is imported here: it imports the importer's
    dialogue package, a cycle at load. Subrecords run EDID VMAD FULL DNAM, as
    every vanilla QUST with a VMAD does.
    """
    from script_convert.pipeline import build_vmad_quest_fragments
    q = pack_string_subrecord('EDID', edid)
    q += pack_subrecord('VMAD', build_vmad_quest_fragments(edid, [], None, None,
                                                           alias_scripts=[(0, scripts)], quest_fid=fid))
    q += pack_string_subrecord('FULL', name)
    q += pack_subrecord('DNAM', struct.pack('<HBBII', _START_ENABLED, 0, 0, 0, 0))
    q += pack_subrecord('NEXT', b'') + pack_uint32_subrecord('ANAM', 1)
    q += pack_uint32_subrecord('ALST', 0) + pack_string_subrecord('ALID', 'Player')
    q += pack_uint32_subrecord('FNAM', _ALIAS_FLAGS) + pack_formid_subrecord('ALFR', _PLAYER_REF)
    q += pack_formid_subrecord('VTCK', 0) + pack_subrecord('ALED', b'')
    writer.add_record('QUST', pack_record('QUST', fid, 0, q))
