"""FO3/FNV packages wait behind a locked door their actor cannot open.

See: docs/commentary/tes5_import_package.md#locked-door-gates
"""
from tes5_import.packages.door_gates_falloutnv import CellNavmesh, Door, _blocking

#: Vault101ExitDoor's base bounds (VDoor01) and placement.
_BASE = {'OBND.X1': '-78', 'OBND.Y1': '-8', 'OBND.Z1': '0', 'OBND.X2': '91', 'OBND.Y2': '46', 'OBND.Z2': '177'}
_REF = {'PosX': '10752', 'PosY': '4480', 'PosZ': '2816', 'RotZ': '3.1416'}


def test_a_door_covers_the_triangles_of_its_doorway_whichever_way_it_turns():
    """The triangles under the exit door (22 and 27 units off) are covered; one 118 units away is not."""
    for rot in ('3.1416', '0.0'):
        door = Door(dict(_REF, RotZ=rot), _BASE)
        assert door.covers((10773.0, 4486.0, 2816.0)) and door.covers((10731.0, 4463.0, 2821.0))
        assert not door.covers((10714.0, 4368.0, 2821.0))


def _corridor(side_room: bool) -> CellNavmesh:
    """A line of triangles 0-1-2-3 with a door over 2, and optionally a way round it through 4."""
    mesh = CellNavmesh([], {})
    for i in range(5):
        mesh.centre[(1, i)] = (float(i), 0.0, 0.0)
    links = [(0, 1), (1, 2), (2, 3)] + ([(1, 4), (4, 3)] if side_room else [])
    for a, b in links:
        mesh.next[(1, a)].append((1, b))
        mesh.next[(1, b)].append((1, a))
    mesh.door[7] = {(1, 2)}
    return mesh


def test_a_package_waits_only_when_every_route_crosses_a_door_its_actor_cannot_open():
    """The door blocks the corridor; a way round it, or the door's key, frees the actor."""
    npc, keyed = {'FormID': '00000100'}, {'FormID': '00000100', 'Item[0].FormID': '00000AAA'}
    locks = {7: (0xAAA, 0)}
    assert _blocking(_corridor(False), (0.0, 0, 0), (3.0, 0, 0), locks, npc) == {7}
    assert _blocking(_corridor(True), (0.0, 0, 0), (3.0, 0, 0), locks, npc) == frozenset()
    assert _blocking(_corridor(False), (0.0, 0, 0), (3.0, 0, 0), locks, keyed) == frozenset()
