"""
Per-record-type tests for the TES4 export tool.

Tests parse actual Oblivion.esm records and validate the export output
for correctness, field presence, and data integrity.

Usage:
    python -m pytest tes4_export/tests/test_export.py -v
    python -m pytest tes4_export/tests/test_export.py -v -k "test_STAT"
    python -m tes4_export/tests/test_export.py   (standalone)
"""

import os
import struct
import unittest

# Determine Oblivion.esm path
OBLIVION_ESM = None
_candidates = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Oblivion\Data\Oblivion.esm",
    r"C:\Program Files\Steam\steamapps\common\Oblivion\Data\Oblivion.esm",
]
for p in _candidates:
    if os.path.isfile(p):
        OBLIVION_ESM = p
        break

# Lazy-loaded parsed records cache
_cache = {}


def get_records():
    """Parse Oblivion.esm once and cache result."""
    if "records" not in _cache:
        from tes4_export.tes4_reader import read_file
        header, records = read_file(OBLIVION_ESM)
        _cache["header"] = header
        _cache["records"] = records
        # Index by type for fast lookup
        from collections import defaultdict
        by_type = defaultdict(list)
        for rec in records:
            by_type[rec.type].append(rec)
        _cache["by_type"] = by_type
    return _cache


def get_by_type(sig: str) -> list:
    """Get all records of a given type."""
    data = get_records()
    return data["by_type"].get(sig, [])


def find_record(sig: str, edid: str = None, form_id: int = None):
    """Find a specific record by EditorID or FormID."""
    from tes4_export.tes4_reader import get_string, get_subrecord
    recs = get_by_type(sig)
    for rec in recs:
        if edid:
            edid_sub = get_subrecord(rec, "EDID")
            if edid_sub and get_string(edid_sub) == edid:
                return rec
        if form_id is not None and rec.form_id == form_id:
            return rec
    return None


def export_record(rec) -> dict:
    """Export a record and parse the output lines into a dict."""
    from tes4_export.export import format_record
    text = format_record(rec)
    result = {}
    for line in text.split("\n"):
        if line.startswith("---") or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key] = value
    return result


def skip_if_no_esm(fn):
    """Decorator to skip tests if Oblivion.esm not found."""
    def wrapper(*args, **kwargs):
        if OBLIVION_ESM is None:
            raise unittest.SkipTest("Oblivion.esm not found")
        return fn(*args, **kwargs)
    return wrapper


class TestBinaryReader(unittest.TestCase):
    """Test the core binary reader."""

    @skip_if_no_esm
    def test_parse_file(self):
        data = get_records()
        self.assertGreater(len(data["records"]), 1000000)

    @skip_if_no_esm
    def test_header(self):
        data = get_records()
        header = data["header"]
        self.assertEqual(header.type, "TES4")

    @skip_if_no_esm
    def test_record_types_present(self):
        data = get_records()
        types = set(data["by_type"].keys())
        expected = {"STAT", "NPC_", "CREA", "WEAP", "ARMO", "CELL", "REFR",
                    "ENCH", "SPEL", "ALCH", "BOOK", "CONT", "DOOR", "MISC",
                    "KEYM", "FACT", "RACE", "CLAS", "DIAL", "INFO", "QUST",
                    "PACK", "WRLD", "LAND", "LTEX", "GLOB", "GMST"}
        self.assertTrue(expected.issubset(types),
                        f"Missing types: {expected - types}")


class TestSTAT(unittest.TestCase):
    @skip_if_no_esm
    def test_basic_stat(self):
        recs = get_by_type("STAT")
        self.assertGreater(len(recs), 5000)
        # Just check the first record has the right fields
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "STAT")
        self.assertIn("EditorID", d)
        self.assertIn("Model.MODL", d)


