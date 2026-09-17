#!/usr/bin/env python3

from typing import Dict, List, Tuple
import sys
import os
import re
from pathlib import Path
import logging

# https://chrisyeh96.github.io/2017/08/08/definitive-guide-python-imports.html#case-3-importing-from-parent-directory
sys.path.insert(1, os.path.join(sys.path[0], "../sof/tools/sof_ri_info"))
import sof_ri_info

logging.basicConfig(level=logging.INFO)

# Friendly names of library modules that are known to be built as a stub
# ("mock") for community/CI builds (see CONFIG_GOOGLE_RTC_AUDIO_PROCESSING_MOCK
# and CONFIG_GOOGLE_CTC_AUDIO_PROCESSING_MOCK in sof.git, forced on for
# community board configs because CI can't use extra CONFIGs, see sof.git
# issues #9410, #8722, #9386). Intel-signed builds may ship the real,
# proprietary library instead, so a content difference here is expected, not
# a defect.
MOCK_MODULE_NAME_RE = re.compile(r"google_(rtc|ctc)_audio_processing", re.I)

UUID_BIN_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\.bin$"
)


def is_mock_module_name(name: str) -> bool:
    return bool(MOCK_MODULE_NAME_RE.search(name))


def find_files_by_pattern(topdir: str, pattern: str) -> Dict[str, List[str]]:
    """"Finds all files matching `pattern`. Returns a map of all the
    different subdirectories where each basename can be found, example:
    { 'sof-apl.ri' : [ 'v2.2.x/v2.0/community/', 'v2.2.x/v2.0/intel-signed' ]
    """

    basename_dirs: Dict[str, List[str]] = {}
    for curdir, _, files in os.walk(topdir):
        for f in files:
            if Path(f).match(pattern):
                if basename_dirs.get(f):
                    basename_dirs[f].append(curdir)
                else:
                    basename_dirs[f] = [curdir]

    # Remove symlinks pointing to the SAME basename because the target
    # should be in the list already. This is purposedly NOT recursive!
    for base, dirs in basename_dirs.items():
        filtered_dirs = dirs
        for d in dirs:
            p = Path(d, base)
            if not p.is_symlink():
                continue
            target = Path(os.readlink(p))
            if target.name == base:
                logging.debug("Ignoring symlink %s, target has same basename", p)
                filtered_dirs.remove(d)
                continue
        basename_dirs[base] = filtered_dirs

    return basename_dirs


def find_ri_files(topdir: str) -> Dict[str, List[str]]:
    "Finds all *.ri files, see find_files_by_pattern()"
    return find_files_by_pattern(topdir, "*.ri")


def find_llext_files(topdir: str) -> Dict[str, List[str]]:
    """Finds all *.llext library module files, see find_files_by_pattern().

    Unlike *.ri files, .llext friendly names are NOT platform-qualified: the
    same basename (e.g. tester.llext) legitimately recurs, unrelated, across
    different platforms. So the grouping this returns is only safe to use as
    an existence check (does this directory tree contain any .llext files at
    all?), never to compare same-named files across different locations."""
    return find_files_by_pattern(topdir, "*.llext")


class TestResults:
    def __init__(self, d, c, f, s):
        self.different = d
        self.comparisons = c
        self.errors = f
        self.skipped = s

    def __add__(self, o):
        return TestResults(
            self.different + o.different,
            self.comparisons + o.comparisons,
            self.errors + o.errors,
            self.skipped + o.skipped,
        )


def checksum_parsed_fw(src_path: Path, parsed_fw):

    d = src_path.parent
    if Path(d).is_absolute():
        # Drop the initial '/'
        output_dir = Path("reproducible_images", *Path(d).parts[1:])
    else:
        output_dir = Path("reproducible_images", d)

    Path.mkdir(output_dir, parents=True, exist_ok=True)

    output_file = output_dir / src_path.name

    # Erase the signature and other variables before checksumming
    logging.debug("EraseVariables %s -> %s", src_path, output_file)
    chksum = sof_ri_info.EraseVariables(src_path, parsed_fw, output_file)
    assert (
        chksum is not None
    ), "this requires sof_ri_info.py version 1e4236be68f7b or above"

    return chksum, output_file


def get_modules(parsed_fw) -> Dict[str, Tuple[str, bytes]]:
    """Reads the ADSP manifest already parsed by sof_ri_info and returns
    every module it contains as {mod_name: (uuid, hash_bytes)}"""

    modules: Dict[str, Tuple[str, bytes]] = {}
    adsp_mft = parsed_fw.cdir.get("adsp_mft")
    if adsp_mft is None:
        return modules
    for comp in adsp_mft.components:
        if comp.name != "Module Entry":
            continue
        mod_name = comp.adir["mod_name"].val.strip()
        modules[mod_name] = (comp.adir["uuid"].val, comp.adir["hash"].val)
    return modules


