"""Quest stages the source game can reach and the converted game cannot.

Every SetStage site is judged twice. In the source it is live when its
container runs: a reached stage, a reachable and speakable line, a package or
a script. In the build it must also still set that stage, compile, be
attached, and run in Skyrim terms. A fixed point over each side gives the
reached stages; a stage only the source reaches is an error, and one that
rests on a setter the audit could not confirm is marked for review.

See: docs/commentary/tools_preflight.md#quest-progression
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from script_convert.constants import papyrus_script_name
from tes5_import.packages.scripts_falloutnv import folds_change, package_sections
from tools.validate.preflight.findings import Finding
from tools.validate.preflight.quest_converted import SELF_QUEST, ConvertedDialogue
from tools.validate.preflight.quest_source import START, speakable

#: Source sites listed per finding before the rest are counted.
SITES_SHOWN = 6


@dataclass
class QuestContext:
    """Everything the quest audit reads for one game."""

    game: str
    source: object
    scripts: dict
    index: object
    manifest: dict = field(default_factory=dict)
    prefix: str = ''
    offset: int = 0

    def __post_init__(self):
        """Derive the prefix, FormID shift, both dialogue models and the converted setter map."""
        self.prefix = self.prefix or script_prefix_of(self.scripts)
        self.offset = self.offset or fid_offset(self.source, self.index)
        self.dialogue = ConvertedDialogue(self.index)
        self.source_topics = self.source.reachable_topics()
        self.qf_owner = {papyrus_script_name(edid, self.prefix + 'QF_').lower(): edid.lower()
                         for edid in self.source.quests.values()}
        self.setters_at = self._setters_by_stage()

    def built_fid(self, owner: str) -> int:
        """The built FormID of the source record whose FormID is `owner` (hex)."""
        hit = self.manifest.get(owner.upper())
        if hit:
            return hit
        src = int(owner, 16)
        return (((src >> 24) + self.offset) << 24) | (src & 0xFFFFFF)

    def context_quest(self, script: str) -> str:
        """The quest a script's `Self` or `GetOwningQuest()` means, lower, or ''."""
        if script in self.qf_owner:
            return self.qf_owner[script]
        tif = self.prefix.lower() + 'tif__'
        if script.startswith(tif):
            info = self.source.infos.get(int(script[len(tif):], 16))
            return self.source.quest_fids.get(info.quest, '').lower() if info else ''
        quests = [f for f in self.index.attached.get(script, ())
                  if self.index.by_fid[f].type == 'QUST']
        return self.index.edid(quests[0]).lower() if quests else ''

    def resolve(self, expr: str, script: str):
        """The quest EditorID (lower) a SetStage's quest expression names, or None."""
        if expr in SELF_QUEST:
            return self.context_quest(script) or None
        fid = self.index.script_props.get(script, {}).get(expr)
        if fid and fid in self.index.by_fid and self.index.by_fid[fid].type == 'QUST':
            return self.index.edid(fid).lower()
        return expr if expr in self.source.quests else None

    def _setters_by_stage(self) -> dict:
        """{(quest lower, stage): [script names]} over every resolvable converted SetStage."""
        out = {}
        for name, script in self.scripts.items():
            for call in script.calls:
                quest = self.resolve(call.quest_expr, name)
                if quest:
                    out.setdefault((quest, call.stage), []).append(name)
        return out


def script_prefix_of(scripts: dict) -> str:
    """The generated-script prefix most script names share, as in `FALLOUT3_`."""
    heads = Counter(name.split('_', 1)[0] for name in scripts if '_' in name)
    return heads.most_common(1)[0][0].upper() + '_' if heads else ''


def fid_offset(source, index) -> int:
    """How far the build shifted source load-order indices, read from matching quest EditorIDs."""
    built = {index.edid(r.form_id).lower(): r.form_id for r in index.by_type['QUST']}
    shifts = Counter((built[e.lower()] >> 24) - (fid >> 24)
                     for fid, e in source.quest_fids.items() if e.lower() in built)
    return shifts.most_common(1)[0][0] if shifts else 0


def load_manifest(path: Path) -> dict:
    """{source FormID hex: built FormID} from a build's manifest, or {}."""
    if not Path(path).is_file():
        return {}
    records = json.loads(Path(path).read_text(encoding='utf-8')).get('records', {})
    return {k.upper(): v['fid'] for k, v in records.items() if isinstance(v, dict) and 'fid' in v}


