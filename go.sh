# TODO: Helper script - automate the mundane !

# This script should do several things.
#
# 1) Install the firmware and topologies in the correct target directories
#    depending on PREFIX and vendor. PREFIX should be set as cmd line argument
#    otherwise default to /lib/firmware. "install" rule.
#
# 2) As 1, but for the ldc files. This is the "install_debug" rule.
#
# 3) Take a SOF tag as cmd line argument, checkout tag locally, build topologies
#    and copy them here under tag name directory. "update-tplg" rule.
#
# 4) As 3, but for firmware and sign with public key. Build with XCC where
#    possible or download binaries (signed with any key) from external resource.
#    "update-firmware" rule.
#
# 5) Publish all new topologies and firmwares by commiting and pushing this
#    local copy of repo to upstream master. This should check for any missing
#    files (e.g. signed public releases should match signed intel releases).
#    "publish" rule. 

echo "Nothing implemeted"

