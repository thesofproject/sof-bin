#!/usr/bin/env python3
"""
Unit and integration tests for validate_sof_install.py
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent directory to sys.path so we can import validate_sof_install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import validate_sof_install
from validate_sof_install import (
    HostTarget,
    LocalHostTarget,
    SofBinRepo,
    SofValidator,
    Status,
    ValidationRecord,
    compute_file_md5,
    generate_md5_manifest,
)


class TestSofBinRepo(unittest.TestCase):
    """Test repository detection and version resolution."""

    def setUp(self):
        self.repo_dir = Path(__file__).resolve().parent.parent
        self.repo = SofBinRepo(self.repo_dir)

    def test_find_repo(self):
        found = SofBinRepo.find_repo(str(self.repo_dir))
        self.assertEqual(found.repo_dir, self.repo_dir)

    def test_list_available_versions(self):
        versions = self.repo.list_available_versions()
        self.assertGreater(len(versions), 5)
        v_names = [v["version_dir"] for v in versions]
        self.assertIn("v2.14.x", v_names)
        self.assertIn("v2.11.x", v_names)
        self.assertIn("v2.2.x", v_names)

    def test_resolve_version_components_ipc4(self):
        comps = self.repo.resolve_version_components("v2.14.1")
        self.assertIn("fw", comps)
        self.assertIn("tplg", comps)
        self.assertIn("llext", comps)
        self.assertTrue(comps["fw"].name.startswith("sof-ipc4-v"))
        self.assertTrue(comps["llext"].name.startswith("sof-ipc4-lib-v"))
        self.assertTrue(comps["tplg"].name.startswith("sof-ipc4-tplg-v"))

    def test_resolve_version_uppercase(self):
        comps = self.repo.resolve_version_components("V2.14.1")
        self.assertIn("fw", comps)
        self.assertTrue(comps["fw"].name.startswith("sof-ipc4-v"))

        comps_no_v = self.repo.resolve_version_components("2.14")
        self.assertIn("fw", comps_no_v)

    def test_resolve_version_components_ipc3(self):
        comps = self.repo.resolve_version_components("v2.2")
        self.assertIn("fw", comps)
        self.assertIn("tplg", comps)
        self.assertTrue(comps["fw"].name.startswith(("sof-v", "sof-ipc3-zephyr-v")))

    def test_resolve_invalid_version(self):
        with self.assertRaises(ValueError):
            self.repo.resolve_version_components("v999.999")

    def test_global_md5_database_lookup(self):
        with tempfile.TemporaryDirectory() as td:
            repo_path = Path(td)
            vdir = repo_path / "v2.12.x" / "sof-ipc4-v2.12" / "tgl" / "community"
            vdir.mkdir(parents=True)
            test_fw = vdir / "sof-tgl.ri"
            test_fw.write_bytes(b"MOCK_TGL_V2.12_BINARY_DATA")

            mock_repo = SofBinRepo(repo_path)
            h = compute_file_md5(test_fw)
            matched = mock_repo.lookup_md5(h, "sof-tgl.ri")
            self.assertIsNotNone(matched)
            self.assertIn("v2.12", matched)


class TestLocalHostTarget(unittest.TestCase):
    """Test local target file operations and checksumming."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Create test files
        (self.root / "file1.bin").write_bytes(b"hello world")
        (self.root / "file2.bin").write_bytes(b"sof firmware binary test")
        os.symlink("file1.bin", self.root / "sym1.bin")
        os.symlink("missing.bin", self.root / "broken_sym.bin")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_compute_md5(self):
        f1 = self.root / "file1.bin"
        expected = hashlib.md5(b"hello world").hexdigest()
        self.assertEqual(compute_file_md5(f1), expected)

    def test_compute_file_md5_error_handling(self):
        # Non-existent file
        self.assertIsNone(compute_file_md5(self.root / "nonexistent.bin"))
        # Directory instead of file
        self.assertIsNone(compute_file_md5(self.root))

    def test_batch_query(self):
        target = LocalHostTarget(target_root=self.root)
        paths = ["/file1.bin", "/file2.bin", "/sym1.bin", "/broken_sym.bin", "/nonexistent.bin"]
        res = target.batch_query(paths)

        # file1.bin
        exists, is_sym, size, sym_tgt, md5_val, man_info = res["/file1.bin"]
        self.assertTrue(exists)
        self.assertFalse(is_sym)
        self.assertEqual(size, 11)
        self.assertEqual(md5_val, hashlib.md5(b"hello world").hexdigest())

        # sym1.bin
        exists, is_sym, size, sym_tgt, md5_val, man_info = res["/sym1.bin"]
        self.assertTrue(exists)
        self.assertTrue(is_sym)
        self.assertEqual(sym_tgt, "file1.bin")
        self.assertEqual(md5_val, hashlib.md5(b"hello world").hexdigest())

        # broken_sym.bin
        exists, is_sym, size, sym_tgt, md5_val, man_info = res["/broken_sym.bin"]
        self.assertTrue(exists)
        self.assertTrue(is_sym)
        self.assertIsNone(md5_val)

        # nonexistent.bin
        exists, is_sym, size, sym_tgt, md5_val, man_info = res["/nonexistent.bin"]
        self.assertFalse(exists)

    def test_fix_file_operations(self):
        target = LocalHostTarget(target_root=self.root)
        src_file = self.root / "file1.bin"
        dest_path = "/installed/target.bin"

        # Dry run
        ok, msg = target.fix_file(str(src_file), dest_path, is_symlink=False, symlink_target=None, dry_run=True)
        self.assertTrue(ok)
        self.assertIn("Would copy", msg)
        self.assertFalse((self.root / "installed/target.bin").exists())

        # Real fix
        ok, msg = target.fix_file(str(src_file), dest_path, is_symlink=False, symlink_target=None, dry_run=False)
        self.assertTrue(ok)
        self.assertTrue((self.root / "installed/target.bin").exists())
        self.assertEqual((self.root / "installed/target.bin").read_bytes(), b"hello world")

        # Symlink fix
        sym_dest = "/installed/target_sym.bin"
        ok, msg = target.fix_file(str(src_file), sym_dest, is_symlink=True, symlink_target="target.bin", dry_run=False)
        self.assertTrue(ok)
        self.assertTrue((self.root / "installed/target_sym.bin").is_symlink())
        self.assertEqual(os.readlink(self.root / "installed/target_sym.bin"), "target.bin")


