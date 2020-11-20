#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# Copyright(c) 2020 Intel Corporation. All rights reserved.

# stop on most errors
set -e

RELEASE_PLATFORMS=(byt cht bdw apl cnl icl jsl tgl ehl)

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
       -v release version
       -i Intel signed FW source
       -p public signed FW source
       -t tools binary source
       -l tplg binary source
EOF
}

while getopts "v:i:p:t:l:" OPTION; do
  case "$OPTION" in
    v) RELEASE_VERSION=$OPTARG ;;
    i) INTEL_SIGNED_SRC_DIR=$OPTARG ;;
    p) PUBLIC_SIGNED_SRC_DIR=$OPTARG ;;
    t) TOOLS_SRC_DIR=$OPTARG ;;
    l) TPLG_SRC_DIR=$OPTARG ;;
    *) print_usage; exit 1 ;;
  esac
done
shift $((OPTIND-1))

# checkout branch
[[ $(git branch --show-current) == "stable-$RELEASE_VERSION" ]] || git checkout -b "stable-$RELEASE_VERSION"

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

# publish FW
for platform in "${RELEASE_PLATFORMS[@]}"
do
  case $platform in
    # lagcy platform, no sign needed
    byt | cht | bdw)
      [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && cp "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ri" "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ldc" "$BIN_DIR/$SOF_FW_DIR"
      ;;
    apl | cnl | icl | tgl | jsl)
      [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && cp "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ldc" "$BIN_DIR/$SOF_FW_DIR"
      [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && cp "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ri" "$BIN_DIR/$PUBLIC_SIGNED_DIR"
      [[ "$INTEL_SIGNED_SRC_DIR" ]] && cp "$INTEL_SIGNED_SRC_DIR/sof-$platform.ri" "$BIN_DIR/$INTEL_SIGNED_DIR"
      ;;
    # ehl is same binary with tgl but different intel key to sign
    ehl)
      [[ "$INTEL_SIGNED_SRC_DIR" ]] && cp "$INTEL_SIGNED_SRC_DIR/sof-$platform.ldc" "$BIN_DIR/$SOF_FW_DIR"
      [[ "$INTEL_SIGNED_SRC_DIR" ]] && cp "$INTEL_SIGNED_SRC_DIR/sof-$platform.ri" "$BIN_DIR/$INTEL_SIGNED_DIR"
  esac
done

# rename the ri and ldc files
rename -v "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$SOF_FW_DIR/"*.ri
rename -v "s/\.ldc$/-""$RELEASE_VERSION"".ldc/" "$BIN_DIR/$SOF_FW_DIR/"*.ldc
rename -v "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$PUBLIC_SIGNED_DIR/"*.ri
rename -v "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$INTEL_SIGNED_DIR/"*.ri

# publish tools and tplg
[[ "$TPLG_SRC_DIR" ]] && cp "$TPLG_SRC_DIR"/*.tplg "$BIN_DIR/$TPLG_DIR"
[[ "$TOOLS_SRC_DIR" ]] && cp "$TOOLS_SRC_DIR"/sof-* "$BIN_DIR/$TOOLS_DIR"

# reset the file mode
chmod 644 "$BIN_DIR/$SOF_FW_DIR/"*.ri "$BIN_DIR/$SOF_FW_DIR/"*.ldc "$BIN_DIR/$PUBLIC_SIGNED_DIR/"*.ri "$BIN_DIR/$INTEL_SIGNED_DIR/"*.ri "$BIN_DIR/$TPLG_DIR"/*.tplg
chmod 755 "$BIN_DIR/$TOOLS_DIR"/sof-*

# create check sum files
sha256sum "$BIN_DIR/$SOF_FW_DIR/"sof-* "$BIN_DIR/$SOF_FW_DIR/"*/*.ri "$BIN_DIR/$TPLG_DIR"/*.tplg "$BIN_DIR/$TOOLS_DIR"/sof-* > checksum.sha256
sha1sum "$BIN_DIR/$SOF_FW_DIR/"sof-* "$BIN_DIR/$SOF_FW_DIR/"*/*.ri "$BIN_DIR/$TPLG_DIR"/*.tplg "$BIN_DIR/$TOOLS_DIR"/sof-* > checksum.sha1
md5sum "$BIN_DIR/$SOF_FW_DIR/"sof-* "$BIN_DIR/$SOF_FW_DIR/"*/*.ri "$BIN_DIR/$TPLG_DIR"/*.tplg "$BIN_DIR/$TOOLS_DIR"/sof-* > checksum.md5