class TestNPC(unittest.TestCase):
    @skip_if_no_esm
    def test_npc_fields(self):
        # Imperial Watch Captain is a well-known NPC
        rec = find_record("NPC_", edid="ImperialWatchCaptain")
        if rec is None:
            # Try another common NPC
            recs = get_by_type("NPC_")
            self.assertGreater(len(recs), 0)
            rec = recs[0]
        d = export_record(rec)
        self.assertEqual(d["Signature"], "NPC_")
        self.assertIn("ACBS.Flags", d)
        self.assertIn("ACBS.Level", d)
        self.assertIn("FactionCount", d)

    @skip_if_no_esm
    def test_npc_data_skills(self):
        """Verify NPC_ DATA has all 21 skill fields."""
        recs = get_by_type("NPC_")
        # Find one with DATA
        for rec in recs[:50]:
            d = export_record(rec)
            if "DATA.Blade" in d:
                self.assertIn("DATA.Armorer", d)
                self.assertIn("DATA.Speechcraft", d)
                self.assertIn("DATA.Health", d)
                self.assertIn("DATA.Strength", d)
                self.assertIn("DATA.Luck", d)
                return
        self.skipTest("No NPC_ with DATA skills found in first 50")

    @skip_if_no_esm
    def test_faction_rank_reasonable(self):
        """Verify faction ranks are small values (not garbage from misparse)."""
        recs = get_by_type("NPC_")
        for rec in recs[:100]:
            d = export_record(rec)
            fc = int(d.get("FactionCount", "0"))
            for i in range(fc):
                rank = d.get(f"Faction[{i}].Rank")
                if rank is not None:
                    rank_val = int(rank)
                    self.assertGreaterEqual(rank_val, -1,
                                            f"Rank too low for {d.get('EditorID')}")
                    self.assertLessEqual(rank_val, 127,
                                         f"Rank too high for {d.get('EditorID')}: {rank_val}")


class TestCREA(unittest.TestCase):
    @skip_if_no_esm
    def test_creature_fields(self):
        recs = get_by_type("CREA")
        self.assertGreater(len(recs), 0)
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "CREA")
        self.assertIn("ACBS.Flags", d)

    @skip_if_no_esm
    def test_creature_data(self):
        recs = get_by_type("CREA")
        for rec in recs[:20]:
            d = export_record(rec)
            if "DATA.Type" in d:
                self.assertIn("DATA.CombatSkill", d)
                self.assertIn("DATA.Health", d)
                self.assertIn("DATA.Strength", d)
                return
        self.skipTest("No CREA with DATA found")


class TestWEAP(unittest.TestCase):
    @skip_if_no_esm
    def test_weapon_data(self):
        """Verify WEAP DATA fields parse correctly."""
        recs = get_by_type("WEAP")
        found = False
        for rec in recs[:50]:
            d = export_record(rec)
            if "DATA.Type" in d:
                found = True
                self.assertIn("DATA.Speed", d)
                self.assertIn("DATA.Reach", d)
                self.assertIn("DATA.Value", d)
                self.assertIn("DATA.Damage", d)
                # Sanity check values
                speed = float(d["DATA.Speed"])
                self.assertGreater(speed, 0)
                self.assertLess(speed, 10)
                damage = int(d["DATA.Damage"])
                self.assertGreaterEqual(damage, 0)
                self.assertLess(damage, 1000)
                break
        self.assertTrue(found, "No WEAP with DATA found")


class TestARMO(unittest.TestCase):
    @skip_if_no_esm
    def test_armor_fields(self):
        recs = get_by_type("ARMO")
        self.assertGreater(len(recs), 0)
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "ARMO")
        self.assertIn("BMDT.BipedFlags", d)

    @skip_if_no_esm
    def test_armor_data(self):
        recs = get_by_type("ARMO")
        for rec in recs[:20]:
            d = export_record(rec)
            if "DATA.ArmorRating" in d:
                rating = int(d["DATA.ArmorRating"])
                self.assertGreaterEqual(rating, 0)
                self.assertLess(rating, 10000)
                return
        self.skipTest("No ARMO with DATA found")


class TestCLOT(unittest.TestCase):
    @skip_if_no_esm
    def test_clothing_fields(self):
        recs = get_by_type("CLOT")
        self.assertGreater(len(recs), 0)
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "CLOT")


