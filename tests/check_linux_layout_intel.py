#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
#
# Copyright (c) 2024, Intel Corporation.

import argparse
import os
import pathlib

sof_ri_info = None
try:
    import sof_ri_info
except ImportError:
    print("Note: not using sof_ri_info")
    pass

# List of Intel firmware files and their paths the upstream SOF Linux driver
# expects to find under /lib/firmware/intel. A sof-bin release should have
# binaries for all these targets.
fw_list = [
    "sof/sof-apl.ri",
    "sof/sof-adl-n.ri",
    "sof/sof-ehl.ri",
    "sof/sof-glk.ri",
    "sof/sof-adl.ri",
    "sof/sof-rpl.ri",
    "sof/community/sof-apl.ri",
    "sof/community/sof-adl-n.ri",
    "sof/community/sof-ehl.ri",
    "sof/community/sof-glk.ri",
    "sof/community/sof-adl.ri",
    "sof/community/sof-rpl.ri",
    "sof/community/sof-cnl.ri",
    "sof/community/sof-tgl.ri",
    "sof/community/sof-icl.ri",
    "sof/community/sof-tgl-h.ri",
    "sof/community/sof-rpl-s.ri",
    "sof/community/sof-jsl.ri",
    "sof/community/sof-adl-s.ri",
    "sof/community/sof-cfl.ri",
    "sof/community/sof-cml.ri",
    "sof/intel-signed/sof-apl.ri",
    "sof/intel-signed/sof-adl-n.ri",
    "sof/intel-signed/sof-ehl.ri",
    "sof/intel-signed/sof-glk.ri",
    "sof/intel-signed/sof-adl.ri",
    "sof/intel-signed/sof-rpl.ri",
    "sof/intel-signed/sof-cnl.ri",
    "sof/intel-signed/sof-tgl.ri",
    "sof/intel-signed/sof-icl.ri",
    "sof/intel-signed/sof-tgl-h.ri",
    "sof/intel-signed/sof-rpl-s.ri",
    "sof/intel-signed/sof-jsl.ri",
    "sof/intel-signed/sof-adl-s.ri",
    "sof/intel-signed/sof-cfl.ri",
    "sof/intel-signed/sof-cml.ri",
    "sof/sof-cnl.ri",
    "sof/sof-cht.ri",
    "sof/sof-tgl.ri",
    "sof/sof-byt.ri",
    "sof/sof-icl.ri",
    "sof/sof-bdw.ri",
    "sof/sof-tgl-h.ri",
    "sof/sof-rpl-s.ri",
    "sof/sof-jsl.ri",
    "sof/sof-adl-s.ri",
    "sof/sof-cfl.ri",
    "sof/sof-cml.ri",
    "sof-ipc4/rpl/sof-rpl.ri",
    "sof-ipc4/rpl/community/sof-rpl.ri",
    "sof-ipc4/rpl/intel-signed/sof-rpl.ri",
    "sof-ipc4/adl-n/sof-adl-n.ri",
    "sof-ipc4/adl-n/community/sof-adl-n.ri",
    "sof-ipc4/adl-n/intel-signed/sof-adl-n.ri",
    "sof-ipc4/tgl-h/community/sof-tgl-h.ri",
    "sof-ipc4/tgl-h/intel-signed/sof-tgl-h.ri",
    "sof-ipc4/tgl-h/sof-tgl-h.ri",
    "sof-ipc4/mtl/community/sof-mtl.ri",
    "sof-ipc4/mtl/intel-signed/sof-mtl.ri",
    "sof-ipc4/mtl/sof-mtl.ri",
    "sof-ipc4/rpl-s/community/sof-rpl-s.ri",
    "sof-ipc4/rpl-s/intel-signed/sof-rpl-s.ri",
    "sof-ipc4/rpl-s/sof-rpl-s.ri",
    "sof-ipc4/adl-s/community/sof-adl-s.ri",
    "sof-ipc4/adl-s/intel-signed/sof-adl-s.ri",
    "sof-ipc4/adl-s/sof-adl-s.ri",
    "sof-ipc4/tgl/community/sof-tgl.ri",
    "sof-ipc4/tgl/intel-signed/sof-tgl.ri",
    "sof-ipc4/tgl/sof-tgl.ri",
    "sof-ipc4/adl/sof-adl.ri",
    "sof-ipc4/adl/community/sof-adl.ri",
    "sof-ipc4/adl/intel-signed/sof-adl.ri",
 ]

