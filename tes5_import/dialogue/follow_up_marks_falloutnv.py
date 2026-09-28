"""FO3/FNV follow-up chains the player can walk away from: the marks that resume them.

FO3/FNV could not leave a conversation mid-line; Skyrim can, and the lines a
speaker was about to continue with are then lost. Each line of a scripted chain
marks itself said, through a global its OnBegin fragment sets: a source line
its From global, a follow-up its Said global. A speaker whose source was said
and none of whose follow-ups was resumes the chain when next spoken to.

See: docs/commentary/tes5_import_dialogue.md#fallout-follow-ups-resume
"""

from ..base.text_reader import info_result_script
from ..packages.scripts_falloutnv import has_code

#: Global a source line sets as it begins, per source INFO (low 24 bits, hex).
FROM_GLOBAL = 'TES4FollowUpFrom_{:06X}'

#: Global a follow-up line sets as it begins, per follow-up INFO.
SAID_GLOBAL = 'TES4FollowUpSaid_{:06X}'


def _fid24(value) -> int:
    """The low 24 bits of a hex FormID string, 0 when unparseable."""
    try:
        return int(value or '0', 16) & 0xFFFFFF
    except ValueError:
        return 0


def follow_up_targets(infos: list) -> dict:
    """{source INFO fid24: [follow-up INFO fid24]} for every INFO with a Follow Up list."""
    out = {}
    for rec in infos:
        count = int(rec.get('FollowUpCount') or 0)
        targets = [_fid24(rec.get(f'FollowUp[{i}]')) for i in range(count)]
        if any(targets):
            out[_fid24(rec.get('FormID'))] = [t for t in targets if t]
    return out


def _scripted_chains(infos: list, follows: dict) -> set:
    """Follow-up INFOs whose line, or any line down its own follow-ups, runs a script."""
    scripted = {_fid24(r.get('FormID')) for r in infos if has_code(info_result_script(r))}
    found, changed = set(), True
    while changed:
        changed = False
        for fid in {t for ts in follows.values() for t in ts} - found:
            if fid in scripted or any(t in found for t in follows.get(fid, ())):
                found.add(fid)
                changed = True
    return found


def follow_up_marks(infos: list) -> dict:
    """{INFO fid24: sorted [global]} each line of a scripted follow-up chain sets as it begins."""
    follows = follow_up_targets(infos)
    scripted = _scripted_chains(infos, follows)
    marks = {}
    for source, targets in follows.items():
        if not scripted.intersection(targets):
            continue
        marks.setdefault(source, set()).add(FROM_GLOBAL.format(source))
        for target in targets:
            marks.setdefault(target, set()).add(SAID_GLOBAL.format(target))
    return {fid: sorted(names) for fid, names in marks.items()}
