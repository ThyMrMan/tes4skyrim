"""Scripts that fail to compile, quest commands left inert, and properties that read None.

Compile failures are grouped by cause. A `;NE:` marker on a command that
moves a quest along is marked for review, grouped by command, since whether
the quest still finishes depends on what the command did. A property that
cannot bind (wrong record type, unbound, or an Actor property on a non-actor
reference) reads None and aborts every function that touches it; a FormID
that names no record can hang the load.

See: docs/commentary/tools_preflight.md#script-health
"""

import re
from collections import defaultdict
from pathlib import Path

from tools.validate.dangling_ref_check import dangling_refs
from tools.validate.preflight.findings import Finding
from tools.validate.preflight.quest_converted import strip_papyrus_comment
from tools.validate.property_type_audit import unbindable_actor_properties
from tools.validate.vmad_property_typecheck import (MasterTables, cross_master_problems, declared_properties,
                                                    script_extends, unbound_properties)

#: Commands whose loss can leave a quest unfinishable; SetStage and StartQuest are the quest audits'.
FLOW_COMMANDS = frozenset({
    'completeallobjectives', 'setobjectivedisplayed', 'setobjectivecompleted', 'completequest',
    'stopquest', 'killactor', 'setplayerteammate', 'placeleveledactoratme', 'placeatme', 'moveto',
    'enable', 'disable', 'addtopic', 'startconversation', 'additem', 'removeitem', 'resurrect',
    'unlock', 'lock', 'setquestobject', 'startcombat', 'evp', 'addscriptpackage'})

#: Property names the engine fills itself, so an unbound one is always a bug.
ENGINE_NAMES = frozenset({'player', 'playerref', 'gamehour', 'gameday', 'gamedayspassed', 'gamemonth',
                          'gameyear', 'timescale'})

#: The command a `;NE:` marker names: past `TODO:` and any `ref.` prefix.
_NE_COMMAND = re.compile(r';NE:\s*(?:TODO:\s*)?(?:[\w\[\]]+\.)?([A-Za-z]\w*)')

#: A name in a compiler message: a token with an uppercase letter, digit or underscore.
_NAME = re.compile(r'\b\w*[A-Z0-9_]\w*\b')

#: A property type that is a generated script, as in `FALLOUT3_CRBrahminScript`.
_SCRIPT_TYPE = re.compile(r'^[A-Z0-9]+_')

#: Record types a script of each engine type may be attached to; a type not listed is not judged.
ATTACHABLE = {'actor': {'ACHR', 'NPC_'}, 'quest': {'QUST'}, 'topicinfo': {'INFO'}, 'package': {'PACK'},
              'scene': {'SCEN'}, 'activemagiceffect': {'MGEF'}}

#: Samples listed per finding.
SAMPLES = 4


def _samples(rows: list) -> tuple:
    """The first SAMPLES rows, then a count of the rest."""
    more = [f'... {len(rows) - SAMPLES} more'] if len(rows) > SAMPLES else []
    return tuple(rows[:SAMPLES] + more)


def compile_findings(game: str, scripts_dir: Path, scripts: dict) -> list:
    """One error per compile cause, from the compiler's log and the sources with no `.pex`."""
    log = Path(scripts_dir) / 'compile_errors.log'
    causes = defaultdict(list)
    logged = set()
    for line in (log.read_text(encoding='utf-8', errors='replace').splitlines() if log.is_file() else ()):
        name, _, message = line.partition(': ')
        stem = Path(name.split('(')[0]).stem.lower()
        logged.add(stem)
        cause = _NAME.sub('#', message.split('): ', 1)[-1]).strip() or 'unknown'
        causes[cause].append(f'{stem}: {message[:100]}')
    for name, script in sorted(scripts.items()):
        if not script.compiled and name not in logged:
            causes['no .pex and no logged error'].append(name)
    return [Finding('scripts', f'scripts|{game}|compile|{cause[:80]}', 'error',
                    f'{len(rows)} scripts failed to compile: {cause[:100]}', _samples(sorted(rows)))
            for cause, rows in sorted(causes.items())]


def inert_findings(game: str, source_dir: Path, owner) -> list:
    """One review per quest-moving command the converter left as a `;NE:` marker."""
    by_command = defaultdict(list)
    for path in sorted(Path(source_dir).glob('*.psc')):
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            match = _NE_COMMAND.search(line)
            if match and match.group(1).lower() in FLOW_COMMANDS:
                by_command[match.group(1).lower()].append((owner(path.stem.lower()), line.strip()))
    out = []
    for command, rows in sorted(by_command.items()):
        quests = sorted({q for q, _line in rows})
        detail = [f'in {len(quests)} quests or scripts: {", ".join(quests[:8])}'
                  + (' ...' if len(quests) > 8 else '')] + [line[:110] for _q, line in rows[:2]]
        out.append(Finding('scripts', f'scripts|{game}|inert|{command}', 'review',
                           f'{len(rows)} {command} calls were left inert (;NE:)', tuple(detail)))
    return out


