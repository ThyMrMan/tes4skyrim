"""One read of a built plugin, indexed for every preflight audit.

The plugin is read once, and each audit asks this index for records by type,
by FormID, their subrecords, and the scripts their VMAD attaches.

See: docs/commentary/tools_preflight.md#the-plugin-index
"""

import math
import struct
from collections import defaultdict

from tools.esm.tes5_esm_reader import read_tes5_file

#: Record flag of a worldspace's persistent cell, whose references stand in grid cells of their own.
_PERSISTENT = 0x400

#: World units along one side of an exterior cell.
_CELL_UNITS = 4096

#: VMAD property types whose value is a fixed size: {type: bytes}.
_FIXED_PROPERTY_SIZE = {3: 4, 4: 4, 5: 1}

#: VMAD array property types: {type: bytes per element}; 12 (strings) is sized per element.
_ARRAY_ELEMENT_SIZE = {11: 8, 13: 4, 14: 4, 15: 1}


def first(rec, sig: str) -> bytes:
    """The data of `rec`'s first `sig` subrecord, or b''."""
    return next((s.data for s in rec.subrecords if s.type == sig), b'')


def every(rec, sig: str) -> list:
    """The data of every `sig` subrecord of `rec`."""
    return [s.data for s in rec.subrecords if s.type == sig]


def zstring(data: bytes) -> str:
    """A NUL-terminated subrecord string."""
    return data.split(b'\0', 1)[0].decode('latin-1')


def u32(data: bytes, offset: int = 0) -> int:
    """The little-endian u32 at `offset`, or 0 past the end."""
    return struct.unpack_from('<I', data, offset)[0] if len(data) >= offset + 4 else 0


def _wstring(data: bytes, pos: int) -> tuple:
    """(text, next position) of a u16-prefixed VMAD string."""
    size = struct.unpack_from('<H', data, pos)[0]
    return data[pos + 2:pos + 2 + size].decode('latin-1'), pos + 2 + size


def _object_fid(data: bytes, pos: int, obj_format: int) -> int:
    """The FormID of an 8-byte VMAD object value."""
    return u32(data, pos + 4) if obj_format == 2 else u32(data, pos)


def _property_value(data: bytes, pos: int, ptype: int, obj_format: int) -> tuple:
    """(FormID or None, next position) of one VMAD property value."""
    if ptype == 1:
        return _object_fid(data, pos, obj_format), pos + 8
    if ptype == 2:
        return None, _wstring(data, pos)[1]
    if ptype in _FIXED_PROPERTY_SIZE:
        return None, pos + _FIXED_PROPERTY_SIZE[ptype]
    count = u32(data, pos)
    pos += 4
    if ptype == 12:
        for _ in range(count):
            pos = _wstring(data, pos)[1]
        return None, pos
    if ptype in _ARRAY_ELEMENT_SIZE:
        return None, pos + count * _ARRAY_ELEMENT_SIZE[ptype]
    raise ValueError(f'VMAD property type {ptype}')


def _script_properties(data: bytes, pos: int, version: int, obj_format: int) -> tuple:
    """({property name lower: FormID or None}, next position) for one VMAD script."""
    props = {}
    count = struct.unpack_from('<H', data, pos)[0]
    pos += 2
    for _ in range(count):
        name, pos = _wstring(data, pos)
        ptype = data[pos]
        pos += 2 if version >= 4 else 1
        fid, pos = _property_value(data, pos, ptype, obj_format)
        props[name.lower()] = fid or None
    return props, pos


def vmad_scripts(data: bytes) -> list:
    """[(script name lower, {property lower: FormID, None when not an object})] a VMAD attaches.

    Parsing stops at the first value it cannot size, keeping the scripts read
    so far; fragment data after the script list is not read.
    """
    out = []
    try:
        version, obj_format, count = struct.unpack_from('<hhH', data, 0)
        pos = 6
        for _ in range(count):
            name, pos = _wstring(data, pos)
            pos += 1 if version >= 4 else 0
            props, pos = _script_properties(data, pos, version, obj_format)
            out.append((name.lower(), props))
    except (struct.error, ValueError, IndexError):
        pass
    return out


