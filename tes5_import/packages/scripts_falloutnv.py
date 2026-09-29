"""FO3/FNV package scripts: which OnBegin/OnEnd/OnChange sections a PACK runs.

A FO3/FNV package runs an embedded script, and says a topic, when it begins,
ends or changes. Skyrim packages carry the same three fragments. This is the
contract both stages read: `package_sections` decides which fragments exist,
for the fragment script `script_convert` writes and the VMAD the importer writes.

See: docs/commentary/script_convert.md#package-fragments
"""

import re

#: FO3/FNV PKDT.Type of a Dialogue package, as the export writes it.
_DIALOGUE_TYPE = '15'

#: The player's reference and base FormIDs as the export writes them.
_PLAYER_FIDS = frozenset({'00000014', '00000007'})

#: The three sections, in the order the VMAD lists their fragments, with their flag bits.
PACKAGE_SECTIONS = (('OnBegin', 0x01), ('OnEnd', 0x02), ('OnChange', 0x04))

#: FO3/FNV PKDT flag Once Per Day: the package is left as soon as it completes.
_ONCE_PER_DAY = 0x400

#: A `setstage <quest> <stage>` statement, the whole line.
_SETSTAGE = re.compile(r'^\s*setstage\s+(\w+)\s+(\d+)\s*$', re.IGNORECASE)


def has_code(text: str) -> bool:
    """Whether a script text holds any statement outside comments."""
    return any(line.split(';', 1)[0].strip() for line in text.splitlines())


def change_stages(rec: dict) -> list:
    """[(quest EditorID, stage)] of the `setstage` lines a PACK's OnChange runs."""
    lines = (rec.get('OnChange.Script') or '').splitlines()
    return [(m.group(1), int(m.group(2))) for m in map(_SETSTAGE.match, lines) if m]


def section_refs(rec: dict, section: str) -> list:
    """The SCRO FormIDs a section's script names, in table order."""
    out = []
    while (fid := rec.get(f'{section}.SCRO[{len(out)}]')) is not None:
        out.append(fid)
    return out


def folds_change(rec: dict) -> bool:
    """Whether a run-once package's OnChange runs at its end, since Skyrim stays in it.

    See: docs/commentary/script_convert.md#run-once-package-change
    """
    return bool(int(rec.get('PKDT.Flags') or 0) & _ONCE_PER_DAY) and bool(change_stages(rec))


def package_sections(rec: dict) -> list:
    """[(section, flag)] of a PACK's sections that run a script or say a topic."""
    return [(name, flag) for name, flag in PACKAGE_SECTIONS
            if has_code(rec.get(f'{name}.Script') or '') or rec.get(f'{name}.Topic')
            or (name == 'OnEnd' and folds_change(rec))]


def package_flags(rec: dict) -> int:
    """The VMAD fragment flags of a PACK: one bit per section it runs."""
    return sum(flag for _name, flag in package_sections(rec))


def section_source(rec: dict, section: str, formid_to_edid: dict) -> str:
    """A section's script, then `Say <topic>` for the topic it says.

    A folded OnEnd runs OnChange after it, then re-evaluates the actor's package.
    """
    topic = formid_to_edid.get((rec.get(f'{section}.Topic') or '').upper(), '')
    own = (rec.get(f'{section}.Script') or '') + (f'\nSay {topic}\n' if topic else '')
    if section != 'OnEnd' or not folds_change(rec):
        return own
    return f"{own}\n{section_source(rec, 'OnChange', formid_to_edid)}\nevp\n"


def dialogue_source(rec: dict, formid_to_edid: dict) -> str:
    """`SayTo <target> <topic>` for a Dialogue package (PKDT.Type 15), else ''."""
    topic = formid_to_edid.get((rec.get('PKDD.Topic') or '').upper(), '')
    if rec.get('PKDT.Type') != _DIALOGUE_TYPE or not topic:
        return ''
    target = (rec.get('PTDT.Target') or '').upper()
    name = 'player' if target in _PLAYER_FIDS else formid_to_edid.get(target, target)
    return f'SayTo {name} {topic}'


def package_source(rec: dict, formid_to_edid: dict) -> str:
    """The sections' sources and a Dialogue package's topic, for the call-site scans."""
    parts = [section_source(rec, name, formid_to_edid) for name, _flag in package_sections(rec)]
    return '\n'.join(parts + [dialogue_source(rec, formid_to_edid)])


def edids_by_formid(by_type: dict) -> dict:
    """{FormID (upper hex): EditorID} of the topics and placed references in `by_type`."""
    return {(r.get('FormID') or '').upper(): r.get('EditorID') or ''
            for sig in ('DIAL', 'ACHR', 'ACRE', 'REFR') for r in by_type.get(sig, ())}