class TestSofValidatorWithMock(unittest.TestCase):
    """Test validator logic using mock directory trees."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

        # 1. Create mock sof-bin repo with v2.98 (earlier) and v2.99 (target)
        self.mock_repo_dir = self.base / "mock-sof-bin"

        # Earlier v2.98
        v298_dir = self.mock_repo_dir / "v2.98.x" / "sof-ipc4-v2.98" / "tgl" / "community"
        v298_dir.mkdir(parents=True)
        (v298_dir / "sof-tgl.ri").write_bytes(b"OLD_V2.98_TGL_FW")

        # Target v2.99
        vdir = self.mock_repo_dir / "v2.99.x"
        fw_dir = vdir / "sof-ipc4-v2.99"
        lib_dir = vdir / "sof-ipc4-lib-v2.99"
        tplg_dir = vdir / "sof-ipc4-tplg-v2.99"
        tools_dir = vdir / "tools-v2.99"

        (fw_dir / "tgl" / "community").mkdir(parents=True)
        (fw_dir / "tgl" / "intel-signed").mkdir(parents=True)
        (lib_dir / "tgl" / "community").mkdir(parents=True)
        tplg_dir.mkdir(parents=True)
        tools_dir.mkdir(parents=True)

        self.tgl_comm_fw = fw_dir / "tgl" / "community" / "sof-tgl.ri"
        self.tgl_comm_fw.write_bytes(b"MOCK_TGL_COMMUNITY_FW_V2.99")
        self.tgl_signed_fw = fw_dir / "tgl" / "intel-signed" / "sof-tgl.ri"
        self.tgl_signed_fw.write_bytes(b"MOCK_TGL_INTEL_SIGNED_FW_V2.99")

        # Symlink in platform root
        os.symlink("community/sof-tgl.ri", fw_dir / "tgl" / "sof-tgl.ri")

        # LLEXT module
        self.llext_file = lib_dir / "tgl" / "community" / "eq.llext"
        self.llext_file.write_bytes(b"MOCK_LLEXT_EQ_MODULE")
        os.symlink("eq.llext", lib_dir / "tgl" / "community" / "uuid-1234.bin")

        # Topology
        self.tplg_file = tplg_dir / "sof-tgl-nocodec.tplg"
        self.tplg_file.write_bytes(b"MOCK_TOPOLOGY_DATA")

        # Tools
        self.tool_file = tools_dir / "sof-logger"
        self.tool_file.write_bytes(b"MOCK_SOF_LOGGER_BINARY")

        self.repo = SofBinRepo(self.mock_repo_dir)

        # 2. Create mock target installation
        self.target_dir = self.base / "target_root"
        self.fw_dest = "/lib/firmware/intel"
        self.tools_dest = "/usr/local/bin"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_pass_validation(self):
        """Install everything correctly and verify 100% PASS."""
        tgt_tgl_dir = self.target_dir / "lib/firmware/intel/sof-ipc4/tgl"
        (tgt_tgl_dir / "community").mkdir(parents=True)
        (tgt_tgl_dir / "intel-signed").mkdir(parents=True)
        (tgt_tgl_dir / "community" / "sof-tgl.ri").write_bytes(b"MOCK_TGL_COMMUNITY_FW_V2.99")
        (tgt_tgl_dir / "intel-signed" / "sof-tgl.ri").write_bytes(b"MOCK_TGL_INTEL_SIGNED_FW_V2.99")
        os.symlink("community/sof-tgl.ri", tgt_tgl_dir / "sof-tgl.ri")

        tgt_lib_dir = self.target_dir / "lib/firmware/intel/sof-ipc4-lib/tgl/community"
        tgt_lib_dir.mkdir(parents=True)
        (tgt_lib_dir / "eq.llext").write_bytes(b"MOCK_LLEXT_EQ_MODULE")
        os.symlink("eq.llext", tgt_lib_dir / "uuid-1234.bin")

        tgt_tplg_dir = self.target_dir / "lib/firmware/intel/sof-ipc4-tplg"
        tgt_tplg_dir.mkdir(parents=True)
        (tgt_tplg_dir / "sof-tgl-nocodec.tplg").write_bytes(b"MOCK_TOPOLOGY_DATA")

        tgt_tools_dir = self.target_dir / "usr/local/bin"
        tgt_tools_dir.mkdir(parents=True)
        (tgt_tools_dir / "sof-logger").write_bytes(b"MOCK_SOF_LOGGER_BINARY")

        target = LocalHostTarget(target_root=self.target_dir)
        validator = SofValidator(
            repo=self.repo,
            target=target,
            fw_dest=self.fw_dest,
            tools_dest=self.tools_dest,
        )

        records = validator.validate_installation("v2.99")
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertIn(r.status, (Status.MATCH, Status.SYMLINK_MATCH), f"Failed for {r.rel_path}: {r.message}")

    def test_mismatch_and_historical_release_match(self):
        """Verify that a mismatch matching an earlier release is detected and reported."""
        tgt_tgl_dir = self.target_dir / "lib/firmware/intel/sof-ipc4/tgl/community"
        tgt_tgl_dir.mkdir(parents=True)
        # Write content from older v2.98
        (tgt_tgl_dir / "sof-tgl.ri").write_bytes(b"OLD_V2.98_TGL_FW")

        target = LocalHostTarget(target_root=self.target_dir)
        validator = SofValidator(
            repo=self.repo,
            target=target,
            fw_dest=self.fw_dest,
            tools_dest=self.tools_dest,
            platform_filter={"tgl"},
            component_filter={"fw"},
        )

        records = validator.validate_installation("v2.99")
        status_map = {r.rel_path: r for r in records}

        rec = status_map["sof-ipc4/tgl/community/sof-tgl.ri"]
        self.assertEqual(rec.status, Status.MISMATCH)
        self.assertIsNotNone(rec.matched_release)
        self.assertIn("v2.98", rec.matched_release)
        self.assertIn("matches v2.98", rec.message)

    def test_fix_records_repairs_installation(self):
        """Verify that fix_records repairs mismatched and missing files."""
        tgt_tgl_dir = self.target_dir / "lib/firmware/intel/sof-ipc4/tgl/community"
        tgt_tgl_dir.mkdir(parents=True)
        # 1. Corrupted file
        (tgt_tgl_dir / "sof-tgl.ri").write_bytes(b"OLD_V2.98_TGL_FW")

        target = LocalHostTarget(target_root=self.target_dir)
        validator = SofValidator(
            repo=self.repo,
            target=target,
            fw_dest=self.fw_dest,
            tools_dest=self.tools_dest,
            platform_filter={"tgl"},
            component_filter={"fw"},
        )

        records = validator.validate_installation("v2.99")
        # Should have mismatches and missing files
        has_issues = any(r.status != Status.MATCH and r.status != Status.SYMLINK_MATCH for r in records)
        self.assertTrue(has_issues)

        # Apply fix
        fix_res = validator.fix_records(records, dry_run=False)
        self.assertGreater(len(fix_res), 0)
        for _, ok, msg in fix_res:
            self.assertTrue(ok, msg)

        # Re-validate
        records_after = validator.validate_installation("v2.99")
        for r in records_after:
            self.assertIn(r.status, (Status.MATCH, Status.SYMLINK_MATCH), f"Post-fix failure on {r.rel_path}")

    def test_identify_installed_files(self):
        """Verify that identify_installed correctly scans target filesystem and detects versions."""
        tgt_tgl_dir = self.target_dir / "lib/firmware/intel/sof-ipc4/tgl/community"
        tgt_tgl_dir.mkdir(parents=True)
        # Install v2.98 file
        (tgt_tgl_dir / "sof-tgl.ri").write_bytes(b"OLD_V2.98_TGL_FW")

        target = LocalHostTarget(target_root=self.target_dir)
        validator = SofValidator(
            repo=self.repo,
            target=target,
            fw_dest=self.fw_dest,
            tools_dest=self.tools_dest,
        )

        identified = validator.identify_installed()
        self.assertEqual(len(identified), 1)
        item = identified[0]
        self.assertEqual(item["component"], "fw")
        self.assertEqual(item["platform"], "tgl")
        self.assertEqual(item["installed_version"], "v2.98")
        self.assertIn("v2.98", item["matched_release"])

    def test_strict_mode_extra_files(self):
        """Verify that strict mode flags extraneous installed files with Status.EXTRA."""
        tgt_tgl_dir = self.target_dir / "lib/firmware/intel/sof-ipc4/tgl/community"
        tgt_tgl_dir.mkdir(parents=True)
        # Valid expected file
        (tgt_tgl_dir / "sof-tgl.ri").write_bytes(b"V2.99_TGL_FW_BINARY_DATA")
        # Extra/extraneous file not in v2.99 components
        (tgt_tgl_dir / "sof-extra-unknown.ri").write_bytes(b"EXTRA_UNTRACKED_FILE")

        target = LocalHostTarget(target_root=self.target_dir)
        # Non-strict validator: should only check expected files
        validator_normal = SofValidator(
            repo=self.repo,
            target=target,
            fw_dest=self.fw_dest,
            tools_dest=self.tools_dest,
            platform_filter={"tgl"},
            component_filter={"fw"},
            strict=False,
        )
        recs_normal = validator_normal.validate_installation("v2.99")
        self.assertFalse(any(r.status == Status.EXTRA for r in recs_normal))

        # Strict validator: should detect the extraneous file
        validator_strict = SofValidator(
            repo=self.repo,
            target=target,
            fw_dest=self.fw_dest,
            tools_dest=self.tools_dest,
            platform_filter={"tgl"},
            component_filter={"fw"},
            strict=True,
        )
        recs_strict = validator_strict.validate_installation("v2.99")
        extra_recs = [r for r in recs_strict if r.status == Status.EXTRA]
        self.assertEqual(len(extra_recs), 1)
        self.assertIn("sof-extra-unknown.ri", extra_recs[0].rel_path)

    def test_downgrade_detection_and_prevention(self):
        from validate_sof_install import (
            ValidationRecord,
            Status,
            parse_version_tuple,
            is_downgrade,
            SofValidator,
            LocalHostTarget,
        )

        # Version tuple parsing tests
        self.assertEqual(parse_version_tuple("v2.14.1"), (2, 14, 1))
        self.assertEqual(parse_version_tuple("2.14"), (2, 14))
        self.assertEqual(parse_version_tuple("v2.14.1.2"), (2, 14, 1, 2))
        self.assertEqual(parse_version_tuple("v2.14.1 (manifest)"), (2, 14, 1))
        self.assertIsNone(parse_version_tuple("-"))
        self.assertIsNone(parse_version_tuple("unknown"))

        # Downgrade logic tests
        rec_downgrade = ValidationRecord(
            component="llext",
            platform="lnl",
            rel_path="sof-ipc4-lib/lnl/community/drc.llext",
            expected_version="v2.14",
            installed_version="v2.14.1",
            source_path=str(self.mock_repo_dir / "v2.99.x/sof-ipc4-v2.99/tgl/community/sof-tgl.ri"),
            target_path=str(self.target_dir / "lib/firmware/intel/sof-ipc4-lib/lnl/community/drc.llext"),
            status=Status.MISMATCH,
            actual_manifest={"manifest_version": "v2.14.1", "build_date": "2025-12-18"},
            expected_manifest={"manifest_version": "v2.14.0", "build_date": "2025-12-04"},
        )
        self.assertTrue(is_downgrade(rec_downgrade, target_version="2.14"))

        # Upgrade test
        rec_upgrade = ValidationRecord(
            component="fw",
            platform="tgl",
            rel_path="sof-ipc4/tgl/sof-tgl.ri",
            expected_version="v2.14.1",
            installed_version="v2.12",
            status=Status.MISMATCH,
        )
        self.assertFalse(is_downgrade(rec_upgrade, target_version="v2.14.1"))

        # Test fix_records with downgrade prevention
        target = LocalHostTarget(target_root=self.target_dir)
        validator = SofValidator(repo=self.repo, target=target, fw_dest=self.fw_dest, tools_dest=self.tools_dest)

        # Without allow_downgrade: skipped
        res_skipped = validator.fix_records([rec_downgrade], dry_run=True, allow_downgrade=False)
        self.assertEqual(len(res_skipped), 1)
        self.assertFalse(res_skipped[0][1])
        self.assertIn("would downgrade", res_skipped[0][2])

        # With allow_downgrade: permitted
        res_allowed = validator.fix_records([rec_downgrade], dry_run=True, allow_downgrade=True)
        self.assertEqual(len(res_allowed), 1)
        self.assertTrue(res_allowed[0][1])


class TestManifestParsing(unittest.TestCase):
    """Test binary manifest parsing functions."""

    def test_parse_binary_manifest_am1_and_mn2(self):
        import struct
        from validate_sof_install import parse_binary_manifest, format_manifest_summary

        # Build synthetic binary with $MN2 (BCD date) and $AM1 header
        # $MN2 BCD date 0x20251218: mod_id is 8 bytes after date field in CSS header
        data = bytearray(1000)
        struct.pack_into("<II4s", data, 100, 0x20251218, 0, b"$MN2")
        # $AM1 header: maj=0, min=2, hotfix=14, build=1
        struct.pack_into(
            "<4sI8sIIHHHHHI",
            data,
            300,
            b"$AM1",
            52,
            b"ADSPFW\x00\x00",
            14,
            4,
            2,
            0,
            2,
            14,
            1,
            65537,
        )
        man = parse_binary_manifest(bytes(data))
        self.assertEqual(man.get("build_date"), "2025-12-18")
        self.assertEqual(man.get("manifest_version"), "v2.14.1")
        self.assertEqual(man.get("component_name"), "ADSPFW")
        self.assertEqual(man.get("modules_count"), 1)

        summary = format_manifest_summary(man)
        self.assertIn("ver v2.14.1", summary)
        self.assertIn("built 2025-12-18", summary)

    def test_parse_binary_manifest_cosa_topology(self):
        import struct
        from validate_sof_install import parse_binary_manifest, format_manifest_summary

        # Build synthetic topology binary with CoSA block type 8 (MANIFEST)
        # struct snd_soc_tplg_hdr (36 bytes): magic=CoSA, abi=0, ver=0, type=8, size=36+120, vendor=0, payload_sz=120, index=0, count=1
        # man_data (120 bytes): priv_size=6 at offset 108, priv_data at offset 112 (abi_maj=3, abi_min=29, abi_patch=1)
        data = bytearray(500)
        struct.pack_into("<IIIIIIIII", data, 50, 0x41536f43, 0, 0, 8, 156, 0, 120, 0, 1)
        struct.pack_into("<I", data, 50 + 36 + 108, 6)
        struct.pack_into("<HHH", data, 50 + 36 + 112, 3, 29, 1)

        man = parse_binary_manifest(bytes(data))
        self.assertEqual(man.get("tplg_abi"), "3.29.1")
        summary = format_manifest_summary(man)
        self.assertEqual(summary, "ABI 3.29.1")

    def test_format_fix_record_transitions(self):
        from validate_sof_install import ValidationRecord, Status, format_fix_record

        rec = ValidationRecord(
            component="llext",
            platform="lnl",
            rel_path="sof-ipc4-lib/lnl/community/drc.llext",
            expected_version="v2.14.0",
            installed_version="v2.14.1",
            status=Status.MISMATCH,
            actual_manifest={"manifest_version": "v2.14.1", "build_date": "2025-12-18"},
            expected_manifest={"manifest_version": "v2.14.0", "build_date": "2025-12-04"},
        )
        lines = format_fix_record(rec, ok=True, msg="Transferred src -> dst", target_version="v2.14", colorize=False)
        self.assertTrue(any("sof-ipc4-lib/lnl/community/drc.llext" in l for l in lines))
        self.assertTrue(any("Version: v2.14.1 -> v2.14.0" in l for l in lines))
        self.assertTrue(any("Manifest: Host [ver v2.14.1, built 2025-12-18] -> Expected [ver v2.14.0, built 2025-12-04]" in l for l in lines))

        # Test missing record
        rec_missing = ValidationRecord(
            component="fw",
            platform="lnl",
            rel_path="sof-ipc4/lnl/sof-lnl.ri",
            expected_version="v2.14.1",
            installed_version="-",
            status=Status.MISSING,
            expected_manifest={"manifest_version": "v2.14.1", "build_date": "2025-12-18"},
        )
        lines_missing = format_fix_record(rec_missing, ok=True, msg="Installed src -> dst", target_version="v2.14.1", colorize=False)
        self.assertTrue(any("Version: (missing) -> v2.14.1" in l for l in lines_missing))
        self.assertTrue(any("Manifest: Host (missing) -> Expected [ver v2.14.1, built 2025-12-18]" in l for l in lines_missing))


class TestPackageValidation(unittest.TestCase):
    """Test Debian (.deb) and RPM (.rpm) package extraction, inspection, and validation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _build_test_deb(self, data_files: Dict[str, bytes], control_fields: Dict[str, str], out_path: Path) -> Path:
        """Create a standard Debian .deb package (ar archive containing debian-binary, control.tar.gz, data.tar.gz)."""
        import io
        import tarfile

        # 1. debian-binary
        deb_bin = b"2.0\n"

        # 2. control.tar.gz
        ctrl_buf = io.BytesIO()
        with tarfile.open(fileobj=ctrl_buf, mode="w:gz") as tar:
            ctrl_text = "".join(f"{k}: {v}\n" for k, v in control_fields.items()).encode("utf-8")
            ti = tarfile.TarInfo(name="control")
            ti.size = len(ctrl_text)
            ti.mode = 0o644
            tar.addfile(ti, io.BytesIO(ctrl_text))
        ctrl_data = ctrl_buf.getvalue()

        # 3. data.tar.gz
        data_buf = io.BytesIO()
        with tarfile.open(fileobj=data_buf, mode="w:gz") as tar:
            for rel_path, content in data_files.items():
                ti = tarfile.TarInfo(name=rel_path)
                ti.size = len(content)
                ti.mode = 0o644
                tar.addfile(ti, io.BytesIO(content))
        data_bytes = data_buf.getvalue()

        def make_ar_member(name: str, payload: bytes) -> bytes:
            hdr = f"{name:<16}{1700000000:<12}{0:<6}{0:<6}{100644:<8}{len(payload):<10}\x60\n".encode("ascii")
            pad = b"\n" if len(payload) % 2 == 1 else b""
            return hdr + payload + pad

        ar_data = b"!<arch>\n"
        ar_data += make_ar_member("debian-binary", deb_bin)
        ar_data += make_ar_member("control.tar.gz", ctrl_data)
        ar_data += make_ar_member("data.tar.gz", data_bytes)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(ar_data)
        return out_path

    def test_extract_deb_package(self):
        from validate_sof_install import extract_deb

        deb_path = self.base / "firmware-sof-signed_2.14.1_all.deb"
        self._build_test_deb(
            data_files={
                "lib/firmware/intel/sof-ipc4/tgl/community/sof-tgl.ri": b"TEST_TGL_FW_DATA",
                "lib/firmware/intel/sof-ipc4-tplg/sof-tgl-nocodec.tplg": b"TEST_TPLG_DATA",
            },
            control_fields={
                "Package": "firmware-sof-signed",
                "Version": "2.14.1-1",
                "Architecture": "all",
                "Description": "Sound Open Firmware binary release",
            },
            out_path=deb_path,
        )

        dest_dir = self.base / "extracted_deb"
        dest_dir.mkdir()
        meta = extract_deb(deb_path, dest_dir)

        self.assertEqual(meta.get("package"), "firmware-sof-signed")
        self.assertEqual(meta.get("version"), "2.14.1-1")
        self.assertEqual(meta.get("architecture"), "all")

        extracted_files = [str(p.relative_to(dest_dir)) for p in dest_dir.rglob("*") if p.is_file()]
        self.assertIn("lib/firmware/intel/sof-ipc4/tgl/community/sof-tgl.ri", extracted_files)
        self.assertIn("lib/firmware/intel/sof-ipc4-tplg/sof-tgl-nocodec.tplg", extracted_files)

    def test_collect_packages(self):
        from validate_sof_install import collect_packages

        deb1 = self.base / "pkg1.deb"
        deb2 = self.base / "pkg2.deb"
        deb1.write_bytes(b"dummy1")
        deb2.write_bytes(b"dummy2")

        # Comma-separated list
        res = collect_packages([f"{deb1},{deb2}"])
        self.assertEqual(res, [deb1.resolve(), deb2.resolve()])

        # Directory containing packages
        pkg_dir = self.base / "pkgs"
        pkg_dir.mkdir()
        (pkg_dir / "a.deb").write_bytes(b"a")
        (pkg_dir / "b.rpm").write_bytes(b"b")

        dir_res = collect_packages([str(pkg_dir)])
        self.assertEqual(len(dir_res), 2)

        # Missing file error
        with self.assertRaises(FileNotFoundError):
            collect_packages([str(self.base / "nonexistent.deb")])

    def test_package_target_validation_and_identify(self):
        from validate_sof_install import PackageTarget, SofBinRepo, SofValidator, Status

        # 1. Create mock sof-bin repo with v2.99
        repo_dir = self.base / "sof-bin"
        vdir = repo_dir / "v2.99.x"
        fw_dir = vdir / "sof-ipc4-v2.99" / "tgl" / "community"
        tplg_dir = vdir / "sof-ipc4-tplg-v2.99"
        fw_dir.mkdir(parents=True)
        tplg_dir.mkdir(parents=True)

        fw_content = b"IDENTICAL_FW_DATA_FOR_VALIDATION"
        tplg_content = b"IDENTICAL_TPLG_DATA_FOR_VALIDATION"

        (fw_dir / "sof-tgl.ri").write_bytes(fw_content)
        (tplg_dir / "sof-tgl-hdmi.tplg").write_bytes(tplg_content)

        repo = SofBinRepo(repo_dir)

        # 2. Build test deb matching repo contents
        deb_path = self.base / "firmware-sof_2.99_all.deb"
        self._build_test_deb(
            data_files={
                "lib/firmware/intel/sof-ipc4/tgl/community/sof-tgl.ri": fw_content,
                "lib/firmware/intel/sof-ipc4-tplg/sof-tgl-hdmi.tplg": tplg_content,
            },
            control_fields={"Package": "firmware-sof", "Version": "2.99-1", "Architecture": "all"},
            out_path=deb_path,
        )

        # 3. Validate PackageTarget against v2.99
        target = PackageTarget([deb_path])
        try:
            validator = SofValidator(
                repo=repo,
                target=target,
                platform_filter={"tgl"},
            )

            records = validator.validate_installation("v2.99")
            self.assertGreater(len(records), 0)
            self.assertTrue(all(r.status in (Status.MATCH, Status.SYMLINK_MATCH) for r in records))

            # 4. Identify mode on PackageTarget
            identified = validator.identify_installed()
            self.assertEqual(len(identified), 2)
            self.assertTrue(all(item["installed_version"] == "v2.99" for item in identified))
        finally:
            target.cleanup()

    def test_rpm_package_target(self):
        import shutil
        import subprocess
        from validate_sof_install import PackageTarget, SofBinRepo, SofValidator, Status

        if not shutil.which("rpmbuild") or not shutil.which("rpm2cpio"):
            self.skipTest("rpmbuild or rpm2cpio not installed")

        # 1. Create mock repo
        repo_dir = self.base / "sof-bin-rpm"
        vdir = repo_dir / "v2.99.x"
        fw_dir = vdir / "sof-ipc4-v2.99" / "tgl" / "community"
        fw_dir.mkdir(parents=True)
        fw_content = b"RPM_TGL_FW_TEST_PAYLOAD"
        (fw_dir / "sof-tgl.ri").write_bytes(fw_content)
        repo = SofBinRepo(repo_dir)

        # 2. Build minimal test RPM
        topdir = self.base / "rpmbuild_test"
        for sub in ["BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS"]:
            (topdir / sub).mkdir(parents=True)

        payload_dir = self.base / "payload"
        (payload_dir / "lib/firmware/intel/sof-ipc4/tgl/community").mkdir(parents=True)
        (payload_dir / "lib/firmware/intel/sof-ipc4/tgl/community/sof-tgl.ri").write_bytes(fw_content)

        spec = f"""
Name: test-sof-firmware
Version: 2.99
Release: 1
Summary: Test SOF Firmware Package
License: BSD
BuildArch: noarch

%description
Test package

%install
mkdir -p %{{buildroot}}/lib/firmware/intel/sof-ipc4/tgl/community
cp {payload_dir}/lib/firmware/intel/sof-ipc4/tgl/community/sof-tgl.ri %{{buildroot}}/lib/firmware/intel/sof-ipc4/tgl/community/

%files
/lib/firmware/intel/sof-ipc4/tgl/community/sof-tgl.ri
"""
        spec_file = self.base / "test.spec"
        spec_file.write_text(spec)

        subprocess.run(
            ["rpmbuild", "-bb", "--define", f"_topdir {topdir}", str(spec_file)],
            check=True,
            capture_output=True,
        )

        rpm_files = list((topdir / "RPMS").rglob("*.rpm"))
        self.assertTrue(len(rpm_files) > 0)
        rpm_file = rpm_files[0]

        # 3. Validate with PackageTarget
        target = PackageTarget([rpm_file])
        try:
            validator = SofValidator(repo=repo, target=target, platform_filter={"tgl"})
            records = validator.validate_installation("v2.99")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, Status.MATCH)

            identified = validator.identify_installed()
            self.assertEqual(len(identified), 1)
            self.assertEqual(identified[0]["installed_version"], "v2.99")
        finally:
            target.cleanup()


