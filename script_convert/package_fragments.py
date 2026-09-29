"""FO3/FNV package scripts written as a Skyrim package's fragment script.

Which sections exist is `tes5_import.packages.scripts_falloutnv`, the contract
the importer's VMAD reads too; this writes the `PF_` script those name, and
hands the importer the properties it declares.

See: docs/commentary/script_convert.md#package-fragments
"""

from script_convert.constants import script_prefix
from script_convert.converter import ScriptConverter
from script_convert.scro_refs import add_scro_ref, resolve_scro_aliases, scro_list
from script_convert.symbols import property_declarations
from tes5_import.packages.scripts_falloutnv import folds_change, package_sections, section_source


def package_fragment_name(formid: str) -> str:
    """The PF_ script name of the package with source FormID `formid`."""
    return f'{script_prefix("_PF__")}{formid.upper()}'


def _convert_package(rec: dict, xref) -> tuple:
    """(converter, fragment function lines) for one package's sections.

    Each body converts as a TopicInfo fragment, whose implicit subject is
    `akSpeakerRef`; here that is the actor running the package.
    """
    conv = ScriptConverter(xref)
    bodies = []
    for i, (section, _flag) in enumerate(package_sections(rec)):
        source = section_source(rec, section, xref.formid_to_edid)
        refs = scro_list(rec, f'{section}.')
        if section == 'OnEnd' and folds_change(rec):
            refs += scro_list(rec, 'OnChange.')
        for fid in refs:
            add_scro_ref(conv, fid, xref)
        conv.set_scro_aliases(resolve_scro_aliases(source, refs, xref))
        bodies += [f'Function Fragment_{i}(Actor akActor)',
                   '  ObjectReference akSpeakerRef = akActor']
        bodies += conv.convert_fragment(source, 'TopicInfo') + ['EndFunction', '']
    return conv, bodies


def package_psc(rec: dict, xref) -> str:
    """The Papyrus of one package's fragment script, one Fragment_N per section."""
    conv, bodies = _convert_package(rec, xref)
    head = [f'ScriptName {package_fragment_name(rec["FormID"])} extends Package Hidden', '']
    props = property_declarations(dict(conv.sc.property_refs), set())
    return '\n'.join(head + props + [''] + bodies + conv.get_cell_family_helpers())


def package_property_refs(rec: dict, xref) -> dict:
    """{property: Papyrus type} the package's fragment script declares."""
    return dict(_convert_package(rec, xref)[0].sc.property_refs)
