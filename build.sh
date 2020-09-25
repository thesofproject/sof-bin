#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# Copyright(c) 2020 Intel Corporation. All rights reserved.

# stop on most errors
set -e

RELEASE_PLATFORMS=(byt cht bdw apl cnl icl tgl)
PLATFORMS=()

PATH=$pwd/local/bin:$PATH

BIN_DIR=$(pwd)

die()
{
  >&2 printf '%s ERROR: ' "$0"
  # We want die() to be usable exactly like printf
  # shellcheck disable=SC2059
  >&2 printf "$@"
  exit 1
}

print_usage()
{
    cat <<EOF
Build FW and tplg from SOF repo and cp to this repo
ENV XTENSA_TOOLS_ROOT is needed for FW XCC build
usage: build.sh [options] platform(s)
       -s SOF dir
       -v release version
       -m path to MEU tool
       -a Build all platforms
EOF
}

while getopts "s:v:m:a" OPTION; do
  case "$OPTION" in
    s) SOF_DIR=$OPTARG ;;
    v) RELEASE_VERSION=$OPTARG ;;
    m) MEU_TOOL_PATH=$OPTARG ;;
    a) PLATFORMS=("${RELEASE_PLATFORMS[@]}") ;;
    *) print_usage; exit 1 ;;
  esac
done
shift $((OPTIND-1))

# parse platform args
for arg in "$@"; do
  platform=none
  for i in "${RELEASE_PLATFORMS[@]}"; do
    if [ x"$i" = x"$arg" ]; then
      PLATFORMS=("${PLATFORMS[@]}" "$i")
      platform=$i
      shift || true
      break
    fi
  done
  if [ "$platform" == "none" ]; then
    echo "Error: Unknown platform specified: $arg"
    echo "Supported platforms are: ${RELEASE_PLATFORMS[*]}"
    exit 1
  fi
done

# checkout branch
git checkout -b "stable-$RELEASE_VERSION"

# define folders
SOF_FW_DIR="lib/firmware/intel/sof/$RELEASE_VERSION"
PUBLIC_SIGNED_DIR="$SOF_FW_DIR/public-signed"
INTEL_SIGNED_DIR="$SOF_FW_DIR/intel-signed"
TPLG_DIR="lib/firmware/intel/sof-tplg-$RELEASE_VERSION"
TOOLS_DIR="tools/$RELEASE_VERSION"


# create folders
mkdir -p "$PUBLIC_SIGNED_DIR"
mkdir -p "$INTEL_SIGNED_DIR"
mkdir -p "$TOOLS_DIR"
mkdir -p "$TPLG_DIR"

cd "$SOF_DIR"

# build FW
echo $PLATFORMS
for platform in "${PLATFORMS[@]}"
do
  echo $PLATFORMS
  case $platform in
    # lagcy platform, no sign needed
    byt | cht | bdw)
      ./scripts/xtensa-build-all.sh "$platform"
      cp build_${platform}_xcc/sof-$platform.ri build_${platform}_xcc/sof-$platform.ldc "$BIN_DIR/$SOF_FW_DIR"
      ;;
    apl | cnl | icl)
      ./scripts/xtensa-build-all.sh "$platform"
      cp build_${platform}_xcc/sof-$platform.ri "$BIN_DIR/$PUBLIC_SIGNED_DIR"
      cp build_${platform}_xcc/sof-$platform.ldc "$BIN_DIR/$SOF_FW_DIR"
      ;;
    # tgl platform, meu needed
    tgl)
      ./scripts/xtensa-build-all.sh -m "$MEU_TOOL_PATH" "$platform"
      cp build_${platform}_xcc/sof-$platform.ri "$BIN_DIR/$PUBLIC_SIGNED_DIR"
      cp build_${platform}_xcc/sof-$platform.ldc "$BIN_DIR/$SOF_FW_DIR"
      ;;
  esac
done

rename -v "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$SOF_FW_DIR/"*.ri
rename -v "s/\.ldc$/-""$RELEASE_VERSION"".ldc/" "$BIN_DIR/$SOF_FW_DIR/"*.ldc
rename -v "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$PUBLIC_SIGNED_DIR/"*.ri

# build tools and TPLG
./scripts/build-tools.sh

cp tools/build_tools/topology/*.tplg "$BIN_DIR/$TPLG_DIR"
cp tools/build_tools/probes/sof-probes "$BIN_DIR/$TOOLS_DIR"
cp tools/build_tools/ctl//sof-ctl "$BIN_DIR/$TOOLS_DIR"
cp tools/build_tools/logger/sof-logger "$BIN_DIR/$TOOLS_DIR"
cp tools/build_tools/fuzzer/sof-fuzzer "$BIN_DIR/$TOOLS_DIR"