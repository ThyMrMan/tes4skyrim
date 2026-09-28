"""The VMAD binding a FO3/FNV package to its PF_ fragment script.

See: docs/commentary/script_convert.md#package-fragments
"""

from ..base.owned_records import WELL_KNOWN_PROPERTIES
from ..base.text_reader import get_str
from ..base.writer import pack_subrecord
from .scripts_falloutnv import package_flags


def package_vmad(rec: dict, xref) -> bytes:
    """A PACK's VMAD naming one fragment per section it runs, or b'' for none.

    The properties are the ones the PF_ script declares, from the same
    conversion. script_convert is imported here, not at module scope: its
    converter imports this package's sibling `tes5_import.dialogue`, a cycle.
    """
    flags = package_flags(rec)
    if not flags or xref is None:
        return b''
    from script_convert.package_fragments import package_fragment_name, package_property_refs
    from script_convert.pipeline import build_vmad_package_fragment
    from ..dialogue.converter import bind_script_properties
    props = bind_script_properties(package_property_refs(rec, xref), xref,
                                   WELL_KNOWN_PROPERTIES)
    return pack_subrecord('VMAD', build_vmad_package_fragment(
        package_fragment_name(get_str(rec, 'FormID')), object_props=props, flags=flags))
