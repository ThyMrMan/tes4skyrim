"""convert_meshes: a --mesh-subdirs run converts the named NIFs and nothing else."""
import pytest

from asset_convert import asset_pipeline

POST_PASSES = ('_profile_hair_and_grass', '_split_magic_art',
               '_copy_and_fix_textures')


@pytest.fixture
def calls(tmp_path, monkeypatch):
    """Stub every step of convert_meshes; return the list of steps that ran."""
    ran = []
    (tmp_path / 'export' / 'Test.esm' / 'meshes').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(asset_pipeline, '_activate_namespace', lambda _d: 'tes4')
    monkeypatch.setattr(asset_pipeline, 'assemble_armor', lambda *_a: 0)
    monkeypatch.setattr(asset_pipeline, '_persist_mesh_manifests',
                        lambda *_a: None)
    monkeypatch.setattr(asset_pipeline, '_convert_mesh_tree',
                        lambda *_a: ran.append('batch') or {})
    for name in POST_PASSES:
        monkeypatch.setattr(asset_pipeline, name,
                            lambda *_a, _n=name: ran.append(_n))
    monkeypatch.setattr(asset_pipeline.landscape_normals, 'ensure_ltex_normals',
                        lambda *_a: ran.append('ltex_normals') or (0, 0))
    return ran


def test_filtered_run_converts_only_the_meshes(calls):
    """A --mesh-subdirs run stops after the NIF batch: no whole-tree pass runs."""
    asset_pipeline.convert_meshes('Test.esm', mesh_subdirs=['dungeons/a.nif'])
    assert calls == ['batch']


def test_unfiltered_run_runs_every_pass(calls):
    """A full run still runs the hair/grass, magic art, texture and LTEX passes."""
    asset_pipeline.convert_meshes('Test.esm')
    assert calls == ['batch', *POST_PASSES, 'ltex_normals']
