#!/usr/bin/env python3
"""Record placed actors' AI and combat state from the running game, over time.

Per tick, for each actor: position, health, dead, combat state and target,
whether it detects / has line of sight to the player, distance to the player,
current AI package and procedure, running / weapon out / attacking / fleeing,
aggression and confidence, which of the named magic effects it carries and
which of the named packages it is running. Also each named quest's Papyrus
variables, each `--vars` ref's script variables (`sv`), and every Papyrus line
the VM logs. Everything goes through the game bridge (one client).

    python tools/live/actor_record.py --plugin Nehrim.esm --quests MQ00 \
        --refs MQ00TrollA01 MQ00TrollA02 MQ00MerzulRef \
        --effects TES4ConfidenceFleeEffect --packages MQ00TrollTravel \
        --vars 001BDEB8 --seconds 900 --out temp/trolls.txt

Writes `<out>` (changes only, readable) and `<out>.jsonl` (every tick, whole
state). Prints as it goes, so a stopped run is still usable.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, __file__.rsplit('tools', 1)[0])
from tools.esm.tes5_esm_reader import read_tes5_file
from tools.live.game_bridge import Bridge, BridgeError
from tools.live.quest_labtest import detect_index, editorid_index, runtime_formid
from tools.live.quest_multi_record import snapshot

#: The player reference, which every per-actor probe measures against.
PLAYER = 'player'

#: Per-actor probes: (label, console command after `<ref>.`); `{p}` is the player.
PROBES = (
    ('x', 'getpos x'), ('y', 'getpos y'), ('z', 'getpos z'),
    ('health', 'getav health'), ('dead', 'getdead'),
    ('in_combat', 'isincombat'), ('combat_state', 'getcombatstate'),
    ('combat_target', 'getcombattarget'), ('detects_player', 'getdetected {p}'),
    ('los_player', 'getlos {p}'), ('dist_player', 'getdistance {p}'),
    ('should_attack', 'getshouldattack {p}'), ('package', 'getcurrentaipackage'),
    ('procedure', 'getcurrentaiprocedure'), ('running', 'isrunning'),
    ('weapon_out', 'isweaponout'), ('attacking', 'isattacking'),
    ('fleeing', 'isfleeing'), ('aggression', 'getav aggression'),
    ('confidence', 'getav confidence'),
)

#: Labels whose value moves every tick; logged only past this step in world units.
_POSITION = {'x', 'y', 'z', 'dist_player'}
_POSITION_STEP = 64.0

_VALUE_RE = re.compile(r'>>\s*(.+?)\s*$')


def _value(output: str) -> str:
    """The `>> value` part of one console reply, else the whole reply on one line."""
    text = ' '.join((output or '').split())
    m = _VALUE_RE.search(text)
    return m.group(1) if m else text


def _output_edids(plugin: str, sigs: set) -> dict:
    """{EditorID.lower(): FormID} for records of `sigs` in the converted ESM."""
    esm = Path('output') / plugin / plugin
    _h, records, _l = read_tes5_file(str(esm), parse_types=sigs)
    out = {}
    for rec in records:
        for sub in rec.subrecords or ():
            if sub.type == 'EDID':
                out[sub.data.rstrip(b'\0').decode('cp1252').lower()] = f'{rec.form_id:08X}'
    return out


def resolve(args) -> dict:
    """{'refs': {name: fid}, 'effects': {...}, 'packages': {...}, 'vars': {...}} at runtime ids."""
    refs = editorid_index(args.plugin)
    packs = editorid_index(args.plugin, ('PACK',))
    gen = _output_edids(args.plugin, {'MGEF'}) if args.effects else {}
    out = {'refs': {}, 'effects': {}, 'packages': {}, 'vars': {}}
    for key, names, table in (('refs', args.refs, refs), ('packages', args.packages, packs),
                              ('vars', args.vars, refs), ('effects', args.effects, gen)):
        for name in names:
            fid = table.get(name.lower()) or (name if re.fullmatch(r'[0-9A-Fa-f]{6,8}', name) else '')
            if not fid:
                print(f'** {key}: {name} not found', file=sys.stderr)
                continue
            out[key][name] = runtime_formid(fid, args.index)
    return out


def _probe(bridge: Bridge, command: str, ref: str) -> str:
    """One console command run on `ref`; a bridge error becomes the value."""
    try:
        return _value(bridge.console(command, ref=ref))
    except BridgeError as exc:
        return f'error: {exc}'


def actor_state(bridge: Bridge, ref: str, forms: dict) -> dict:
    """Every probe for one actor, each run with the ref selected (`<id>.cmd` is not parsed)."""
    probes = [(label, cmd.format(p=PLAYER)) for label, cmd in PROBES]
    probes += [(f'has:{n}', f'hasmagiceffect {fid}') for n, fid in forms['effects'].items()]
    probes += [(f'pkg:{n}', f'getiscurrentpackage {fid}') for n, fid in forms['packages'].items()]
    return {label: _probe(bridge, cmd, ref) for label, cmd in probes}


def ref_vars(bridge: Bridge, ref: str) -> dict:
    """The script variables `sv` prints for a reference."""
    try:
        text = bridge.console('sv', ref=ref)
    except BridgeError as exc:
        return {'_error': str(exc)}
    pairs = (re.match(r'^\s*(\S+)\s*=\s*(.*?)\s*$', ln) for ln in (text or '').splitlines())
    return {m.group(1): m.group(2) for m in pairs if m}


def _changed(label: str, old, new) -> bool:
    """True when a value changed enough to log; positions only past a step."""
    if old == new:
        return False
    if label in _POSITION:
        try:
            return abs(float(old) - float(new)) >= _POSITION_STEP
        except (TypeError, ValueError):
            return True
    return True


def diff(name: str, old: dict, new: dict, emit) -> dict:
    """Emit each field that changed; return the state to compare against next tick."""
    kept = dict(old)
    for label in sorted(set(old) | set(new)):
        if _changed(label, old.get(label), new.get(label)):
            emit(f'{name}.{label}: {old.get(label)} -> {new.get(label)}')
            kept[label] = new.get(label)
    return kept


def papyrus_lines(bridge: Bridge) -> list:
    """Papyrus lines logged since the last call; re-arms the capture slice."""
    try:
        lines = bridge.vmlog(take=True).get('lines', [])
        bridge.vmlog(arm=True)
    except BridgeError as exc:
        return [f'vmlog error: {exc}']
    return lines


def tick(bridge: Bridge, args, forms: dict) -> dict:
    """One whole-state sample: every actor, quest and script-variable ref."""
    state = {name: actor_state(bridge, ref, forms) for name, ref in forms['refs'].items()}
    state.update({f'quest:{q}': snapshot(bridge, q) for q in args.quests})
    state.update({f'vars:{n}': ref_vars(bridge, ref) for n, ref in forms['vars'].items()})
    return state


def record(bridge: Bridge, args, forms: dict) -> None:
    """Poll until the time runs out, writing the change log and the full-state JSONL."""
    start = time.time()
    log = open(args.out, 'w', encoding='utf-8')
    full = open(args.out + '.jsonl', 'w', encoding='utf-8')

    def emit(msg: str) -> None:
        """Print and append one timestamped line."""
        line = f'[{time.time() - start:7.1f}s] {msg}'
        print(line, flush=True)
        log.write(line + '\n')
        log.flush()
    emit(f'forms {json.dumps(forms)}')
    bridge.vmlog(arm=True)
    prev = {}
    while time.time() - start < args.seconds:
        state = tick(bridge, args, forms)
        full.write(json.dumps({'t': round(time.time() - start, 2), 'state': state}) + '\n')
        full.flush()
        for name, values in state.items():
            prev[name] = diff(name, prev.get(name, {}), values, emit)
        for line in papyrus_lines(bridge):
            emit(f'papyrus: {line}')
        time.sleep(args.interval)
    emit('done')
    log.close()
    full.close()


def main() -> int:
    """Resolve the forms, find the plugin's load-order slot, then record."""
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--plugin', required=True, help='export/output folder name, e.g. Nehrim.esm')
    ap.add_argument('--refs', nargs='+', required=True, help='placed actors: EditorID or export FormID')
    ap.add_argument('--quests', nargs='*', default=[], help='quest EditorIDs to snapshot with sqv')
    ap.add_argument('--effects', nargs='*', default=[], help='MGEF EditorIDs (output ESM) to test HasMagicEffect')
    ap.add_argument('--packages', nargs='*', default=[], help='PACK EditorIDs to test GetIsCurrentPackage')
    ap.add_argument('--vars', nargs='*', default=[], help='refs whose script variables to log (sv)')
    ap.add_argument('--index', default='', help='load-order index byte; detected when omitted')
    ap.add_argument('--seconds', type=float, default=900)
    ap.add_argument('--interval', type=float, default=0.5)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    bridge = Bridge()
    if not args.index:
        probe = editorid_index(args.plugin, ('QUST',)).get((args.quests or [''])[0].lower(), '')
        args.index = (detect_index(bridge, probe) if probe else None) or '01'
        print(f'load-order index {args.index}')
    record(bridge, args, resolve(args))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
