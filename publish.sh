#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# Copyright(c) 2020 Intel Corporation. All rights reserved.

# stop on most errors
set -e

SOF_RI_INFO_URL="https://raw.githubusercontent.com/thesofproject/sof/master/tools/sof_ri_info/sof_ri_info.py"

# Need to check and update the release platforms
NO_SIGNED_PLATFORMS=(byt cht bdw)
PUBLIC_SIGNED_PLATFORMS=(apl cnl icl jsl tgl tgl-h)
INTEL_SIGNED_PLATFORMS=(apl cnl icl tgl tgl-h ehl)

ISSUED_PLATFORMS=""

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
       -c check only
EOF
}

check_fw()
{
  target_key="$1"
  ri_path="$2"
  ri_name=$(basename $ri_path)

  echo "========================================================================"
  echo "checking $ri_path"

  if [[ ! -f "$ri_path" ]]; then
    echo "$ri_name does not exist"
    ISSUED_PLATFORMS="$ISSUED_PLATFORMS [$target_key]$ri_name(file not exist)"
    return
  fi

  USING_KEY=$(python3 "$RI_INFO" "$ri_path" | grep Modulus -A 1 | tail -1)
  echo ${USING_KEY}
  if echo ${USING_KEY} | grep -qi "$target_key"; then
    echo "$ri_name get correct key"
  else
    echo "$ri_name get wrong key"
    ISSUED_PLATFORMS="$ISSUED_PLATFORMS [$target_key]$ri_name(wrong key)"
  fi
}

while getopts "v:i:p:t:l:c" OPTION; do
  case "$OPTION" in
    v) RELEASE_VERSION=${OPTARG%%/} ;;
    i) INTEL_SIGNED_SRC_DIR=${OPTARG%%/} ;;
    p) PUBLIC_SIGNED_SRC_DIR=${OPTARG%%/} ;;
    t) TOOLS_SRC_DIR=${OPTARG%%/} ;;
    l) TPLG_SRC_DIR=${OPTARG%%/} ;;
    c) CHECK_ONLY=true ;;
    *) print_usage; exit 1 ;;
  esac
done
shift $((OPTIND-1))

# define folders
SOF_FW_DIR="lib/firmware/intel/sof/$RELEASE_VERSION"
PUBLIC_SIGNED_DIR="$SOF_FW_DIR/public-signed"
INTEL_SIGNED_DIR="$SOF_FW_DIR/intel-signed"
TPLG_DIR="lib/firmware/intel/sof-tplg-$RELEASE_VERSION"
TOOLS_DIR="tools/$RELEASE_VERSION"

# prepare binary check tmp ENV
TMP_DIR=$(mktemp -d --tmpdir sof-bin.XXXX)
RI_INFO="$TMP_DIR/sof_ri_info.py"
wget -q $SOF_RI_INFO_URL -O $RI_INFO || die "Could not get tool sof_ri_info.py from remote"

# run check on firmware
# for platform in "${NO_SIGNED_PLATFORMS[@]}"
# do
#   [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && check_fw "$platform" "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ri"
# done

for platform in "${PUBLIC_SIGNED_PLATFORMS[@]}"
do
  [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && check_fw "Community" "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ri"
done

for platform in "${INTEL_SIGNED_PLATFORMS[@]}"
do
  case $platform in
    tgl-h)
      [[ "$INTEL_SIGNED_SRC_DIR" ]] && check_fw "TGL Intel prod" "$INTEL_SIGNED_SRC_DIR/sof-$platform.ri"
      ;;
    *)
      [[ "$INTEL_SIGNED_SRC_DIR" ]] && check_fw "$platform Intel prod" "$INTEL_SIGNED_SRC_DIR/sof-$platform.ri"
      ;;
  esac
done

if [[ -n "$ISSUED_PLATFORMS" ]]; then
  die "Please check: $ISSUED_PLATFORMS"
  exit 1
else
  echo "========================================================================"
  echo "All FW binary pass check!"
fi
[[ "$CHECK_ONLY" ]] && exit 0

