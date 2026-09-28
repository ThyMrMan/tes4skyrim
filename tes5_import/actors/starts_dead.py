"""Placed actors that start dead: TES4 corpse props.

TES4 places a corpse as an actor whose base has a health pool of 0. Skyrim does
not treat health as editor-dead: the actor loads alive, dies on its first
update, and never equips its outfit, so the corpse lies naked. Skyrim's own
corpses carry the ACHR "Starts Dead" record flag instead (~1,140 in Skyrim.esm).

A ref a script resurrects keeps the health path, because the Papyrus
`Resurrect` native refuses an actor with that flag ("is dead from the editor
and cannot be resurrected", 1.6.1170 rva 0x9e99f0). FO3/FNV mark a corpse on
its BASE record (record flag bit 19), so every placement of such a base gets
the flag.

See: docs/commentary/tes5_import_actors.md#fallout-starts-dead
"""

import re

from ..base.text_reader import get_int, get_str
from ..dialogue.say_topics import collect_script_texts
from ..record_types.world_falloutnv import is_fallout_source

#: ACHR record flag 0x200: "Starts Dead".
STARTS_DEAD_FLAG = 0x00000200

#: FO3/FNV NPC_/CREA record flag bit 19 (xEdit "Unknown 19"): every placement starts dead.
_FALLOUT_DEAD_BASE = 0x00080000

_RESURRECT_RE = re.compile(r'(?:"?(\w+)"?[ \t]*\.[ \t]*)?\bresurrect\b', re.IGNORECASE)
_ACTOR_SIGS = ('NPC_', 'CREA')

#: Placed-actor FormIDs (export hex, upper) that get the flag; built by index_starts_dead.
_STARTS_DEAD = set()


def _unescape(text: str) -> str:
    """Script source with its exported `\\r`, `\\n` and `\\t` escapes turned to spaces."""
    return text.replace('\\r', ' ').replace('\\n', ' ').replace('\\t', ' ')


def _master_records(master_export: dict, sigs: tuple):
    """(FormID, record) for each master record of `sigs`."""
    return [(fid, r) for fid, r in (master_export or {}).items()
            if r.get('Signature') in sigs]


def _dead_bases(by_type: dict, master_export: dict) -> dict:
    """Base FormID (upper) -> record, for every NPC_/CREA authored dead."""
    pairs = [(get_str(r, 'FormID'), r) for sig in _ACTOR_SIGS for r in by_type.get(sig, [])]
    pairs += _master_records(master_export, _ACTOR_SIGS)
    return {fid.upper(): r for fid, r in pairs if fid and _is_dead_base(r)}


def _is_dead_base(rec: dict) -> bool:
    """Whether a base actor is authored dead in its own game's way."""
    if is_fallout_source():
        return bool(get_int(rec, 'RecordFlags') & _FALLOUT_DEAD_BASE)
    return 'DATA.Health' in rec and get_int(rec, 'DATA.Health') <= 0


def _resurrect_targets(by_type: dict, master_export: dict) -> tuple:
    """(EditorIDs a script resurrects, lowercased; SCPT FormIDs that resurrect their own actor)."""
    scpts = [(get_str(r, 'FormID'), r) for r in by_type.get('SCPT', [])]
    scpts += _master_records(master_export, ('SCPT',))
    texts = collect_script_texts(by_type) + [get_str(r, 'SCTX') for _, r in scpts]
    named = {m.group(1).lower() for t in texts
             for m in _RESURRECT_RE.finditer(_unescape(t or '')) if m.group(1)}
    own = {fid.upper() for fid, r in scpts
           if any(not m.group(1) for m in _RESURRECT_RE.finditer(_unescape(get_str(r, 'SCTX'))))}
    return named, own


def index_starts_dead(by_type: dict, master_export: dict) -> int:
    """Record every placed ACHR/ACRE that gets the Starts Dead flag; returns the count."""
    _STARTS_DEAD.clear()
    bases = _dead_bases(by_type, master_export)
    named, own = _resurrect_targets(by_type, master_export)
    for sig in ('ACHR', 'ACRE'):
        for ref in by_type.get(sig, []):
            base = bases.get(get_str(ref, 'NAME').upper())
            if base is None or get_str(base, 'SCRI').upper() in own:
                continue
            if {get_str(ref, 'EditorID').lower(), get_str(base, 'EditorID').lower()} & named:
                continue
            _STARTS_DEAD.add(get_str(ref, 'FormID').upper())
    return len(_STARTS_DEAD)


def starts_dead(ref_fid: str) -> bool:
    """True when the placed actor with this export FormID starts dead."""
    return ref_fid.upper() in _STARTS_DEAD
