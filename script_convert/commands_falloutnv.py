"""FO3/FNV command handlers whose behaviour depends on the RECEIVER's record.

A row in `FALLOUT_COMMAND_ROWS` renders one template for every call site. A
handler belongs here only where FO3/FNV spell one command against two different
receiver types, which a single template cannot express.

Exported as a plain table rather than through `commands.command`, so this module
imports nothing from `commands` and the two cannot form a cycle.

See: docs/commentary/script_convert.md#getfactionrelation-has-two-receivers
"""

from script_convert.constants import safe_property_name, typed_already
from script_convert.message_menus import authored_site
from tes5_import.record_types.equipment_falloutnv import WEAPON_ANIM_LISTS


def faction_relation(ctx, call):
    """`<x>.GetFactionRelation <actor>` -- reaction toward another actor.

    Declines (returns None) for an ACTOR receiver so the row renders the real
    `Actor.GetFactionReaction`; only the FACTION receiver is handled here,
    because Papyrus has no faction-toward-actor read at all.
    """
    ref = call.ref or ''
    fid = ctx.xref.edid_to_formid.get(ref.lower(), '') if ctx.xref else ''
    if not fid or ctx.xref.record_type.get(fid, '') != 'FACT':
        return None
    return ctx.note(f'NE: {ref}.GetFactionRelation - Papyrus has no '
                    f'faction-toward-actor reaction (read as 0)')


#: FO3/FNV command -> Quest native it becomes, the quest argument as receiver.
_QUEST_NATIVES = {
    'setobjectivedisplayed': 'SetObjectiveDisplayed',
    'setobjectivecompleted': 'SetObjectiveCompleted',
    'setobjectivefailed': 'SetObjectiveFailed',
    'getobjectivedisplayed': 'IsObjectiveDisplayed',
    'getobjectivecompleted': 'IsObjectiveCompleted',
    'getobjectivefailed': 'IsObjectiveFailed',
    'setquestdelay': 'RegisterForSingleUpdate',
}


#: Quest EditorID (lower) -> frozenset of authored QOBJ indices, per process.
_QUEST_OBJECTIVES: dict = {}


def set_quest_objectives(index: dict) -> None:
    """Install the authored-objective index in this process."""
    _QUEST_OBJECTIVES.clear()
    _QUEST_OBJECTIVES.update(index)


def quest_objective_indices(by_type: dict) -> dict:
    """Quest EditorID (lower) -> frozenset of authored QOBJ indices.

    Only quests that author an Objective[] block appear; a quest absent from
    this map is never second-guessed.
    See: docs/commentary/script_convert.md#fnv-unknown-objective-index
    """
    out = {}
    for rec in by_type.get('QUST', []):
        edid = (rec.get('EditorID') or '').lower()
        count = rec.get('ObjectiveCount')
        if not edid or count is None:
            continue
        idx = set()
        for i in range(int(count or 0)):
            raw = rec.get(f'Objective[{i}].Index')
            if raw is not None:
                try:
                    idx.add(int(raw))
                except (TypeError, ValueError):
                    pass
        if idx:
            out[edid] = frozenset(idx)
    return out


def _unauthored_objective(quest_edid: str, index_src: str) -> bool:
    """True when this quest authors objectives but not THIS index.

    FO3/FNV scripts call objective indices their own quest never defines
    (nVPrimmDeputyConv polls 31 of an authored 10).  Fallout ignored the call;
    Skyrim logs "unknown quest objective N" on every one, and these sit in
    GameMode polls.  Unknown quest or non-literal index -> never suppressed.
    """
    authored = _QUEST_OBJECTIVES.get(quest_edid.lower())
    if not authored:
        return False
    src = (index_src or '').strip()
    return src.isdigit() and int(src) not in authored