class TestPlatformConsistency(unittest.TestCase):
    """Test verification that LLEXT versions and build dates match base FW for each platform."""

    def test_platform_consistency_matching(self):
        from validate_sof_install import ValidationRecord, Status, check_platform_fw_llext_consistency, format_consistency_report

        fw_rec = ValidationRecord(
            component="fw",
            platform="lnl",
            rel_path="sof-ipc4/lnl/community/sof-lnl.ri",
            installed_version="v2.14.1",
            status=Status.MATCH,
            actual_manifest={"manifest_version": "v2.14.1", "build_date": "2025-12-18"},
        )
        llext_rec = ValidationRecord(
            component="llext",
            platform="lnl",
            rel_path="sof-ipc4-lib/lnl/community/drc.llext",
            installed_version="v2.14.1",
            status=Status.MATCH,
            actual_manifest={"manifest_version": "v2.14.1", "build_date": "2025-12-18"},
        )

        report = check_platform_fw_llext_consistency([fw_rec, llext_rec])
        self.assertIn("lnl", report)
        self.assertTrue(report["lnl"]["consistent"])
        self.assertEqual(report["lnl"]["fw_version"], "v2.14.1")
        self.assertEqual(report["lnl"]["fw_build_date"], "2025-12-18")
        self.assertEqual(len(report["lnl"]["issues"]), 0)

        lines = format_consistency_report(report, colorize=False)
        self.assertTrue(any("✓ lnl" in l for l in lines))
        self.assertTrue(any("Consistent" in l for l in lines))

    def test_platform_consistency_mismatch(self):
        from validate_sof_install import ValidationRecord, Status, check_platform_fw_llext_consistency, format_consistency_report

        fw_rec = ValidationRecord(
            component="fw",
            platform="lnl",
            rel_path="sof-ipc4/lnl/community/sof-lnl.ri",
            installed_version="v2.14.1",
            status=Status.MATCH,
            actual_manifest={"manifest_version": "v2.14.1", "build_date": "2025-12-18"},
        )
        llext_rec = ValidationRecord(
            component="llext",
            platform="lnl",
            rel_path="sof-ipc4-lib/lnl/community/drc.llext",
            installed_version="v2.14.0",
            status=Status.MISMATCH,
            actual_manifest={"manifest_version": "v2.14.0", "build_date": "2025-12-04"},
        )

        report = check_platform_fw_llext_consistency([fw_rec, llext_rec])
        self.assertIn("lnl", report)
        self.assertFalse(report["lnl"]["consistent"])
        self.assertGreater(len(report["lnl"]["issues"]), 0)
        self.assertTrue(any("Build date mismatch" in iss for iss in report["lnl"]["issues"]))
        self.assertTrue(any("Version mismatch" in iss for iss in report["lnl"]["issues"]))

        lines = format_consistency_report(report, colorize=False)
        self.assertTrue(any("✗ lnl" in l for l in lines))
        self.assertTrue(any("Inconsistent" in l for l in lines))

    def test_platform_consistency_from_dict_scan(self):
        from validate_sof_install import check_platform_fw_llext_consistency

        scan_items = [
            {
                "component": "fw",
                "platform": "ptl",
                "rel_path": "sof-ipc4/ptl/community/sof-ptl.ri",
                "installed_version": "v2.14.1",
                "manifest": {"build_date": "2025-12-18", "manifest_version": "v2.14.1"},
            },
            {
                "component": "llext",
                "platform": "ptl",
                "rel_path": "sof-ipc4-lib/ptl/community/eq_iir.llext",
                "installed_version": "v2.14.1",
                "manifest": {"build_date": "2025-12-18", "manifest_version": "v2.14.1"},
            },
        ]
        report = check_platform_fw_llext_consistency(scan_items)
        self.assertIn("ptl", report)
        self.assertTrue(report["ptl"]["consistent"])


