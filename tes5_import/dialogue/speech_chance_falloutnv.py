"""FO3/FNV speech challenge facts both the importer and the script stage read.

Which INFOs are challenge and failure lines, the threshold globals, and the
chance `Fallout3.exe` computes. Nothing here imports the dialogue builder, so
`script_convert` can use it without an import cycle.

See: docs/commentary/tes5_import_dialogue.md#fallout-speech-challenges
"""

from ..base.text_reader import get_int, get_str

#: The engine's SpeechChallengeFailure and ANY topics, by their fixed FormIDs.
FAILURE_TOPIC, ANY_TOPIC = 0xFD, 0xD3

#: INFO DATA flag: Speech Challenge.
CHALLENGE_FLAG = 0x80

#: One threshold global per DNAM difficulty, None (0) to Very Hard (5).
NEED_GLOBALS = tuple(f'TES4SpeechNeed{i}' for i in range(6))

#: Each difficulty's setting and Fallout3.exe's default; None has no setting and reads -1.
_DIFFICULTIES = (('', -1.0), ('iSpeechChallengeDifficultyVeryEasy', 0.0),
                 ('iSpeechChallengeDifficultyEasy', 25.0), ('iSpeechChallengeDifficultyAverage', 50.0),
                 ('iSpeechChallengeDifficultyHard', 75.0), ('iSpeechChallengeDifficultyVeryHard', 100.0))

#: The chance's other settings and Fallout3.exe's defaults.
_SETTINGS = (('fSpeechChallengeSpeechBase', 50.0), ('fSpeechChallengeMultiplier', 1.0),
             ('fSpeechAutoSuccessThreshold', 0.8))


def chance_settings(*gmst_lists) -> dict:
    """Each chance setting by name: the last list naming it, else Fallout3.exe's default."""
    values = {get_str(r, 'EditorID'): r.get('DATA.Value') for recs in gmst_lists for r in recs}
    out = {}
    for name, default in _SETTINGS + _DIFFICULTIES[1:]:
        try:
            out[name] = float(values.get(name, default))
        except (TypeError, ValueError):
            out[name] = default
    return out


def difficulties(settings: dict) -> list:
    """The difficulty of each DNAM level, None to Very Hard."""
    return [settings[name] if name else default for name, default in _DIFFICULTIES]


def auto_point(settings: dict) -> float:
    """The least chance that auto-succeeds; the exe's test is strict."""
    return settings['fSpeechAutoSuccessThreshold'] + 1e-6


def roll_point(roll: int, settings: dict) -> float:
    """The chance a roll of 0-99 needs, capped where every roll succeeds."""
    return min((roll + 0.5) / 100.0, auto_point(settings))


def speech_needed(point: float, difficulty: float, settings: dict) -> float:
    """The Speech whose chance reaches `point`: Fallout3.exe 0x601ef0 solved for Speech, disposition neutral.

    See: docs/commentary/tes5_import_dialogue.md#fallout-speech-chance
    """
    if difficulty >= 100.0:
        return 1000.0
    return (settings['fSpeechChallengeSpeechBase']
            + (point * 100.0 / (100.0 - difficulty) - 1.0) * 100.0 / settings['fSpeechChallengeMultiplier'])


def raw_formid(rec: dict, key: str) -> int:
    """A FormID field as the source wrote it, before any load-order remap."""
    return int(rec.get(key) or '0', 16)


def is_failure(rec: dict) -> bool:
    """Whether an INFO belongs to the engine's SpeechChallengeFailure topic."""
    return raw_formid(rec, 'ParentDIAL') == FAILURE_TOPIC


def is_challenge(rec: dict) -> bool:
    """Whether an INFO is a speech challenge line."""
    return bool(get_int(rec, 'DATA.Flags') & CHALLENGE_FLAG) and not is_failure(rec)


def rerolls(rec: dict, fallout: bool) -> bool:
    """Whether a Fallout INFO's End fragment rolls the next challenge."""
    return fallout and (is_challenge(rec) or is_failure(rec))
