"""
Actor-related record types: NPC_, CREA, CONT, FACT, RACE, CLAS, EYES, HAIR,
BSGN, SKIL, CSTY, IDLE.

Pure TES4 data dump - no transformations.
"""

import struct

from ..tes4_reader import Record, get_all_subrecords, get_formid_str, get_subrecord
from .common import (
    emit_conditions,
    emit_float,
    escape_value,
    emit_formid,
    emit_icon,
    emit_model,
    emit_script,
    emit_string,
    emit_u8,
)


def _emit_items(lines: list, rec: Record):
    """Emit CNTO item entries."""
    cntos = get_all_subrecords(rec, "CNTO")
    lines.append(f"ItemCount={len(cntos)}")
    for i, cnto in enumerate(cntos):
        if len(cnto.data) >= 8:
            fid = struct.unpack_from("<I", cnto.data, 0)[0]
            count = struct.unpack_from("<i", cnto.data, 4)[0]
            lines.append(f"Item[{i}].FormID={get_formid_str(fid)}")
            lines.append(f"Item[{i}].Count={count}")


def _emit_factions(lines: list, rec: Record):
    """Emit SNAM faction membership entries (FormID + u8 rank + 3 unused)."""
    snams = get_all_subrecords(rec, "SNAM")
    lines.append(f"FactionCount={len(snams)}")
    for i, snam in enumerate(snams):
        if len(snam.data) >= 5:
            fid = struct.unpack_from("<I", snam.data, 0)[0]
            rank = struct.unpack_from("<b", snam.data, 4)[0]
            lines.append(f"Faction[{i}].FormID={get_formid_str(fid)}")
            lines.append(f"Faction[{i}].Rank={rank}")


def _emit_aidt(lines: list, rec: Record):
    """Emit AIDT AI data."""
    aidt = get_subrecord(rec, "AIDT")
    if aidt and len(aidt.data) >= 12:
        d = aidt.data
        lines.append(f"AIDT.Aggression={d[0]}")
        lines.append(f"AIDT.Confidence={d[1]}")
        lines.append(f"AIDT.EnergyLevel={d[2]}")
        lines.append(f"AIDT.Responsibility={d[3]}")
        lines.append(f"AIDT.Services={struct.unpack_from('<I', d, 4)[0]}")
        lines.append(f"AIDT.Teaches={d[8]}")
        lines.append(f"AIDT.MaxTraining={d[9]}")


def _emit_ai_packages(lines: list, rec: Record):
    """Emit PKID AI package references."""
    pkids = get_all_subrecords(rec, "PKID")
    lines.append(f"AIPackageCount={len(pkids)}")
    for i, pkid in enumerate(pkids):
        if len(pkid.data) >= 4:
            lines.append(f"AIPackage[{i}]={get_formid_str(struct.unpack_from('<I', pkid.data, 0)[0])}")


def _emit_spells(lines: list, rec: Record):
    """Emit SPLO spell references."""
    splos = get_all_subrecords(rec, "SPLO")
    if splos:
        lines.append(f"SpellCount={len(splos)}")
        for i, splo in enumerate(splos):
            if len(splo.data) >= 4:
                lines.append(f"Spell[{i}]={get_formid_str(struct.unpack_from('<I', splo.data, 0)[0])}")


def _emit_appearance(lines: list, rec) -> None:
    """Hair, eyes, combat style and the three FaceGen PCA blobs (raw hex)."""
    emit_formid(lines, "HNAM.Hair", get_subrecord(rec, "HNAM"))
    emit_float(lines, "LNAM.HairLength", get_subrecord(rec, "LNAM"))
    emit_formid(lines, "ENAM.Eyes", get_subrecord(rec, "ENAM"))
    hclr = get_subrecord(rec, "HCLR")
    if hclr and len(hclr.data) >= 4:
        lines.append(f"HCLR.R={hclr.data[0]}")
        lines.append(f"HCLR.G={hclr.data[1]}")
        lines.append(f"HCLR.B={hclr.data[2]}")
    emit_formid(lines, "ZNAM.CombatStyle", get_subrecord(rec, "ZNAM"))
    for sig in ("FGGS", "FGGA", "FGTS"):
        sub = get_subrecord(rec, sig)
        if sub:
            lines.append(f"{sig}={sub.data.hex()}")