def explain_ri_mismatch(fpath0: Path, fpath1: Path, parsed_fws) -> bool:
    """Reads the manifest of both binaries and prints the module list,
    explaining a whole-file mismatch in terms of the individual modules
    it's made of. Returns True if the difference is one we know to be
    harmless (pure module reordering, or a known community-mock vs.
    Intel-signed-real module), False if it's a real difference."""

    mods0 = get_modules(parsed_fws[0])
    mods1 = get_modules(parsed_fws[1])

    if not mods0 and not mods1:
        logging.info("No module manifest found in %s / %s, cannot explain mismatch",
                      fpath0, fpath1)
        return False

    all_names = sorted(set(mods0) | set(mods1))
    unexplained = False

    for name in all_names:
        if name not in mods0:
            logging.error("  EXTRA module (only in %s): %s", fpath1, name)
            unexplained = True
        elif name not in mods1:
            logging.error("  EXTRA module (only in %s): %s", fpath0, name)
            unexplained = True
        else:
            uuid0, hash0 = mods0[name]
            uuid1, hash1 = mods1[name]
            if hash0 == hash1:
                logging.info("  module %-9s %s  OK (identical, position may differ)",
                             name, uuid0)
            elif is_mock_module_name(name):
                logging.warning(
                    "  module %-9s %s  MISMATCH but OK: known mock/real module",
                    name, uuid0)
            else:
                logging.error("  module %-9s %s  MISMATCH", name, uuid0)
                unexplained = True

    return not unexplained


def files_match(fpath0: Path, fpath1: Path):

    fpaths = [fpath0, fpath1]
    parsed_fws = [sof_ri_info.parse_fw_bin(str(f), False, False) for f in fpaths]

    sum0, out0 = checksum_parsed_fw(fpath0, parsed_fws[0])
    sum1, out1 = checksum_parsed_fw(fpath1, parsed_fws[1])

    if sum0 != sum1:
        logging.error("MISMATCH: %s\tis different from\t%s", fpath0, fpath1)
        logging.info("Reading manifests to explain the difference in terms of modules:")
        if explain_ri_mismatch(fpath0, fpath1, parsed_fws):
            logging.warning(
                "...but every module matches: OK (%s vs %s)", fpath0, fpath1)
            os.remove(out0)
            os.remove(out1)
            return True
        return False

    logging.info("match  OK: %s\tis the same as\t%s", fpath0, fpath1)
    os.remove(out0)
    os.remove(out1)
    return True


def compare_same_basename(basename: str, locations: List[str],
                           match_fn=None) -> TestResults:
    "Uses match_fn (defaults to sof_ri_info-based files_match) to compare the same filename in multiple locations"

    if match_fn is None:
        match_fn = files_match

    res = TestResults(0, 0, 0, 0)

    if len(locations) == 1:
        logging.info("Only one location for %s, skipped", Path(locations[0], basename))
        res.skipped += 1
        return res

    valid_dirs = []
    for d in locations:
        src_path = Path(d, basename)
        if not src_path.exists():
            logging.error("Broken symlink? Failed %s", src_path)
            res.errors += 1
            continue
        valid_dirs.append(d)

    if len(valid_dirs) == 0:
        # e.g.: all broken symlinks
        logging.warning("Zero valid instance of %s", basename)
        res.errors += 1
        return res

    if len(valid_dirs) == 1:
        logging.info("Only one valid %s, skipped", Path(valid_dirs[0], basename))
        res.skipped += 1
        return res

    first_dir = valid_dirs[0]
    for d in valid_dirs[1:]:
        res.comparisons += 1
        try:
            if match_fn(Path(first_dir, basename), Path(d, basename)):
                continue
        except Exception as ex:
            logging.error("Failed to compare %s in %s vs %s: %s",
                          basename, first_dir, d, ex)
        res.different += 1
        logging.error(
            "MISMATCH:\t%s\tdifferent \tin %s vs  %s", basename, first_dir, d
        )

    return res


def check_module_dir_links(d: Path) -> int:
    """Checks the community/intel-signed convention inside a single dir:
    every UUID.bin must be a symlink to the friendly-named real file it
    stands for, never the other way around."""

    errors = 0
    if not d.is_dir():
        return errors

    for entry in sorted(d.iterdir()):
        if not UUID_BIN_RE.match(entry.name):
            continue
        if not entry.is_symlink():
            logging.error("LINK ERROR: %s should be a symlink to its friendly-named "
                          "module, not a real file", entry)
            errors += 1
            continue
        target = os.readlink(entry)
        if not (d / target).is_file():
            logging.error("LINK ERROR: %s -> %s is a broken symlink", entry, target)
            errors += 1

    return errors


