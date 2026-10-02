"""FO3/FNV dialogue pauses the world: a quest whose PlayerRef alias runs TES4_DialoguePause, and its switch.

Written last in the import, after every other generated record, so the two
new FormIDs never displace another generated record's.

See: docs/commentary/tes5_import_dialogue.md#fallout-dialogue-pause
"""

from ..base.owned_records import emit_global
from ..record_types.world_falloutnv import is_fallout_source
from .player_alias_quest import player_alias_quest

#: The static script that freezes the other actors while the player talks.
PAUSE_SCRIPT = 'TES4_DialoguePause'

#: The per-game switch, 1 (on) as built; 0 lets the world run on in dialogue.
PAUSE_GLOBAL = 'TES4DialoguePause'

#: The quest hosting the script on its PlayerRef alias.
PAUSE_QUEST = 'TES4DialoguePauseQuest'


def build_dialogue_pause(writer) -> int:
    """Write the switch and the quest for a FO3/FNV plugin; the quest's FormID, else 0."""
    if not is_fallout_source():
        return 0
    switch = emit_global(writer, PAUSE_GLOBAL, 's', 1.0)
    fid = writer.derive_formid('SYNTH_QUST', PAUSE_QUEST)
    player_alias_quest(writer, fid, PAUSE_QUEST, 'TES4 Dialogue Pause', [(PAUSE_SCRIPT, {PAUSE_GLOBAL: switch})])
    return fid