def converted_name(site, prefix: str) -> str:
    """The generated script (lower) that should hold a source site's SetStage."""
    if site.kind == 'stage':
        return papyrus_script_name(site.owner.split('|')[0], prefix + 'QF_').lower()
    if site.kind == 'info':
        return f'{prefix}TIF__{site.owner}'.lower()
    if site.kind == 'package':
        return f'{prefix}PF__{site.owner}'.lower()
    return papyrus_script_name(site.owner, prefix).lower()


def fragment_scope(site, ctx):
    """A test of whether a function name is where a site's SetStage may sit."""
    if site.kind == 'stage':
        head = f'fragment_stage_{int(site.owner.split("|")[1]):04d}_'
        return lambda function: function.startswith(head)
    if site.kind != 'package':
        return lambda function: True
    rec = ctx.source.packages.get(site.owner, {})
    names = [name for name, _flag in package_sections(rec)]
    wanted = [site.part] + (['OnEnd'] if site.part == 'OnChange' and folds_change(rec) else [])
    functions = {f'fragment_{names.index(w)}' for w in wanted if w in names}
    return lambda function: function in functions


def _package_change_only(site, ctx, hits: list):
    """A review outcome when an OnChange SetStage survives only in the OnChange fragment."""
    if site.kind != 'package' or site.part != 'OnChange':
        return None
    rec = ctx.source.packages.get(site.owner, {})
    names = [name for name, _flag in package_sections(rec)]
    if 'OnEnd' in names and any(c.function == f'fragment_{names.index("OnEnd")}' for c in hits):
        return None
    return ('review', f'package {rec.get("EditorID", site.owner)} sets it only in OnChange, '
                      'which Skyrim runs only when the actor leaves the package')


def check_setter(site, ctx) -> tuple:
    """(ok | review | lost, reason) for whether the build still sets a source site's stage."""
    name = converted_name(site, ctx.prefix)
    script = ctx.scripts.get(name)
    quest = site.quest.lower()
    command = 'StartQuest' if site.stage == START else 'SetStage'
    moved = [s for s in ctx.setters_at.get((quest, site.stage), ()) if s != name]
    if script is None:
        return (('review', f'{name} was not generated; {moved[0]} has the {command}')
                if moved else ('lost', f'{name} was not generated'))
    if not script.compiled:
        return 'lost', f'{name} failed to compile'
    scope = fragment_scope(site, ctx)
    hits = [c for c in script.calls if c.stage == site.stage and scope(c.function)]
    confirmed = [c for c in hits if ctx.resolve(c.quest_expr, name) == quest]
    if confirmed:
        return _package_change_only(site, ctx, confirmed) or ('ok', '')
    unresolved = [c for c in hits if ctx.resolve(c.quest_expr, name) is None]
    if unresolved:
        return 'review', (f'{name} has a {command} on "{unresolved[0].quest_expr}", '
                          'a quest the audit cannot resolve')
    inert = [why for call, why in script.inert if call.stage == site.stage
             and scope(call.function) and ctx.resolve(call.quest_expr, name) in (quest, None)]
    if inert:
        return 'lost', f'{name}: the {command} {inert[0]}'
    if moved:
        return 'review', f'not in {name}; {moved[0]} has the {command}'
    return 'lost', f'{name} has no {command} for it'


def check_runs(site, ctx) -> str:
    """'' when the site's container runs in the build, else why it does not."""
    name = converted_name(site, ctx.prefix)
    if site.kind == 'info':
        fid = ctx.built_fid(site.owner)
        if fid not in ctx.index.by_fid:
            return ctx.dialogue.reachable_info(fid)
        if fid not in ctx.index.attached.get(name, ()):
            return 'its fragment is not attached to the built INFO'
        return ctx.dialogue.reachable_info(fid)
    if site.kind in ('script', 'package') and not ctx.index.attached.get(name):
        return f'{name} is attached to no record'
    return ''


