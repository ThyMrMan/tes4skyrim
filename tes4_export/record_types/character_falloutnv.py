"""
FO3/FNV character records: actor values (AVIF), perks (PERK), reputations
(REPU), and the Fallout layout of a class's DATA and ATTR.

A pure dump: every field as the record stores it, conditions and entry-point
data as hex for the importer to read.

See: docs/commentary/tes4_export_falloutnv.md#character-records
"""

import struct

from ..tes4_reader import Record, get_formid_str, get_string, get_subrecord
from .common import emit_float, emit_icon, emit_string, escape_value

#: A class's ATTR bytes, in the order Fallout stores its S.P.E.C.I.A.L.
SPECIAL_NAMES = ("Strength", "Perception", "Endurance", "Charisma",
                 "Intelligence", "Agility", "Luck")

#: PRKE's first byte: what kind of effect follows.
PERK_EFFECT_KINDS = {0: "QuestStage", 1: "Ability", 2: "EntryPoint"}

#: PERK DATA's fields, in order; FO3 plugins may stop before Hidden.
_PERK_DATA_FIELDS = ("Trait", "MinLevel", "Ranks", "Playable", "Hidden")

#: A Fallout CLAS DATA: four tag skills, flags, services, teaches, max training.
_CLAS_DATA_SIZE = 26


def export_ACTORVALUE(rec: Record) -> list:
    """An AVIF: the name, description and short name of one actor value."""
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_string(lines, "DESC", get_subrecord(rec, "DESC"))
    emit_icon(lines, "ICON", rec)
    emit_string(lines, "ANAM", get_subrecord(rec, "ANAM"))
    return lines


def export_REPUTATION(rec: Record) -> list:
    """A REPU: a New Vegas faction reputation and its starting value."""
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_icon(lines, "ICON", rec)
    emit_float(lines, "DATA.Value", get_subrecord(rec, "DATA"))
    return lines


def emit_class_deltas(lines: list, rec: Record):
    """A Fallout CLAS's tag skills, flags, services and S.P.E.C.I.A.L., which the TES4 layout misses."""
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= _CLAS_DATA_SIZE:
        d = data.data
        for i in range(4):
            lines.append(f"DATA.TagSkill[{i}]={struct.unpack_from('<i', d, i * 4)[0]}")
        flags, services = struct.unpack_from("<II", d, 16)
        lines.append(f"DATA.Flags={flags}")
        lines.append(f"DATA.Services={services}")
        lines.append(f"DATA.Teaches={struct.unpack_from('<b', d, 24)[0]}")
        lines.append(f"DATA.MaxTraining={d[25]}")
    attr = get_subrecord(rec, "ATTR")
    if attr:
        for name, value in zip(SPECIAL_NAMES, attr.data):
            lines.append(f"ATTR.{name}={value}")


def _effect_data(lines: list, pfx: str, kind: int, d: bytes):
    """One perk effect's DATA, by the kind its PRKE declared."""
    if kind == 0 and len(d) >= 6:
        lines.append(f"{pfx}.Quest={get_formid_str(struct.unpack_from('<I', d, 0)[0])}")
        lines.append(f"{pfx}.Stage={struct.unpack_from('<H', d, 4)[0]}")
    elif kind == 1 and len(d) >= 4:
        lines.append(f"{pfx}.Ability={get_formid_str(struct.unpack_from('<I', d, 0)[0])}")
    elif kind == 2 and len(d) >= 3:
        lines.append(f"{pfx}.EntryPoint={d[0]}")
        lines.append(f"{pfx}.Function={d[1]}")
        lines.append(f"{pfx}.ConditionTabs={d[2]}")


#: An entry point's value subrecords -> (export key, reader): its type, data, button label, script flags and source.
_VALUE_FIELDS = {
    "EPFT": ("ValueType", lambda sub: sub.data[0]),
    "EPFD": ("Value", lambda sub: sub.data.hex()),
    "EPF2": ("ButtonLabel", get_string),
    "EPF3": ("ScriptFlags", lambda sub: struct.unpack_from("<H", sub.data, 0)[0]),
    "SCTX": ("ScriptText", lambda sub: escape_value(get_string(sub))),
}


class _PerkWriter:
    """Walks a PERK's subrecords in order: its requirements, DATA, then each effect."""

    def __init__(self, lines: list):
        """Appends to `lines`; no effect or tab is open yet."""
        self.lines = lines
        self.requirements = 0
        self.effect = -1
        self.kind = None
        self.tab = -1
        self.tab_conditions = 0

    def _pfx(self) -> str:
        """The current effect's key prefix."""
        return f"Effect[{self.effect}]"

    def data(self, d: bytes):
        """The perk's own DATA before any effect, else the current effect's."""
        if self.effect < 0:
            for name, value in zip(_PERK_DATA_FIELDS, d):
                self.lines.append(f"DATA.{name}={value}")
        else:
            _effect_data(self.lines, self._pfx(), self.kind, d)

    def header(self, d: bytes):
        """A PRKE: a new effect of this kind, rank and priority."""
        self.effect += 1
        self.kind, self.tab = d[0], -1
        pfx = self._pfx()
        self.lines.append(f"{pfx}.Type={PERK_EFFECT_KINDS.get(d[0], d[0])}")
        self.lines.append(f"{pfx}.Rank={d[1]}")
        self.lines.append(f"{pfx}.Priority={d[2]}")

    def condition(self, d: bytes):
        """A CTDA: the perk's requirement before any effect, else the open tab's."""
        if self.effect < 0:
            self.lines.append(f"Condition[{self.requirements}].Raw={d.hex()}")
            self.requirements += 1
        else:
            self.lines.append(f"{self._pfx()}.Tab[{self.tab}].Condition[{self.tab_conditions}].Raw={d.hex()}")
            self.tab_conditions += 1

    def run_on(self, d: bytes):
        """A PRKC: a new condition tab, run on the subject its index names."""
        self.tab += 1
        self.tab_conditions = 0
        self.lines.append(f"{self._pfx()}.Tab[{self.tab}].RunOn={struct.unpack_from('<b', d, 0)[0]}")

    def function_value(self, sub):
        """One of the current effect's _VALUE_FIELDS."""
        key, read = _VALUE_FIELDS[sub.type]
        self.lines.append(f"{self._pfx()}.{key}={read(sub)}")


def export_PERK(rec: Record) -> list:
    """A PERK: identity, requirements, DATA, and every effect with its conditions and value.

    See: docs/commentary/tes4_export_falloutnv.md#character-records
    """
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_string(lines, "DESC", get_subrecord(rec, "DESC"))
    emit_icon(lines, "ICON", rec)
    writer = _PerkWriter(lines)
    handlers = {"DATA": lambda s: writer.data(s.data), "PRKE": lambda s: writer.header(s.data),
                "CTDA": lambda s: writer.condition(s.data), "PRKC": lambda s: writer.run_on(s.data)}
    for sub in rec.subrecords:
        if sub.type in handlers:
            handlers[sub.type](sub)
        elif sub.type in _VALUE_FIELDS and writer.effect >= 0:
            writer.function_value(sub)
    lines.append(f"EffectCount={writer.effect + 1}")
    return lines


#: FO3/FNV character types Oblivion lacks -> their exporter.
CHARACTER_EXPORTERS = {
    "AVIF": export_ACTORVALUE,
    "PERK": export_PERK,
    "REPU": export_REPUTATION,
}
