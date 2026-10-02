"""FO3/FNV packages wait behind a locked door their actor cannot open.

FO3/FNV AI stops at a locked door it holds no key for and waits, and quests
gate actors that way: CG04 unlocks the Vault 101 exit at stage 145 "so guards
can come in". Skyrim's AI walks up, sticks, and its failsafe warp moves the
actor past (CG04's guards reached their marker 17 s after stage 140 without
opening a door). So a package whose every navmesh route, from a holder's
placed position to its destination in the same cell, crosses such a door asks
`GetLocked == 0` of that door, and the actor runs its next package until the
door is unlocked. The table is filled before PACK converts.

See: docs/commentary/tes5_import_package.md#locked-door-gates
"""

import math
import struct
from collections import defaultdict, deque

from ..base.text_reader import get_formid, get_hex_bytes, get_int
from ..base.writer import pack_subrecord
from ..record_types.navm_falloutnv import parse_door_links, parse_edge_links, parse_triangles, parse_vertices
from ..record_types.world_falloutnv import is_fallout_source

#: Output PACK FormID -> output FormIDs of the doors that must be unlocked before it runs.
DOOR_GATES: dict = {}

#: TES5 GetLocked, and the run-on value Reference.
_FUNC_GET_LOCKED, _RUN_ON_REFERENCE = 5, 2

#: PLDT type Near Reference: the package's destination is a placed reference.
_NEAR_REFERENCE = 0

#: Units a door's footprint is widened by, so the triangles of its doorway fall inside.
_DOOR_MARGIN = 32.0


def _position(rec: dict) -> tuple:
    """A placed reference's (x, y, z)."""
    return tuple(float(rec.get(k) or 0) for k in ('PosX', 'PosY', 'PosZ'))


class Door:
    """A placed door's footprint: its bounds turned by its Z rotation about its position."""

    def __init__(self, ref: dict, base: dict):
        """Read the reference's position and rotation and the base's OBND."""
        self.pos, angle = _position(ref), float(ref.get('RotZ') or 0)
        self.cos, self.sin = math.cos(angle), math.sin(angle)
        self.half = tuple(max(abs(get_int(base, f'OBND.{a}1')), abs(get_int(base, f'OBND.{a}2'))) + _DOOR_MARGIN
                          for a in 'XY')
        self.top = get_int(base, 'OBND.Z2') + _DOOR_MARGIN

    def covers(self, point: tuple) -> bool:
        """Whether `point` lies inside the door's widened footprint."""
        dx, dy, dz = (p - q for p, q in zip(point, self.pos))
        local = (dx * self.cos + dy * self.sin, -dx * self.sin + dy * self.cos)
        return abs(local[0]) <= self.half[0] and abs(local[1]) <= self.half[1] and -_DOOR_MARGIN <= dz <= self.top


class CellNavmesh:
    """One cell's navmesh triangles as a graph: centroids, neighbours, and the triangles each door covers."""

    def __init__(self, navms: list, doors: dict):
        """Join every NAVM of the cell through its edge links; `doors` is {door FormID: Door}.

        A door's triangles are its NVDP links plus those under its footprint:
        an in-cell door has no link, and its navmesh runs straight under it.
        """
        self.centre, self.next, self.door = {}, defaultdict(list), defaultdict(set)
        for rec in navms:
            self._add(get_formid(rec, 'FormID'), rec)
        for fid, door in doors.items():
            self.door[fid] |= {node for node, point in self.centre.items() if door.covers(point)}

    def _add(self, navm: int, rec: dict) -> None:
        """Add one navmesh's triangles, neighbours, cross-navmesh links and linked doors."""
        verts = parse_vertices(get_hex_bytes(rec, 'NVVX'))
        tris, adj, links = parse_triangles(get_hex_bytes(rec, 'NVTR'))
        targets = parse_edge_links(get_hex_bytes(rec, 'NVEX'))
        for i, tri in enumerate(tris):
            pts = [verts[v] for v in tri if v < len(verts)]
            self.centre[(navm, i)] = tuple(sum(p[k] for p in pts) / max(len(pts), 1) for k in range(3))
            self.next[(navm, i)] += [(navm, e) for e in adj[i] if e >= 0]
        for tri, _slot, index in links:
            if 0 <= index < len(targets):
                self.next[(navm, tri)].append(targets[index][1:])
        for tri, door in parse_door_links(get_hex_bytes(rec, 'NVDP')):
            self.door[door].add((navm, tri))

    def nearest(self, point: tuple):
        """The triangle whose centroid is closest to `point`, or None for an empty mesh."""
        return min(self.centre, key=lambda n: sum((a - b) ** 2 for a, b in zip(self.centre[n], point)), default=None)

    def route(self, start, goal, blocked: set):
        """The triangles of a shortest route from `start` to `goal` avoiding `blocked`, or None."""
        back, todo = {start: None}, deque([start])
        while todo:
            node = todo.popleft()
            if node == goal:
                path = []
                while node is not None:
                    path.append(node)
                    node = back[node]
                return path
            for other in self.next[node]:
                if other not in back and other not in blocked and other in self.centre:
                    back[other] = node
                    todo.append(other)
        return None


