#!/bin/sh
# shellcheck disable=SC3043

# Keep this script as short as possible _and_ optional - some
# distributions don't use it at all.
#
# The "real" installation process belongs to sof/installer/ in the
# main repo where any developer can use it and fix it.

set -e

# Default values, override on the command line
: "${FW_DEST:=/lib/firmware/intel}"
: "${TOOLS_DEST:=/usr/local/bin}"

usage()
{
    cat <<EOF
Usage example:
        sudo $0 [[v1.8.x/]v1.8]
EOF
    exit 1
}

main()
{
    test "$#" -le 1 || usage

    # Never empty, dirname returns "." instead (opengroup.org)
    local path; path=$(dirname "$1")
    local ver; ver=$(basename "$1")
    local sdir sloc optversuffix

    [ -z "$ver" ] || optversuffix="-$ver"

    for sdir in sof sof-tplg; do
        sloc="$path/${sdir}${optversuffix}"
        test -d "$sloc" ||
            die "%s not found\n" "$sloc"
    done

    # Do this first so we can fail immediately and not leave a
    # half-install behind
    if [ -n "$optversuffix" ]; then
    set -x
    for sdir in sof sof-tplg; do
        ln -sT "$sdir-$ver" "${FW_DEST}/$sdir" || {
            set +x
            die '%s already installed? (Re)move it first.\n' "${FW_DEST}/$sdir"
        }
    done
    fi

    # Trailing slash in srcdir/ ~= srcdir/*
    rsync -a "${path}"/sof*"$optversuffix" "${FW_DEST}"/
    rsync -a "${path}"/tools"$optversuffix"/ "${TOOLS_DEST}"/
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
