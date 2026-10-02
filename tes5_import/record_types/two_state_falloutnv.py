"""FO3/FNV two-state activators: an ACTI whose model has Open and Close sequences carries TES4_TwoStateActivator.

Fallout gave such an activator (a vault gear door, a wall switch, a radio) a
door's open state; Skyrim keeps none for an activator, so the static script
does, appended to any object script the ACTI already carries.

See: docs/commentary/script_convert.md#two-state-activators
"""

import os

from ..base.object_scripts import get_object_vmad, set_object_vmad
from ..base.text_reader import get_formid
from ..base.writer import pack_subrecord
from .world_falloutnv import is_fallout_source

#: The static script a two-state activator carries.
TWO_STATE_SCRIPT = 'TES4_TwoStateActivator'

#: The NIF header string-table entries (u32 length, then the name) of the two sequences.
_OPEN, _CLOSE = b'\x04\x00\x00\x00Open', b'\x05\x00\x00\x00Close'

#: Bytes of a packed subrecord's header.
_SUB_HEADER = 6

#: Upper-hex FormIDs of the ACTIs carrying TES4_TwoStateActivator, filled by attach_two_state_activators.
_TWO_STATE_BASES: set = set()


def opens_and_closes(export_dir: str, model: str) -> bool:
    """Whether the exported NIF at `model` (relative to meshes/) names both an Open and a Close sequence."""
    path = os.path.join(export_dir, 'meshes', model.replace('\\', '/').lower())
    if not model or not os.path.isfile(path):
        return False
    with open(path, 'rb') as f:
        data = f.read()
    return _OPEN in data and _CLOSE in data


def attach_two_state_activators(by_type: dict, export_dir: str) -> int:
    """Append TES4_TwoStateActivator to every FO3/FNV ACTI whose model opens and closes; returns how many.

    script_convert.pipeline is imported here: it imports the importer's
    dialogue package, a cycle at load.
    """
    from script_convert.pipeline import append_vmad_object_script
    _TWO_STATE_BASES.clear()
    if not is_fallout_source():
        return 0
    seen = {}
    for rec in by_type.get('ACTI', ()):
        model = rec.get('Model.MODL') or ''
        if model not in seen:
            seen[model] = opens_and_closes(export_dir, model)
        if seen[model]:
            fid = get_formid(rec, 'FormID')
            vmad = append_vmad_object_script(get_object_vmad(fid)[_SUB_HEADER:], TWO_STATE_SCRIPT)
            set_object_vmad(fid, pack_subrecord('VMAD', vmad))
            _TWO_STATE_BASES.add(rec['FormID'].upper())
    return len(_TWO_STATE_BASES)


def open_by_default_vmad(rec: dict) -> bytes:
    """A placed two-state activator's VMAD setting TES4OpenByDefault when it is placed open, else b''.

    script_convert.pipeline is imported here, as above: a cycle at load.
    See: docs/commentary/script_convert.md#two-state-activators
    """
    from script_convert.pipeline import build_vmad_object_script
    if rec.get('ONAM.OpenByDefault') != '1' or (rec.get('NAME') or '').upper() not in _TWO_STATE_BASES:
        return b''
    return pack_subrecord('VMAD', build_vmad_object_script(
        TWO_STATE_SCRIPT, value_props={'TES4OpenByDefault': ('bool', True)}))