class TestTopologyUpgrade(unittest.TestCase):
    """Test identifying whether a topology can be upgraded from sof-bin to match FW."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)

        # Create mock sof-bin structure with multiple tplg versions
        v214_dir = self.repo_dir / "v2.14.x"
        v214_dir.mkdir(parents=True)

        tplg_v214 = v214_dir / "sof-ipc4-tplg-v2.14"
        tplg_v214.mkdir(parents=True)
        (tplg_v214 / "sof-tgl-nocs42l43.tplg").write_bytes(b"tplg v2.14 content")

        tplg_v214_2 = v214_dir / "sof-ipc4-tplg-v2.14.2"
        tplg_v214_2.mkdir(parents=True)
        (tplg_v214_2 / "sof-tgl-nocs42l43.tplg").write_bytes(b"tplg v2.14.2 content")

        self.repo = SofBinRepo(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_find_topology_upgrade_available(self):
        # Installed version is v2.14 (older than v2.14.2)
        old_md5 = compute_file_md5(self.repo_dir / "v2.14.x" / "sof-ipc4-tplg-v2.14" / "sof-tgl-nocs42l43.tplg")
        upgrade = self.repo.find_topology_upgrade(
            filename="sof-tgl-nocs42l43.tplg",
            installed_version="v2.14",
            installed_md5=old_md5,
            fw_version="v2.14.1",
        )
        self.assertIsNotNone(upgrade)
        self.assertEqual(upgrade["target_version"], "v2.14.2")
        self.assertEqual(upgrade["component"], "sof-ipc4-tplg-v2.14.2")
        self.assertEqual(upgrade["fw_version"], "v2.14.1")

    def test_find_topology_upgrade_already_newest(self):
        # Installed version is already v2.14.2
        newest_md5 = compute_file_md5(self.repo_dir / "v2.14.x" / "sof-ipc4-tplg-v2.14.2" / "sof-tgl-nocs42l43.tplg")
        upgrade = self.repo.find_topology_upgrade(
            filename="sof-tgl-nocs42l43.tplg",
            installed_version="v2.14.2",
            installed_md5=newest_md5,
            fw_version="v2.14.1",
        )
        self.assertIsNone(upgrade)

    def test_format_identify_table_shows_upgrades(self):
        from validate_sof_install import format_identify_table

        records = [
            {
                "component": "fw",
                "platform": "tgl",
                "rel_path": "sof-ipc4/tgl/sof-tgl.ri",
                "installed_version": "v2.14.1",
                "md5": "abc123",
                "is_symlink": False,
                "symlink_target": None,
                "manifest": None,
            },
            {
                "component": "tplg",
                "platform": "tgl",
                "rel_path": "sof-ipc4-tplg/sof-tgl-nocs42l43.tplg",
                "installed_version": "v2.14",
                "md5": "def456",
                "is_symlink": False,
                "symlink_target": None,
                "manifest": None,
                "upgrade_available": {
                    "target_version": "v2.14.2",
                    "component": "sof-ipc4-tplg-v2.14.2",
                    "fw_version": "v2.14.1",
                },
            },
        ]
        output = format_identify_table(records, colorize=False)
        self.assertIn("Upgrade Available", output)
        self.assertIn("v2.14 -> v2.14.2", output)
        self.assertIn("TOPOLOGY UPGRADES AVAILABLE", output)


if __name__ == "__main__":
    unittest.main()