def quest_native(ctx, call):
    """`<cmd> <quest> <args...>` -- Papyrus makes the quest the receiver.

    The quest property keeps a type it already has (a TES4_<script> class
    answers these natives and its variable reads need that type).
    See: docs/commentary/script_convert.md#fnv-objective-commands
    """
    parts = ctx.arg_srcs()
    if len(parts) < 2:
        return None
    quest_edid = parts[0].strip()
    native = _QUEST_NATIVES[call.name]
    if (native != 'RegisterForSingleUpdate'
            and _unauthored_objective(quest_edid, parts[1])):
        return ctx.note(f'{call.name} {quest_edid} {parts[1].strip()} - '
                        f'{quest_edid} authors no such objective')
    prop = safe_property_name(quest_edid)
    if not typed_already(ctx.sc.property_refs, prop):
        ctx.sc.property_refs[prop] = 'Quest'
    args = ', '.join(call.arg(i) for i in range(1, len(parts)))
    return f'{prop}.{native}({args})' + _objective_mirror(ctx, call, quest_edid, parts)


def _mirror_values(name: str, flag: str, value: str) -> dict:
    """{state: Papyrus value} an objective command sets; completing also displays."""
    if name == 'setobjectivedisplayed':
        return {'Shown': value}
    return {'Done': value, **({'Shown': '1'} if flag not in ('0', '') else {})}


def _objective_mirror(ctx, call, quest_edid: str, parts: list) -> str:
    """The SetValue lines keeping this objective's condition globals in step, or ''.

    See: docs/commentary/tes5_import_conditions.md#fallout-objective-conditions
    """
    index = parts[1].strip()
    if call.name not in ('setobjectivecompleted', 'setobjectivedisplayed') or not index.isdigit():
        return ''
    globs = ctx.objective_globals.get((quest_edid.lower(), int(index)), {})
    flag = parts[2].strip() if len(parts) > 2 else '1'
    value = call.arg(2) if len(parts) > 2 else '1'
    out = ''
    for state, setting in _mirror_values(call.name, flag if flag.isdigit() else '', value).items():
        if state in globs:
            ctx.sc.property_refs.setdefault(globs[state], 'GlobalVariable')
            out += f'\n  {globs[state]}.SetValue({setting})'
    return out


def show_message(ctx, call):
    """`ShowMessage <MESG> ...` -- a buttoned MESG is a menu: Show() parks
    this thread and the pick feeds the script's GetButtonPressed poll.

    Declines (None) so the row renders a plain Show() unless the MESG is one
    of this script's planned button sites (message_menus.button_messages).
    See: docs/commentary/script_convert.md#fnv-showmessage-menus
    """
    name = authored_site(ctx.message_menus, ctx.sc.edid,
                         call.source(0).strip() if len(call) else '')
    if not name:
        return None
    mesg = safe_property_name(name)
    ctx.sc.property_refs[mesg] = 'Message'
    ctx.sc.uses_msg_buttons = True
    return f'TES4_MsgButton = TES4_ShowMsg({mesg})'


#: TES4 command name -> handler, merged into `commands.REGISTRY`.
def weapon_anim_type(ctx, call) -> str:
    """`<actor>.GetWeaponAnimType`: the Fallout animation type of the equipped weapon.

    Each type's weapons are a FormList the importer writes, so the value is
    the sum of each type times whether its list holds the weapon; no weapon
    reads 0, Hand to Hand, as in Fallout. Skyrim's own weapon types number
    differently (a converted rifle is a crossbow).
    See: docs/commentary/script_convert.md#fallout-weapon-anim-type
    """
    ref = ctx._convert_ref(call.ref, call.extends, as_receiver=True) if call.ref else 'Self'
    weapon = f'({ref} as Actor).GetEquippedWeapon()'
    for name in WEAPON_ANIM_LISTS.values():
        ctx.sc.property_refs[name] = 'FormList'
    terms = (f'{kind} * ({name}.HasForm({weapon}) as Int)' for kind, name in WEAPON_ANIM_LISTS.items())
    return '(' + ' + '.join(terms) + ')'


FALLOUT_HANDLERS = {'getfactionrelation': faction_relation,
                    'getweaponanimtype': weapon_anim_type,
                    'showmessage': show_message,
                    **{name: quest_native for name in _QUEST_NATIVES}}
