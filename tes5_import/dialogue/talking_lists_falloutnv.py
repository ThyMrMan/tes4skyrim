"""Build FO3/FNV talking activators' speakers: their voices, voice NPCs and talking-as lists.

`[talker.]SetTalkingActivatorActor <actor>` call sites pair a TACT with an
actor. Each actor gets a FLST holding its own base, all listed in
`TALKING_LISTS_PROPERTY`; each voiced TACT a line names gets an unplaced voice
NPC for its lines' Speaker. The tables this fills live in `talking_as_falloutnv`.

See: docs/commentary/tes5_import_dialogue.md#fallout-talking-activators
"""

import re

from script_convert.constants import TALKING_LISTS_PROPERTY
from ..actors.leveled_actors import pack_voice_npc
from ..base.conditions import read_getisid_fids
from ..base.equivalents import DEFAULT_RACE
from ..base.text_reader import get_formid, get_str, info_result_script
from ..base.writer import pack_formid_subrecord, pack_record, pack_string_subrecord
from ..record_types.talking_activator_falloutnv import tact_voice
from .talking_as_falloutnv import TALKER_VOICE, TALKING_LIST, TALKING_VOICES

#: `[ref.]SetTalkingActivatorActor [actor]` on one TES4 script line.
_CALL = re.compile(r'^[ \t]*(?:(\w+)[ \t]*\.[ \t]*)?settalkingactivatoractor\b[ \t]*(\w*)', re.I | re.M)


def _bodies(by_type: dict):
    """(SCPT record or None, script text) for every script, INFO result and quest stage result."""
    for rec in by_type.get('SCPT', []):
        yield rec, get_str(rec, 'SCTX') or ''
    for rec in by_type.get('INFO', []):
        yield None, info_result_script(rec)
    for rec in by_type.get('QUST', []):
        yield from ((None, v) for k, v in rec.items() if 'ResultScript' in k and isinstance(v, str))


def _code(text: str) -> str:
    """A script text with real newlines and no `;` comments."""
    lines = text.replace('\\r\\n', '\n').replace('\\n', '\n').split('\n')
    return '\n'.join(line.split(';', 1)[0] for line in lines)


def scan_pairs(by_type: dict) -> set:
    """{(TACT EditorID lower, actor base source FormID hex)} named by each call site.

    The talker is the call's reference, or for a bare call every TACT the script is attached to.
    """
    tacts = {get_str(r, 'EditorID').lower(): r for r in by_type.get('TACT', []) if get_str(r, 'EditorID')}
    placed = {get_str(r, 'EditorID').lower(): r for s in ('REFR', 'ACHR', 'ACRE')
              for r in by_type.get(s, []) if get_str(r, 'EditorID')}
    base_edid = {r.get('FormID', '').upper(): e for e, r in tacts.items()}
    pairs = set()
    for script, text in _bodies(by_type):
        for talker, actor in _CALL.findall(_code(text)):
            actor_ref = placed.get(actor.lower())
            if actor_ref is None:
                continue
            if talker:
                ref = placed.get(talker.lower())
                names = [base_edid.get((ref or {}).get('NAME', '').upper())]
            else:
                names = [e for e, r in tacts.items() if script and r.get('SCRI') == script.get('FormID')]
            pairs |= {(n, actor_ref['NAME'].upper()) for n in names if n}
    return pairs


def _pack_list(fid: int, edid: str, members: list) -> bytes:
    """One FLST of `members` in order."""
    subs = pack_string_subrecord('EDID', edid)
    subs += b''.join(pack_formid_subrecord('LNAM', m) for m in members)
    return pack_record('FLST', fid, 0, subs)


def _actor_lists(pairs: set, by_type: dict, writer) -> list:
    """Mint one FLST per actor holding its own base; fills TALKING_LIST and TALKING_VOICES."""
    tacts = {get_str(r, 'EditorID').lower(): r for r in by_type.get('TACT', [])}
    actors = {r.get('FormID', '').upper(): r for s in ('NPC_', 'CREA') for r in by_type.get(s, [])}
    lists = []
    for actor_hex in sorted({a for _t, a in pairs}):
        actor = actors.get(actor_hex)
        if actor is None:
            continue
        base = get_formid(actor, 'FormID')
        fid = writer.derive_formid('TALKING_AS_FLST', actor_hex)
        writer.add_record('FLST', _pack_list(fid, f'TES4TalkingAs_{get_str(actor, "EditorID")}', [base]))
        TALKING_LIST[base] = fid
        TALKING_VOICES[base] = {tact_voice(tacts[t]) for t, a in pairs if a == actor_hex} - {0}
        lists.append(fid)
    return lists


def _voice_speakers(by_type: dict, writer) -> None:
    """Mint a voice NPC for each voiced TACT a line names as its speaker; fills TALKER_VOICE."""
    named = set().union(*(read_getisid_fids(r, positive_only=True) for r in by_type.get('INFO', [])))
    for rec in by_type.get('TACT', []):
        fid, edid = get_formid(rec, 'FormID'), get_str(rec, 'EditorID')
        if fid in named and tact_voice(rec):
            npc = writer.derive_formid('TALKER_VOICE_NPC', rec['FormID'].upper())
            writer.add_record('NPC_', pack_voice_npc(npc, f'TES4VoiceOf_{edid}', get_str(rec, 'FULL'),
                                                     tact_voice(rec), DEFAULT_RACE))
            TALKER_VOICE[fid] = npc


def build_talking_lists(by_type: dict, writer, npc_to_vtyp: dict) -> int:
    """Voice every TACT in `npc_to_vtyp` and for its lines, mint the talking-as lists; the lists' FLST, or 0.

    See: docs/commentary/tes5_import_dialogue.md#fallout-talking-activators
    """
    for table in (TALKING_LIST, TALKING_VOICES, TALKER_VOICE):
        table.clear()
    for rec in by_type.get('TACT', []):
        if tact_voice(rec):
            npc_to_vtyp[get_formid(rec, 'FormID')] = tact_voice(rec)
    _voice_speakers(by_type, writer)
    lists = _actor_lists(scan_pairs(by_type), by_type, writer)
    if not lists:
        return 0
    fid = writer.derive_formid('SYNTH_FLST', TALKING_LISTS_PROPERTY)
    writer.add_record('FLST', _pack_list(fid, TALKING_LISTS_PROPERTY, lists))
    return fid
