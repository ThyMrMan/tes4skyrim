"""FO3/FNV patrol-point scripts as a Papyrus script on the marker.

FO3/FNV runs a patrol point's embedded script on the actor that reaches it.
Skyrim has no event for that, so the marker watches while its cell is loaded:
the closest actor within reach whose current package is one of the patrol
packages routed through this marker (`TES4PatrolPackages`, bound by the
importer) runs the body once per arrival.

See: docs/commentary/tes5_import_package.md#patrol-points
"""

from script_convert.constants import script_prefix
from script_convert.converter import ScriptConverter
from script_convert.scro_refs import add_scro_ref, resolve_scro_aliases, scro_list
from script_convert.symbols import property_declarations

#: How close an arriving actor must be, how far away it must go to arrive again, and the watch interval.
ARRIVE_RADIUS, LEAVE_RADIUS, WATCH_SECONDS = 128.0, 256.0, 0.5

#: The marker's watch: arm on cell attach, stop on detach, run the body once per arrival.
_WATCH = f'''Package[] Property TES4PatrolPackages Auto
Actor TES4Arrived
Bool TES4Watching

Event OnCellAttach()
  TES4Watching = True
  RegisterForSingleUpdate({WATCH_SECONDS})
EndEvent

Event OnCellDetach()
  TES4Watching = False
  TES4Arrived = None
EndEvent

Event OnUpdate()
  If !TES4Watching
    Return
  EndIf
  Actor a = Game.FindClosestActorFromRef(Self, {ARRIVE_RADIUS})
  If a && a != TES4Arrived && a != Game.GetPlayer() && TES4PatrolPackages.Find(a.GetCurrentPackage()) >= 0
    TES4Arrived = a
    TES4PatrolArrived(a)
  ElseIf TES4Arrived && TES4Arrived.GetDistance(Self) > {LEAVE_RADIUS}
    TES4Arrived = None
  EndIf
  RegisterForSingleUpdate({WATCH_SECONDS})
EndEvent
'''


def patrol_script_name(formid: str) -> str:
    """The PM_ script name of the patrol marker with source FormID `formid`."""
    return f'{script_prefix("_PM__")}{formid.upper()}'


def _convert_patrol(rec: dict, xref) -> tuple:
    """(converter, body lines) of a patrol point's script, run on the arriving actor.

    The body converts as a TopicInfo fragment, whose implicit subject is
    `akSpeakerRef`; here that is the actor that arrived.
    """
    conv = ScriptConverter(xref)
    source = rec.get('Patrol.Script') or ''
    refs = scro_list(rec, 'Patrol.')
    for fid in refs:
        add_scro_ref(conv, fid, xref)
    conv.set_scro_aliases(resolve_scro_aliases(source, refs, xref))
    return conv, conv.convert_fragment(source, 'TopicInfo')


def patrol_psc(rec: dict, xref) -> str:
    """The Papyrus of one patrol marker's script."""
    conv, body = _convert_patrol(rec, xref)
    head = [f'ScriptName {patrol_script_name(rec["FormID"])} extends ObjectReference', '']
    props = property_declarations(dict(conv.sc.property_refs), {'tes4patrolpackages'})
    arrived = ['Function TES4PatrolArrived(Actor akActor)',
               '  ObjectReference akSpeakerRef = akActor'] + body + ['EndFunction', '']
    return '\n'.join(head + props + ['', _WATCH, ''] + arrived + conv.get_cell_family_helpers())


def patrol_property_refs(rec: dict, xref) -> dict:
    """{property: Papyrus type} the marker's script declares from its body."""
    return dict(_convert_patrol(rec, xref)[0].sc.property_refs)
