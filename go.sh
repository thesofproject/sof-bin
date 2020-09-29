#!/bin/bash

# This script installs the firmware and topologies in /lib/firmware/intel.
# Optionally if ROOT is set as an environment variable by the caller it will be
# prepended to the installation path.
#
# The script will attempt to use git to work out the version automatically, if
# that is not possible on your environment specify SOF_VERSION as an environment
# variable when calling.

test -n "${ROOT}" ||  \
    ROOT=
test -n "${INTEL_PATH}" || \
    INTEL_PATH=lib/firmware/intel
test -n "${SOF_VERSION}" || \
    SOF_VERSION=$(git symbolic-ref HEAD 2>/dev/null | cut -d"/" -f 3| cut -d"-" -f 2)
test -n "${SOF_VERSION}" || \
    { echo "Can't work out SOF_VERSION using git, please specify SOF_VERSION as environment variable"; exit 1; }

test -d ${INTEL_PATH}/sof-tplg-${SOF_VERSION} || \
    { echo "Can't find version ${SOF_VERSION} - are you missing leading v?"; exit 2; }

echo "Installing Intel firmware and topology $SOF_VERSION to $INTEL_PATH"

# wipe previous releases
rm -rf ${ROOT}/${INTEL_PATH}/sof/*
rm -rf ${ROOT}/${INTEL_PATH}/sof-tplg-*
rm -rf ${ROOT}/${INTEL_PATH}/sof-tplg

# copy to destination
cd lib/firmware
cp -rf intel ${ROOT}/lib/firmware

# add symlinks
cd ${ROOT}/${INTEL_PATH}/sof

ln -s ${SOF_VERSION}/sof-bdw-${SOF_VERSION}.ri sof-bdw.ri
ln -s ${SOF_VERSION}/sof-byt-${SOF_VERSION}.ri sof-byt.ri
ln -s ${SOF_VERSION}/sof-cht-${SOF_VERSION}.ri sof-cht.ri
ln -s ${SOF_VERSION}/intel-signed/sof-apl-${SOF_VERSION}.ri sof-apl.ri
ln -s ${SOF_VERSION}/intel-signed/sof-apl-${SOF_VERSION}.ri sof-glk.ri
ln -s ${SOF_VERSION}/intel-signed/sof-cnl-${SOF_VERSION}.ri sof-cfl.ri
ln -s ${SOF_VERSION}/intel-signed/sof-cnl-${SOF_VERSION}.ri sof-cnl.ri
ln -s ${SOF_VERSION}/intel-signed/sof-cnl-${SOF_VERSION}.ri sof-cml.ri
ln -s ${SOF_VERSION}/intel-signed/sof-icl-${SOF_VERSION}.ri sof-icl.ri

cd ..
ln -s sof-tplg-${SOF_VERSION} sof-tplg

echo "Done installing Intel firmware and topology $SOF_VERSION"