BASE="/lib/firmware/intel"

def check_fw_files_kernel_to_bundle():
    for i in fw_list:
        full_path = bundle_base + "/" + i
        if os.path.isfile(full_path):
            if verbose_mode: print("File %s found." % full_path);
        else:
            raise Exception("File %s NOT found." % full_path);

def check_fw_files_bundle_to_kernel():
    #for entry in os.scandir(bundle_base):
    paths = pathlib.Path(bundle_base).glob("sof*/*/*.ri")
    for path in paths:
        bundle_path  = path.relative_to(bundle_base)
        if not str(bundle_path) in fw_list:
            raise Exception("Firmware %s not expected by SOF Linux driver" % str(bundle_path))

def check_sign_key():
    for i in fw_list:
        full_path = bundle_base + "/" + i
        try:
            fw_bin = sof_ri_info.parse_fw_bin(full_path, False, False)
        except Exception as e:
            print("FW parse error for %s: %s" % (full_path, str(e)))
            pass

        if fw_bin == None:
            return

        hdr = sof_ri_info.getCssManifest(fw_bin).cdir['css_mft_hdr']
        for attr in hdr.attribs:
            if attr.name == "modulus":
                if "/community" in i:
                    if attr.val != sof_ri_info.COMMUNITY_KEY and \
                       attr.val != sof_ri_info.COMMUNITY_KEY2:
                        raise Exception("FW %s not signed with community key" % full_path)

                elif "/intel-signed" in i:
                    if attr.val == sof_ri_info.COMMUNITY_KEY or \
                       attr.val == sof_ri_info.COMMUNITY_KEY2 or \
                       not attr.val in sof_ri_info.KNOWN_KEYS:
                        raise Exception("Intel signed firmware signed with unexpected key")


def check_ipc_version():
    for i in fw_list:
        full_path = bundle_base + "/" + i
        try:
            fw_bin = sof_ri_info.parse_fw_bin(full_path, False, False)
        except Exception as e:
            print("FW parse error for %s: %s" % (full_path, str(e)))
            pass

        if fw_bin == None:
            return

        ipc4 = "sof-ipc4/" in i
        for comp in fw_bin.components:
            # This check is not 100% certain. It is theoretically possible
            # IPC3 firwmare to have AE1 style extended manifest header.
            if not ipc4 and type(comp).__name__ == "ExtendedManifestAE1":
                print("WARNING: %s IPC3 firmware but AE1 ext manifest" % full_path)

            if ipc4 and type(comp).__name__ == "ExtendedManifestXMan":
                raise Exception("WARNING: %s IPC4 firmware but Xman ext manifest" % full_path)

def main():
    global verbose_mode
    global bundle_base

    parser = argparse.ArgumentParser(description='SOF firmware binary layout tester.')

    parser.add_argument('-r', '--root', type=str, help="Root of the SOF FW bundle")
    parser.add_argument('-v', '--verbose', action="store_true")

    args = parser.parse_args()
    verbose_mode = args.verbose
    bundle_base = args.root
    if bundle_base == None:
        bundle_base = BASE

    if verbose_mode: print("Running tests for SOF FW bundle at %s" % bundle_base)

    # check all FW expected by kernel is found in the FW bundle
    check_fw_files_kernel_to_bundle()

    # check all files in SOF Intel FW bundle and ensure they are listed in fw_list
    check_fw_files_bundle_to_kernel()

    # go through all files and ensure prod-signed files are really prod-signed (if doable)
    if sof_ri_info != None: check_sign_key()

    # go through all files and ensure IPC4 FW files are really IPC4
    if sof_ri_info != None: check_ipc_version()

if __name__ == "__main__":
    main()
