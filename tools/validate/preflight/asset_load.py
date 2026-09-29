"""Red error markers found before play: every model a player can see must load.

Models come from what is placed, held in containers and inventories, worn
through outfits, and rolled from leveled lists. Each model must exist, loose
or in the game's archives; each must hold only block types the exe can build;
each texture it names must exist. An embedded weapon needs its NNAM node.
A path outside the game's own folder that the build does not ship is probably
a vanilla Skyrim asset, so it is marked for review rather than failed.

See: docs/commentary/tools_preflight.md#asset-load
"""

import re
from collections import defaultdict
from pathlib import Path

from asset_convert.sources.bsa_extract import read_bsa_files
from tools.misc.bsa_list_names import list_names
from tools.validate.nif_block_type_audit import parse_header, rtti_names
from tools.validate.preflight.findings import Finding
from tools.validate.preflight.plugin_index import every, first, u32, zstring

#: The unpacked build the user plays, whose RTTI decides which blocks load.
DEFAULT_EXE = r'C:\Coding\tes4skyrim\SkyrimSE.exe.unpacked.exe'

#: Subrecords that may hold a model path.
_MODEL_SUBS = ('MODL', 'MOD2', 'MOD3', 'MOD4', 'MOD5')

#: A texture path inside NIF bytes.
_TEXTURE = re.compile(rb'[A-Za-z0-9_\\/ .\'&()-]{3,200}\.dds', re.I)

#: NIFs read from one archive per batch, which bounds memory.
_BATCH = 1500

#: WEAP DNAM flag: the weapon is part of the actor's body, fired from its NNAM node.
_EMBEDDED = 0x20

#: Users shown per finding.
_USERS_SHOWN = 3


def norm(path: str, root: str) -> str:
    """`path` lower-cased with backslashes, under `root` (meshes or textures)."""
    p = path.strip().lower().replace('/', '\\').lstrip('\\')
    return p if p.startswith(root + '\\') else f'{root}\\{p}'


def _contents(rec, index) -> list:
    """FormIDs a record hands on: container and inventory items, outfit and leveled entries, ARMAs."""
    out = [u32(d) for d in every(rec, 'CNTO')]
    out += [u32(d) for d in every(rec, 'DOFT')]
    out += [u32(d, i) for d in every(rec, 'INAM') if rec.type == 'OTFT' for i in range(0, len(d), 4)]
    out += [u32(d, 4) for d in every(rec, 'LVLO')]
    if rec.type == 'ARMO':
        out += [u32(d) for d in every(rec, 'MODL') if len(d) == 4]
    return [f for f in out if f in index.by_fid]


def used_records(index) -> dict:
    """{FormID: placement count} of every record a player can meet, placed or carried."""
    counts = defaultdict(int)
    for sig in ('REFR', 'ACHR'):
        for rec in index.by_type[sig]:
            counts[u32(first(rec, 'NAME'))] += 1
    pending = [f for f in counts if f in index.by_fid]
    while pending:
        rec = index.by_fid[pending.pop()]
        for fid in _contents(rec, index):
            if fid not in counts:
                pending.append(fid)
            counts[fid] += 0
    return counts


def model_users(index) -> dict:
    """{mesh path: [(user label, placements)]} for every model of a used record."""
    out = defaultdict(list)
    for fid, placed in used_records(index).items():
        rec = index.by_fid.get(fid)
        if rec is None:
            continue
        for sig in _MODEL_SUBS:
            for data in every(rec, sig):
                path = zstring(data)
                if len(data) > 4 and path.lower().endswith('.nif'):
                    out[norm(path, 'meshes')].append((f'{rec.type} {index.edid(fid)} {fid:08X}', placed))
    return out


class Archives:
    """The files a built game ships: loose under its folder and inside its BSAs."""

    def __init__(self, game_dir: Path):
        """Index every archived file name under `game_dir`'s BSAs."""
        self.game_dir = Path(game_dir)
        self.bsa_of = {}
        for bsa in sorted(self.game_dir.glob('*.bsa')):
            for name in list_names(bsa):
                self.bsa_of.setdefault(name.lower(), bsa)

    def loose(self, path: str) -> Path:
        """The loose file for an archive path."""
        return self.game_dir / path

    def exists(self, path: str) -> bool:
        """Whether the game ships `path`, loose or archived."""
        return path in self.bsa_of or self.loose(path).is_file()

    def read_all(self, paths: list):
        """Yield (path, bytes) for each shipped path, loose files first."""
        archived = defaultdict(list)
        for path in paths:
            if self.loose(path).is_file():
                yield path, self.loose(path).read_bytes()
            elif path in self.bsa_of:
                archived[self.bsa_of[path]].append(path)
        for bsa, names in archived.items():
            for i in range(0, len(names), _BATCH):
                yield from read_bsa_files(bsa, names[i:i + _BATCH]).items()