class TestENCH(unittest.TestCase):
    @skip_if_no_esm
    def test_enchantment_effects(self):
        """Verify ENCH effect magnitudes are sane values."""
        recs = get_by_type("ENCH")
        for rec in recs[:30]:
            d = export_record(rec)
            if "EffectCount" in d:
                count = int(d["EffectCount"])
                if count > 0 and "Effect[0].Magnitude" in d:
                    mag = int(d["Effect[0].Magnitude"])
                    # Magnitudes should be reasonable (0-500 typical)
                    self.assertGreaterEqual(mag, 0)
                    self.assertLess(mag, 100000,
                                    f"Magnitude {mag} suspiciously large for {d.get('EditorID')}")
                    return
        self.skipTest("No ENCH with effects found")

    @skip_if_no_esm
    def test_enit_flags_u8(self):
        """Verify ENIT.Flags is a small value (u8, not garbage from u32 read)."""
        recs = get_by_type("ENCH")
        for rec in recs[:50]:
            d = export_record(rec)
            if "ENIT.Flags" in d:
                flags = int(d["ENIT.Flags"])
                self.assertLessEqual(flags, 255,
                                     f"ENIT.Flags={flags} too large, should be u8")


class TestSPEL(unittest.TestCase):
    @skip_if_no_esm
    def test_spell_fields(self):
        recs = get_by_type("SPEL")
        self.assertGreater(len(recs), 0)
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "SPEL")

    @skip_if_no_esm
    def test_spit_flags_u8(self):
        recs = get_by_type("SPEL")
        for rec in recs[:50]:
            d = export_record(rec)
            if "SPIT.Flags" in d:
                flags = int(d["SPIT.Flags"])
                self.assertLessEqual(flags, 255)


class TestALCH(unittest.TestCase):
    @skip_if_no_esm
    def test_potion_fields(self):
        recs = get_by_type("ALCH")
        self.assertGreater(len(recs), 0)
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "ALCH")

    @skip_if_no_esm
    def test_potion_effects(self):
        recs = get_by_type("ALCH")
        for rec in recs[:20]:
            d = export_record(rec)
            if "EffectCount" in d and int(d["EffectCount"]) > 0:
                self.assertIn("Effect[0].EFID", d)
                self.assertIn("Effect[0].Magnitude", d)
                return


class TestCELL(unittest.TestCase):
    @skip_if_no_esm
    def test_cell_count(self):
        recs = get_by_type("CELL")
        self.assertGreater(len(recs), 30000)

    @skip_if_no_esm
    def test_interior_cell(self):
        """Find an interior cell with lighting data."""
        recs = get_by_type("CELL")
        for rec in recs[:100]:
            d = export_record(rec)
            if "XCLL.AmbientR" in d:
                # Has lighting data - must be interior
                r = int(d["XCLL.AmbientR"])
                self.assertGreaterEqual(r, 0)
                self.assertLessEqual(r, 255)
                return

    @skip_if_no_esm
    def test_exterior_cell(self):
        """Find an exterior cell with grid coordinates."""
        recs = get_by_type("CELL")
        for rec in recs[:1000]:
            d = export_record(rec)
            if "XCLC.X" in d:
                x = int(d["XCLC.X"])
                int(d["XCLC.Y"])  # Verify Y is parseable
                # Grid coordinates should be reasonable
                self.assertGreater(x, -200)
                self.assertLess(x, 200)
                return


class TestREFR(unittest.TestCase):
    @skip_if_no_esm
    def test_refr_count(self):
        recs = get_by_type("REFR")
        self.assertGreater(len(recs), 1000000)

    @skip_if_no_esm
    def test_refr_has_name(self):
        """Most REFRs should have NAME (base object reference)."""
        recs = get_by_type("REFR")
        count_with_name = sum(1 for rec in recs[:1000]
                              if any(s.type == "NAME" for s in rec.subrecords))
        self.assertGreater(count_with_name, 900)

    @skip_if_no_esm
    def test_refr_placement(self):
        recs = get_by_type("REFR")
        for rec in recs[:50]:
            d = export_record(rec)
            if "PosX" in d:
                # Position should be finite
                px = float(d["PosX"])
                self.assertTrue(-1e6 < px < 1e6,
                                f"PosX={px} out of range")
                return