def locked_doors(by_type: dict) -> tuple:
    """({cell: {door FormID: Door}} of every placed door, {door FormID: (key, owner)} of the locked ones)."""
    bases = {r['FormID'].upper(): r for r in by_type.get('DOOR', ())}
    placed, locks = defaultdict(dict), {}
    for rec in by_type.get('REFR', ()):
        base = bases.get((rec.get('NAME') or '').upper())
        if base is None:
            continue
        fid = get_formid(rec, 'FormID')
        placed[(rec.get('ParentCELL') or '').upper()][fid] = Door(rec, base)
        if rec.get('XLOC.Level') is not None:
            locks[fid] = (int(rec.get('XLOC.Key') or '0', 16), int(rec.get('XOWN.Owner') or '0', 16))
    return placed, locks


def _opens(npc: dict, lock: tuple) -> bool:
    """Whether the actor holds the door's key or owns it (itself or one of its factions)."""
    key, owner = lock
    held = {int(v, 16) for k, v in npc.items() if k.startswith('Item[') and k.endswith('.FormID') and v}
    mine = {int(npc['FormID'], 16)} | {int(v, 16) for k, v in npc.items()
                                        if k.startswith('Faction[') and k.endswith('.FormID') and v}
    return bool(key and key in held) or bool(owner and owner in mine)


def _blocking(mesh: CellNavmesh, start: tuple, goal: tuple, locks: dict, npc: dict) -> frozenset:
    """Doors the actor cannot open that every route from `start` to `goal` crosses; empty when one avoids them."""
    a, b = mesh.nearest(start), mesh.nearest(goal)
    shut = {d: mesh.door[d] for d, lock in locks.items() if mesh.door.get(d) and not _opens(npc, lock)}
    if a is None or b is None or not shut or mesh.route(a, b, set().union(*shut.values())):
        return frozenset()
    path = mesh.route(a, b, set())
    return frozenset(d for d, tris in shut.items() if path and tris & set(path))


def _holders(by_type: dict) -> dict:
    """{source PACK FormID upper: [(placed ACHR record, its base NPC_ record)]}."""
    npcs = {r['FormID'].upper(): r for r in by_type.get('NPC_', ())}
    out = defaultdict(list)
    for ref in by_type.get('ACHR', ()):
        npc = npcs.get((ref.get('NAME') or '').upper())
        for i in range(get_int(npc or {}, 'AIPackageCount')):
            out[(npc.get(f'AIPackage[{i}]') or '').upper()].append((ref, npc))
    return out


def plan_door_gates(by_type: dict) -> int:
    """Fill DOOR_GATES for this FO3/FNV plugin's packages; returns how many packages are gated."""
    DOOR_GATES.clear()
    if not is_fallout_source():
        return 0
    refs = {r['FormID'].upper(): r for sig in ('REFR', 'ACHR') for r in by_type.get(sig, ())}
    (placed, locks), holders, navms, meshes = locked_doors(by_type), _holders(by_type), defaultdict(list), {}
    for rec in by_type.get('NAVM', ()):
        navms[(rec.get('ParentCELL') or '').upper()].append(rec)
    for pack in by_type.get('PACK', ()):
        target = refs.get((pack.get('PLDT.Location') or '').upper())
        if get_int(pack, 'PLDT.Type', -1) != _NEAR_REFERENCE or target is None:
            continue
        cell = (target.get('ParentCELL') or '').upper()
        mine = [(ref, npc) for ref, npc in holders.get(pack['FormID'].upper(), ())
                if (ref.get('ParentCELL') or '').upper() == cell]
        shut = {d: locks[d] for d in placed.get(cell, ()) if d in locks}
        if not mine or not shut or not navms.get(cell):
            continue
        mesh = meshes.get(cell) or meshes.setdefault(cell, CellNavmesh(navms[cell], placed[cell]))
        gates = [_blocking(mesh, _position(ref), _position(target), shut, npc) for ref, npc in mine]
        if all(gates) and frozenset.intersection(*gates):
            DOOR_GATES[get_formid(pack, 'FormID')] = sorted(frozenset.intersection(*gates))
    return len(DOOR_GATES)


def door_gate(pack_fid: int) -> bytes:
    """`GetLocked == 0` run on each door the package waits behind, or b''."""
    return b''.join(pack_subrecord('CTDA', struct.pack('<B3xfHHIIIII', 0, 0.0, _FUNC_GET_LOCKED, 0, 0, 0,
                                                         _RUN_ON_REFERENCE, door, 0xFFFFFFFF))
                    for door in DOOR_GATES.get(pack_fid, ()))
