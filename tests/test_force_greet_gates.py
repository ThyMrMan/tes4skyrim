"""A line's test on its ForceGreet package becomes that package's own conditions."""

import struct

from tes5_import.base.writer import pack_subrecord
from tes5_import.dialogue.converter import _packed_condition_pairs
from tes5_import.packages import force_greet_gates

_BUTCH_FIND_PLAYER = 0x0103135C


def _ctda(func: int, param: int, value: float = 1.0, flag: int = 0) -> bytes:
    """One TES5 CTDA: `func(param) == value` on the subject."""
    return struct.pack('<B3xfHHIIIIi', flag, value, func, 0, param, 0, 0, 0, -1)


def test_force_greet_test_becomes_the_package_conditions(monkeypatch):
    """Butch's greeting asks the CG02 stages his FindPlayer package asks, not the package itself.

    See: docs/commentary/tes5_import_dialogue.md#force-greet-package-gate
    """
    stage = _ctda(59, 0x01014E84, 1.0)
    monkeypatch.setitem(force_greet_gates.FORCE_GREET_CONDITIONS, _BUTCH_FIND_PLAYER,
                        pack_subrecord('CTDA', stage))
    identity = (_ctda(72, 0x010300EA), b'')
    pairs = [identity, (_ctda(161, _BUTCH_FIND_PLAYER), b'')]
    assert force_greet_gates.while_package_runs(pairs, _packed_condition_pairs) == [identity, (stage, b'')]


def test_a_script_forced_or_unconditional_force_greet_keeps_its_test(monkeypatch):
    """RL-3's greeting package is forced on by AddScriptPackage; Jastira's has no conditions.

    See: docs/commentary/tes5_import_dialogue.md#force-greet-package-gate
    """
    monkeypatch.setattr(force_greet_gates, 'FORCE_GREET_CONDITIONS', {})
    monkeypatch.setattr(force_greet_gates, 'SCRIPT_FORCED', {0x01000001})
    force_greet_gates.gate_for(0x01000001, pack_subrecord('CTDA', _ctda(72, 0x14)))
    force_greet_gates.gate_for(0x01000002, b'')
    force_greet_gates.gate_for(0x01000003, pack_subrecord('CTDA', _ctda(72, 0x14)))
    assert list(force_greet_gates.FORCE_GREET_CONDITIONS) == [0x01000003]


def test_a_test_inside_an_or_chain_or_on_another_package_is_kept(monkeypatch):
    """Only a lone `== 1` test on a known ForceGreet is replaced."""
    monkeypatch.setitem(force_greet_gates.FORCE_GREET_CONDITIONS, _BUTCH_FIND_PLAYER, b'')
    chained = [(_ctda(161, _BUTCH_FIND_PLAYER, flag=1), b''), (_ctda(72, 0x010300EA), b'')]
    other = [(_ctda(161, 0x01000123), b'')]
    assert force_greet_gates.while_package_runs(chained, _packed_condition_pairs) == chained
    assert force_greet_gates.while_package_runs(other, _packed_condition_pairs) == other