class TestLAND(unittest.TestCase):
    @skip_if_no_esm
    def test_land_count(self):
        recs = get_by_type("LAND")
        self.assertGreater(len(recs), 30000)

    @skip_if_no_esm
    def test_land_layers(self):
        """Some LAND records should have layers."""
        recs = get_by_type("LAND")
        for rec in recs[:200]:
            d = export_record(rec)
            if "LayerCount" in d:
                count = int(d["LayerCount"])
                self.assertGreater(count, 0)
                self.assertIn("Layer[0].Type", d)
                return


class TestWRLD(unittest.TestCase):
    @skip_if_no_esm
    def test_worldspaces(self):
        recs = get_by_type("WRLD")
        self.assertGreater(len(recs), 5)
        # Tamriel should be there
        found = False
        for rec in recs:
            d = export_record(rec)
            if d.get("EditorID") == "Tamriel":
                found = True
                self.assertIn("DATA.Flags", d)
                break
        self.assertTrue(found, "Tamriel worldspace not found")


class TestDIAL(unittest.TestCase):
    @skip_if_no_esm
    def test_dialog_count(self):
        recs = get_by_type("DIAL")
        self.assertGreater(len(recs), 3000)

    @skip_if_no_esm
    def test_dialog_type(self):
        recs = get_by_type("DIAL")
        for rec in recs[:20]:
            d = export_record(rec)
            if "DATA.Type" in d:
                dtype = int(d["DATA.Type"])
                self.assertGreaterEqual(dtype, 0)
                self.assertLessEqual(dtype, 4)
                return


class TestINFO(unittest.TestCase):
    @skip_if_no_esm
    def test_info_count(self):
        recs = get_by_type("INFO")
        self.assertGreater(len(recs), 15000)

    @skip_if_no_esm
    def test_info_has_parent_dial(self):
        """INFO records should have ParentDIAL set."""
        recs = get_by_type("INFO")
        count_with_dial = 0
        for rec in recs[:100]:
            if rec.parent_dial:
                count_with_dial += 1
        self.assertGreater(count_with_dial, 50)


class TestFACT(unittest.TestCase):
    @skip_if_no_esm
    def test_faction_fields(self):
        recs = get_by_type("FACT")
        self.assertGreater(len(recs), 100)
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "FACT")


class TestGLOB(unittest.TestCase):
    @skip_if_no_esm
    def test_global_fields(self):
        recs = get_by_type("GLOB")
        for rec in recs[:10]:
            d = export_record(rec)
            self.assertEqual(d["Signature"], "GLOB")
            self.assertIn("FNAM.Type", d)
            self.assertIn("FLTV.Value", d)
            return


class TestGMST(unittest.TestCase):
    @skip_if_no_esm
    def test_gamesetting_count(self):
        recs = get_by_type("GMST")
        self.assertGreater(len(recs), 300)


class TestRACE(unittest.TestCase):
    @skip_if_no_esm
    def test_race_data(self):
        recs = get_by_type("RACE")
        self.assertGreater(len(recs), 10)
        for rec in recs:
            d = export_record(rec)
            if d.get("EditorID") in ("Imperial", "Nord", "Breton"):
                self.assertIn("DATA.MaleHeight", d)
                self.assertIn("DATA.Flags", d)
                return


class TestLTEX(unittest.TestCase):
    @skip_if_no_esm
    def test_ltex_fields(self):
        recs = get_by_type("LTEX")
        self.assertGreater(len(recs), 100)
        for rec in recs[:10]:
            d = export_record(rec)
            if "ICON" in d:
                self.assertIn("HNAM.Material", d)
                return


class TestSOUN(unittest.TestCase):
    @skip_if_no_esm
    def test_sound_fields(self):
        recs = get_by_type("SOUN")
        self.assertGreater(len(recs), 500)
        for rec in recs[:10]:
            d = export_record(rec)
            if "FNAM.Filename" in d:
                return
        self.skipTest("No SOUN with filename found")


class TestQUST(unittest.TestCase):
    @skip_if_no_esm
    def test_quest_fields(self):
        recs = get_by_type("QUST")
        self.assertGreater(len(recs), 100)
        d = export_record(recs[0])
        self.assertEqual(d["Signature"], "QUST")


