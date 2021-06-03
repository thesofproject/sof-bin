#!/bin/sh

set -e

# Default values, override on the command line
: "${FW_DEST:=/lib/firmware/intel}"
: "${TOOLS_DEST:=/usr/local/bin}"

usage()
{
    cat <<EOF
Usage:
        sudo $0 v1.7
EOF
    exit 1
}

main()
{
    test "$#" -eq 1 || usage

    local path; path=$(dirname "$1")
    local ver; ver=$(basename "$1")

    # Do this first so we can fail immediately and not leave a
    # half-install behind
    set -x
    for sdir in sof sof-tplg; do
        ln -s "$sdir-$ver" "${FW_DEST}/$sdir" || {
            set +x
            die '%s already installed? (Re)move it first.\n' "${FW_DEST}/$sdir"
        }
    done

    # Trailing slash in srcdir/ ~= srcdir/*
    rsync -a "${path}"/sof*"$ver" "${FW_DEST}"/
    rsync -a "${path}"/tools-"$ver"/ "${TOOLS_DEST}"/
}

die()
{
    >&2 printf '%s ERROR: ' "$0"
    # We want die() to be usable exactly like printf
    # shellcheck disable=SC2059
    >&2 printf "$@"
    exit 1
}

main "$@"