def source_live(site, ctx) -> bool:
    """Whether a site's container runs in the source game."""
    if site.kind == 'script':
        return site.owner.lower() in ctx.source.used_scripts
    if site.kind != 'info':
        return True
    info = ctx.source.infos.get(int(site.owner, 16))
    return bool(info) and info.dial in ctx.source_topics and speakable(info.conditions,
                                                                       ctx.source.present)


def owner_stage(site):
    """(quest lower, stage) a quest-stage site runs in, or None for other kinds."""
    if site.kind != 'stage':
        return None
    quest, stage = site.owner.split('|')
    return quest.lower(), int(stage)


def reached_stages(sites: list, live) -> set:
    """{(quest lower, stage)} reached by a fixed point over the sites `live` accepts."""
    reached, pending, changed = set(), [s for s in sites if s.stage is not None], True
    while changed:
        changed, rest = False, []
        for site in pending:
            if owner_stage(site) and owner_stage(site) not in reached:
                rest.append(site)
            elif live(site):
                reached.add((site.quest.lower(), site.stage))
                changed = True
        pending = rest
    return reached


def describe(site, ctx) -> str:
    """A person-readable name for a source site."""
    if site.kind == 'stage':
        quest, stage = site.owner.split('|')
        return f'{quest} stage {stage} result script'
    if site.kind == 'info':
        info = ctx.source.infos.get(int(site.owner, 16))
        topic = ctx.source.dials.get(info.dial, ('',))[0] if info else ''
        return f'dialogue line {site.owner} (topic {topic or "?"})'
    if site.kind == 'package':
        return f'package {ctx.source.packages.get(site.owner, {}).get("EditorID", site.owner)} {site.part}'
    return f'script {site.owner}' + (f' (Begin {site.part})' if site.part else '')


def judge(ctx) -> dict:
    """{site: (status, reason)} for every source-live site, status ok, review or lost."""
    out = {}
    for site in ctx.source.setters:
        if site.stage is None or not source_live(site, ctx):
            continue
        status, reason = check_setter(site, ctx)
        blocked = check_runs(site, ctx) if status != 'lost' else ''
        out[site] = ('lost', blocked) if blocked else (status, reason)
    return out


def site_lines(stage_sites: list, verdicts: dict, ctx, reached: set) -> list:
    """Detail lines for the source setters of one stage."""
    lines = []
    for site in stage_sites[:SITES_SHOWN]:
        status, reason = verdicts[site]
        owner = owner_stage(site)
        if owner and owner not in reached:
            reason = f'runs in stage {owner[1]}, which the build does not reach'
        lines.append(f'{describe(site, ctx)}: {status}{" - " + reason if reason else ""}')
    if len(stage_sites) > SITES_SHOWN:
        lines.append(f'... {len(stage_sites) - SITES_SHOWN} more setters')
    return lines


def graphs(ctx) -> tuple:
    """(verdicts, source reached, hopeful build reached, strict build reached) for one game."""
    verdicts = judge(ctx)
    source = reached_stages([s for s in ctx.source.setters if source_live(s, ctx)], lambda s: True)
    hopeful = reached_stages(list(verdicts), lambda s: verdicts[s][0] != 'lost')
    strict = reached_stages(list(verdicts), lambda s: verdicts[s][0] == 'ok')
    return verdicts, source, hopeful, strict


def audit(ctx) -> list:
    """The quest progression findings for one game; quest starts are `quest_start`'s."""
    verdicts, source, hopeful, strict = graphs(ctx)
    sites = list(verdicts)
    computed = {s.quest.lower() for s in ctx.source.setters if s.stage is None}
    out = []
    for quest, stage in sorted(k for k in source - strict if k[1] != START):
        stage_sites = [s for s in sites if (s.quest.lower(), s.stage) == (quest, stage)]
        detail = site_lines(stage_sites, verdicts, ctx, hopeful)
        lost = (quest, stage) not in hopeful
        if lost and quest in computed:
            detail.append('the quest also has a SetStage with a computed stage number, which may reach it')
        severity = 'error' if lost and quest not in computed else 'review'
        name = ctx.source.quests.get(quest, quest)
        summary = (f'{name} stage {stage} cannot be reached after conversion' if lost else
                   f'{name} stage {stage} rests on setters the audit could not confirm')
        out.append(Finding('quest', f'quest|{ctx.game}|{name}|{stage}', severity, summary,
                           tuple(detail)))
    return out