class TestBOOK(unittest.TestCase):
    @skip_if_no_esm
    def test_book_data(self):
        recs = get_by_type("BOOK")
        self.assertGreater(len(recs), 500)
        for rec in recs[:20]:
            d = export_record(rec)
            if "DATA.Value" in d:
                val = int(d["DATA.Value"])
                self.assertGreaterEqual(val, 0)
                return


class TestINGR(unittest.TestCase):
    @skip_if_no_esm
    def test_ingredient_effects(self):
        recs = get_by_type("INGR")
        self.assertGreater(len(recs), 100)
        for rec in recs[:20]:
            d = export_record(rec)
            if "EffectCount" in d:
                count = int(d["EffectCount"])
                self.assertGreater(count, 0)
                return


class TestLVLI(unittest.TestCase):
    @skip_if_no_esm
    def test_leveled_item_entries(self):
        recs = get_by_type("LVLI")
        self.assertGreater(len(recs), 1000)
        for rec in recs[:10]:
            d = export_record(rec)
            if "EntryCount" in d:
                count = int(d["EntryCount"])
                if count > 0:
                    self.assertIn("Entry[0].FormID", d)
                    self.assertIn("Entry[0].Level", d)
                    return


class TestSCPT(unittest.TestCase):
    @skip_if_no_esm
    def test_script_source(self):
        recs = get_by_type("SCPT")
        self.assertGreater(len(recs), 1000)
        for rec in recs[:20]:
            d = export_record(rec)
            if "SCTX" in d:
                # Should have some script text
                self.assertGreater(len(d["SCTX"]), 0)
                return


class TestCLAS(unittest.TestCase):
    @skip_if_no_esm
    def test_class_data(self):
        recs = get_by_type("CLAS")
        self.assertGreater(len(recs), 50)
        for rec in recs[:10]:
            d = export_record(rec)
            if "DATA.Specialization" in d:
                spec = int(d["DATA.Specialization"])
                self.assertIn(spec, [0, 1, 2])  # Combat, Magic, Stealth
                return


class TestACHR(unittest.TestCase):
    @skip_if_no_esm
    def test_placed_npc(self):
        recs = get_by_type("ACHR")
        self.assertGreater(len(recs), 1000)
        for rec in recs[:20]:
            d = export_record(rec)
            if "NAME" in d:
                self.assertIn("PosX", d)
                return


class TestACRE(unittest.TestCase):
    @skip_if_no_esm
    def test_placed_creature(self):
        recs = get_by_type("ACRE")
        self.assertGreater(len(recs), 1000)


if __name__ == "__main__":
    # Allow running standalone
    unittest.main(verbosity=2)


class TestSkillData:
    """SKIL DATA starts with the skill's own Action index, before the governing attribute.

    See: docs/plans/character_sheet.md#bug-skil-shift
    """

    #: SkillAlchemy (Oblivion.esm SKIL 00000044) DATA, verbatim.
    RAW = bytes.fromhex('1300000001000000010000000000a0400000003f')

    def test_fields_land_on_their_own_names(self):
        """Alchemy: Action 19, Intelligence, Magic, use values 5.0 and 0.5."""
        from tes4_export.tes4_reader import Record, Subrecord
        from tes4_export.record_types.actors import export_SKIL
        rec = Record(type='SKIL', data_size=0, flags=0, form_id=0x44,
                     subrecords=[Subrecord('EDID', b'SkillAlchemy\x00'), Subrecord('DATA', self.RAW)])
        got = dict(line.partition('=')[::2] for line in export_SKIL(rec))
        assert got['DATA.Action'] == '19'
        assert got['DATA.Attribute'] == '1'
        assert got['DATA.Specialization'] == '1'
        assert float(got['DATA.UseValue1']) == 5.0
        assert float(got['DATA.UseValue2']) == 0.5