def textures_in(data: bytes) -> set:
    """The texture paths a NIF's bytes name."""
    return {norm(m.decode('latin-1'), 'textures') for m in _TEXTURE.findall(data)}


def _users_detail(users: list) -> tuple:
    """Detail lines naming a mesh's first users and its placement total."""
    placed = sum(n for _label, n in users)
    lines = [f'used by {label}' for label, _n in users[:_USERS_SHOWN]]
    if len(users) > _USERS_SHOWN:
        lines.append(f'... and {len(users) - _USERS_SHOWN} more records')
    return tuple(lines + [f'{placed} placed references'])


def nif_findings(game: str, path: str, data: bytes, known: set, users: list) -> list:
    """Findings for one NIF: blocks the exe cannot build, or a header the audit cannot read."""
    try:
        header = parse_header(data)
    except (IndexError, ValueError, UnicodeDecodeError):
        return [Finding('assets', f'assets|{game}|unreadable|{path}', 'review',
                        f'{path} has a header the audit cannot read', _users_detail(users))]
    dead = sorted({header['types'][t] for t in header['tidx']} - known)
    if not dead:
        return []
    return [Finding('assets', f'assets|{game}|block|{path}', 'error',
                    f'{path} has blocks Skyrim cannot build ({", ".join(dead)}): a red error marker',
                    _users_detail(users))]


def in_source(path: str, source_dir: Path) -> bool:
    """Whether the source export holds the file an own-folder build path came from."""
    root, _own, rest = path.split('\\', 2)
    return (Path(source_dir) / root / rest).is_file()


def _absent(game: str, kind: str, path: str, source_dir: Path, what: str, detail) -> Finding:
    """An error for an asset the build lost, or a review when the source lacks it too."""
    key = f'assets|{game}|{kind}|{path}'
    if in_source(path, source_dir):
        return Finding('assets', key, 'error', f'{path} is not in the build: {what}', tuple(detail))
    return Finding('assets', key, 'review', f"{path} is not in the build or the source game's files",
                   tuple(detail))


def _missing_meshes(game: str, users: dict, archives, own: str, source_dir: Path) -> list:
    """Findings for meshes the build does not ship, and the paths it may borrow from Skyrim."""
    out, outside = [], defaultdict(list)
    for path in sorted(users):
        if archives.exists(path):
            continue
        if path.split('\\')[1:2] == [own]:
            out.append(_absent(game, 'missing', path, source_dir, 'a red error marker',
                               _users_detail(users[path])))
        else:
            outside[path.split('\\')[1]].append(path)
    for folder, paths in sorted(outside.items()):
        out.append(Finding('assets', f'assets|{game}|outside|meshes\\{folder}', 'review',
                           f'{len(paths)} meshes under meshes\\{folder} are not in the build; '
                           'fine if vanilla Skyrim ships them', tuple(paths[:_USERS_SHOWN])))
    return out


def _texture_findings(game: str, used_by: dict, archives, own: str, source_dir: Path) -> list:
    """Findings for textures under the game's own folder that the build does not ship."""
    return [_absent(game, 'texture', tex, source_dir, 'the mesh shows purple',
                    [f'named by {n}' for n in sorted(nifs)[:_USERS_SHOWN]])
            for tex, nifs in sorted(used_by.items())
            if tex.split('\\')[1:2] == [own] and not archives.exists(tex)]


def embedded_findings(game: str, index) -> list:
    """Embedded weapons without the NNAM node they are and fire from."""
    out = []
    for rec in index.by_type['WEAP']:
        if u32(first(rec, 'DNAM'), 12) & _EMBEDDED and not zstring(first(rec, 'NNAM')):
            edid = index.edid(rec.form_id)
            out.append(Finding('assets', f'assets|{game}|embedded|{edid}', 'error',
                               f'embedded weapon {edid} has no NNAM node, so its actor drops it'))
    return out


def audit(game: str, index, game_dir: Path, own: str, source_dir: Path, exe: str = DEFAULT_EXE) -> list:
    """The asset load findings for one game; `own` is its folder under meshes and textures."""
    users = model_users(index)
    archives = Archives(game_dir)
    known = rtti_names(exe)
    out = _missing_meshes(game, users, archives, own, source_dir)
    textures = defaultdict(set)
    for path, data in archives.read_all([p for p in users if archives.exists(p)]):
        out += nif_findings(game, path, data, known, users[path])
        for tex in textures_in(data):
            textures[tex].add(path)
    return (out + _texture_findings(game, textures, archives, own, source_dir)
            + embedded_findings(game, index))