# checkout branch
[[ $(git branch --show-current) == "stable-$RELEASE_VERSION" ]] || git checkout -b "stable-$RELEASE_VERSION" || git checkout "stable-$RELEASE_VERSION"

# create folders
mkdir -p "$PUBLIC_SIGNED_DIR"
mkdir -p "$INTEL_SIGNED_DIR"
mkdir -p "$TOOLS_DIR"
mkdir -p "$TPLG_DIR"

# publish FW
for platform in "${NO_SIGNED_PLATFORMS[@]}"
do
  [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && cp "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ri" "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ldc" "$BIN_DIR/$SOF_FW_DIR"
  rename -v -f "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$SOF_FW_DIR/sof-$platform.ri"
  rename -v -f "s/\.ldc$/-""$RELEASE_VERSION"".ldc/" "$BIN_DIR/$SOF_FW_DIR/sof-$platform.ldc"
done

for platform in "${PUBLIC_SIGNED_PLATFORMS[@]}"
do
  [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && cp "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ldc" "$BIN_DIR/$SOF_FW_DIR"
  [[ "$PUBLIC_SIGNED_SRC_DIR" ]] && cp "$PUBLIC_SIGNED_SRC_DIR/sof-$platform.ri" "$BIN_DIR/$PUBLIC_SIGNED_DIR"
  rename -v -f "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$PUBLIC_SIGNED_DIR/sof-$platform.ri"
  rename -v -f "s/\.ldc$/-""$RELEASE_VERSION"".ldc/" "$BIN_DIR/$SOF_FW_DIR/sof-$platform.ldc"
done

for platform in "${INTEL_SIGNED_PLATFORMS[@]}"
do
  [[ "$INTEL_SIGNED_SRC_DIR" ]] && cp "$INTEL_SIGNED_SRC_DIR/sof-$platform.ldc" "$BIN_DIR/$SOF_FW_DIR"
  [[ "$INTEL_SIGNED_SRC_DIR" ]] && cp "$INTEL_SIGNED_SRC_DIR/sof-$platform.ri" "$BIN_DIR/$INTEL_SIGNED_DIR"
  rename -v -f "s/\.ri$/-""$RELEASE_VERSION"".ri/" "$BIN_DIR/$INTEL_SIGNED_DIR/sof-$platform.ri"
  rename -v -f "s/\.ldc$/-""$RELEASE_VERSION"".ldc/" "$BIN_DIR/$SOF_FW_DIR/sof-$platform.ldc"
done

# publish tools and tplg
[[ "$TPLG_SRC_DIR" ]] && cp "$TPLG_SRC_DIR"/*.tplg "$BIN_DIR/$TPLG_DIR"
[[ "$TOOLS_SRC_DIR" ]] && cp "$TOOLS_SRC_DIR"/sof-* "$BIN_DIR/$TOOLS_DIR"

# reset the file mode
chmod 644 "$BIN_DIR/$SOF_FW_DIR/"*.ri "$BIN_DIR/$SOF_FW_DIR/"*.ldc "$BIN_DIR/$PUBLIC_SIGNED_DIR/"*.ri "$BIN_DIR/$INTEL_SIGNED_DIR/"*.ri "$BIN_DIR/$TPLG_DIR"/*.tplg
chmod 755 "$BIN_DIR/$TOOLS_DIR"/sof-*

cd $BIN_DIR
# create check sum files
sha256sum "$SOF_FW_DIR/"sof-* "$SOF_FW_DIR/"*/*.ri "$TPLG_DIR"/*.tplg "$TOOLS_DIR"/sof-* > checksum.sha256
sha1sum "$SOF_FW_DIR/"sof-* "$SOF_FW_DIR/"*/*.ri "$TPLG_DIR"/*.tplg "$TOOLS_DIR"/sof-* > checksum.sha1
md5sum "$SOF_FW_DIR/"sof-* "$SOF_FW_DIR/"*/*.ri "$TPLG_DIR"/*.tplg "$TOOLS_DIR"/sof-* > checksum.md5