class TestFalloutActorAcbs:
    """FO3/FNV ACBS drops TES4's SpellPoints, shifting every later field.

    See docs/commentary/tes4_export_falloutnv.md#acbs-lost-its-spellpoints.
    """

    #: VSpawnTier3GiantRadscorpionMed (FalloutNV.esm CREA 00156782), verbatim.
    RAW = bytes.fromhex('40020000320000000100000000006400000000002300df01')

    def _rec(self, *subs):
        """A CREA Record carrying the given (signature, bytes) subrecords."""
        from tes4_export.tes4_reader import Record, Subrecord
        return Record(type='CREA', data_size=0, flags=0, form_id=0x00156782,
                      subrecords=[Subrecord(t, d) for t, d in subs])

    def _lines(self, *subs):
        """The FO3/FNV delta lines for that record, as a key -> value dict."""
        from tes4_export.record_types.falloutnv import export_deltas
        out = {}
        for line in export_deltas(self._rec(*subs)):
            key, _, value = line.partition('=')
            out[key] = value
        return out

    def test_fields_read_two_bytes_earlier_than_tes4(self):
        """Every field past byte 4 sits where TES4 puts the one after it."""
        got = self._lines(('ACBS', self.RAW))
        assert got['ACBS.Fatigue'] == '50'
        assert got['ACBS.BarterGold'] == '0'
        assert got['ACBS.Level'] == '1'
        assert got['ACBS.CalcMin'] == '0'
        assert got['ACBS.CalcMax'] == '0'
        assert got['ACBS.SpeedMultiplier'] == '100'
        assert got['ACBS.Disposition'] == '35'
        assert 'ACBS.SpellPoints' not in got

    def test_template_flags_and_tplt_survive(self):
        """Bit 6 (Model/Animation) is what tells the importer to follow TPLT."""
        got = self._lines(('ACBS', self.RAW),
                          ('TPLT', (0x001567A0).to_bytes(4, 'little')))
        assert int(got['ACBS.TemplateFlags']) == 0x01DF
        assert int(got['ACBS.TemplateFlags']) & (1 << 6)
        assert got['TPLT.Template'] == '001567A0'

    def test_a_seventeen_byte_data_still_yields_stats(self):
        """TES4's CREA DATA is 20 bytes, so the shared exporter emitted none."""
        raw = bytes.fromhex('0032323232000000000005050505050505')
        got = self._lines(('ACBS', self.RAW), ('DATA', raw))
        assert got['DATA.Health'] == '50'
        assert got['DATA.Luck'] == '5'
        assert 'DATA.Soul' not in got

    def test_a_tes4_sized_acbs_is_left_to_the_shared_exporter(self):
        """A 16-byte ACBS is TES4's, so this emitter must not touch it."""
        assert self._lines(('ACBS', self.RAW[:16])) == {}


class TestFalloutQuestDeltas:
    """FO3/FNV QUST: the 8-byte DATA delay and the QOBJ/NNAM objectives.

    See docs/commentary/tes4_export_falloutnv.md#quest-delay-and-objectives.
    """

    #: PreordVault13CanteenQuest DATA (FalloutNV.esm 00174095): flags 0x11, priority 50, delay 300.
    CANTEEN_DATA = bytes.fromhex('1132436100009643')
    #: VMQ01 objective 40 target 0: FormID 0009289B, flag 1, three unused bytes.
    QSTA = bytes.fromhex('9b28090001f94707')
    #: A 28-byte FNV CTDA (GetQuestVariable VMQ01, Run On 3) under that target.
    CTDA = bytes.fromhex('000000000000803f4f000000dd420800030000000000000000000000')

    def _lines(self, *subs):
        """The FO3/FNV delta lines of a QUST built from (signature, bytes)."""
        from tes4_export.tes4_reader import Record, Subrecord
        from tes4_export.record_types.falloutnv import export_deltas
        rec = Record(type='QUST', data_size=0, flags=0, form_id=0x00174095,
                     subrecords=[Subrecord(t, d) for t, d in subs])
        out = {}
        for line in export_deltas(rec):
            key, _, value = line.partition('=')
            out[key] = value
        return out

    def test_delay_float_is_emitted(self):
        """The 300 s canteen delay reaches the text; no objectives, no block."""
        got = self._lines(('DATA', self.CANTEEN_DATA))
        assert got['DATA.Delay'] == '300'
        assert 'ObjectiveCount' not in got

    def test_objectives_group_their_targets_and_conditions(self):
        """Targets and their CTDAs nest under the objective they follow."""
        got = self._lines(
            ('DATA', self.CANTEEN_DATA),
            ('QOBJ', (40).to_bytes(4, 'little')),
            ('NNAM', b'Head to Novac.\0'),
            ('QSTA', self.QSTA), ('CTDA', self.CTDA),
            ('QOBJ', (50).to_bytes(4, 'little')),
            ('NNAM', b'Intercept the Khans.\0'),
        )
        assert got['ObjectiveCount'] == '2'
        assert got['Objective[0].Index'] == '40'
        assert got['Objective[0].Text'] == 'Head to Novac.'
        assert got['Objective[0].TargetCount'] == '1'
        assert got['Objective[0].Target[0].FormID'] == '0009289B'
        assert got['Objective[0].Target[0].Flags'] == '1'
        assert got['Objective[0].Target[0].ConditionCount'] == '1'
        assert got['Objective[0].Target[0].Condition[0].Raw'] == self.CTDA.hex()
        assert got['Objective[1].Index'] == '50'
        assert got['Objective[1].TargetCount'] == '0'

    def test_flat_target_lines_are_superseded_for_quests(self):
        """The TES4 walker's flat Target[] lines are dropped for an FNV QUST."""
        from tes4_export.export_falloutnv import superseded_keys
        from tes4_export.tes4_reader import Record
        rec = Record(type='QUST', data_size=0, flags=0, form_id=1)
        assert 'Target[' in superseded_keys(rec)
        assert 'TargetCount=' in superseded_keys(rec)


