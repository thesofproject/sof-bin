#!/usr/bin/env python3
"""
SOF Installation MD5 Validator (validate_sof_install.py)

Validates that Sound Open Firmware (SOF) binaries, LLEXT modules, topologies,
and userspace tools from the sof-bin repository are correctly installed on a
target host's /lib/firmware directory using MD5 checksums.

Features:
- Local host validation (/lib/firmware/intel or custom path)
- Offline rootfs / NFS rootfs validation (--target-root /srv/nfs/spider-rootfs)
- Remote SSH target validation (--ssh root@spider)
- Filesystem identification mode (-i / --identify) to inspect installed versions
- Mismatch detection against historical SOF releases
- Displays version of installed files in summary table
- Fix mode (--fix, --dry-run) to automatically sync/repair installed files
- Platform filtering (-p tgl, -p mtl, -p ptl, etc.)
- Component filtering (-c fw, -c llext, -c tplg, -c tools)
- Signing flavor filtering (-f community, -f intel-signed)
- JSON output for test automation (--json)
- Standalone md5sum manifest export (--generate-md5 <file>)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class Status(Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"
    SYMLINK_MATCH = "SYMLINK_MATCH"
    SYMLINK_MISMATCH = "SYMLINK_MISMATCH"
    BROKEN_SYMLINK = "BROKEN_SYMLINK"
    EXTRA = "EXTRA"
    ERROR = "ERROR"


@dataclass
class ValidationRecord:
    component: str  # fw, llext, tplg, tools
    platform: str  # tgl, mtl, ptl, generic, etc.
    rel_path: str  # relative to fw_dest (or tools_dest)
    expected_version: str = ""  # target version requested e.g. v2.14.1
    installed_version: Optional[str] = None  # version found on host e.g. v2.12, v2.14.1, unknown
    source_path: Optional[str] = None  # in sof-bin
    target_path: Optional[str] = None  # on host
    is_symlink: bool = False
    symlink_target_expected: Optional[str] = None
    symlink_target_actual: Optional[str] = None
    expected_md5: Optional[str] = None
    actual_md5: Optional[str] = None
    expected_size: Optional[int] = None
    actual_size: Optional[int] = None
    matched_release: Optional[str] = None  # if mismatch matches an earlier release
    fix_applied: bool = False
    fix_message: Optional[str] = None
    status: Status = Status.MISSING
    message: str = ""
    expected_manifest: Optional[Dict[str, Any]] = None
    actual_manifest: Optional[Dict[str, Any]] = None
    upgrade_available: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "platform": self.platform,
            "rel_path": self.rel_path,
            "expected_version": self.expected_version,
            "installed_version": self.installed_version,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "is_symlink": self.is_symlink,
            "symlink_target_expected": self.symlink_target_expected,
            "symlink_target_actual": self.symlink_target_actual,
            "expected_md5": self.expected_md5,
            "actual_md5": self.actual_md5,
            "expected_size": self.expected_size,
            "actual_size": self.actual_size,
            "matched_release": self.matched_release,
            "fix_applied": self.fix_applied,
            "fix_message": self.fix_message,
            "status": self.status.value,
            "message": self.message,
            "expected_manifest": self.expected_manifest,
            "actual_manifest": self.actual_manifest,
            "upgrade_available": self.upgrade_available,
        }


def compute_file_md5(file_path: Path, block_size: int = 65536) -> Optional[str]:
    """Compute MD5 hash of a local file safely in all environments."""
    if not file_path.is_file():
        return None
    try:
        try:
            hasher = hashlib.md5(usedforsecurity=False)
        except (TypeError, ValueError):
            hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(block_size), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, IOError, ValueError, Exception):
        return None


def parse_binary_manifest(data: bytes) -> Dict[str, Any]:
    """
    Parse embedded manifest and metadata from firmware (.ri), LLEXT (.llext/.bin),
    and topology (.tplg) binaries.
    
    Supports:
    - CSS headers ($MN2): BCD build date (YYYY-MM-DD)
    - ADSP FW header ($AM1): SOF major/minor/hotfix/build version, component name, modules
    - Extended Manifest (XMan): FW version, ABI version, date/time strings
    - Embedded build strings: Zephyr version/commit, SOF tags
    - ALSA Topology Manifest (CoSA / type 8): Topology SOF ABI version
    """
    if not data:
        return {}
    info: Dict[str, Any] = {}

    # 1. CSS Header ($MN2)
    pos_mn2 = data.find(b"$MN2")
    if pos_mn2 != -1 and pos_mn2 >= 8:
        try:
            date_raw = struct.unpack_from("<I", data, pos_mn2 - 8)[0]
            year = ((date_raw >> 28) & 0xf) * 1000 + ((date_raw >> 24) & 0xf) * 100 + ((date_raw >> 20) & 0xf) * 10 + ((date_raw >> 16) & 0xf)
            month = ((date_raw >> 12) & 0xf) * 10 + ((date_raw >> 8) & 0xf)
            day = ((date_raw >> 4) & 0xf) * 10 + (date_raw & 0xf)
            if 1970 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
                info["build_date"] = f"{year:04d}-{month:02d}-{day:02d}"
        except Exception:
            pass

    # 2. ADSP FW Manifest ($AM1)
    pos_am1 = data.find(b"$AM1")
    if pos_am1 != -1 and pos_am1 + 52 <= len(data):
        try:
            hdr_id, hdr_len, name, preload_pages, flags, feat_mask, maj, min_v, hotfix, bld, num_mods = struct.unpack_from(
                "<4sI8sIIIHHHHI", data, pos_am1
            )
            if maj == 0:
                ver_str = f"v{min_v}.{hotfix}.{bld}"
            elif bld in (0, 1):
                ver_str = f"v{maj}.{min_v}.{hotfix}"
            else:
                ver_str = f"v{maj}.{min_v}.{hotfix}.{bld}"
            info["manifest_version"] = ver_str
            name_str = name.decode("ascii", "replace").strip("\x00")
            if name_str:
                info["component_name"] = name_str
            info["modules_count"] = num_mods & 0xffff
        except Exception:
            pass

    # 3. Extended Manifest (XMan)
    pos_xman = data.find(b"XMan")
    if pos_xman != -1 and pos_xman + 16 <= len(data):
        try:
            magic, full_sz, hdr_sz, hdr_ver = struct.unpack_from("<IIII", data, pos_xman)
            offset = pos_xman + hdr_sz
            end = min(pos_xman + full_sz, len(data))
            while offset + 8 <= end:
                elem_type, elem_sz = struct.unpack_from("<II", data, offset)
                if elem_sz == 0:
                    break
                if elem_type == 0 and offset + 16 + 44 <= len(data):  # FW_VERSION
                    v_off = offset + 16
                    major, minor, micro, build = struct.unpack_from("<HHHH", data, v_off)
                    date_b = data[v_off+8:v_off+20].split(b"\x00")[0].decode("ascii", "replace").strip()
                    time_b = data[v_off+20:v_off+30].split(b"\x00")[0].decode("ascii", "replace").strip()
                    tag_b = data[v_off+30:v_off+36].split(b"\x00")[0].decode("ascii", "replace").strip()
                    abi_ver, src_hash = struct.unpack_from("<II", data, v_off+36)
                    if not info.get("manifest_version"):
                        if major == 0:
                            info["manifest_version"] = f"v{minor}.{micro}.{build}"
                        elif build in (0, 1):
                            info["manifest_version"] = f"v{major}.{minor}.{micro}"
                        else:
                            info["manifest_version"] = f"v{major}.{minor}.{micro}.{build}"
                    if date_b and not info.get("build_date"):
                        info["build_date"] = date_b
                    if time_b:
                        info["build_time"] = time_b
                    if tag_b:
                        info["sof_tag"] = tag_b
                    if abi_ver:
                        info["abi_version"] = f"0x{abi_ver:x}"
                offset += elem_sz
        except Exception:
            pass

    # 4. Embedded strings (Zephyr / SOF version banner)
    try:
        zephyr_match = re.search(rb"Booting Zephyr OS build ([^\s\*\r\n\x00]+)", data)
        if zephyr_match:
            info["zephyr_build"] = zephyr_match.group(1).decode("ascii", "replace").strip()

        fw_tag_match = re.search(rb"tags SOF:([^\s\x00]+) zephyr:([^\s\x00]+)", data)
        if fw_tag_match:
            info["sof_tag"] = fw_tag_match.group(1).decode("ascii", "replace")
            info["zephyr_tag"] = fw_tag_match.group(2).decode("ascii", "replace")
    except Exception:
        pass

    # 5. ALSA Topology Manifest (CoSA)
    pos_cosa = data.find(b"CoSA")
    if pos_cosa != -1:
        try:
            offset = pos_cosa
            while offset + 36 <= len(data):
                if data[offset:offset+4] != b"CoSA":
                    break
                magic, abi, ver, ttype, sz, vendor_type, payload_sz, idx, count = struct.unpack_from("<IIIIIIIII", data, offset)
                if ttype == 8:  # MANIFEST
                    man_data = data[offset+36 : offset+36+payload_sz]
                    if len(man_data) >= 112:
                        priv_sz = struct.unpack_from("<I", man_data, 108)[0]
                        priv_data = man_data[112:112+priv_sz]
                        if len(priv_data) >= 6:
                            abi_maj, abi_min, abi_patch = struct.unpack_from("<HHH", priv_data, 0)
                            info["tplg_abi"] = f"{abi_maj}.{abi_min}.{abi_patch}"
                    break
                offset += 36 + payload_sz
        except Exception:
            pass

    return info


def format_manifest_summary(man: Optional[Dict[str, Any]]) -> str:
    """Format manifest dictionary into a concise single-line description."""
    if not man:
        return ""
    parts = []
    if man.get("manifest_version"):
        parts.append(f"ver {man['manifest_version']}")
    if man.get("build_date"):
        dt = man["build_date"]
        if man.get("build_time"):
            dt += f" {man['build_time']}"
        parts.append(f"built {dt}")
    if man.get("tplg_abi"):
        parts.append(f"ABI {man['tplg_abi']}")
    elif man.get("abi_version"):
        parts.append(f"ABI {man['abi_version']}")
    if man.get("sof_tag") and man.get("sof_tag") != man.get("manifest_version"):
        parts.append(f"tag {man['sof_tag']}")
    if man.get("zephyr_build"):
        parts.append(f"zephyr {man['zephyr_build']}")
    return ", ".join(parts)


def parse_version_tuple(ver_str: Optional[str]) -> Optional[Tuple[int, ...]]:
    """Parse version string like 'v2.14.1', '2.14', 'v2.14.1.1', 'v2.14.1 (manifest)' into an integer tuple."""
    if not ver_str or ver_str in ("-", "unknown", "broken", "broken link", "target mismatch", "error", "(missing)"):
        return None
    m = re.search(r"v?(\d+(?:\.\d+)*)", ver_str)
    if m:
        nums = m.group(1).split(".")
        return tuple(int(n) for n in nums if n.isdigit())
    nums = re.findall(r"\d+", ver_str)
    if nums:
        return tuple(int(n) for n in nums)
    return None


class SofBinRepo:
    """Interface to inspect the sof-bin repository."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir.resolve()
        if not self.repo_dir.is_dir():
            raise FileNotFoundError(f"sof-bin repository directory not found: {self.repo_dir}")
        self._md5_db: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._filename_md5_cache: Dict[str, Dict[str, List[Dict[str, str]]]] = {}

    @classmethod
    def find_repo(cls, hint_dir: Optional[str] = None) -> "SofBinRepo":
        """Auto-detect the sof-bin repository location."""
        candidates = []
        if hint_dir:
            candidates.append(Path(hint_dir))
        if "SOF_BIN_DIR" in os.environ:
            candidates.append(Path(os.environ["SOF_BIN_DIR"]))

        # Script location
        script_dir = Path(__file__).resolve().parent
        candidates.append(script_dir)
        if (script_dir / "sof-bin").is_dir():
            candidates.append(script_dir / "sof-bin")

        # Standard work locations
        home = Path.home()
        candidates.extend([
            home / "work" / "sof-ptl" / "sof-bin",
            home / "work" / "sof-tgl" / "sof-bin",
            home / "work" / "sof-arl" / "sof-bin",
            home / "work" / "sof-bin",
            Path.cwd(),
            Path.cwd() / "sof-bin",
        ])

        for c in candidates:
            if c.is_dir() and (cls._is_sof_bin_dir(c)):
                return cls(c)

        raise FileNotFoundError(
            "Could not locate sof-bin repository. Please specify --sof-bin-dir."
        )

    @classmethod
    def _is_sof_bin_dir(cls, path: Path) -> bool:
        """Check if a directory contains SOF release directories (e.g. v2.14.x, v2.12.x)."""
        has_version_dirs = any(
            d.is_dir() and (re.match(r"^v?\d+\.\d+", d.name) or d.name.startswith("v20"))
            for d in path.iterdir()
        )
        return has_version_dirs

    def get_version_dirs(self) -> List[Path]:
        """Return sorted list of version directories in the repo (newest first)."""
        dirs = [
            d for d in self.repo_dir.iterdir()
            if d.is_dir() and (re.match(r"^v?\d+\.\d+", d.name) or d.name.startswith("v20"))
        ]
        def sort_key(p: Path) -> Tuple[int, ...]:
            nums = re.findall(r"\d+", p.name)
            return tuple(int(n) for n in nums) if nums else (0,)
        return sorted(dirs, key=sort_key, reverse=True)

    def list_available_versions(self) -> List[Dict[str, Any]]:
        """Return metadata for all available releases in sof-bin."""
        versions = []
        for vdir in self.get_version_dirs():
            subdirs = [p.name for p in vdir.iterdir() if p.is_dir()]
            fw_sub = [s for s in subdirs if s.startswith(("sof-ipc4-v", "sof-ipc3-zephyr-v", "sof-v"))]
            tplg_sub = [s for s in subdirs if s.startswith(("sof-ipc4-tplg-v", "sof-ace-tplg-v", "sof-tplg-v"))]
            lib_sub = [s for s in subdirs if s.startswith("sof-ipc4-lib-v")]
            tools_sub = [s for s in subdirs if s.startswith("tools-v")]

            fw_version = fw_sub[0] if fw_sub else None
            tplg_version = tplg_sub[0] if tplg_sub else None
            lib_version = lib_sub[0] if lib_sub else None

            platforms = set()
            for root, _, files in os.walk(vdir):
                for f in files:
                    if f.endswith(".ri"):
                        m = re.search(r"sof-([a-z0-9_]+)\.ri", f)
                        if m:
                            platforms.add(m.group(1))

            versions.append({
                "version_dir": vdir.name,
                "directory": vdir.name,
                "path": str(vdir),
                "fw_component": fw_version,
                "tplg_component": tplg_version,
                "lib_component": lib_version,
                "tools_component": tools_sub[0] if tools_sub else None,
                "platforms": sorted(platforms),
            })
        return versions

    def resolve_version_components(self, target_version: str) -> Dict[str, Path]:
        """
        Given a version string (e.g. 'v2.14.1', '2.14', 'V2.14.1', 'v2.12', 'v2.2.2'),
        locate the matching component directories in sof-bin.
        """
        norm_ver = target_version.strip().lower()
        if not norm_ver.startswith("v") and not norm_ver.startswith("20"):
            norm_ver = "v" + norm_ver

        vdir: Optional[Path] = None
        m = re.match(r"^v?(\d+)\.(\d+)(\.|\b|-)", norm_ver)
        if m:
            expected_vdir = f"v{m.group(1)}.{m.group(2)}.x"
            candidate = self.repo_dir / expected_vdir
            if candidate.is_dir():
                vdir = candidate

        if not vdir:
            for d in self.get_version_dirs():
                d_name_lower = d.name.lower()
                if norm_ver in d_name_lower or any(norm_ver in p.name.lower() for p in d.iterdir()):
                    vdir = d
                    break

        if not vdir:
            for d in self.get_version_dirs():
                if d.name.lower().startswith(norm_ver):
                    vdir = d
                    break

        if not vdir or not vdir.is_dir():
            available = [d.name for d in self.get_version_dirs()]
            raise ValueError(
                f"Version '{target_version}' not found in sof-bin. Available major versions: {', '.join(available)}"
            )

        subdirs = [p for p in vdir.iterdir() if p.is_dir()]

        def find_best_match(comp_name: str, prefixes: Tuple[str, ...], ver: str) -> Optional[Path]:
            matching = [p for p in subdirs if p.name.lower().startswith(prefixes)]
            if not matching:
                return None
            for p in matching:
                p_lower = p.name.lower()
                if p_lower.endswith("-" + ver) or p_lower.endswith(ver):
                    return p
            ver_clean = ver.lstrip("v")
            for p in matching:
                p_lower = p.name.lower()
                if p_lower.endswith("-" + ver_clean) or p_lower.endswith(ver_clean):
                    return p
            def ver_key(p: Path) -> List[int]:
                nums = re.findall(r"\d+", p.name)
                return [int(n) for n in nums]
            newest = sorted(matching, key=ver_key)[-1]
            sys.stderr.write(
                f"Note: Component '{comp_name}' exact version '{ver}' not found in {vdir.name}; using newest available subversion '{newest.name}'\n"
            )
            return newest

        fw_dir = find_best_match("fw", ("sof-ipc4-v", "sof-ipc3-zephyr-v", "sof-v"), norm_ver)
        llext_dir = find_best_match("llext", ("sof-ipc4-lib-v",), norm_ver)
        tplg_dir = find_best_match("tplg", ("sof-ipc4-tplg-v", "sof-ace-tplg-v", "sof-tplg-v"), norm_ver)
        tools_dir = find_best_match("tools", ("tools-v",), norm_ver)

        components: Dict[str, Path] = {"vdir": vdir}
        if fw_dir:
            components["fw"] = fw_dir
        if llext_dir:
            components["llext"] = llext_dir
        if tplg_dir:
            components["tplg"] = tplg_dir
        if tools_dir:
            components["tools"] = tools_dir

        return components

    def build_global_md5_database(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Build an index of all regular files in all version directories by MD5 checksum.
        Returns: md5_hash -> list of {version_dir, component, filename, rel_path}
        """
        if self._md5_db is not None:
            return self._md5_db

        db: Dict[str, List[Dict[str, str]]] = {}
        for vdir in self.get_version_dirs():
            for root, _, files in os.walk(vdir):
                for f in files:
                    file_p = Path(root) / f
                    if file_p.is_file() and not file_p.is_symlink():
                        md5_val = compute_file_md5(file_p)
                        if md5_val:
                            rel_to_vdir = file_p.relative_to(vdir)
                            comp_name = rel_to_vdir.parts[0] if rel_to_vdir.parts else "root"
                            entry = {
                                "version_dir": vdir.name,
                                "component": comp_name,
                                "filename": f,
                                "rel_path": str(rel_to_vdir),
                                "full_path": str(file_p),
                            }
                            if md5_val not in db:
                                db[md5_val] = []
                            db[md5_val].append(entry)

        self._md5_db = db
        return db

    def lookup_md5(self, md5_hash: Optional[str], target_filename: Optional[str] = None) -> Optional[str]:
        """
        Look up an MD5 hash across all releases and return a human-readable release identifier.
        Uses fast on-demand caching per target filename to avoid scanning the entire repository.
        """
        if not md5_hash:
            return None

        clean_hash = md5_hash.lower()

        if target_filename:
            if target_filename not in self._filename_md5_cache:
                fn_db: Dict[str, List[Dict[str, str]]] = {}
                for vdir in self.get_version_dirs():
                    for root, _, files in os.walk(vdir):
                        if target_filename in files:
                            file_p = Path(root) / target_filename
                            if file_p.is_file() and not file_p.is_symlink():
                                h = compute_file_md5(file_p)
                                if h:
                                    rel_to_vdir = file_p.relative_to(vdir)
                                    comp_name = rel_to_vdir.parts[0] if rel_to_vdir.parts else "root"
                                    entry = {
                                        "version_dir": vdir.name,
                                        "component": comp_name,
                                        "filename": target_filename,
                                        "rel_path": str(rel_to_vdir),
                                        "full_path": str(file_p),
                                    }
                                    fn_db.setdefault(h, []).append(entry)
                self._filename_md5_cache[target_filename] = fn_db

            matches = self._filename_md5_cache[target_filename].get(clean_hash)
            if not matches and self._md5_db is not None:
                matches = [m for m in self._md5_db.get(clean_hash, []) if m["filename"] == target_filename]
        else:
            db = self.build_global_md5_database()
            matches = db.get(clean_hash)

        if not matches:
            return None

        descriptions = []
        for m in matches:
            comp = m["component"]
            ver_match = re.search(r"v\d+(\.\d+)*(-[a-zA-Z0-9]+)?", comp)
            ver_label = ver_match.group(0) if ver_match else m["version_dir"]
            descriptions.append(f"{ver_label} ({comp})")

        return ", ".join(dict.fromkeys(descriptions))

    def find_topology_upgrade(
        self,
        filename: str,
        installed_version: Optional[str] = None,
        installed_md5: Optional[str] = None,
        fw_version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find if a topology file can be upgraded from sof-bin to match installed FW version or newest available release.
        Returns upgrade info dict if an upgrade is available, else None.
        """
        candidates: List[Dict[str, Any]] = []

        target_vdirs = self.get_version_dirs()
        if fw_version:
            norm_fw = fw_version.lstrip("v")
            parts = norm_fw.split(".")
            major_minor_prefix = f"v{parts[0]}.{parts[1]}" if len(parts) >= 2 else f"v{parts[0]}"
            matching_vdirs = [v for v in target_vdirs if v.name.startswith(major_minor_prefix)]
            if matching_vdirs:
                target_vdirs = matching_vdirs + [v for v in target_vdirs if v not in matching_vdirs]

        for vdir in target_vdirs:
            for item in vdir.iterdir():
                if item.is_dir() and item.name.startswith(("sof-ipc4-tplg", "sof-ace-tplg", "sof-tplg")):
                    file_p = item / filename
                    if file_p.is_file():
                        m = re.search(r"v\d+(\.\d+)*(-[a-zA-Z0-9]+)?", item.name)
                        cand_ver = m.group(0) if m else vdir.name
                        cand_tup = parse_version_tuple(cand_ver)
                        md5_val = compute_file_md5(file_p)
                        candidates.append({
                            "version_dir": vdir.name,
                            "component": item.name,
                            "version": cand_ver,
                            "version_tuple": cand_tup or (0,),
                            "filename": filename,
                            "rel_path": f"sof-ipc4-tplg/{filename}" if item.name.startswith("sof-ipc4") else f"sof-tplg/{filename}",
                            "full_path": str(file_p),
                            "md5": md5_val,
                        })

        if not candidates:
            return None

        # Sort candidates by version tuple descending
        candidates.sort(key=lambda x: (x["version_tuple"], x["version"]), reverse=True)
        best_cand = candidates[0]

        # If installed file already matches the best candidate checksum, no upgrade needed
        if installed_md5 and best_cand["md5"] and installed_md5.lower() == best_cand["md5"].lower():
            return None

        inst_tup = parse_version_tuple(installed_version)
        cand_tup = best_cand["version_tuple"]

        is_newer = False
        if inst_tup and cand_tup:
            max_len = max(len(inst_tup), len(cand_tup), 3)
            norm_inst = inst_tup + (0,) * (max_len - len(inst_tup))
            norm_cand = cand_tup + (0,) * (max_len - len(cand_tup))
            if norm_cand > norm_inst:
                is_newer = True
            elif norm_cand == norm_inst and installed_version != best_cand["version"]:
                is_newer = True
        elif not inst_tup or installed_version in ("-", "unknown", "broken link"):
            is_newer = True

        if is_newer:
            reason = f"Upgrade available to match FW {fw_version}" if fw_version else "Newer topology available in sof-bin"
            return {
                "target_version": best_cand["version"],
                "component": best_cand["component"],
                "filename": filename,
                "rel_path": best_cand["rel_path"],
                "source_path": best_cand["full_path"],
                "md5": best_cand["md5"],
                "fw_version": fw_version,
                "reason": reason,
            }

        return None


class HostTarget:
    """Interface to read, check, and fix files on target host (local or remote)."""

    def is_remote(self) -> bool:
        return False

    def batch_query(self, paths: List[str]) -> Dict[str, Tuple[bool, bool, Optional[int], Optional[str], Optional[str], Optional[Dict[str, Any]]]]:
        raise NotImplementedError

    def fix_file(
        self,
        source_path: str,
        target_path: str,
        is_symlink: bool,
        symlink_target: Optional[str],
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        raise NotImplementedError

    def scan_installed_files(self, fw_dest: str = "/lib/firmware/intel", tools_dest: str = "/usr/local/bin") -> List[Dict[str, Any]]:
        raise NotImplementedError


class LocalHostTarget(HostTarget):
    """Local filesystem host target."""

    def __init__(self, target_root: Optional[Path] = None):
        self.target_root = target_root.resolve() if target_root else None

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if self.target_root and p.is_absolute():
            rel = str(p).lstrip("/")
            return self.target_root / rel
        elif self.target_root:
            return self.target_root / p
        return p

    def is_remote(self) -> bool:
        return False

    def batch_query(self, paths: List[str]) -> Dict[str, Tuple[bool, bool, Optional[int], Optional[str], Optional[str], Optional[Dict[str, Any]]]]:
        results = {}
        for p_str in paths:
            p = self._resolve(p_str)
            is_sym = p.is_symlink()
            exists = p.exists() or is_sym
            size = None
            target = None
            md5_val = None
            man_info = None

            if is_sym:
                try:
                    target = os.readlink(p)
                except OSError:
                    target = None
                try:
                    resolved = p.resolve()
                    if resolved.is_file():
                        size = resolved.stat().st_size
                        raw_data = resolved.read_bytes()
                        md5_val = hashlib.md5(raw_data).hexdigest()
                        man_info = parse_binary_manifest(raw_data)
                except OSError:
                    pass
            elif exists and p.is_file():
                try:
                    size = p.stat().st_size
                    raw_data = p.read_bytes()
                    md5_val = hashlib.md5(raw_data).hexdigest()
                    man_info = parse_binary_manifest(raw_data)
                except OSError:
                    pass

            results[p_str] = (exists, is_sym, size, target, md5_val, man_info)
        return results

    def fix_file(
        self,
        source_path: str,
        target_path: str,
        is_symlink: bool,
        symlink_target: Optional[str],
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        real_tgt = self._resolve(target_path)
        if dry_run:
            if is_symlink:
                return True, f"[DRY-RUN] Would create symlink {real_tgt} -> {symlink_target}"
            return True, f"[DRY-RUN] Would copy {source_path} -> {real_tgt}"

        try:
            real_tgt.parent.mkdir(parents=True, exist_ok=True)
            if real_tgt.exists() or real_tgt.is_symlink():
                real_tgt.unlink()

            if is_symlink:
                if not symlink_target:
                    return False, f"Cannot create symlink at {real_tgt}: missing symlink target"
                os.symlink(symlink_target, real_tgt)
                return True, f"Created symlink {real_tgt} -> {symlink_target}"
            else:
                shutil.copy2(source_path, real_tgt)
                return True, f"Copied {source_path} -> {real_tgt}"
        except PermissionError:
            return False, f"Permission denied writing to {real_tgt}. Please re-run with sudo or check permissions."
        except Exception as e:
            return False, f"Error fixing {real_tgt}: {e}"

    def scan_installed_files(self, fw_dest: str = "/lib/firmware/intel", tools_dest: str = "/usr/local/bin") -> List[Dict[str, Any]]:
        results = []
        real_fw = self._resolve(fw_dest)
        if real_fw.is_dir():
            for root, _, files in os.walk(real_fw):
                for name in files:
                    p = Path(root) / name
                    rel = str(p.relative_to(real_fw))
                    is_sym = p.is_symlink()
                    sym_target = os.readlink(p) if is_sym else None
                    md5_val = None
                    size = None
                    man_info = None
                    if is_sym:
                        try:
                            resolved = p.resolve()
                            if resolved.is_file():
                                size = resolved.stat().st_size
                                raw_data = resolved.read_bytes()
                                md5_val = hashlib.md5(raw_data).hexdigest()
                                man_info = parse_binary_manifest(raw_data)
                        except OSError:
                            pass
                    elif p.is_file():
                        try:
                            size = p.stat().st_size
                            raw_data = p.read_bytes()
                            md5_val = hashlib.md5(raw_data).hexdigest()
                            man_info = parse_binary_manifest(raw_data)
                        except OSError:
                            pass
                    results.append({
                        "path_type": "fw",
                        "rel_path": rel,
                        "full_path": f"{fw_dest.rstrip('/')}/{rel}",
                        "filename": name,
                        "is_symlink": is_sym,
                        "symlink_target": sym_target,
                        "size": size,
                        "md5": md5_val,
                        "manifest": man_info,
                    })

        real_tools = self._resolve(tools_dest)
        if real_tools.is_dir():
            for name in os.listdir(real_tools):
                p = real_tools / name
                if name.startswith(("sof-", "mtrace-")) or name in ("sof-logger", "sof-probes", "sof-coredump", "sof-ctl"):
                    is_sym = p.is_symlink()
                    sym_target = os.readlink(p) if is_sym else None
                    md5_val = None
                    size = None
                    man_info = None
                    if is_sym:
                        try:
                            resolved = p.resolve()
                            if resolved.is_file():
                                size = resolved.stat().st_size
                                raw_data = resolved.read_bytes()
                                md5_val = hashlib.md5(raw_data).hexdigest()
                                man_info = parse_binary_manifest(raw_data)
                        except OSError:
                            pass
                    elif p.is_file():
                        try:
                            size = p.stat().st_size
                            raw_data = p.read_bytes()
                            md5_val = hashlib.md5(raw_data).hexdigest()
                            man_info = parse_binary_manifest(raw_data)
                        except OSError:
                            pass
                    results.append({
                        "path_type": "tools",
                        "rel_path": f"tools/{name}",
                        "full_path": f"{tools_dest.rstrip('/')}/{name}",
                        "filename": name,
                        "is_symlink": is_sym,
                        "symlink_target": sym_target,
                        "size": size,
                        "md5": md5_val,
                        "manifest": man_info,
                    })
        return results


def extract_deb(deb_path: Path, dest_dir: Path) -> Dict[str, Any]:
    """Extract Debian package (.deb) into dest_dir and return package metadata."""
    meta: Dict[str, Any] = {"package_type": "deb", "file": deb_path.name, "path": str(deb_path)}

    extracted = False
    if shutil.which("dpkg-deb"):
        try:
            subprocess.run(["dpkg-deb", "-x", str(deb_path), str(dest_dir)], check=True, capture_output=True)
            extracted = True
        except subprocess.SubprocessError:
            extracted = False

    if not extracted:
        data = deb_path.read_bytes()
        if not data.startswith(b"!<arch>\n"):
            raise ValueError(f"Invalid Debian package (missing ar magic): {deb_path}")
        pos = 8
        members: Dict[str, bytes] = {}
        while pos + 60 <= len(data):
            hdr = data[pos : pos + 60]
            name = hdr[:16].decode("ascii", "replace").strip().rstrip("/")
            size_str = hdr[48:58].decode("ascii", "replace").strip()
            size = int(size_str) if size_str.isdigit() else 0
            member_data = data[pos + 60 : pos + 60 + size]
            members[name] = member_data
            pos += 60 + size + (1 if size % 2 == 1 else 0)

        data_arch_name = next((k for k in members if k.startswith("data.tar")), None)
        if not data_arch_name:
            raise ValueError(f"No data.tar member found in Debian package: {deb_path}")

        data_payload = members[data_arch_name]
        try:
            with tarfile.open(fileobj=io.BytesIO(data_payload), mode="r:*") as tar:
                tar.extractall(dest_dir)
        except Exception:
            p = subprocess.Popen(["tar", "-xf", "-", "-C", str(dest_dir)], stdin=subprocess.PIPE)
            p.communicate(input=data_payload)
            if p.returncode != 0:
                raise RuntimeError(f"Failed to extract {data_arch_name} from {deb_path}")

        ctrl_arch_name = next((k for k in members if k.startswith("control.tar")), None)
        if ctrl_arch_name:
            try:
                with tarfile.open(fileobj=io.BytesIO(members[ctrl_arch_name]), mode="r:*") as tar:
                    for member in tar.getmembers():
                        if member.name.endswith("control") or member.name == "control":
                            f = tar.extractfile(member)
                            if f:
                                for line in f.read().decode("utf-8", "replace").splitlines():
                                    if ":" in line:
                                        k, v = line.split(":", 1)
                                        meta[k.strip().lower()] = v.strip()
            except Exception:
                pass

    if "package" not in meta and shutil.which("dpkg-deb"):
        try:
            res = subprocess.run(["dpkg-deb", "-f", str(deb_path)], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
        except Exception:
            pass

    return meta


def extract_rpm(rpm_path: Path, dest_dir: Path) -> Dict[str, Any]:
    """Extract RPM package (.rpm) into dest_dir and return package metadata."""
    meta: Dict[str, Any] = {"package_type": "rpm", "file": rpm_path.name, "path": str(rpm_path)}

    extracted = False
    if shutil.which("rpm2cpio") and shutil.which("cpio"):
        try:
            p1 = subprocess.Popen(["rpm2cpio", str(rpm_path)], stdout=subprocess.PIPE)
            p2 = subprocess.Popen(["cpio", "-idmv"], stdin=p1.stdout, cwd=str(dest_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p1.stdout:
                p1.stdout.close()
            p2.communicate()
            p1.wait()
            if p2.returncode == 0:
                extracted = True
        except Exception:
            extracted = False

    if not extracted and shutil.which("rpm2archive") and shutil.which("tar"):
        try:
            with open(rpm_path, "rb") as fh:
                p1 = subprocess.Popen(["rpm2archive", "-n"], stdin=fh, stdout=subprocess.PIPE)
                p2 = subprocess.Popen(["tar", "-C", str(dest_dir), "-xf", "-"], stdin=p1.stdout)
                if p1.stdout:
                    p1.stdout.close()
                p2.communicate()
                p1.wait()
                if p2.returncode == 0:
                    extracted = True
        except Exception:
            extracted = False

    if not extracted:
        raise RuntimeError(f"Could not extract RPM package {rpm_path}: requires rpm2cpio + cpio or rpm2archive + tar")

    if shutil.which("rpm"):
        try:
            res = subprocess.run(
                ["rpm", "-qp", "--queryformat", "%{NAME}\n%{VERSION}\n%{RELEASE}\n%{ARCH}\n%{SUMMARY}", str(rpm_path)],
                capture_output=True,
                text=True,
            )
            lines = res.stdout.strip().splitlines()
            if len(lines) >= 4:
                meta["package"] = lines[0].strip()
                meta["version"] = f"{lines[1].strip()}-{lines[2].strip()}"
                meta["architecture"] = lines[3].strip()
                if len(lines) >= 5:
                    meta["description"] = lines[4].strip()
        except Exception:
            pass

    return meta


def extract_package(pkg_path: Path, dest_dir: Path) -> Dict[str, Any]:
    """Auto-detect package format (.deb or .rpm) and extract into dest_dir."""
    try:
        with open(pkg_path, "rb") as f:
            magic = f.read(8)
    except OSError as e:
        raise FileNotFoundError(f"Cannot read package file {pkg_path}: {e}")

    if magic.startswith(b"!<arch>\n") or pkg_path.suffix == ".deb":
        return extract_deb(pkg_path, dest_dir)
    elif magic.startswith(b"\xed\xab\xee\xdb") or pkg_path.suffix == ".rpm":
        return extract_rpm(pkg_path, dest_dir)
    else:
        raise ValueError(f"Unsupported package format: {pkg_path.name} (magic: {magic[:4]!r})")


def collect_packages(pkg_args: List[str]) -> List[Path]:
    """Collect and resolve list of package paths from arguments (handles directories and commas)."""
    collected = []
    for item in pkg_args:
        for p_str in item.split(","):
            p_str = p_str.strip()
            if not p_str:
                continue
            p = Path(p_str).resolve()
            if p.is_dir():
                found = sorted(list(p.glob("*.deb")) + list(p.glob("*.rpm")))
                if not found:
                    raise FileNotFoundError(f"No .deb or .rpm packages found in directory: {p}")
                collected.extend(found)
            elif p.is_file():
                collected.append(p)
            else:
                raise FileNotFoundError(f"Package file or directory not found: {p_str}")
    return collected


class PackageTarget(HostTarget):
    """Target host backed by extracted .deb or .rpm packages in a managed temporary directory."""

    def __init__(self, packages: List[Path], temp_dir: Optional[tempfile.TemporaryDirectory] = None):
        self.packages = [Path(p).resolve() for p in packages]
        self._temp_dir_obj = temp_dir or tempfile.TemporaryDirectory(prefix="sof_pkg_")
        self.target_root = Path(self._temp_dir_obj.name)
        self.package_metadata: List[Dict[str, Any]] = []
        self._delegate = LocalHostTarget(target_root=self.target_root)
        self._extract_all()

    def _extract_all(self):
        for pkg in self.packages:
            if not pkg.is_file():
                raise FileNotFoundError(f"Package file not found: {pkg}")
            meta = extract_package(pkg, self.target_root)
            self.package_metadata.append(meta)

    def is_remote(self) -> bool:
        return False

    def batch_query(self, paths: List[str]) -> Dict[str, Tuple[bool, bool, Optional[int], Optional[str], Optional[str], Optional[Dict[str, Any]]]]:
        return self._delegate.batch_query(paths)

    def fix_file(
        self,
        source_path: str,
        target_path: str,
        is_symlink: bool,
        symlink_target: Optional[str],
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        return self._delegate.fix_file(source_path, target_path, is_symlink, symlink_target, dry_run)

    def scan_installed_files(self, fw_dest: str = "/lib/firmware/intel", tools_dest: str = "/usr/local/bin") -> List[Dict[str, Any]]:
        return self._delegate.scan_installed_files(fw_dest, tools_dest)

    def cleanup(self):
        if self._temp_dir_obj:
            try:
                self._temp_dir_obj.cleanup()
            except Exception:
                pass


def _build_remote_manifest_script() -> str:
    return (
        "import sys, os, json, hashlib, struct, re\n"
        "def parse_man(data):\n"
        "    if not data: return {}\n"
        "    info = {}\n"
        "    p_mn2 = data.find(b'$MN2')\n"
        "    if p_mn2 != -1 and p_mn2 >= 8:\n"
        "        try:\n"
        "            d_raw = struct.unpack_from('<I', data, p_mn2 - 8)[0]\n"
        "            y = ((d_raw >> 28) & 0xf) * 1000 + ((d_raw >> 24) & 0xf) * 100 + ((d_raw >> 20) & 0xf) * 10 + ((d_raw >> 16) & 0xf)\n"
        "            m = ((d_raw >> 12) & 0xf) * 10 + ((d_raw >> 8) & 0xf)\n"
        "            d = ((d_raw >> 4) & 0xf) * 10 + (d_raw & 0xf)\n"
        "            if 1970 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31:\n"
        "                info['build_date'] = f'{y:04d}-{m:02d}-{d:02d}'\n"
        "        except Exception: pass\n"
        "    p_am1 = data.find(b'$AM1')\n"
        "    if p_am1 != -1 and p_am1 + 52 <= len(data):\n"
        "        try:\n"
        "            hdr_id, hdr_len, name, preload, flags, feat, maj, min_v, hotfix, bld, num_mods = struct.unpack_from('<4sI8sIIIHHHHI', data, p_am1)\n"
        "            if maj == 0:\n"
        "                ver_str = f'v{min_v}.{hotfix}.{bld}'\n"
        "            elif bld in (0, 1):\n"
        "                ver_str = f'v{maj}.{min_v}.{hotfix}'\n"
        "            else:\n"
        "                ver_str = f'v{maj}.{min_v}.{hotfix}.{bld}'\n"
        "            info['manifest_version'] = ver_str\n"
        "            ns = name.decode('ascii', 'replace').strip('\\x00')\n"
        "            if ns: info['component_name'] = ns\n"
        "            info['modules_count'] = num_mods & 0xffff\n"
        "        except Exception: pass\n"
        "    p_xman = data.find(b'XMan')\n"
        "    if p_xman != -1 and p_xman + 16 <= len(data):\n"
        "        try:\n"
        "            _, full_sz, hdr_sz, _ = struct.unpack_from('<IIII', data, p_xman)\n"
        "            off = p_xman + hdr_sz\n"
        "            end = min(p_xman + full_sz, len(data))\n"
        "            while off + 8 <= end:\n"
        "                et, esz = struct.unpack_from('<II', data, off)\n"
        "                if esz == 0: break\n"
        "                if et == 0 and off + 16 + 44 <= len(data):\n"
        "                    v_off = off + 16\n"
        "                    maj, min_v, mic, bld = struct.unpack_from('<HHHH', data, v_off)\n"
        "                    db = data[v_off+8:v_off+20].split(b'\\x00')[0].decode('ascii', 'replace').strip()\n"
        "                    tb = data[v_off+20:v_off+30].split(b'\\x00')[0].decode('ascii', 'replace').strip()\n"
        "                    tag = data[v_off+30:v_off+36].split(b'\\x00')[0].decode('ascii', 'replace').strip()\n"
        "                    abi, src_h = struct.unpack_from('<II', data, v_off+36)\n"
        "                    if not info.get('manifest_version'):\n"
        "                        if maj == 0:\n"
        "                            info['manifest_version'] = f'v{min_v}.{mic}.{bld}'\n"
        "                        elif bld in (0, 1):\n"
        "                            info['manifest_version'] = f'v{maj}.{min_v}.{mic}'\n"
        "                        else:\n"
        "                            info['manifest_version'] = f'v{maj}.{min_v}.{mic}.{bld}'\n"
        "                    if db and not info.get('build_date'): info['build_date'] = db\n"
        "                    if tb: info['build_time'] = tb\n"
        "                    if tag: info['sof_tag'] = tag\n"
        "                    if abi: info['abi_version'] = f'0x{abi:x}'\n"
        "                off += esz\n"
        "        except Exception: pass\n"
        "    zm = re.search(rb'Booting Zephyr OS build ([^\\s\\*\\r\\n\\x00]+)', data)\n"
        "    if zm: info['zephyr_build'] = zm.group(1).decode('ascii', 'replace').strip()\n"
        "    fm = re.search(rb'tags SOF:([^\\s\\x00]+) zephyr:([^\\s\\x00]+)', data)\n"
        "    if fm:\n"
        "        info['sof_tag'] = fm.group(1).decode('ascii', 'replace')\n"
        "        info['zephyr_tag'] = fm.group(2).decode('ascii', 'replace')\n"
        "    p_cosa = data.find(b'CoSA')\n"
        "    if p_cosa != -1:\n"
        "        try:\n"
        "            off = p_cosa\n"
        "            while off + 36 <= len(data):\n"
        "                if data[off:off+4] != b'CoSA': break\n"
        "                _, _, _, tt, _, _, psz, _, _ = struct.unpack_from('<IIIIIIIII', data, off)\n"
        "                if tt == 8 and psz >= 112:\n"
        "                    mdata = data[off+36 : off+36+psz]\n"
        "                    pvsz = struct.unpack_from('<I', mdata, 108)[0]\n"
        "                    pvdata = mdata[112:112+pvsz]\n"
        "                    if len(pvdata) >= 6:\n"
        "                        amaj, amin, ap = struct.unpack_from('<HHH', pvdata, 0)\n"
        "                        info['tplg_abi'] = f'{amaj}.{amin}.{ap}'\n"
        "                    break\n"
        "                off += 36 + psz\n"
        "        except Exception: pass\n"
        "    return info\n"
    )


class RemoteSshTarget(HostTarget):
    """Remote host target accessed via SSH."""

    def __init__(self, ssh_host: str, target_root: Optional[str] = None):
        self.ssh_host = ssh_host
        self.target_root = target_root

    def is_remote(self) -> bool:
        return True

    def _format_remote_path(self, path: str) -> str:
        if self.target_root and path.startswith("/"):
            return os.path.join(self.target_root, path.lstrip("/"))
        return path

    def batch_query(self, paths: List[str]) -> Dict[str, Tuple[bool, bool, Optional[int], Optional[str], Optional[str], Optional[Dict[str, Any]]]]:
        results: Dict[str, Tuple[bool, bool, Optional[int], Optional[str], Optional[str], Optional[Dict[str, Any]]]] = {}
        if not paths:
            return results

        remote_paths = {p: self._format_remote_path(p) for p in paths}
        payload = json.dumps(remote_paths)

        remote_script = (
            _build_remote_manifest_script() +
            "paths = json.loads(sys.stdin.read())\n"
            "out = {}\n"
            "for orig, target in paths.items():\n"
            "    is_sym = os.path.islink(target)\n"
            "    exists = os.path.exists(target) or is_sym\n"
            "    size = None\n"
            "    sym_target = None\n"
            "    md5_val = None\n"
            "    man_info = None\n"
            "    if is_sym:\n"
            "        try: sym_target = os.readlink(target)\n"
            "        except Exception: pass\n"
            "    if exists:\n"
            "        try:\n"
            "            real_path = os.path.realpath(target) if is_sym else target\n"
            "            if os.path.isfile(real_path):\n"
            "                size = os.path.getsize(real_path)\n"
            "                with open(real_path, 'rb') as f:\n"
            "                    raw_data = f.read()\n"
            "                md5_val = hashlib.md5(raw_data).hexdigest()\n"
            "                man_info = parse_man(raw_data)\n"
            "        except Exception: pass\n"
            "    out[orig] = [exists, is_sym, size, sym_target, md5_val, man_info]\n"
            "print(json.dumps(out))\n"
        )

        b64_script = base64.b64encode(remote_script.encode("utf-8")).decode("ascii")
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            self.ssh_host,
            f"python3 -c \"import base64; exec(base64.b64decode('{b64_script}'))\"",
        ]

        try:
            proc = subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            raw_out = json.loads(proc.stdout.strip())
            for orig_p, (exists, is_sym, size, sym_tgt, md5_val, man_info) in raw_out.items():
                results[orig_p] = (exists, is_sym, size, sym_tgt, md5_val, man_info)
        except Exception as e:
            sys.stderr.write(f"Warning: Remote python inspection failed ({e}), using fallback.\n")
            results = self._shell_fallback_batch(paths)

        return results

    def _shell_fallback_batch(self, paths: List[str]) -> Dict[str, Tuple[bool, bool, Optional[int], Optional[str], Optional[str], Optional[Dict[str, Any]]]]:
        results: Dict[str, Tuple[bool, bool, Optional[int], Optional[str], Optional[str], Optional[Dict[str, Any]]]] = {}
        for p in paths:
            rem_p = self._format_remote_path(p)
            q_rem_p = shlex.quote(rem_p)
            shell_cmd = (
                f'if [ -L {q_rem_p} ]; then '
                f'  echo "SYM $(readlink {q_rem_p})"; '
                f'  if [ -f {q_rem_p} ]; then md5sum {q_rem_p} 2>/dev/null | awk \'{{print $1}}\'; else echo "BROKEN"; fi; '
                f'elif [ -f {q_rem_p} ]; then '
                f'  echo "FILE $(stat -c %s {q_rem_p} 2>/dev/null || echo 0)"; '
                f'  md5sum {q_rem_p} 2>/dev/null | awk \'{{print $1}}\'; '
                f'else echo "MISSING"; fi'
            )
            try:
                proc = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", self.ssh_host, shell_cmd],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
                if not lines or lines[0] == "MISSING":
                    results[p] = (False, False, None, None, None, None)
                elif lines[0].startswith("SYM"):
                    sym_tgt = lines[0][4:].strip()
                    md5_val = lines[1] if len(lines) > 1 and lines[1] != "BROKEN" else None
                    results[p] = (True, True, None, sym_tgt, md5_val, None)
                elif lines[0].startswith("FILE"):
                    size_val = int(lines[0][5:].strip()) if lines[0][5:].strip().isdigit() else None
                    md5_val = lines[1] if len(lines) > 1 else None
                    results[p] = (True, False, size_val, None, md5_val, None)
            except Exception:
                results[p] = (False, False, None, None, None, None)
        return results

    def fix_file(
        self,
        source_path: str,
        target_path: str,
        is_symlink: bool,
        symlink_target: Optional[str],
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        rem_p = self._format_remote_path(target_path)
        if dry_run:
            if is_symlink:
                return True, f"[DRY-RUN] Would create remote symlink {rem_p} -> {symlink_target} via SSH"
            return True, f"[DRY-RUN] Would scp {source_path} -> {self.ssh_host}:{rem_p}"

        try:
            parent_dir = os.path.dirname(rem_p)
            subprocess.run(
                ["ssh", "-o", "BatchMode=yes", self.ssh_host, f'mkdir -p "{parent_dir}"'],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )

            if is_symlink:
                if not symlink_target:
                    return False, f"Cannot create remote symlink at {rem_p}: missing symlink target"
                cmd = f'rm -f "{rem_p}" && ln -sf "{symlink_target}" "{rem_p}"'
                subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", self.ssh_host, cmd],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                return True, f"Created remote symlink {rem_p} -> {symlink_target}"
            else:
                subprocess.run(
                    ["scp", "-o", "BatchMode=yes", "-p", source_path, f"{self.ssh_host}:{rem_p}"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return True, f"Transferred {source_path} -> {self.ssh_host}:{rem_p}"
        except (subprocess.SubprocessError, OSError, Exception) as e:
            return False, f"SSH/SCP error fixing {rem_p}: {e}"

    def scan_installed_files(self, fw_dest: str = "/lib/firmware/intel", tools_dest: str = "/usr/local/bin") -> List[Dict[str, Any]]:
        rem_fw = self._format_remote_path(fw_dest)
        rem_tools = self._format_remote_path(tools_dest)
        payload = json.dumps({"fw_dest": rem_fw, "tools_dest": rem_tools})

        remote_script = (
            _build_remote_manifest_script() +
            "cfg = json.loads(sys.stdin.read())\n"
            "fw_dest = cfg['fw_dest']\n"
            "tools_dest = cfg['tools_dest']\n"
            "out = []\n"
            "if os.path.isdir(fw_dest):\n"
            "    for root, _, files in os.walk(fw_dest):\n"
            "        for f in files:\n"
            "            fp = os.path.join(root, f)\n"
            "            rel = os.path.relpath(fp, fw_dest)\n"
            "            is_sym = os.path.islink(fp)\n"
            "            sym_tgt = os.readlink(fp) if is_sym else None\n"
            "            real_fp = os.path.realpath(fp) if is_sym else fp\n"
            "            sz = os.path.getsize(real_fp) if os.path.isfile(real_fp) else None\n"
            "            md5 = None\n"
            "            man_info = None\n"
            "            if os.path.isfile(real_fp):\n"
            "                try:\n"
            "                    with open(real_fp, 'rb') as fh: rdata = fh.read()\n"
            "                    md5 = hashlib.md5(rdata).hexdigest()\n"
            "                    man_info = parse_man(rdata)\n"
            "                except Exception: pass\n"
            "            out.append({\n"
            "                'path_type': 'fw',\n"
            "                'rel_path': rel,\n"
            "                'full_path': fp,\n"
            "                'filename': f,\n"
            "                'is_symlink': is_sym,\n"
            "                'symlink_target': sym_tgt,\n"
            "                'size': sz,\n"
            "                'md5': md5,\n"
            "                'manifest': man_info,\n"
            "            })\n"
            "if os.path.isdir(tools_dest):\n"
            "    for f in os.listdir(tools_dest):\n"
            "        if f.startswith(('sof-', 'mtrace-')) or f in ('sof-logger', 'sof-probes', 'sof-coredump', 'sof-ctl'):\n"
            "            fp = os.path.join(tools_dest, f)\n"
            "            is_sym = os.path.islink(fp)\n"
            "            sym_tgt = os.readlink(fp) if is_sym else None\n"
            "            real_fp = os.path.realpath(fp) if is_sym else fp\n"
            "            sz = os.path.getsize(real_fp) if os.path.isfile(real_fp) else None\n"
            "            md5 = None\n"
            "            man_info = None\n"
            "            if os.path.isfile(real_fp):\n"
            "                try:\n"
            "                    with open(real_fp, 'rb') as fh: rdata = fh.read()\n"
            "                    md5 = hashlib.md5(rdata).hexdigest()\n"
            "                    man_info = parse_man(rdata)\n"
            "                except Exception: pass\n"
            "            out.append({\n"
            "                'path_type': 'tools',\n"
            "                'rel_path': 'tools/' + f,\n"
            "                'full_path': fp,\n"
            "                'filename': f,\n"
            "                'is_symlink': is_sym,\n"
            "                'symlink_target': sym_tgt,\n"
            "                'size': sz,\n"
            "                'md5': md5,\n"
            "                'manifest': man_info,\n"
            "            })\n"
            "print(json.dumps(out))\n"
        )

        b64_script = base64.b64encode(remote_script.encode("utf-8")).decode("ascii")
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            self.ssh_host,
            f"python3 -c \"import base64; exec(base64.b64decode('{b64_script}'))\"",
        ]
        try:
            proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, check=True, timeout=60)
            return json.loads(proc.stdout.strip())
        except Exception as e:
            sys.stderr.write(f"Warning: Remote python file scan failed ({e}).\n")
            return []



def is_downgrade(rec: ValidationRecord, target_version: Optional[str] = None) -> bool:
    """
    Check if replacing installed file with expected file would be a downgrade.
    Returns True if installed version on host is strictly newer than expected target version.
    """
    if rec.status == Status.MISSING:
        return False
    if not rec.installed_version or rec.installed_version in ("-", "unknown", "broken", "broken link", "target mismatch", "error"):
        return False

    inst_tup = parse_version_tuple(rec.installed_version)
    exp_tup = parse_version_tuple(rec.expected_version or target_version)

    if inst_tup and exp_tup:
        max_len = max(len(inst_tup), len(exp_tup), 3)
        norm_inst = inst_tup + (0,) * (max_len - len(inst_tup))
        norm_exp = exp_tup + (0,) * (max_len - len(exp_tup))
        if norm_inst > norm_exp:
            return True
        if norm_inst < norm_exp:
            return False

    # Check manifest metadata (manifest version and build dates)
    if rec.actual_manifest and rec.expected_manifest:
        act_man_ver = rec.actual_manifest.get("manifest_version")
        exp_man_ver = rec.expected_manifest.get("manifest_version")
        if act_man_ver and exp_man_ver:
            m_inst_tup = parse_version_tuple(act_man_ver)
            m_exp_tup = parse_version_tuple(exp_man_ver)
            if m_inst_tup and m_exp_tup:
                max_len = max(len(m_inst_tup), len(m_exp_tup), 3)
                norm_m_inst = m_inst_tup + (0,) * (max_len - len(m_inst_tup))
                norm_m_exp = m_exp_tup + (0,) * (max_len - len(m_exp_tup))
                if norm_m_inst > norm_m_exp:
                    return True
                if norm_m_inst < norm_m_exp:
                    return False

        act_date = rec.actual_manifest.get("build_date")
        exp_date = rec.expected_manifest.get("build_date")
        if act_date and exp_date:
            if act_date > exp_date:
                return True

    return False


class SofValidator:
    """Main verification and repair engine."""

    def __init__(
        self,
        repo: SofBinRepo,
        target: HostTarget,
        fw_dest: str = "/lib/firmware/intel",
        tools_dest: str = "/usr/local/bin",
        platform_filter: Optional[Set[str]] = None,
        flavor_filter: Optional[str] = None,
        component_filter: Optional[Set[str]] = None,
        strict: bool = False,
    ):
        self.repo = repo
        self.target = target
        self.fw_dest = fw_dest.rstrip("/")
        self.tools_dest = tools_dest.rstrip("/")
        self.platform_filter = platform_filter
        self.flavor_filter = flavor_filter
        self.component_filter = component_filter or {"fw", "llext", "tplg", "tools"}
        self.strict = strict

    def extract_platform_from_path(self, component: str, rel_path: str) -> str:
        parts = rel_path.split("/")
        if component in ("fw", "llext"):
            for part in parts:
                if part in ("community", "intel-signed"):
                    continue
                clean = part.replace("sof-ipc4-lib-", "").replace("sof-ipc4-", "").replace("sof-", "")
                if clean in ("tgl", "tgl-h", "mtl", "arl", "arl-s", "ptl", "lnl", "adl", "adl-s", "adl-n", "rpl", "rpl-s", "ehl", "icl", "jsl", "cml", "cnl", "cfl", "glk", "apl", "byt", "cht", "bdw", "wcl"):
                    return clean
        elif component == "tplg":
            base = parts[-1]
            m = re.match(r"^sof-([a-zA-Z0-9]+(-[shn])?)-", base)
            if m:
                return m.group(1)
            if "hda-generic" in base:
                return "generic-hda"
        return "generic"

    def should_include(self, component: str, platform: str, rel_path: str) -> bool:
        if self.component_filter and component not in self.component_filter:
            return False

        if self.flavor_filter and self.flavor_filter != "all":
            if self.flavor_filter == "community" and "/intel-signed/" in f"/{rel_path}/":
                return False
            if self.flavor_filter == "intel-signed" and "/community/" in f"/{rel_path}/":
                return False

        if self.platform_filter:
            matched = False
            for p in self.platform_filter:
                if platform == p or platform.startswith(p + "-") or p == "all":
                    matched = True
                    break
                if component in ("tplg", "tools") and platform in ("generic", "generic-hda"):
                    matched = True
                    break
            if not matched:
                return False

        return True

    def scan_source_components(self, comp_dirs: Dict[str, Path], target_version: str) -> List[ValidationRecord]:
        records: List[ValidationRecord] = []

        # 1. Firmware
        if "fw" in comp_dirs and "fw" in self.component_filter:
            fw_dir = comp_dirs["fw"]
            is_ipc4 = "ipc4" in fw_dir.name
            radix = "sof-ipc4" if is_ipc4 else "sof"
            ver_match = re.search(r"v\d+(\.\d+)*(-[a-zA-Z0-9]+)?", fw_dir.name)
            fw_ver = ver_match.group(0) if ver_match else target_version

            for root, _, files in os.walk(fw_dir):
                for f in files:
                    src_p = Path(root) / f
                    rel_to_comp = src_p.relative_to(fw_dir)
                    rel_install = f"{radix}/{rel_to_comp}"
                    platform = self.extract_platform_from_path("fw", str(rel_to_comp))

                    if not self.should_include("fw", platform, str(rel_to_comp)):
                        continue

                    is_sym = src_p.is_symlink()
                    sym_tgt = os.readlink(src_p) if is_sym else None
                    target_file = src_p.resolve() if is_sym else src_p
                    expected_md5 = compute_file_md5(src_p) if not is_sym else None
                    if is_sym and src_p.resolve().is_file():
                        expected_md5 = compute_file_md5(src_p.resolve())

                    expected_man = None
                    if target_file.is_file():
                        try:
                            expected_man = parse_binary_manifest(target_file.read_bytes())
                        except Exception:
                            pass

                    records.append(ValidationRecord(
                        component="fw",
                        platform=platform,
                        rel_path=rel_install,
                        expected_version=fw_ver,
                        source_path=str(src_p),
                        is_symlink=is_sym,
                        symlink_target_expected=sym_tgt,
                        expected_md5=expected_md5,
                        expected_size=src_p.stat().st_size if not is_sym else (src_p.resolve().stat().st_size if src_p.resolve().exists() else None),
                        expected_manifest=expected_man,
                    ))

        # 2. LLEXT
        if "llext" in comp_dirs and "llext" in self.component_filter:
            lib_dir = comp_dirs["llext"]
            ver_match = re.search(r"v\d+(\.\d+)*(-[a-zA-Z0-9]+)?", lib_dir.name)
            lib_ver = ver_match.group(0) if ver_match else target_version

            for root, _, files in os.walk(lib_dir):
                for f in files:
                    src_p = Path(root) / f
                    rel_to_comp = src_p.relative_to(lib_dir)
                    rel_install = f"sof-ipc4-lib/{rel_to_comp}"
                    platform = self.extract_platform_from_path("llext", str(rel_to_comp))

                    if not self.should_include("llext", platform, str(rel_to_comp)):
                        continue

                    is_sym = src_p.is_symlink()
                    sym_tgt = os.readlink(src_p) if is_sym else None
                    target_file = src_p.resolve() if is_sym else src_p
                    expected_md5 = compute_file_md5(src_p) if not is_sym else None
                    if is_sym and src_p.resolve().is_file():
                        expected_md5 = compute_file_md5(src_p.resolve())

                    expected_man = None
                    if target_file.is_file():
                        try:
                            expected_man = parse_binary_manifest(target_file.read_bytes())
                        except Exception:
                            pass

                    records.append(ValidationRecord(
                        component="llext",
                        platform=platform,
                        rel_path=rel_install,
                        expected_version=lib_ver,
                        source_path=str(src_p),
                        is_symlink=is_sym,
                        symlink_target_expected=sym_tgt,
                        expected_md5=expected_md5,
                        expected_size=src_p.stat().st_size if not is_sym else (src_p.resolve().stat().st_size if src_p.resolve().exists() else None),
                        expected_manifest=expected_man,
                    ))

        # 3. Topologies
        if "tplg" in comp_dirs and "tplg" in self.component_filter:
            tplg_dir = comp_dirs["tplg"]
            is_ipc4 = "ipc4" in tplg_dir.name or "ace" in tplg_dir.name
            radix = "sof-ipc4-tplg" if is_ipc4 else "sof-tplg"
            ver_match = re.search(r"v\d+(\.\d+)*(-[a-zA-Z0-9]+)?", tplg_dir.name)
            tplg_ver = ver_match.group(0) if ver_match else target_version

            for root, _, files in os.walk(tplg_dir):
                for f in files:
                    src_p = Path(root) / f
                    rel_to_comp = src_p.relative_to(tplg_dir)
                    rel_install = f"{radix}/{rel_to_comp}"
                    platform = self.extract_platform_from_path("tplg", f)

                    if not self.should_include("tplg", platform, str(rel_to_comp)):
                        continue

                    is_sym = src_p.is_symlink()
                    sym_tgt = os.readlink(src_p) if is_sym else None
                    target_file = src_p.resolve() if is_sym else src_p
                    expected_md5 = compute_file_md5(src_p) if not is_sym else None
                    if is_sym and src_p.resolve().is_file():
                        expected_md5 = compute_file_md5(src_p.resolve())

                    expected_man = None
                    if target_file.is_file():
                        try:
                            expected_man = parse_binary_manifest(target_file.read_bytes())
                        except Exception:
                            pass

                    records.append(ValidationRecord(
                        component="tplg",
                        platform=platform,
                        rel_path=rel_install,
                        expected_version=tplg_ver,
                        source_path=str(src_p),
                        is_symlink=is_sym,
                        symlink_target_expected=sym_tgt,
                        expected_md5=expected_md5,
                        expected_size=src_p.stat().st_size if not is_sym else (src_p.resolve().stat().st_size if src_p.resolve().exists() else None),
                        expected_manifest=expected_man,
                    ))

        # 4. Tools
        if "tools" in comp_dirs and "tools" in self.component_filter:
            tools_dir = comp_dirs["tools"]
            ver_match = re.search(r"v\d+(\.\d+)*(-[a-zA-Z0-9]+)?", tools_dir.name)
            tools_ver = ver_match.group(0) if ver_match else target_version

            for root, _, files in os.walk(tools_dir):
                for f in files:
                    src_p = Path(root) / f
                    rel_to_comp = src_p.relative_to(tools_dir)
                    rel_install = f"tools/{rel_to_comp}"
                    platform = "tools"

                    if not self.should_include("tools", platform, str(rel_to_comp)):
                        continue

                    is_sym = src_p.is_symlink()
                    sym_tgt = os.readlink(src_p) if is_sym else None
                    expected_md5 = compute_file_md5(src_p) if not is_sym else None
                    if is_sym and src_p.resolve().is_file():
                        expected_md5 = compute_file_md5(src_p.resolve())

                    records.append(ValidationRecord(
                        component="tools",
                        platform=platform,
                        rel_path=rel_install,
                        expected_version=tools_ver,
                        source_path=str(src_p),
                        is_symlink=is_sym,
                        symlink_target_expected=sym_tgt,
                        expected_md5=expected_md5,
                        expected_size=src_p.stat().st_size if not is_sym else (src_p.resolve().stat().st_size if src_p.resolve().exists() else None),
                    ))

        return records

    def validate_installation(self, version: str) -> List[ValidationRecord]:
        comp_dirs = self.repo.resolve_version_components(version)
        records = self.scan_source_components(comp_dirs, target_version=version)

        target_path_map: Dict[str, str] = {}
        for rec in records:
            if rec.component == "tools":
                tool_name = rec.rel_path.replace("tools/", "")
                tgt_p = f"{self.tools_dest}/{tool_name}"
            else:
                tgt_p = f"{self.fw_dest}/{rec.rel_path}"
            rec.target_path = tgt_p
            target_path_map[rec.rel_path] = tgt_p

        all_target_paths = list(target_path_map.values())
        query_results = self.target.batch_query(all_target_paths)

        for rec in records:
            tgt_p = rec.target_path
            stat_res = query_results.get(tgt_p, (False, False, None, None, None, None))
            exists, is_sym, size, sym_target, actual_md5, actual_manifest = stat_res

            rec.actual_size = size
            rec.actual_md5 = actual_md5
            rec.symlink_target_actual = sym_target
            rec.actual_manifest = actual_manifest

            if not exists:
                rec.status = Status.MISSING
                rec.installed_version = "-"
                rec.message = f"File not found on target: {tgt_p}"
                continue

            if rec.is_symlink:
                if not is_sym:
                    if actual_md5 and rec.expected_md5 and actual_md5.lower() == rec.expected_md5.lower():
                        rec.status = Status.MATCH
                        rec.installed_version = rec.expected_version
                        rec.message = f"Installed as regular file matching MD5 (expected symlink -> {rec.symlink_target_expected})"
                    else:
                        rec.status = Status.MISMATCH
                        matched_rel = self.repo.lookup_md5(actual_md5, Path(rec.rel_path).name)
                        rec.matched_release = matched_rel
                        rec.installed_version = matched_rel.split()[0] if matched_rel else "unknown"
                        match_info = f" (installed file matches {matched_rel})" if matched_rel else ""
                        rec.message = f"Expected symlink -> {rec.symlink_target_expected}, found regular file with MD5 mismatch{match_info}"
                else:
                    norm_exp = os.path.normpath(rec.symlink_target_expected) if rec.symlink_target_expected else ""
                    norm_act = os.path.normpath(sym_target) if sym_target else ""
                    if norm_exp and norm_act and (norm_exp == norm_act or norm_exp.endswith(norm_act) or norm_act.endswith(norm_exp)):
                        if actual_md5 and rec.expected_md5 and actual_md5.lower() == rec.expected_md5.lower():
                            rec.status = Status.SYMLINK_MATCH
                            rec.installed_version = rec.expected_version
                            rec.message = f"Symlink matches -> {sym_target} (resolved MD5 OK)"
                        elif actual_md5 is None:
                            rec.status = Status.BROKEN_SYMLINK
                            rec.installed_version = "broken"
                            rec.message = f"Broken symlink on target: {tgt_p} -> {sym_target} (target missing)"
                        else:
                            rec.status = Status.MISMATCH
                            matched_rel = self.repo.lookup_md5(actual_md5, Path(rec.rel_path).name)
                            rec.matched_release = matched_rel
                            rec.installed_version = matched_rel.split()[0] if matched_rel else "unknown"
                            match_info = f" (target matches {matched_rel})" if matched_rel else ""
                            rec.message = f"Symlink target {sym_target} has MD5 mismatch: expected {rec.expected_md5}, got {actual_md5}{match_info}"
                    else:
                        rec.status = Status.SYMLINK_MISMATCH
                        matched_rel = self.repo.lookup_md5(actual_md5, Path(rec.rel_path).name)
                        rec.matched_release = matched_rel
                        rec.installed_version = matched_rel.split()[0] if matched_rel else "target mismatch"
                        rec.message = f"Symlink target mismatch: expected '{rec.symlink_target_expected}', got '{sym_target}'"
            else:
                if is_sym:
                    if actual_md5 and rec.expected_md5 and actual_md5.lower() == rec.expected_md5.lower():
                        rec.status = Status.MATCH
                        rec.installed_version = rec.expected_version
                        rec.message = f"Symlink resolved to valid file (MD5 match: {actual_md5})"
                    else:
                        rec.status = Status.MISMATCH
                        matched_rel = self.repo.lookup_md5(actual_md5, Path(rec.rel_path).name)
                        rec.matched_release = matched_rel
                        rec.installed_version = matched_rel.split()[0] if matched_rel else "unknown"
                        match_info = f" (target matches {matched_rel})" if matched_rel else ""
                        rec.message = f"Symlink resolved to mismatched file: expected {rec.expected_md5}, got {actual_md5}{match_info}"
                else:
                    if actual_md5 and rec.expected_md5:
                        if actual_md5.lower() == rec.expected_md5.lower():
                            rec.status = Status.MATCH
                            rec.installed_version = rec.expected_version
                            rec.message = "MD5 checksum matched"
                        else:
                            rec.status = Status.MISMATCH
                            matched_rel = self.repo.lookup_md5(actual_md5, Path(rec.rel_path).name)
                            rec.matched_release = matched_rel
                            rec.installed_version = matched_rel.split()[0] if matched_rel else "unknown"
                            match_info = f" (installed file matches {matched_rel})" if matched_rel else ""
                            rec.message = f"MD5 mismatch: expected {rec.expected_md5}, got {actual_md5}{match_info}"
                    else:
                        rec.status = Status.ERROR
                        rec.installed_version = "error"
                        rec.message = "Could not compute MD5 checksum on target"

            # Attach manifest details on mismatch if available
            if rec.status in (Status.MISMATCH, Status.SYMLINK_MISMATCH):
                act_man_str = format_manifest_summary(rec.actual_manifest)
                exp_man_str = format_manifest_summary(rec.expected_manifest)
                if act_man_str or exp_man_str:
                    rec.message += f" [Manifest: Host({act_man_str or 'none'}) vs Expected({exp_man_str or 'none'})]"

            # Check if a topology upgrade is available in sof-bin
            if rec.component == "tplg":
                filename = Path(rec.rel_path).name
                rec.upgrade_available = self.repo.find_topology_upgrade(
                    filename=filename,
                    installed_version=rec.installed_version,
                    installed_md5=rec.actual_md5,
                    fw_version=version,
                )

        if self.strict:
            expected_paths = {r.rel_path for r in records}
            installed_items = self.target.scan_installed_files(self.fw_dest, self.tools_dest)
            for item in installed_items:
                rel = item["rel_path"]
                if rel.startswith("sof-ipc4-lib"):
                    comp = "llext"
                elif rel.startswith(("sof-ipc4-tplg", "sof-tplg", "sof-ace-tplg")):
                    comp = "tplg"
                elif rel.startswith("tools/"):
                    comp = "tools"
                else:
                    comp = "fw"

                plat = self.extract_platform_from_path(comp, rel)
                if not self.should_include(comp, plat, rel):
                    continue

                if rel not in expected_paths:
                    matched_rel = self.repo.lookup_md5(item["md5"], item["filename"]) if item["md5"] else None
                    inst_ver = matched_rel.split()[0] if matched_rel else "unknown"
                    extra_rec = ValidationRecord(
                        component=comp,
                        platform=plat,
                        rel_path=rel,
                        expected_version=version,
                        installed_version=inst_ver,
                        target_path=item["full_path"],
                        is_symlink=item["is_symlink"],
                        symlink_target_actual=item["symlink_target"],
                        actual_md5=item["md5"],
                        actual_size=item["size"],
                        matched_release=matched_rel,
                        status=Status.EXTRA,
                        message=f"Extraneous installed file found on target (not part of {version})",
                        actual_manifest=item.get("manifest"),
                    )
                    records.append(extra_rec)

        return records

    def identify_installed(self) -> List[Dict[str, Any]]:
        """Scan target filesystem and identify the release version of each installed file."""
        installed_items = self.target.scan_installed_files(self.fw_dest, self.tools_dest)
        identified_records: List[Dict[str, Any]] = []

        for item in installed_items:
            rel = item["rel_path"]

            if rel.startswith("sof-ipc4-lib"):
                component = "llext"
            elif rel.startswith(("sof-ipc4-tplg", "sof-tplg", "sof-ace-tplg")):
                component = "tplg"
            elif rel.startswith("tools/"):
                component = "tools"
            else:
                component = "fw"

            platform = self.extract_platform_from_path(component, rel)
            if not self.should_include(component, platform, rel):
                continue

            md5_val = item["md5"]
            matched_rel = self.repo.lookup_md5(md5_val, item["filename"]) if md5_val else None
            man_info = item.get("manifest")

            installed_version = "unknown"
            if matched_rel:
                installed_version = matched_rel.split()[0]
            elif man_info and man_info.get("manifest_version"):
                installed_version = f"{man_info['manifest_version']} (manifest)"
            elif item["is_symlink"] and not md5_val:
                installed_version = "broken link"

            identified_records.append({
                "component": component,
                "platform": platform,
                "rel_path": rel,
                "full_path": item["full_path"],
                "installed_version": installed_version,
                "matched_release": matched_rel,
                "md5": md5_val,
                "is_symlink": item["is_symlink"],
                "symlink_target": item["symlink_target"],
                "size": item["size"],
                "manifest": man_info,
            })

        # Detect FW versions per platform and evaluate topology upgrades
        platform_fw: Dict[str, str] = {}
        for r in identified_records:
            if r["component"] == "fw" and r["platform"] and r["installed_version"] not in ("-", "unknown", "broken link", "error"):
                platform_fw[r["platform"]] = r["installed_version"]

        for r in identified_records:
            if r["component"] == "tplg":
                filename = Path(r["rel_path"]).name
                fw_ver = platform_fw.get(r["platform"])
                if not fw_ver and len(set(platform_fw.values())) == 1:
                    fw_ver = list(platform_fw.values())[0]
                r["upgrade_available"] = self.repo.find_topology_upgrade(
                    filename=filename,
                    installed_version=r["installed_version"],
                    installed_md5=r["md5"],
                    fw_version=fw_ver,
                )

        def sort_key(r: Dict[str, Any]) -> Tuple[int, str, str]:
            comp_order = {"fw": 0, "llext": 1, "tplg": 2, "tools": 3}
            return (comp_order.get(r["component"], 9), r["platform"], r["rel_path"])

        return sorted(identified_records, key=sort_key)

    def fix_records(
        self,
        records: List[ValidationRecord],
        dry_run: bool = False,
        allow_downgrade: bool = False,
        target_version: Optional[str] = None,
    ) -> List[Tuple[ValidationRecord, bool, str]]:
        """Fix all records that need repair, preventing downgrades unless allow_downgrade is True."""
        fix_results: List[Tuple[ValidationRecord, bool, str]] = []
        for r in records:
            if r.status in (Status.MISMATCH, Status.MISSING, Status.SYMLINK_MISMATCH, Status.BROKEN_SYMLINK, Status.ERROR):
                if not r.source_path or not r.target_path:
                    continue

                if is_downgrade(r, target_version=target_version) and not allow_downgrade:
                    from_v = r.installed_version if r.installed_version and r.installed_version != "-" else "current"
                    to_v = r.expected_version or target_version or "target"
                    msg = f"Skipped: would downgrade from {from_v} to {to_v} (use --downgrade to allow)"
                    r.fix_applied = False
                    r.fix_message = msg
                    fix_results.append((r, False, msg))
                    continue

                ok, msg = self.target.fix_file(
                    source_path=r.source_path,
                    target_path=r.target_path,
                    is_symlink=r.is_symlink,
                    symlink_target=r.symlink_target_expected,
                    dry_run=dry_run,
                )
                r.fix_applied = ok
                r.fix_message = msg
                fix_results.append((r, ok, msg))
        return fix_results


def format_fix_record(rec: ValidationRecord, ok: bool, msg: str, target_version: str, colorize: bool = False) -> List[str]:
    """Format a single fix record and its version and manifest transitions."""
    lines = []
    if ok:
        status_prefix = "\033[92m✓\033[0m" if colorize else "✓"
    elif "downgrade" in msg.lower():
        status_prefix = "\033[93m⊘\033[0m" if colorize else "⊘"
    else:
        status_prefix = "\033[91m✗\033[0m" if colorize else "✗"

    lines.append(f"  {status_prefix} {rec.rel_path}: {msg}")

    # Version change
    from_ver = rec.installed_version if (rec.installed_version and rec.installed_version != "-") else "(missing)"
    to_ver = rec.expected_version if rec.expected_version else target_version
    if from_ver != to_ver:
        lines.append(f"    └─ Version: {from_ver} -> {to_ver}")

    # Manifest change
    host_man_summary = format_manifest_summary(rec.actual_manifest)
    exp_man_summary = format_manifest_summary(rec.expected_manifest)
    if host_man_summary or exp_man_summary:
        host_str = f"[{host_man_summary}]" if host_man_summary else "(missing)" if rec.status == Status.MISSING else "(none)"
        exp_str = f"[{exp_man_summary}]" if exp_man_summary else "(none)"
        lines.append(f"    └─ Manifest: Host {host_str} -> Expected {exp_str}")
    elif rec.is_symlink and rec.symlink_target_expected:
        act_tgt = rec.symlink_target_actual or "(missing)"
        if act_tgt != rec.symlink_target_expected:
            lines.append(f"    └─ Symlink: {act_tgt} -> {rec.symlink_target_expected}")

    return lines


def check_platform_fw_llext_consistency(items: List[Any]) -> Dict[str, Dict[str, Any]]:
    """
    Check that for each platform, all LLEXT module versions and build dates match the base FW version and build date.
    Returns a dictionary keyed by platform with consistency status, FW metadata, LLEXT metadata, and issues.
    """
    by_platform: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for item in items:
        if isinstance(item, ValidationRecord):
            comp = item.component
            plat = item.platform
            if not plat or plat == "all":
                continue
            rec = {
                "rel_path": item.rel_path,
                "version": item.installed_version,
                "manifest": item.actual_manifest or {},
                "status": item.status,
            }
        elif isinstance(item, dict):
            comp = item.get("component")
            plat = item.get("platform")
            if not plat or plat == "all":
                continue
            rec = {
                "rel_path": item.get("rel_path", ""),
                "version": item.get("installed_version"),
                "manifest": item.get("manifest") or {},
                "status": None,
            }
        else:
            continue

        if comp in ("fw", "llext"):
            by_platform.setdefault(plat, {"fw": [], "llext": []})[comp].append(rec)

    results: Dict[str, Dict[str, Any]] = {}

    for plat, comps in by_platform.items():
        fw_list = comps["fw"]
        llext_list = comps["llext"]

        if not fw_list or not llext_list:
            continue

        # Find primary non-symlink FW binary (e.g. sof-<plat>.ri)
        primary_fw = next(
            (f for f in fw_list if f["rel_path"].endswith(f"sof-{plat}.ri") and "intel-signed" not in f["rel_path"]),
            fw_list[0],
        )
        fw_ver = primary_fw["version"]
        fw_man = primary_fw["manifest"] or {}
        fw_date = fw_man.get("build_date")
        fw_man_ver = fw_man.get("manifest_version")

        issues: List[str] = []
        llext_details: List[Dict[str, Any]] = []

        for mod in llext_list:
            mod_name = Path(mod["rel_path"]).name
            mod_ver = mod["version"]
            mod_man = mod["manifest"] or {}
            mod_date = mod_man.get("build_date")
            mod_man_ver = mod_man.get("manifest_version")

            mod_issues = []

            # 1. Build date check
            if fw_date and mod_date and fw_date != mod_date:
                mod_issues.append(f"Build date mismatch: LLEXT built {mod_date} != FW built {fw_date}")

            # 2. Version check
            if fw_ver and mod_ver and fw_ver not in ("-", "unknown", "error") and mod_ver not in ("-", "unknown", "error"):
                tup_fw = parse_version_tuple(fw_ver)
                tup_mod = parse_version_tuple(mod_ver)
                if tup_fw and tup_mod and tup_fw != tup_mod:
                    mod_issues.append(f"Version mismatch: LLEXT {mod_ver} != FW {fw_ver}")
            elif fw_man_ver and mod_man_ver:
                tup_fw_m = parse_version_tuple(fw_man_ver)
                tup_mod_m = parse_version_tuple(mod_man_ver)
                if tup_fw_m and tup_mod_m and tup_fw_m != tup_mod_m:
                    mod_issues.append(f"Manifest version mismatch: LLEXT {mod_man_ver} != FW {fw_man_ver}")

            if mod_issues:
                issues.extend([f"{mod_name}: {iss}" for iss in mod_issues])
                llext_details.append({
                    "file": mod["rel_path"],
                    "version": mod_ver,
                    "build_date": mod_date,
                    "issues": mod_issues,
                })

        results[plat] = {
            "platform": plat,
            "consistent": len(issues) == 0,
            "fw_file": primary_fw["rel_path"],
            "fw_version": fw_ver,
            "fw_build_date": fw_date,
            "llext_count": len(llext_list),
            "issues": issues,
            "mismatched_modules": llext_details,
        }

    return results


def format_consistency_report(consistency_report: Dict[str, Dict[str, Any]], colorize: bool = True) -> List[str]:
    """Format platform FW vs LLEXT consistency check results."""
    if not consistency_report:
        return []

    GREEN = "\033[92m" if colorize else ""
    RED = "\033[91m" if colorize else ""
    YELLOW = "\033[93m" if colorize else ""
    BOLD = "\033[1m" if colorize else ""
    RESET = "\033[0m" if colorize else ""

    lines = []
    lines.append(f"{BOLD}PLATFORM FW vs LLEXT CONSISTENCY CHECK:{RESET}")
    for plat, data in sorted(consistency_report.items()):
        fw_info = f"FW {data.get('fw_version') or 'unknown'}"
        if data.get("fw_build_date"):
            fw_info += f" (built {data['fw_build_date']})"

        if data["consistent"]:
            lines.append(f"  {GREEN}✓ {plat:<6}{RESET} Consistent: {fw_info} matches {data['llext_count']} LLEXT module(s)")
        else:
            lines.append(f"  {RED}✗ {plat:<6}{RESET} Inconsistent: {fw_info}")
            for issue in data["issues"]:
                lines.append(f"    {YELLOW}└─ ⚠ {issue}{RESET}")

    return lines


def format_table(records: List[ValidationRecord], colorize: bool = True, show_manifest: bool = False) -> str:
    GREEN = "\033[92m" if colorize else ""
    RED = "\033[91m" if colorize else ""
    YELLOW = "\033[93m" if colorize else ""
    CYAN = "\033[96m" if colorize else ""
    MAGENTA = "\033[95m" if colorize else ""
    BOLD = "\033[1m" if colorize else ""
    RESET = "\033[0m" if colorize else ""

    lines = []
    lines.append(f"{BOLD}{'COMPONENT':<8} {'PLATFORM':<10} {'STATUS':<16} {'VERSION':<14} {'MD5 CHECKSUM':<34} {'FILE':<40}{RESET}")
    lines.append("-" * 125)

    status_counts: Dict[str, int] = {}

    for r in records:
        status_name = r.status.value
        status_counts[status_name] = status_counts.get(status_name, 0) + 1

        ver_display = r.installed_version or "-"

        if r.status in (Status.MATCH, Status.SYMLINK_MATCH):
            c_status = f"{GREEN}{status_name:<16}{RESET}"
            c_ver = f"{GREEN}{ver_display:<14}{RESET}"
            md5_display = (r.actual_md5 or "--------------------------------")[:32]
        elif r.status in (Status.MISMATCH, Status.SYMLINK_MISMATCH):
            c_status = f"{RED}{status_name:<16}{RESET}"
            c_ver = f"{MAGENTA}{ver_display:<14}{RESET}"
            if r.actual_md5 and r.expected_md5:
                md5_display = f"{r.actual_md5[:8]} != {r.expected_md5[:8]}"
            else:
                md5_display = (r.actual_md5 or "--------------------------------")[:32]
        elif r.status == Status.BROKEN_SYMLINK:
            c_status = f"{RED}{status_name:<16}{RESET}"
            c_ver = f"{RED}{ver_display:<14}{RESET}"
            md5_display = "BROKEN LINK"
        elif r.status == Status.MISSING:
            c_status = f"{YELLOW}{status_name:<16}{RESET}"
            c_ver = f"{YELLOW}{'-':<14}{RESET}"
            md5_display = f"{YELLOW}MISSING{RESET}"
        elif r.status == Status.EXTRA:
            c_status = f"{CYAN}{status_name:<16}{RESET}"
            c_ver = f"{CYAN}{ver_display:<14}{RESET}"
            md5_display = (r.actual_md5 or "--------------------------------")[:32]
        else:
            c_status = f"{CYAN}{status_name:<16}{RESET}"
            c_ver = f"{CYAN}{ver_display:<14}{RESET}"
            md5_display = (r.actual_md5 or "--------------------------------")[:32]

        lines.append(
            f"{r.component:<8} {r.platform:<10} {c_status} {c_ver} {md5_display:<34} {r.rel_path}"
        )

        if r.status in (Status.MISMATCH, Status.SYMLINK_MISMATCH) or show_manifest:
            act_man_str = format_manifest_summary(r.actual_manifest)
            exp_man_str = format_manifest_summary(r.expected_manifest)
            if act_man_str or exp_man_str:
                lines.append(
                    f"  {CYAN}└─ Manifest:{RESET} Host [{act_man_str or 'none'}] vs Expected [{exp_man_str or 'none'}]"
                )

        if getattr(r, "upgrade_available", None) and r.status in (Status.MISMATCH, Status.SYMLINK_MISMATCH):
            upg = r.upgrade_available
            fw_note = f" to match FW {upg['fw_version']}" if upg.get("fw_version") else ""
            lines.append(
                f"  {YELLOW}└─ ⬆ Upgrade Available:{RESET} {r.installed_version} -> {GREEN}{upg['target_version']}{RESET} ({upg['component']} in sof-bin){fw_note}"
            )

    lines.append("=" * 125)
    total = len(records)
    passed = status_counts.get(Status.MATCH.value, 0) + status_counts.get(Status.SYMLINK_MATCH.value, 0)
    failed = status_counts.get(Status.MISMATCH.value, 0) + status_counts.get(Status.SYMLINK_MISMATCH.value, 0) + status_counts.get(Status.BROKEN_SYMLINK.value, 0)
    missing = status_counts.get(Status.MISSING.value, 0)
    extra = status_counts.get(Status.EXTRA.value, 0)

    verdict = f"{GREEN}PASS (100% OK){RESET}" if (passed == total and total > 0 and extra == 0) else f"{RED}FAIL{RESET}"

    extra_str = f" | {CYAN}Extra: {extra}{RESET}" if extra else ""
    lines.append(f"{BOLD}SUMMARY:{RESET} Total: {total} | {GREEN}Passed: {passed}{RESET} | {RED}Failed: {failed}{RESET} | {YELLOW}Missing: {missing}{RESET}{extra_str} | Verdict: {verdict}")

    consistency = check_platform_fw_llext_consistency(records)
    if consistency:
        lines.append("")
        for report_line in format_consistency_report(consistency, colorize=colorize):
            lines.append(report_line)

    return "\n".join(lines)


def format_identify_table(records: List[Dict[str, Any]], colorize: bool = True, show_manifest: bool = False) -> str:
    GREEN = "\033[92m" if colorize else ""
    RED = "\033[91m" if colorize else ""
    YELLOW = "\033[93m" if colorize else ""
    CYAN = "\033[96m" if colorize else ""
    MAGENTA = "\033[95m" if colorize else ""
    BOLD = "\033[1m" if colorize else ""
    RESET = "\033[0m" if colorize else ""

    lines = []
    lines.append(f"{BOLD}{'COMPONENT':<8} {'PLATFORM':<10} {'INSTALLED VERSION':<20} {'MD5 CHECKSUM':<34} {'FILE':<40}{RESET}")
    lines.append("-" * 125)

    ver_counts: Dict[str, int] = {}

    for r in records:
        ver = r["installed_version"]
        ver_counts[ver] = ver_counts.get(ver, 0) + 1

        if ver.startswith("v") or ver.startswith("20"):
            c_ver = f"{GREEN}{ver:<20}{RESET}"
        elif ver == "broken link":
            c_ver = f"{RED}{ver:<20}{RESET}"
        else:
            c_ver = f"{MAGENTA}{ver:<20}{RESET}"

        md5_display = (r["md5"] or "--------------------------------")[:32]
        sym_note = f" -> {r['symlink_target']}" if r["is_symlink"] and r["symlink_target"] else ""

        lines.append(
            f"{r['component']:<8} {r['platform']:<10} {c_ver} {md5_display:<34} {r['rel_path']}{sym_note}"
        )

        if show_manifest or r["installed_version"] == "unknown":
            man_summary = format_manifest_summary(r.get("manifest"))
            if man_summary:
                lines.append(f"  {CYAN}└─ Manifest:{RESET} {man_summary}")

        if r.get("upgrade_available"):
            upg = r["upgrade_available"]
            fw_note = f" to match FW {upg['fw_version']}" if upg.get("fw_version") else ""
            lines.append(
                f"  {YELLOW}└─ ⬆ Upgrade Available:{RESET} {r['installed_version']} -> {GREEN}{upg['target_version']}{RESET} ({upg['component']} in sof-bin){fw_note}"
            )

    lines.append("=" * 125)
    total = len(records)
    lines.append(f"{BOLD}SUMMARY:{RESET} Total Files Scanned: {total}")
    if ver_counts:
        for ver, count in sorted(ver_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  • {ver}: {count} file(s)")

    consistency = check_platform_fw_llext_consistency(records)
    if consistency:
        lines.append("")
        for report_line in format_consistency_report(consistency, colorize=colorize):
            lines.append(report_line)

    upgrades = [r for r in records if r.get("upgrade_available")]
    if upgrades:
        lines.append("")
        lines.append(f"{BOLD}TOPOLOGY UPGRADES AVAILABLE ({len(upgrades)} file(s)):{RESET}")
        for u in upgrades:
            upg = u["upgrade_available"]
            fw_note = f" (matches FW {upg['fw_version']})" if upg.get("fw_version") else ""
            lines.append(f"  {YELLOW}• {u['rel_path']}:{RESET} {u['installed_version']} -> {GREEN}{upg['target_version']}{RESET}{fw_note}")

    return "\n".join(lines)


def generate_md5_manifest(records: List[ValidationRecord]) -> str:
    lines = []
    for r in records:
        if r.expected_md5:
            lines.append(f"{r.expected_md5}  {r.rel_path}")
    return "\n".join(lines) + "\n"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and repair installed Sound Open Firmware (SOF) binaries, LLEXT modules, and topologies against sof-bin via MD5.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Identify all installed SOF versions on local host
  %(prog)s --identify

  # Identify installed files on remote Spider DUT over SSH
  %(prog)s -i -p tgl --ssh root@spider

  # Validate SOF v2.14.1 on local host
  %(prog)s --version v2.14.1

  # Validate only TGL platform for v2.12 on local host
  %(prog)s -v v2.12 -p tgl

  # Automatically fix any mismatches or missing files from sof-bin
  %(prog)s -v v2.14.1 -p tgl --fix

  # Dry-run fix mode (preview what will be repaired)
  %(prog)s -v v2.14.1 -p tgl --fix --dry-run

  # Validate offline NFS root filesystem
  %(prog)s -v v2.12 --target-root /srv/nfs/spider-rootfs

  # Validate Debian (.deb) or RPM (.rpm) package against SOF v2.14.1
  %(prog)s --deb firmware-sof-signed_2.14.1_all.deb -v v2.14.1
  %(prog)s --rpm alsa-sof-firmware-2.14.1.rpm -v v2.14.1

  # Auto-identify SOF release versions inside a package
  %(prog)s --pkg firmware-sof-signed.deb --identify

  # Output JSON for CI test scripts
  %(prog)s -v v2.14.1 --json
        """,
    )

    parser.add_argument(
        "-i", "--identify",
        action="store_true",
        help="Scan installed files on the target filesystem and identify their SOF release version via MD5 (does not require --version).",
    )
    parser.add_argument(
        "-m", "--manifest",
        action="store_true",
        help="Display detailed binary manifest metadata (version, build date/time, ABI) for all files.",
    )
    parser.add_argument(
        "-v", "--version",
        type=str,
        default=None,
        help="SOF version to validate (e.g. v2.14.1, v2.12, v2.2.2, 2023.09).",
    )
    parser.add_argument(
        "--pkg", "--package",
        nargs="+",
        default=None,
        metavar="PACKAGE",
        help="Validate SOF release against Debian (.deb) or RPM (.rpm) package(s) or directory of packages.",
    )
    parser.add_argument(
        "--deb",
        nargs="+",
        default=None,
        metavar="DEB_FILE",
        help="Validate SOF release against one or more Debian (.deb) package files.",
    )
    parser.add_argument(
        "--rpm",
        nargs="+",
        default=None,
        metavar="RPM_FILE",
        help="Validate SOF release against one or more RPM (.rpm) package files.",
    )
    parser.add_argument(
        "-b", "--sof-bin-dir",
        type=str,
        default=None,
        help="Path to the sof-bin repository (default: auto-detect).",
    )
    parser.add_argument(
        "-d", "--fw-dest",
        type=str,
        default="/lib/firmware/intel",
        help="Target firmware installation directory (default: /lib/firmware/intel).",
    )
    parser.add_argument(
        "--tools-dest",
        type=str,
        default="/usr/local/bin",
        help="Target tools directory (default: /usr/local/bin).",
    )
    parser.add_argument(
        "-r", "--target-root",
        type=str,
        default=None,
        help="Target rootfs prefix for offline/NFS validation (e.g. /srv/nfs/spider-rootfs).",
    )
    parser.add_argument(
        "--ssh",
        type=str,
        default=None,
        metavar="USER@HOST",
        help="Remote SSH host to validate (e.g. root@spider, root@dragon-fly).",
    )
    parser.add_argument(
        "-p", "--platform",
        type=str,
        default=None,
        help="Filter by platform (e.g. tgl, mtl, arl, arl-s, ptl, lnl, adl, icl, etc., or comma-separated).",
    )
    parser.add_argument(
        "-c", "--component",
        type=str,
        default=None,
        help="Filter by component: fw, llext, tplg, tools, all (comma-separated).",
    )
    parser.add_argument(
        "-f", "--flavor",
        choices=["community", "intel-signed", "all"],
        default="all",
        help="Filter by signing flavor (default: all).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix missing or mismatched files and symlinks by installing reference files from sof-bin.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Used with --fix to display what would be repaired without making modifications.",
    )
    parser.add_argument(
        "--downgrade", "--allow-downgrade",
        action="store_true",
        dest="downgrade",
        help="Allow downgrading installed packages/files when --fix is used (by default downgrades are prevented).",
    )
    parser.add_argument(
        "-l", "--list-versions",
        action="store_true",
        help="List available SOF versions in sof-bin and exit.",
    )
    parser.add_argument(
        "--generate-md5",
        type=str,
        metavar="OUTFILE",
        default=None,
        help="Generate a standard md5sum manifest file for the specified version and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output.",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode: show summary line only.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: fail on any missing optional files or symlink differences.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    try:
        repo = SofBinRepo.find_repo(args.sof_bin_dir)
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        return 2

    # Handle --list-versions
    if args.list_versions:
        versions = repo.list_available_versions()
        print(f"Available SOF versions in {repo.repo_dir}:")
        print("=" * 80)
        for v in versions:
            print(f"Directory: {v['version_dir']}")
            if v["fw"]:
                print(f"  Firmware:   {', '.join(v['fw'])}")
            if v["lib"]:
                print(f"  LLEXT Libs: {', '.join(v['lib'])}")
            if v["tplg"]:
                print(f"  Topologies: {', '.join(v['tplg'])}")
            if v["tools"]:
                print(f"  Tools:      {', '.join(v['tools'])}")
            if v["markers"]:
                print(f"  Releases:   {', '.join(v['markers'])}")
            print("-" * 80)
        return 0

    platform_filter = set(p.strip().lower() for p in args.platform.split(",")) if args.platform else None
    component_filter = set(c.strip().lower() for c in args.component.split(",")) if args.component else None

    pkg_inputs = []
    if args.pkg:
        pkg_inputs.extend(args.pkg)
    if args.deb:
        pkg_inputs.extend(args.deb)
    if args.rpm:
        pkg_inputs.extend(args.rpm)

    target: HostTarget
    if pkg_inputs:
        try:
            package_paths = collect_packages(pkg_inputs)
            target = PackageTarget(package_paths)
        except Exception as e:
            sys.stderr.write(f"ERROR loading package(s): {e}\n")
            return 2
    elif args.ssh:
        target = RemoteSshTarget(args.ssh, target_root=args.target_root)
    else:
        target = LocalHostTarget(target_root=Path(args.target_root) if args.target_root else None)

    try:
        validator = SofValidator(
            repo=repo,
            target=target,
            fw_dest=args.fw_dest,
            tools_dest=args.tools_dest,
            platform_filter=platform_filter,
            flavor_filter=args.flavor,
            component_filter=component_filter,
            strict=args.strict,
        )

        target_label = "local"
        if isinstance(target, PackageTarget):
            target_label = f"package:{','.join(p.name for p in target.packages)}"
        elif args.ssh:
            target_label = args.ssh
        elif args.target_root:
            target_label = str(args.target_root)

        # Handle --identify mode
        if args.identify:
            identified = validator.identify_installed()
            consistency = check_platform_fw_llext_consistency(identified)
            if args.json:
                ver_counts: Dict[str, int] = {}
                for item in identified:
                    v = item["installed_version"]
                    ver_counts[v] = ver_counts.get(v, 0) + 1
                out_dict = {
                    "mode": "identify",
                    "sof_bin_dir": str(repo.repo_dir),
                    "fw_dest": args.fw_dest,
                    "target": target_label,
                    "package_metadata": target.package_metadata if isinstance(target, PackageTarget) else None,
                    "total_files": len(identified),
                    "version_distribution": ver_counts,
                    "platform_consistency": list(consistency.values()),
                    "files": identified,
                }
                print(json.dumps(out_dict, indent=2))
            elif args.quiet:
                ver_counts = {}
                for item in identified:
                    v = item["installed_version"]
                    ver_counts[v] = ver_counts.get(v, 0) + 1
                summary_str = ", ".join(f"{v}: {c}" for v, c in sorted(ver_counts.items(), key=lambda x: -x[1]))
                print(f"Scanned {len(identified)} files ({summary_str or 'none found'})")
            else:
                use_color = not args.no_color and sys.stdout.isatty()
                if isinstance(target, PackageTarget):
                    for meta in target.package_metadata:
                        pkg_title = f"Package: {meta.get('package', meta['file'])}"
                        if meta.get("version"):
                            pkg_title += f" {meta['version']}"
                        if meta.get("architecture"):
                            pkg_title += f" [{meta['architecture']}]"
                        print(f"Target: {pkg_title} ({meta['file']})")
                print(format_identify_table(identified, colorize=use_color, show_manifest=args.manifest))
            return 0

        if not args.version:
            sys.stderr.write("ERROR: --version or --identify is required (or use --list-versions to see available releases).\n")
            return 2

        try:
            records = validator.validate_installation(args.version)
        except Exception as e:
            sys.stderr.write(f"ERROR during validation setup: {e}\n")
            return 2

        # Handle --generate-md5
        if args.generate_md5:
            manifest_content = generate_md5_manifest(records)
            out_p = Path(args.generate_md5)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(manifest_content)
            print(f"MD5 manifest generated at: {out_p} ({len(records)} entries)")
            return 0

        # Perform Fix if requested
        fix_results: List[Tuple[ValidationRecord, bool, str]] = []
        if args.fix:
            fix_results = validator.fix_records(
                records,
                dry_run=args.dry_run,
                allow_downgrade=args.downgrade,
                target_version=args.version,
            )

        consistency = check_platform_fw_llext_consistency(records)

        # Output results
        if args.json:
            out_dict = {
                "version": args.version,
                "sof_bin_dir": str(repo.repo_dir),
                "fw_dest": args.fw_dest,
                "target": target_label,
                "package_metadata": target.package_metadata if isinstance(target, PackageTarget) else None,
                "total_files": len(records),
                "passed": sum(1 for r in records if r.status in (Status.MATCH, Status.SYMLINK_MATCH)),
                "failed": sum(1 for r in records if r.status in (Status.MISMATCH, Status.SYMLINK_MISMATCH, Status.BROKEN_SYMLINK)),
                "missing": sum(1 for r in records if r.status == Status.MISSING),
                "fixed_count": sum(1 for _, ok, _ in fix_results if ok),
                "skipped_downgrade_count": sum(1 for _, ok, msg in fix_results if not ok and "downgrade" in msg.lower()),
                "platform_consistency": list(consistency.values()),
                "records": [r.to_dict() for r in records],
            }
            print(json.dumps(out_dict, indent=2))
        elif args.quiet:
            total = len(records)
            passed = sum(1 for r in records if r.status in (Status.MATCH, Status.SYMLINK_MATCH))
            failed = sum(1 for r in records if r.status in (Status.MISMATCH, Status.SYMLINK_MISMATCH, Status.BROKEN_SYMLINK))
            missing = sum(1 for r in records if r.status == Status.MISSING)
            verdict = "PASS" if (passed == total and total > 0 and all(c.get("consistent", True) for c in consistency.values())) else "FAIL"
            print(f"SOF {args.version} validation: {verdict} ({passed}/{total} match, {failed} mismatch, {missing} missing)")
            if args.fix:
                n_fixed = sum(1 for _, ok, _ in fix_results if ok)
                n_skipped = sum(1 for _, ok, msg in fix_results if not ok and "downgrade" in msg.lower())
                print(f"Fix applied to {n_fixed} item(s)" + (f" ({n_skipped} downgrades skipped)" if n_skipped else ""))
        else:
            use_color = not args.no_color and sys.stdout.isatty()
            if isinstance(target, PackageTarget):
                for meta in target.package_metadata:
                    pkg_title = f"Package: {meta.get('package', meta['file'])}"
                    if meta.get("version"):
                        pkg_title += f" {meta['version']}"
                    if meta.get("architecture"):
                        pkg_title += f" [{meta['architecture']}]"
                    print(f"Target: {pkg_title} ({meta['file']})")
            print(format_table(records, colorize=use_color, show_manifest=args.manifest))
            if args.fix:
                print("\n" + ("=" * 80))
                mode_tag = "[DRY-RUN FIX]" if args.dry_run else "[FIX]"
                print(f"{mode_tag} Repairing discrepancies -> {args.version}:")
                print("-" * 80)
                if not fix_results:
                    print("All files match! No repairs required.")
                else:
                    for rec, ok, msg in fix_results:
                        for line in format_fix_record(rec, ok, msg, target_version=args.version, colorize=use_color):
                            print(line)
                    n_ok = sum(1 for _, ok, _ in fix_results if ok)
                    n_skipped = sum(1 for _, ok, msg in fix_results if not ok and "downgrade" in msg.lower())
                    n_err = sum(1 for _, ok, msg in fix_results if not ok and "downgrade" not in msg.lower())
                    parts = [f"{n_ok} succeeded"]
                    if n_err:
                        parts.append(f"{n_err} failed")
                    if n_skipped:
                        parts.append(f"{n_skipped} skipped (prevented downgrade - use --downgrade to allow)")
                    print(f"Completed: {', '.join(parts)}.")

        has_inconsistency = any(not c.get("consistent", True) for c in consistency.values())
        has_failure = any(r.status != Status.MATCH and r.status != Status.SYMLINK_MATCH for r in records) or has_inconsistency
        return 1 if (has_failure or len(records) == 0) else 0
    finally:
        if isinstance(target, PackageTarget):
            target.cleanup()


if __name__ == "__main__":
    sys.exit(main())
