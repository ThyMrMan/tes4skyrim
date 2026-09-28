"""A corpse (TES4: base health 0; FO3/FNV: the base's dead flag) is placed with the ACHR Starts Dead flag.

See: docs/commentary/tes5_import_actors.md#corpses-start-dead
"""

import struct

import pytest

from tes5_import.actors import starts_dead as sd
from tes5_import.record_types import world_falloutnv
from tes5_import.record_types.world import convert_ACHR


def _npc(fid, edid, health, script=''):
    """A TES4 NPC_ export record."""
    rec = {'Signature': 'NPC_', 'FormID': fid, 'EditorID': edid, 'DATA.Health': str(health)}
    if script:
        rec['SCRI'] = script
    return rec


def _achr(fid, base, edid=''):
    """A TES4 ACHR export record placing `base`."""
    return {'Signature': 'ACHR', 'FormID': fid, 'EditorID': edid, 'NAME': base,
            'RecordFlags': '1024', 'PosX': '0', 'PosY': '0', 'PosZ': '0',
            'RotX': '0', 'RotY': '0', 'RotZ': '0'}


def _flags(rec) -> int:
    """Record flags of the converted ACHR."""
    return struct.unpack_from('<I', convert_ACHR(rec), 8)[0]


@pytest.fixture
def by_type():
    """A corpse, a resurrected corpse, a self-resurrecting corpse and a living actor."""
    yield {
        'NPC_': [_npc('00000D2F', 'Corpse', 0),
                 _npc('00000D30', 'RaisedCorpse', 0),
                 _npc('00000D31', 'SelfRaiser', 0, script='00000E01'),
                 _npc('00000D32', 'Alive', 50)],
        'ACHR': [_achr('001A9288', '00000D2F'),
                 _achr('001A9289', '00000D30', 'RaisedCorpseRef'),
                 _achr('001A928A', '00000D31'),
                 _achr('001A928B', '00000D32')],
        'SCPT': [{'Signature': 'SCPT', 'FormID': '00000E00',
                  'SCTX': 'begin gamemode\\r\\n\\t"RaisedCorpseRef".Resurrect\\r\\nend'},
                 {'Signature': 'SCPT', 'FormID': '00000E01',
                  'SCTX': 'begin onactivate\\r\\n\\tResurrect\\r\\nend'}],
    }
    sd._STARTS_DEAD.clear()


def test_zero_health_corpse_starts_dead(by_type):
    """A placed 0-health actor gets 0x200 on top of its authored flags."""
    sd.index_starts_dead(by_type, {})
    assert _flags(by_type['ACHR'][0]) == 1024 | sd.STARTS_DEAD_FLAG


def test_living_actor_unflagged(by_type):
    """An actor with health keeps its authored flags."""
    sd.index_starts_dead(by_type, {})
    assert _flags(by_type['ACHR'][3]) == 1024


def test_resurrected_corpses_keep_health_path(by_type):
    """A corpse a script resurrects is not flagged."""
    sd.index_starts_dead(by_type, {})
    assert _flags(by_type['ACHR'][1]) == 1024
    assert _flags(by_type['ACHR'][2]) == 1024


def test_master_owned_corpse_base(by_type):
    """A ref placing a master's 0-health base is flagged too."""
    master = {'00000D40': _npc('00000D40', 'MasterCorpse', 0)}
    by_type['ACHR'].append(_achr('001A928C', '00000D40'))
    sd.index_starts_dead(by_type, master)
    assert sd.starts_dead('001A928C')


def test_fallout_corpse_is_dead_by_its_base_flag():
    """FO3/FNV mark a corpse on its base record (flag bit 19); its health says nothing.

    See: docs/commentary/tes5_import_actors.md#fallout-starts-dead
    """
    corpse = dict(_npc('00153158', 'SLGoodspringsCave02DEAD', 50), RecordFlags=str(0x80000 | 0x40000))
    living = dict(_npc('00153159', 'Wastelander', 50), RecordFlags=str(0x40000))
    fnv = {'NPC_': [corpse, living], 'ACHR': [_achr('001531F7', '00153158'), _achr('001531F8', '00153159')]}
    world_falloutnv.register_fallout_source({'TERM': [1]})
    try:
        sd.index_starts_dead(fnv, {})
        assert [_flags(ref) for ref in fnv['ACHR']] == [1024 | sd.STARTS_DEAD_FLAG, 1024]
    finally:
        world_falloutnv._IS_FALLOUT_SOURCE.clear()
        sd._STARTS_DEAD.clear()