class TestINFOResultScripts(unittest.TestCase):
    """FO3/FNV INFOs embed a Begin and an End script split by NEXT; TES4 one.

    See docs/commentary/tes4_export_falloutnv.md#info-end-script.
    """

    @staticmethod
    def _rec(*subs):
        """An INFO Record whose subrecords are the given (type, bytes) pairs."""
        from tes4_export.tes4_reader import Record, Subrecord
        return Record(type='INFO', data_size=0, flags=0, form_id=1,
                      subrecords=[Subrecord(t, d) for t, d in subs])

    def test_begin_and_end_are_split_at_next(self):
        """The SCTX before NEXT is Begin, the one after it End."""
        from tes4_export.record_types.falloutnv import info_result_scripts
        rec = self._rec(('SCHR', b''), ('SCTX', b'set x to 1'), ('NEXT', b''),
                        ('SCHR', b''), ('SCDA', b''), ('SCTX', b'SetStage VCG01 85'))
        self.assertEqual(info_result_scripts(rec), ('set x to 1', 'SetStage VCG01 85'))

    def test_empty_begin_keeps_end_text_as_end(self):
        """The first SCTX in the stream is NOT the Begin script when Begin is empty."""
        from tes4_export.record_types.falloutnv import info_result_scripts
        rec = self._rec(('SCHR', b''), ('NEXT', b''), ('SCHR', b''),
                        ('SCTX', b'SetStage VCG01 36'))
        self.assertEqual(info_result_scripts(rec), ('', 'SetStage VCG01 36'))

    def test_tes4_single_script_is_begin(self):
        """No NEXT marker: the only script is the Begin script."""
        from tes4_export.record_types.falloutnv import info_result_scripts
        rec = self._rec(('SCHR', b''), ('SCTX', b'setstage q 5'))
        self.assertEqual(info_result_scripts(rec), ('setstage q 5', ''))

    def test_consumers_read_both_halves_in_order(self):
        """info_result_script joins Begin then End; absent halves vanish."""
        from tes5_import.base.text_reader import info_result_script
        rec = {'ResultScript': 'set x to 1', 'ResultScriptEnd': 'SetStage VCG01 85'}
        self.assertEqual(info_result_script(rec), 'set x to 1\nSetStage VCG01 85')
        self.assertEqual(info_result_script({'ResultScriptEnd': 'a'}), 'a')
        self.assertEqual(info_result_script({}), '')