def binding_findings(game: str, index, esm: Path, output: Path, declared: dict, extends: dict) -> list:
    """One error per (declared type, cause) whose bound FormIDs cannot bind.

    A cause is the record type found, or why a type-correct target still fails:
    it lacks the property's script, is a base where a reference is needed, or
    is a reference that is not persistent.
    """
    tables = MasterTables(game, index, str(esm), str(output))
    _checked, bad, _unresolved = cross_master_problems(tables, index, declared, extends)
    groups = defaultdict(list)
    for script, prop, ptype, fid, where, sig, edid in bad:
        kind = 'converted-script-typed' if _SCRIPT_TYPE.match(ptype) else ptype
        cause = 'a record lacking the script' if sig.startswith('lacks ') else (sig if ' ' in sig else f'{sig} records')
        groups[(kind, cause)].append(f'{script}.{prop} ({ptype}) -> {edid or "?"} {fid} in {where}')
    return [Finding('scripts', f'scripts|{game}|binding|{kind}|{cause}', 'error',
                    f'{len(rows)} {kind} properties read None: they name {cause}', _samples(rows))
            for (kind, cause), rows in sorted(groups.items())]


def native_type(script: str, extends: dict) -> str:
    """The engine type a generated script ultimately extends, lower."""
    seen = set()
    while script in extends and script not in seen:
        seen.add(script)
        script = extends[script]
    return script


def attach_mismatches(index, extends: dict) -> dict:
    """{(engine type, record type): [(script, FormID)]} of scripts attached where the engine refuses them."""
    groups = defaultdict(list)
    for script, fids in index.attached.items():
        native = native_type(script, extends)
        allowed = ATTACHABLE.get(native)
        groups_for = [(fid, index.by_fid[fid].type) for fid in fids]
        for fid, sig in groups_for:
            if allowed is not None and sig not in allowed:
                groups[(native, sig)].append((script, fid))
    return groups


def attach_findings(game: str, index, extends: dict) -> list:
    """One error per (engine type, record type) of scripts attached where the engine refuses them."""
    groups = {key: [f'{script} on {index.edid(fid) or hex(fid)}' for script, fid in rows]
              for key, rows in attach_mismatches(index, extends).items()}
    return [Finding('scripts', f'scripts|{game}|attach|{native}|{sig}', 'error',
                    f'{len(rows)} scripts extending {native} are attached to {sig} records, which the engine refuses',
                    _samples(sorted(rows)))
            for (native, sig), rows in sorted(groups.items())]


def used(source_dir: Path, script: str, prop: str, texts: dict) -> bool:
    """Whether `script`'s code, comments aside, names `prop` anywhere past its declaration."""
    if script not in texts:
        path = Path(source_dir) / f'{script}.psc'
        text = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
        texts[script] = '\n'.join(strip_papyrus_comment(line) for line in text.splitlines())
    return len(re.findall(rf'\b{re.escape(prop)}\b', texts[script], re.I)) > 1


def unbound_findings(game: str, index, declared: dict, source_dir: Path) -> list:
    """One error per (declared type, named record type) of used properties no VMAD binds.

    Only a property named after a record in the plugin, or an engine value, is
    judged; any other name is dead in the source game too.
    """
    types, _shared = index.edid_types()
    groups, texts = defaultdict(list), {}
    for script, prop, ptype in unbound_properties(index, declared):
        named = types.get(prop.lower()) or ('engine' if prop.lower() in ENGINE_NAMES else None)
        if named and used(source_dir, script, prop, texts):
            kind = 'converted-script-typed' if _SCRIPT_TYPE.match(ptype) else ptype
            groups[(kind, named)].append(f'{script}.{prop} ({ptype})' if kind != ptype else f'{script}.{prop}')
    return [Finding('scripts', f'scripts|{game}|unbound|{ptype}|{named}', 'error',
                    f'{len(rows)} {ptype} properties named after {named} records are never bound, so they read None',
                    _samples(rows))
            for (ptype, named), rows in sorted(groups.items())]


def actor_findings(game: str, export_dir: Path, source_dir: Path) -> list:
    """One error per Actor property named after a reference whose base is not an actor."""
    return [Finding('scripts', f'scripts|{game}|actor|{name}', 'error',
                    f'Actor property {name} names a reference whose base is a {sig}, so it reads None',
                    _samples(sorted(files)))
            for (name, sig), files in sorted(unbindable_actor_properties(str(export_dir), str(source_dir)).items())]


def dangling_findings(game: str, output: Path) -> list:
    """One error per (record, subrecord, expected file) group of FormIDs that name nothing."""
    result = dangling_refs(game, str(output))
    groups = defaultdict(list)
    for (rsig, ssig, target, where), count in (result[2].items() if result else ()):
        groups[(rsig, ssig, where)].append(f'{target} x{count}')
    return [Finding('scripts', f'scripts|{game}|dangling|{rsig}.{ssig}|{where}', 'error',
                    f'{len(rows)} {rsig}.{ssig} FormIDs name no record in {where}', _samples(rows))
            for (rsig, ssig, where), rows in sorted(groups.items())]


def audit(game: str, index, output: Path, export_dir: Path, scripts: dict, owner) -> list:
    """The script health findings for one game; `owner` names a script's quest, or the script."""
    scripts_dir = output / game / 'scripts'
    declared = declared_properties(str(scripts_dir / 'source'))
    extends = script_extends(str(scripts_dir / 'source'))
    return (compile_findings(game, scripts_dir, scripts)
            + inert_findings(game, scripts_dir / 'source', owner)
            + attach_findings(game, index, extends)
            + binding_findings(game, index, output / game / game, output, declared, extends)
            + unbound_findings(game, index, declared, scripts_dir / 'source')
            + actor_findings(game, export_dir, scripts_dir / 'source')
            + dangling_findings(game, output))