def mirrorable_names(dirpath: Path) -> set:
    """Names inside a community/ or intel-signed/ dir that are expected to
    get a top-level convenience symlink: *.ri files and <UUID>.bin files.
    The friendly-named real file a UUID.bin points to (e.g. drc.llext) is
    an implementation detail and, per the v2.13.x reference layout, never
    gets a top-level symlink of its own.

    Some older (pre-v2.13.x) releases package a platform as a single
    dsp_basefw.bin instead: that file gets the top-level convenience
    symlink and the *.ri underneath it is never meant to be top-level
    reachable at all, so it's excluded from this set in that case."""

    if not dirpath.is_dir():
        return set()
    if (dirpath / "dsp_basefw.bin").exists():
        return {"dsp_basefw.bin"}
    return {
        e.name for e in dirpath.iterdir()
        if e.name.endswith(".ri") or UUID_BIN_RE.match(e.name)
    }


def check_platform_dir_links(pdir: Path) -> int:
    """Checks the top-level convenience-symlink convention for a single
    platform dir, e.g. v2.15.x/sof-ipc4-v2.15/mtl/ or
    v2.15.x/sof-ipc4-lib-v2.15/lnl/, following the pattern established in
    v2.13.x: a top-level file is a symlink into intel-signed/ of the same
    name, present if and only if intel-signed/ actually has that file."""

    errors = 0
    community = pdir / "community"
    signed = pdir / "intel-signed"

    # Only names that actually exist in intel-signed/ (a *.ri file, or a
    # <UUID>.bin module) are expected to get a top-level convenience
    # symlink. Anything else at the top level (e.g. *.ldc debug-info files,
    # or platforms like bdw/byt/cht that were never dual-built) is out of
    # scope for this convention and is left alone.
    signed_names = mirrorable_names(signed)

    for name in signed_names:
        entry = pdir / name
        # Use is_symlink() first: a symlink that exists but whose target
        # chain is broken elsewhere (e.g. a genuinely missing file further
        # down the chain) is a content problem already reported by the
        # regular file comparison, not a link-placement problem.
        if not entry.is_symlink() and not entry.exists():
            logging.error("LINK ERROR: intel-signed/%s exists but %s has no "
                          "top-level convenience symlink for it", name, entry)
            errors += 1
            continue
        if not entry.is_symlink():
            logging.error("LINK ERROR: top-level %s should be a symlink into "
                          "intel-signed/, not a real file", entry)
            errors += 1
            continue
        expected_target = os.path.join("intel-signed", name)
        target = os.readlink(entry)
        if target != expected_target:
            logging.error("LINK ERROR: %s -> %s, expected -> %s",
                          entry, target, expected_target)
            errors += 1

    errors += check_module_dir_links(community)
    errors += check_module_dir_links(signed)

    return errors


def check_symlinks(topdir: str) -> int:
    """Walks topdir looking for platform dirs (any dir containing both a
    community/ and an intel-signed/ subdir) and validates their symlink
    structure against the convention established in the v2.13.x release."""

    errors = 0
    for curdir, subdirs, _files in os.walk(topdir):
        if "community" in subdirs and "intel-signed" in subdirs:
            errors += check_platform_dir_links(Path(curdir))

    return errors


def compare_scanned_dir(d):

    # different, comparison, errors, skipped
    results = TestResults(0, 0, 0, 0)

    ri_locs = find_ri_files(d)
    # *.llext content is not compared here: unlike *.ri, it carries no
    # rimage/CSE manifest, and Intel-signed *.llext are known to differ from
    # their community counterpart by a handful of embedded signing-metadata
    # bytes even when the module itself is unchanged (confirmed empirically
    # against every historical release with a signed .llext). find_llext_files()
    # is only used below as an existence check, for directories (e.g.
    # sof-ipc4-lib-v*) that legitimately contain no *.ri file at all.
    llext_locs = find_llext_files(d)
    if len(ri_locs) == 0 and len(llext_locs) == 0:
        raise Exception("No *.ri or *.llext file found in directory '%s'" % d)
    for basename in ri_locs:
        results = results + compare_same_basename(basename, ri_locs[basename])

    link_errors = check_symlinks(d)
    results.errors += link_errors

    logging.info(
        "%d different / %d comparisons; %d errors; %d skipped",
        results.different,
        results.comparisons,
        results.errors,
        results.skipped,
    )
    return results.different + results.errors


def main(argv) -> int:
    "Main function"

    # TODO: argparse
    if len(argv) == 2:
        return compare_scanned_dir(argv[1])
    elif len(argv) == 3:
        return 0 if files_match(Path(argv[1]), Path(argv[2])) else 1
    else:
        raise Exception("Requires 1 directory or 2 files")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