class TestFalloutPackageScripts(unittest.TestCase):
    """FO3/FNV PACK sections: an idle, an embedded script and a topic each.

    See docs/commentary/tes4_export_falloutnv.md#package-scripts.
    """

    def _lines(self, *subs):
        """The package delta lines of a PACK built from (type, bytes) pairs."""
        from tes4_export.tes4_reader import Record, Subrecord
        from tes4_export.record_types.package_falloutnv import emit_package_deltas
        rec = Record(type='PACK', data_size=0, flags=0, form_id=1,
                     subrecords=[Subrecord(t, d) for t, d in subs])
        lines = []
        emit_package_deltas(lines, rec)
        return lines

    def test_each_section_keeps_its_own_script_refs_and_topic(self):
        """The sections reuse INAM/SCTX/SCRO/TNAM, so stream order decides."""
        lines = self._lines(
            ('POBA', b''), ('INAM', b'\0' * 4), ('SCHR', b'\0' * 20),
            ('SCTX', b'SetStage VCG02 30'), ('SCRO', struct.pack('<I', 0x10A21C)),
            ('TNAM', b'\0' * 4),
            ('POEA', b''), ('INAM', struct.pack('<I', 0x42)), ('SCHR', b'\0' * 20),
            ('TNAM', struct.pack('<I', 0x118A5C)),
            ('POCA', b''), ('INAM', b'\0' * 4), ('SCHR', b'\0' * 20), ('TNAM', b'\0' * 4))
        self.assertEqual(lines, ['OnBegin.Script=SetStage VCG02 30',
                                 'OnBegin.SCRO[0]=0010A21C',
                                 'OnEnd.Idle=00000042', 'OnEnd.Topic=00118A5C'])

    def test_dialogue_data_names_its_topic_and_kind(self):
        """A Dialogue package's PKDD: its topic and Conversation/SayTo type."""
        pkdd = struct.pack('<fIIIII', 30.0, 0x15B6CF, 0, 0, 1, 0)
        lines = self._lines(('PKDD', pkdd))
        self.assertIn('PKDD.Topic=0015B6CF', lines)
        self.assertIn('PKDD.Type=SayTo', lines)


class TestFalloutTopicLinks(unittest.TestCase):
    """FO3/FNV DIAL flags and the INFO prompt are dumped.

    See docs/commentary/tes5_import_dialogue.md#fallout-topic-links.
    """

    @staticmethod
    def _record(sig, *subs):
        """A Record built from (type, bytes) pairs."""
        from tes4_export.tes4_reader import Record, Subrecord
        return Record(type=sig, data_size=0, flags=0, form_id=1,
                      subrecords=[Subrecord(t, d) for t, d in subs])

    def test_dial_flags_follow_the_type(self):
        """FO3/FNV DATA is Type + Flags; Oblivion's one byte has no Flags line."""
        from tes4_export.record_types.dialog_misc import export_DIAL
        self.assertIn('DATA.Flags=2', export_DIAL(self._record('DIAL', ('DATA', b'\x00\x02'))))
        self.assertNotIn('DATA.Flags', ''.join(export_DIAL(self._record('DIAL', ('DATA', b'\x00')))))

    def test_info_prompt(self):
        """INFO RNAM becomes Prompt."""
        from tes4_export.record_types.dialog_misc import export_INFO
        lines = export_INFO(self._record('INFO', ('RNAM', b'Who rescued me?\0')))
        self.assertIn('Prompt=Who rescued me?', lines)


class TestFalloutTriggerPrimitive(unittest.TestCase):
    """An FO3/FNV REFR's XPRM is dumped raw so the importer can copy it.

    See docs/commentary/tes4_export_falloutnv.md#trigger-primitives.
    """

    def test_xprm_raw_is_the_whole_subrecord(self):
        """Bounds stay for readers; XPRM.Raw carries all 32 bytes."""
        from tes4_export.tes4_reader import Record, Subrecord
        from tes4_export.record_types.falloutnv import _emit_refr_deltas
        raw = bytes.fromhex('80A69A4288A5A4430000E0420000803F0000803F8180003F9A99193E01000000')
        rec = Record(type='REFR', data_size=0, flags=0, form_id=1,
                     subrecords=[Subrecord('XPRM', raw)])
        lines = []
        _emit_refr_deltas(lines, rec)
        self.assertIn('XPRM.Raw=' + raw.hex().upper(), lines)
        self.assertTrue(any(l.startswith('XPRM.BoundX=') for l in lines))
