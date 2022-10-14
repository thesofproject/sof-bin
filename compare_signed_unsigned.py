#!/usr/bin/env python3

from typing import List, Dict
import sys
import os
from pathlib import Path
import logging

# https://chrisyeh96.github.io/2017/08/08/definitive-guide-python-imports.html#case-3-importing-from-parent-directory
sys.path.insert(1, os.path.join(sys.path[0], '../sof/tools/sof_ri_info'))
import sof_ri_info

logging.basicConfig(level=logging.INFO)


def find_ri_files(topdir: str) -> Dict[str, List[str]]:
    """"Finds all *.ri files. Returns a map of all the different
    subdirectories where each *.ri basename can be found, example:
    { 'sof-apl.ri' : [ 'v2.2.x/v2.0/community/', 'v2.2.x/v2.0/intel-signed' ]
    """

    basename_dirs: Dict[str, List[str]] = {}
    for curdir, _, files in os.walk(topdir):
        for f in files:
            if Path(f).match("*.ri"):
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


def compare_same_basename(basename: str, locations: List[str]) -> TestResults:
    "Used sof_ri_info to compare the same filename in multiple locations"

    res = TestResults(0, 0, 0, 0)

    if len(locations) == 1:
        logging.info("Only one location for %s, skipped", Path(locations[0], basename))
        res.skipped += 1
        return res

    # 1. Compute all reproducible checksums with sof_ri_info
    dirs_chksum = {}
    for d in locations:
        src_path = Path(d, basename)
        if not src_path.exists():
            logging.error("Broken symlink? Failed %s", src_path)
            res.errors += 1
            continue
        try:
            parsed_fw = sof_ri_info.parse_fw_bin(str(src_path), False, False)
        except Exception as ex:
            logging.error("Failed to parse %s, ignoring it: %s", src_path, ex)
            res.errors += 1
            continue

        if Path(d).is_absolute():
            # Drop the initial '/'
            output_dir = Path("reproducible_images", *Path(d).parts[1:])
        else:
            output_dir = Path("reproducible_images", d)

        Path.mkdir(output_dir, parents=True, exist_ok=True)
        output_file = output_dir / basename

        # Erase the signature and other variables before checksumming
        logging.debug("EraseVariables %s -> %s", src_path, output_file)
        chksum = sof_ri_info.EraseVariables(src_path, parsed_fw, output_file)
        assert (
            chksum is not None
        ), "this requires sof_ri_info.py version 1e4236be68f7b or above"

        dirs_chksum[d] = (chksum, output_file)

    # 2. Compare checksums
    if len(dirs_chksum) == 0:
        # e.g.: all broken symlinks
        logging.warning("Zero valid instance of %s", basename)
        res.errors += 1
        return res

    first_dir = next(iter(dirs_chksum.keys()))

    if len(dirs_chksum) == 1:
        logging.info("Only one valid %s, skipped", Path(first_dir, basename))
        res.skipped += 1
        return res

    # Compare the first one in the list to all the others (usually: just one other)
    first_chksum, first_file = dirs_chksum[first_dir]
    for d in dirs_chksum:
        if d == first_dir:  # don't compare with itself
            continue
        res.comparisons += 1
        chksum, output_file = dirs_chksum[d]
        if chksum == first_chksum:
            logging.info(
                "match  OK:\t%s\tis the same \tin %s and %s", basename, first_dir, d
            )
            os.remove(output_file)
        else:
            res.different += 1
            logging.error(
                "MISMATCH:\t%s\tdifferent \tin %s vs  %s", basename, first_dir, d
            )

    if res.errors == 0 and res.different == 0:
        os.remove(first_file)

    return res


def main(argv) -> int:
    "Main function"

    basename_locs = find_ri_files(argv[1])

    if len(basename_locs) == 0:
        raise Exception("No *.ri file found in directory '%s'", argv[1])

    # different, comparison, errors, skipped
    results = TestResults(0, 0, 0, 0)

    for basename in basename_locs:
        results = results + compare_same_basename(basename, basename_locs[basename])

    logging.info(
        "%d different / %d comparisons; %d errors; %d skipped",
        results.different,
        results.comparisons,
        results.errors,
        results.skipped,
    )
    return results.different + results.errors


if __name__ == "__main__":
    sys.exit(main(sys.argv))
