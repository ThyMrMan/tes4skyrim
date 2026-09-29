"""The Papyrus side of FO3/FNV speech challenges: the per-game roll helper and the fragment call.

Every challenge and failure line's End fragment calls the helper, which rolls
0-99 and sets each difficulty's threshold global to the Speech that roll needs,
by the game's own settings baked in at conversion.

See: docs/commentary/tes5_import_dialogue.md#fallout-speech-challenges
"""

import os

from script_convert.constants import script_prefix
from script_convert.context_setup import load_records
from script_convert.cross_ref import master_names
from tes5_import.dialogue.speech_chance_falloutnv import (NEED_GLOBALS, auto_point, chance_settings,
                                                          difficulties, rerolls)
from tes5_import.record_types.world_falloutnv import export_is_fallout


def speech_script_name() -> str:
    """The active game's roll helper script."""
    return script_prefix('_SpeechChallenge')


def reroll_line() -> str:
    """The End fragment line that rolls the next challenge."""
    return f"  {speech_script_name()}.Reroll({', '.join(NEED_GLOBALS)})"


def speech_helper_psc(settings: dict) -> str:
    """The roll helper's Papyrus for one game's chance settings; mirrors `speech_needed`.

    See: docs/commentary/tes5_import_dialogue.md#fallout-speech-chance
    """
    params = ', '.join(f'GlobalVariable akNeed{i}' for i in range(len(NEED_GLOBALS)))
    sets = [f'  akNeed{i}.SetValue(Needed(point, {d:.6f}))' for i, d in enumerate(difficulties(settings))]
    auto = auto_point(settings)
    return '\n'.join([
        f'ScriptName {speech_script_name()} Hidden', '',
        f'Function Reroll({params}) Global',
        '  Float point = (Utility.RandomInt(0, 99) + 0.5) / 100.0',
        f'  If point > {auto:.6f}', f'    point = {auto:.6f}', '  EndIf',
        *sets, 'EndFunction', '',
        'Float Function Needed(Float afPoint, Float afDifficulty) Global',
        '  If afDifficulty >= 100.0', '    Return 1000.0', '  EndIf',
        f"  Return {settings['fSpeechChallengeSpeechBase']:.6f} + (afPoint * 100.0 / (100.0 - afDifficulty)"
        f" - 1.0) * 100.0 / {settings['fSpeechChallengeMultiplier']:.6f}",
        'EndFunction', ''])


def speech_helper(export_dir: str, infos: list) -> 'tuple | None':
    """(script name, Papyrus) of the roll helper when a Fallout plugin has lines that roll it, else None.

    Settings come from the masters' GMSTs, overridden by the plugin's own.
    """
    fallout = export_is_fallout(export_dir)
    if not any(rerolls(r, fallout) for r in infos):
        return None
    parent = os.path.dirname(os.path.normpath(export_dir))
    gmsts = [load_records(os.path.join(parent, m), ('GMST',))['GMST'] for m in master_names(export_dir)]
    gmsts.append(load_records(export_dir, ('GMST',))['GMST'])
    return speech_script_name(), speech_helper_psc(chance_settings(*gmsts))
