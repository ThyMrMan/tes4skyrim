"""FO3/FNV speech challenges: the rolled threshold, the failure plan and the shared copies."""

import struct

import pytest

from script_convert.speech_challenges_falloutnv import reroll_line, speech_helper_psc, speech_script_name
from tes5_import.base.conditions import CTDA_OR, CTDA_USE_GLOBAL
from tes5_import.base.tes5_reader import subrecords
from tes5_import.base.writer import pack_record, pack_subrecord
from tes5_import.dialogue import speech_challenges_falloutnv as sc
from tes5_import.dialogue import speech_chance_falloutnv as chance
from tes5_import.dialogue.arrest import info_records
from tes5_import.record_types import world_falloutnv
from tes5_import.record_types.common import get_formid

#: Fallout 3's own settings (Fallout3.esm GMSTs, the Speech base from Fallout3.exe).
FO3 = [{'EditorID': name, 'DATA.Value': value} for name, value in (
    ('fSpeechChallengeMultiplier', '2.0'), ('fSpeechAutoSuccessThreshold', '0.9'),
    ('iSpeechChallengeDifficultyVeryEasy', '10'), ('iSpeechChallengeDifficultyEasy', '40'),
    ('iSpeechChallengeDifficultyAverage', '55'), ('iSpeechChallengeDifficultyHard', '70'),
    ('iSpeechChallengeDifficultyVeryHard', '80'))]


class _Writer:
    """Hands out FormIDs and keeps the records written."""

    def __init__(self):
        """No records yet."""
        self.records, self.next = [], 0x01A00000

    def derive_formid(self, _site, _key):
        """The next FormID."""
        self.next += 1
        return self.next

    def add_record(self, sig, data):
        """Keep one record."""
        self.records.append((sig, data))


@pytest.fixture(autouse=True)
def _fallout_source():
    """The import reads a Fallout source while a test runs."""
    world_falloutnv.register_fallout_source({'TERM': [1]})
    yield
    world_falloutnv.register_fallout_source({})


def _chance(speech: float, difficulty: float, s: dict) -> int:
    """Fallout3.exe 0x601ef0's percent, disposition neutral."""
    point = (1 + (speech - s['fSpeechChallengeSpeechBase']) * s['fSpeechChallengeMultiplier'] / 100) \
        * (100 - difficulty) / 100
    return 100 if point > s['fSpeechAutoSuccessThreshold'] else int(point * 100 + 0.5)


def _ctda(func: int, param: int, flags: int = 0) -> str:
    """A 28-byte Fallout condition, `func(param) == 1` on the subject."""
    return struct.pack('<B3xfHxxIIII', flags, 1.0, func, param, 0, 0, 0).hex()


def _info(fid: str, parent: str, flags: int = 0, conds=(), links=(), level: int = 3) -> dict:
    """One exported Fallout INFO."""
    rec = {'FormID': fid, 'ParentDIAL': parent, 'DATA.Flags': str(flags), 'DNAM.SpeechChallenge': str(level)}
    rec.update({f'Condition[{i}].Raw': c for i, c in enumerate(conds)})
    rec.update({f'LinkFrom[{i}]': link for i, link in enumerate(links)})
    return rec


def test_threshold_matches_the_exe_roll():
    """Speech reaching a roll's threshold wins exactly when the exe's roll beats its chance."""
    s = chance.chance_settings(FO3)
    for difficulty in chance.difficulties(s):
        for roll in range(100):
            need = chance.speech_needed(chance.roll_point(roll, s), difficulty, s)
            for speech in range(0, 101, 3):
                assert (speech >= need - 1e-9) == (roll < _chance(speech, difficulty, s)), (difficulty, roll, speech)


def test_failure_lines_follow_link_from_and_speakers():
    """A failure line answers when unlinked or linked here or to ANY, and its speaker can be the challenger's."""
    challenge = _info('00001000', '00002000', 0x80, conds=[_ctda(72, 0x111)])
    failures = [_info('00003001', '000000FD', links=['00002000']),
                _info('00003002', '000000FD', links=['00009999']),
                _info('00003003', '000000FD', links=['000000D3']),
                _info('00003004', '000000FD', conds=[_ctda(72, 0x222)]),
                _info('00003005', '000000FD', conds=[_ctda(72, 0x111, 0x01), _ctda(72, 0x222)])]
    writer = _Writer()
    assert sc.plan_speech_challenges([challenge, *failures], FO3, writer) == 1
    kept = [f['FormID'] for f, _fid in sc.planned_failures(challenge)]
    assert kept == ['00003001', '00003003', '00003005']
    assert [sig for sig, _data in writer.records] == ['GLOB'] * len(chance.NEED_GLOBALS)
    assert sc.labelled(challenge, 'Tell me')['Prompt'] == '[Speech] Tell me'


def test_copies_pass_only_after_a_lost_roll():
    """Each copy names its failure line, tests Speech below the threshold, then the challenge's own gate."""
    challenge = _info('00001000', '00002000', 0x80, level=3)
    failure = _info('00003001', '000000FD')
    sc.plan_speech_challenges([challenge, failure], FO3, _Writer())
    own = struct.pack('<B3xfHHIIIII', CTDA_OR, 1.0, 72, 0, 0x111, 0, 0, 0, 0xFFFFFFFF)
    packed = pack_record('INFO', get_formid(challenge, 'FormID'), 0,
                         sc.success_gate(challenge) + pack_subrecord('CTDA', own))
    copies, count = sc.failure_copies(challenge, packed, lambda rec: pack_record('INFO', 1, 0, b''))
    assert count == 1
    subs = list(subrecords(next(info_records(copies))[2]))
    assert subs[0] == (b'DNAM', struct.pack('<I', get_formid(failure, 'FormID')))
    lost, kept = subs[1][1], subs[2][1]
    assert lost[0] == 0x80 | CTDA_USE_GLOBAL and struct.unpack_from('<I', lost, 4)[0] == sc.speech_props(challenge)["TES4SpeechNeed3"]
    assert kept[0] & CTDA_OR == 0 and kept[1:] == own[1:]
    assert len(subs) == 3


def test_helper_bakes_the_settings():
    """The roll helper carries the game's numbers and every fragment calls it with each threshold."""
    psc = speech_helper_psc(chance.chance_settings(FO3))
    assert psc.startswith(f'ScriptName {speech_script_name()} Hidden')
    assert 'If point > 0.900001' in psc and '100.0 / 2.000000' in psc and 'Needed(point, 55.000000)' in psc
    assert reroll_line().endswith(f"Reroll({', '.join(chance.NEED_GLOBALS)})")
