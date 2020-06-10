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

ROOT=
INTEL_PATH=lib/firmware/intel
VERSION=$(git symbolic-ref HEAD 2>/dev/null | cut -d"/" -f 3| cut -d"-" -f 2)

echo "Installing Intel firmware and topology $VERSION to $INTEL_PATH"

# wipe previous releases
rm -rf ${ROOT}/${INTEL_PATH}/sof/*
rm -rf ${ROOT}/${INTEL_PATH}/sof-tplg-*
rm -rf ${ROOT}/${INTEL_PATH}/sof-tplg

# copy to destination
cd lib/firmware
cp -rf intel ${ROOT}/lib/firmware

# add symlinks
cd ${ROOT}/${INTEL_PATH}/sof

ln -s ${VERSION}/sof-bdw-${VERSION}.ri sof-bdw.ri
ln -s ${VERSION}/sof-byt-${VERSION}.ri sof-byt.ri
ln -s ${VERSION}/sof-cht-${VERSION}.ri sof-cht.ri
ln -s ${VERSION}/intel-signed/sof-apl-${VERSION}.ri sof-apl.ri
ln -s ${VERSION}/intel-signed/sof-apl-${VERSION}.ri sof-glk.ri
ln -s ${VERSION}/intel-signed/sof-cnl-${VERSION}.ri sof-cfl.ri
ln -s ${VERSION}/intel-signed/sof-cnl-${VERSION}.ri sof-cnl.ri
ln -s ${VERSION}/intel-signed/sof-cnl-${VERSION}.ri sof-cml.ri
ln -s ${VERSION}/intel-signed/sof-icl-${VERSION}.ri sof-icl.ri


cd ..
ln -s sof-tplg-${VERSION} sof-tplg

echo "Done installing Intel firmware and topology $VERSION"