def export_NPC_(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_model(lines, "Model", rec)

    # ACBS - base stats
    acbs = get_subrecord(rec, "ACBS")
    if acbs and len(acbs.data) >= 16:
        d = acbs.data
        lines.append(f"ACBS.Flags={struct.unpack_from('<I', d, 0)[0]}")
        lines.append(f"ACBS.SpellPoints={struct.unpack_from('<H', d, 4)[0]}")
        lines.append(f"ACBS.Fatigue={struct.unpack_from('<H', d, 6)[0]}")
        lines.append(f"ACBS.BarterGold={struct.unpack_from('<H', d, 8)[0]}")
        lines.append(f"ACBS.Level={struct.unpack_from('<h', d, 10)[0]}")
        lines.append(f"ACBS.CalcMin={struct.unpack_from('<H', d, 12)[0]}")
        lines.append(f"ACBS.CalcMax={struct.unpack_from('<H', d, 14)[0]}")

    _emit_factions(lines, rec)
    emit_formid(lines, "INAM.DeathItem", get_subrecord(rec, "INAM"))
    emit_formid(lines, "RNAM.Race", get_subrecord(rec, "RNAM"))
    emit_formid(lines, "VTCK.Voice", get_subrecord(rec, "VTCK"))
    _emit_spells(lines, rec)
    emit_script(lines, rec)
    _emit_items(lines, rec)
    _emit_aidt(lines, rec)
    _emit_ai_packages(lines, rec)
    emit_formid(lines, "CNAM.Class", get_subrecord(rec, "CNAM"))
    _emit_appearance(lines, rec)

    # DATA - 33 bytes: 21 skills + health(u32) + 8 attributes
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 33:
        d = data.data
        skill_names = [
            "Armorer", "Athletics", "Blade", "Block", "Blunt",
            "HandToHand", "HeavyArmor", "Alchemy", "Alteration",
            "Conjuration", "Destruction", "Illusion", "Mysticism",
            "Restoration", "Acrobatics", "LightArmor", "Marksman",
            "Mercantile", "Security", "Sneak", "Speechcraft"
        ]
        for i, name in enumerate(skill_names):
            lines.append(f"DATA.{name}={d[i]}")
        lines.append(f"DATA.Health={struct.unpack_from('<I', d, 21)[0]}")
        attr_names = ["Strength", "Intelligence", "Willpower", "Agility",
                      "Speed", "Endurance", "Personality", "Luck"]
        for i, name in enumerate(attr_names):
            lines.append(f"DATA.{name}={d[25 + i]}")

    return lines


def export_CREA(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_model(lines, "Model", rec)
    _emit_items(lines, rec)
    _emit_spells(lines, rec)

    # ACBS
    acbs = get_subrecord(rec, "ACBS")
    if acbs and len(acbs.data) >= 16:
        d = acbs.data
        lines.append(f"ACBS.Flags={struct.unpack_from('<I', d, 0)[0]}")
        lines.append(f"ACBS.SpellPoints={struct.unpack_from('<H', d, 4)[0]}")
        lines.append(f"ACBS.Fatigue={struct.unpack_from('<H', d, 6)[0]}")
        lines.append(f"ACBS.BarterGold={struct.unpack_from('<H', d, 8)[0]}")
        lines.append(f"ACBS.Level={struct.unpack_from('<h', d, 10)[0]}")
        lines.append(f"ACBS.CalcMin={struct.unpack_from('<H', d, 12)[0]}")
        lines.append(f"ACBS.CalcMax={struct.unpack_from('<H', d, 14)[0]}")

    _emit_factions(lines, rec)
    emit_formid(lines, "INAM.DeathItem", get_subrecord(rec, "INAM"))
    emit_script(lines, rec)
    _emit_aidt(lines, rec)
    _emit_ai_packages(lines, rec)

    # DATA - Creature stats (20 bytes)
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 20:
        d = data.data
        lines.append(f"DATA.Type={d[0]}")
        lines.append(f"DATA.CombatSkill={d[1]}")
        lines.append(f"DATA.MagicSkill={d[2]}")
        lines.append(f"DATA.StealthSkill={d[3]}")
        lines.append(f"DATA.Soul={struct.unpack_from('<H', d, 4)[0]}")
        lines.append(f"DATA.Health={struct.unpack_from('<H', d, 6)[0]}")
        lines.append(f"DATA.AttackDamage={struct.unpack_from('<H', d, 10)[0]}")
        lines.append(f"DATA.Strength={d[12]}")
        lines.append(f"DATA.Intelligence={d[13]}")
        lines.append(f"DATA.Willpower={d[14]}")
        lines.append(f"DATA.Agility={d[15]}")
        lines.append(f"DATA.Speed={d[16]}")
        lines.append(f"DATA.Endurance={d[17]}")
        lines.append(f"DATA.Personality={d[18]}")
        lines.append(f"DATA.Luck={d[19]}")

    emit_u8(lines, "RNAM.AttackReach", get_subrecord(rec, "RNAM"))
    emit_formid(lines, "ZNAM.CombatStyle", get_subrecord(rec, "ZNAM"))
    emit_float(lines, "TNAM.TurningSpeed", get_subrecord(rec, "TNAM"))
    emit_float(lines, "BNAM.BaseScale", get_subrecord(rec, "BNAM"))
    emit_float(lines, "WNAM.FootWeight", get_subrecord(rec, "WNAM"))
    emit_formid(lines, "CSCR.InheritSound", get_subrecord(rec, "CSCR"))

    # Creature models
    nift = get_subrecord(rec, "NIFT")
    if nift:
        lines.append(f"NIFT.Size={len(nift.data)}")

    # NIFZ - body part model file list (null-separated string block)
    nifz = get_subrecord(rec, "NIFZ")
    if nifz:
        parts = [p.decode("cp1252", "replace")
                 for p in nifz.data.split(b"\x00") if p]
        lines.append(f"NIFZCount={len(parts)}")
        for i, p in enumerate(parts):
            lines.append(f"NIFZ[{i}]={escape_value(p)}")

    # KFFZ - animation .kf file list (null-separated string block)
    kffz = get_subrecord(rec, "KFFZ")
    if kffz:
        parts = [p.decode("cp1252", "replace")
                 for p in kffz.data.split(b"\x00") if p]
        lines.append(f"KFFZCount={len(parts)}")
        for i, p in enumerate(parts):
            lines.append(f"KFFZ[{i}]={escape_value(p)}")

    # Sound entries: each CSDT (type) is followed IN STREAM ORDER by its
    # CSDI/CSDC (sound + chance) pairs — a type may list several sounds, so
    # positional zipping of the flat CSDT/CSDI lists mispairs them. CSDC is
    # the authored play chance (wbSoundTypeSounds, shared TES4/TES5 struct).
    entries = []                    # (type, [[sound_fid, chance], ...])
    cur = pending = None
    for sub in rec.subrecords:
        if sub.type == "CSDT" and len(sub.data) >= 4:
            cur = (struct.unpack_from('<I', sub.data, 0)[0], [])
            entries.append(cur)
            pending = None
        elif sub.type == "CSDI" and cur is not None and len(sub.data) >= 4:
            pending = [struct.unpack_from('<I', sub.data, 0)[0], None]
            cur[1].append(pending)
        elif sub.type == "CSDC" and pending is not None and sub.data:
            pending[1] = sub.data[0]
            pending = None
    if entries:
        lines.append(f"SoundTypeCount={len(entries)}")
        for i, (stype, sounds) in enumerate(entries):
            lines.append(f"SoundType[{i}].Type={stype}")
            for j, (fid, chance) in enumerate(sounds):
                # first pair keeps the historical un-indexed names
                key = (f"SoundType[{i}].Sound" if j == 0
                       else f"SoundType[{i}].Sound[{j}]")
                lines.append(f"{key}={get_formid_str(fid)}")
                if chance is not None:
                    lines.append(f"{key}.Chance={chance}")

    return lines


def export_CONT(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_model(lines, "Model", rec)
    emit_script(lines, rec)
    _emit_items(lines, rec)
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 5:
        lines.append(f"DATA.Flags={data.data[0]}")
        lines.append(f"DATA.Weight={struct.unpack_from('<f', data.data, 1)[0]}")
    emit_formid(lines, "SNAM.OpenSound", get_subrecord(rec, "SNAM"))
    emit_formid(lines, "QNAM.CloseSound", get_subrecord(rec, "QNAM"))
    return lines


def export_FACT(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))

    _emit_relations(lines, rec)

    # TES4 FACT DATA is a single U8 (xEdit wbDefinitionsTES4: Hidden from
    # Player / Evil / Special Combat) — measured at exactly 1 byte in all 204
    # Nehrim.esm factions.  The old `>= 4` guard with a U32 unpack therefore
    # never fired, silently dropping the flags for every faction in every
    # plugin.
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 1:
        lines.append(f"DATA.Flags={data.data[0]}")
    if data and len(data.data) >= 2:
        lines.append(f"DATA.Flags2={data.data[1]}")
    emit_formid(lines, "WMI1.Reputation", get_subrecord(rec, "WMI1"))

    # CNAM - Crime Gold Multiplier
    emit_float(lines, "CNAM.CrimeGold", get_subrecord(rec, "CNAM"))

    # Ranks (RNAM subrecords)
    rnams = get_all_subrecords(rec, "RNAM")
    if rnams:
        lines.append(f"RankCount={len(rnams)}")
        for i, rnam in enumerate(rnams):
            if len(rnam.data) >= 4:
                lines.append(f"Rank[{i}].Index={struct.unpack_from('<I', rnam.data, 0)[0]}")

    return lines


def _emit_relations(lines: list, rec: Record):
    """XNAM relations: faction and disposition, and FO3/FNV's authored group combat reaction.

    See: docs/commentary/tes5_import_actors.md#faction-relations
    """
    xnams = get_all_subrecords(rec, "XNAM")
    if not xnams:
        return
    lines.append(f"RelationCount={len(xnams)}")
    for i, xnam in enumerate(xnams):
        if len(xnam.data) < 8:
            continue
        fid, disp = struct.unpack_from("<Ii", xnam.data, 0)
        lines.append(f"Relation[{i}].Faction={get_formid_str(fid)}")
        lines.append(f"Relation[{i}].Disposition={disp}")
        if len(xnam.data) >= 12:
            lines.append(f"Relation[{i}].CombatReaction={struct.unpack_from('<I', xnam.data, 8)[0]}")


def export_RACE(rec: Record) -> list:
    """A RACE: identity, spells, relations, stats, defaults, attributes, hair and eyes, parts and FaceGen."""
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_string(lines, "DESC", get_subrecord(rec, "DESC"))
    _emit_spells(lines, rec)
    _emit_relations(lines, rec)
    _emit_race_data(lines, rec)
    _emit_race_defaults(lines, rec)
    _emit_race_attributes(lines, rec)
    _emit_formid_list(lines, rec, "HNAM", "Hair")
    _emit_formid_list(lines, rec, "ENAM", "Eyes")
    _emit_race_parts(lines, rec)
    _emit_race_facegen(lines, rec)
    return lines


def _emit_race_data(lines: list, rec: Record):
    """DATA: seven skill boosts (skill, bonus), heights, weights and flags."""
    data = get_subrecord(rec, "DATA")
    if not data or len(data.data) < 36:
        return
    d = data.data
    for i in range(7):
        lines.append(f"DATA.SkillBoost[{i}].Skill={d[i*2]}")
        lines.append(f"DATA.SkillBoost[{i}].Bonus={d[i*2+1]}")
    for key, offset in (("MaleHeight", 16), ("FemaleHeight", 20), ("MaleWeight", 24), ("FemaleWeight", 28)):
        lines.append(f"DATA.{key}={struct.unpack_from('<f', d, offset)[0]}")
    lines.append(f"DATA.Flags={struct.unpack_from('<I', d, 32)[0]}")


def _emit_race_defaults(lines: list, rec: Record):
    """VNAM voices and DNAM hair (male, female), CNAM hair color, PNAM/UNAM FaceGen clamps."""
    for sig, key in (("VNAM", "Voice"), ("DNAM", "Hair")):
        sub = get_subrecord(rec, sig)
        if sub and len(sub.data) >= 8:
            male, female = struct.unpack_from('<II', sub.data, 0)
            lines.append(f"{sig}.Male{key}={get_formid_str(male)}")
            lines.append(f"{sig}.Female{key}={get_formid_str(female)}")
    cnam = get_subrecord(rec, "CNAM")
    if cnam and len(cnam.data) >= 1:
        lines.append(f"CNAM.DefaultHairColor={cnam.data[0]}")
    for sig, key in (("PNAM", "FaceGenMainClamp"), ("UNAM", "FaceGenFaceClamp")):
        sub = get_subrecord(rec, sig)
        if sub and len(sub.data) >= 4:
            lines.append(f"{sig}.{key}={struct.unpack_from('<f', sub.data, 0)[0]}")


#: A TES4 race's ATTR bytes: male then female, in this order.
_RACE_ATTRIBUTES = ("Strength", "Intelligence", "Willpower", "Agility",
                    "Speed", "Endurance", "Personality", "Luck")


def _emit_race_attributes(lines: list, rec: Record):
    """ATTR: eight male then eight female attribute bytes."""
    attr = get_subrecord(rec, "ATTR")
    if not attr or len(attr.data) < 16:
        return
    for sex, base in (("Male", 0), ("Female", 8)):
        for i, name in enumerate(_RACE_ATTRIBUTES):
            lines.append(f"ATTR.{sex}.{name}={attr.data[base + i]}")


def _emit_formid_list(lines: list, rec: Record, sig: str, key: str):
    """A packed FormID list subrecord (HNAM hair, ENAM eyes) as <key>Count and <key>[i]."""
    for sub in get_all_subrecords(rec, sig):
        count = len(sub.data) // 4
        if count > 0:
            lines.append(f"{key}Count={count}")
            for i in range(count):
                lines.append(f"{key}[{i}]={get_formid_str(struct.unpack_from('<I', sub.data, i*4)[0])}")


def _emit_race_facegen(lines: list, rec: Record):
    """FGGS/FGGA/FGTS: the race-level FaceGen vectors, which carry a shared-texture race's skin tone.

    See: docs/commentary/asset_convert_facegen.md#where-color-actually-lives
    """
    for sig in ("FGGS", "FGGA", "FGTS"):
        sub = get_subrecord(rec, sig)
        if sub and sub.data:
            lines.append(f"{sig}={sub.data.hex()}")


def _emit_race_parts(lines: list, rec: Record):
    """Emit the RACE face-part and body-part model/texture lists.

    The layout is positional, not keyed: NAM0 opens the face-part block and
    NAM1 the body-part block, the latter split into MNAM (male) and FNAM
    (female) sections.  Within a block each part is INDX followed by its
    MODL/ICON, so the subrecords must be walked in order.
    """
    section = None   # 'face' | 'male' | 'female'
    index = None
    for sub in rec.subrecords:
        t = sub.type
        if t == "NAM0":
            section, index = "face", None
            continue
        if t == "NAM1":
            section, index = None, None
            continue
        if t == "MNAM":
            section, index = "male", None
            continue
        if t == "FNAM":
            section, index = "female", None
            continue
        if section is None:
            continue
        if t == "INDX":
            index = struct.unpack_from("<I", sub.data, 0)[0] if len(sub.data) >= 4 else None
            continue
        if index is None:
            continue
        if t in ("MODL", "ICON"):
            val = sub.data.rstrip(b"\x00").decode("cp1252", errors="replace")
            if val:
                key = "Model" if t == "MODL" else "Texture"
                lines.append(f"{section.capitalize()}Part[{index}].{key}"
                             f"={escape_value(val)}")


def export_CLAS(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_string(lines, "DESC", get_subrecord(rec, "DESC"))
    emit_icon(lines, "ICON", rec)
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 50:
        d = data.data
        lines.append(f"DATA.PrimaryAttribute1={struct.unpack_from('<I', d, 0)[0]}")
        lines.append(f"DATA.PrimaryAttribute2={struct.unpack_from('<I', d, 4)[0]}")
        lines.append(f"DATA.Specialization={struct.unpack_from('<I', d, 8)[0]}")
        for i in range(7):
            lines.append(f"DATA.MajorSkill[{i}]={struct.unpack_from('<I', d, 12 + i*4)[0]}")
        lines.append(f"DATA.Flags={struct.unpack_from('<I', d, 40)[0]}")
        lines.append(f"DATA.Services={struct.unpack_from('<I', d, 44)[0]}")
        lines.append(f"DATA.Teaches={d[48]}")
        lines.append(f"DATA.MaxTraining={d[49]}")
    return lines


def export_EYES(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_icon(lines, "ICON", rec)
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 1:
        lines.append(f"DATA.Flags={data.data[0]}")
    return lines


def export_HAIR(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_model(lines, "Model", rec)
    emit_icon(lines, "ICON", rec)
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 1:
        lines.append(f"DATA.Flags={data.data[0]}")
    return lines


def export_BSGN(rec: Record) -> list:
    """Birthsign."""
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_string(lines, "FULL", get_subrecord(rec, "FULL"))
    emit_icon(lines, "ICON", rec)
    emit_string(lines, "DESC", get_subrecord(rec, "DESC"))
    _emit_spells(lines, rec)
    return lines


def export_SKIL(rec: Record) -> list:
    """Skill: INDX is the skill's actor value; DATA is action, attribute,
    specialization and two use values (xEdit `wbDefinitionsTES4` SKIL)."""
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    index = get_subrecord(rec, "INDX")
    if index and len(index.data) >= 4:
        lines.append(f"INDX.Skill={struct.unpack_from('<i', index.data)[0]}")
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 20:
        action, attribute, spec, use1, use2 = struct.unpack_from('<iII2f', data.data)
        lines.append(f"DATA.Action={action}")
        lines.append(f"DATA.Attribute={attribute}")
        lines.append(f"DATA.Specialization={spec}")
        lines.append(f"DATA.UseValue1={use1}")
        lines.append(f"DATA.UseValue2={use2}")
    emit_string(lines, "DESC", get_subrecord(rec, "DESC"))
    return lines


def export_CSTY(rec: Record) -> list:
    """Combat Style."""
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    cstd = get_subrecord(rec, "CSTD")
    if cstd and len(cstd.data) >= 112:
        d = cstd.data
        lines.append(f"CSTD.DodgeChance={d[0]}")
        lines.append(f"CSTD.DodgeLRChance={d[1]}")
        lines.append(f"CSTD.DodgeFWTimer={struct.unpack_from('<f', d, 4)[0]}")
        lines.append(f"CSTD.DodgeBackTimer={struct.unpack_from('<f', d, 8)[0]}")
        lines.append(f"CSTD.IdleTimer={struct.unpack_from('<f', d, 12)[0]}")
        lines.append(f"CSTD.BlockChance={d[16]}")
        lines.append(f"CSTD.AttackChance={d[17]}")
        lines.append(f"CSTD.StaggerRecoilTimer={struct.unpack_from('<f', d, 20)[0]}")
        lines.append(f"CSTD.AcrobaticDodge={struct.unpack_from('<f', d, 24)[0]}")
        lines.append(f"CSTD.RangeMultOptimal={struct.unpack_from('<f', d, 28)[0]}")
        lines.append(f"CSTD.RangeMultMax={struct.unpack_from('<f', d, 32)[0]}")
        lines.append(f"CSTD.SwitchDist={struct.unpack_from('<f', d, 36)[0]}")
        lines.append(f"CSTD.BuffStandoff={struct.unpack_from('<f', d, 40)[0]}")
        lines.append(f"CSTD.GroupStandoff={struct.unpack_from('<f', d, 48)[0]}")
        lines.append(f"CSTD.RushAttackChance={d[56]}")
        lines.append(f"CSTD.RushAttackDist={struct.unpack_from('<f', d, 60)[0]}")
    csad = get_subrecord(rec, "CSAD")
    if csad and len(csad.data) >= 20:
        d = csad.data
        lines.append(f"CSAD.DodgeFatigueModMul={struct.unpack_from('<f', d, 0)[0]}")
        lines.append(f"CSAD.DodgeFatigueModBase={struct.unpack_from('<f', d, 4)[0]}")
        lines.append(f"CSAD.EncMultiplier={struct.unpack_from('<f', d, 8)[0]}")
        lines.append(f"CSAD.EncBase={struct.unpack_from('<f', d, 12)[0]}")
        lines.append(f"CSAD.DodgeUnder={struct.unpack_from('<f', d, 16)[0]}")
    return lines


def export_IDLE(rec: Record) -> list:
    lines = []
    emit_string(lines, "EditorID", get_subrecord(rec, "EDID"))
    emit_model(lines, "Model", rec)
    emit_conditions(lines, rec)
    anam = get_subrecord(rec, "ANAM")
    if anam and len(anam.data) >= 4:
        lines.append(f"ANAM.AnimGroupSection={struct.unpack_from('<H', anam.data, 0)[0]}")
    data = get_subrecord(rec, "DATA")
    if data and len(data.data) >= 8:
        lines.append(f"DATA.IdleParent={get_formid_str(struct.unpack_from('<I', data.data, 0)[0])}")
        lines.append(f"DATA.IdlePrev={get_formid_str(struct.unpack_from('<I', data.data, 4)[0])}")
    return lines