class PluginIndex:
    """A built plugin's records by type and FormID, and its script attachments."""

    def __init__(self, records: list, masters: tuple = ()):
        """Index `records` by type and FormID, and read every VMAD's scripts."""
        self.masters = tuple(masters)
        self._grid = None
        self.by_type = defaultdict(list)
        self.by_fid = {}
        self.attached = defaultdict(list)
        self.script_props = defaultdict(dict)
        self.bound = defaultdict(set)
        self.object_props = []
        for rec in records:
            self.by_type[rec.type].append(rec)
            self.by_fid[rec.form_id] = rec
            vmad = first(rec, 'VMAD')
            for name, props in vmad_scripts(vmad) if vmad else ():
                self._attach(rec.form_id, name, props)

    def _attach(self, fid: int, script: str, props: dict) -> None:
        """Record that record `fid` attaches `script` with `props`."""
        self.attached[script].append(fid)
        self.bound[script] |= set(props)
        for prop, target in props.items():
            if target:
                self.script_props[script][prop] = target
                self.object_props.append((script, prop, target))

    def edid(self, fid: int) -> str:
        """The EditorID of the record `fid`, or ''."""
        rec = self.by_fid.get(fid)
        return zstring(first(rec, 'EDID')) if rec else ''

    def edid_types(self) -> tuple:
        """({EditorID lower: signature}, {EditorIDs two signatures share}).

        A leading-digit EditorID also answers to its digit-stripped name, which
        is how the converter writes it into Papyrus.
        """
        types, shared = {}, set()
        for rec in (r for recs in self.by_type.values() for r in recs):
            edid = zstring(first(rec, 'EDID')).lower()
            for name in {edid, edid.lstrip('0123456789')} - {''}:
                if types.setdefault(name, rec.type) != rec.type:
                    shared.add(name)
        return types, shared

    def interior_cells(self) -> set:
        """FormIDs of the interior cells (CELL DATA flag 0x01)."""
        return {r.form_id for r in self.by_type['CELL'] if first(r, 'DATA')[:1] and first(r, 'DATA')[0] & 1}

    def navmesh_cells(self) -> set:
        """FormIDs of the cells that hold at least one navmesh."""
        return {r.parent_cell for r in self.by_type['NAVM']}

    def home_cell(self, rec) -> int:
        """The cell a placed reference stands in; a persistent exterior one maps to its grid cell.

        See: docs/commentary/tools_preflight.md#the-plugin-index
        """
        if self._grid is None:
            self._grid = {(c.parent_wrld, *struct.unpack_from('<ii', first(c, 'XCLC'))): c.form_id
                          for c in self.by_type['CELL'] if c.parent_wrld and len(first(c, 'XCLC')) >= 8
                          and not c.flags & _PERSISTENT}
        cell = self.by_fid.get(rec.parent_cell)
        if cell is None or not cell.flags & _PERSISTENT or not cell.parent_wrld or len(first(rec, 'DATA')) < 8:
            return rec.parent_cell
        x, y = struct.unpack_from('<ff', first(rec, 'DATA'))
        return self._grid.get((cell.parent_wrld, math.floor(x / _CELL_UNITS), math.floor(y / _CELL_UNITS)),
                              rec.parent_cell)

    def is_own(self, fid: int) -> bool:
        """Whether `fid` is in this plugin's own id space rather than a master's."""
        return fid >> 24 == len(self.masters)

    def placed_bases(self) -> set:
        """Base FormIDs of every placed actor (ACHR)."""
        return {u32(first(r, 'NAME')) for r in self.by_type['ACHR']}


def load_plugin(path: str) -> PluginIndex:
    """Read and index the built plugin at `path`."""
    header, records, _localized = read_tes5_file(str(path))
    return PluginIndex(records, [zstring(d) for d in every(header, 'MAST')])
