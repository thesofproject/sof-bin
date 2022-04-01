#!/bin/sh

set -e

usage()
{
    cat <<EOFHELP

Very small convenience script to tarball topologies only.

Sample usage, this creates a simple tarball of v1.9.x/sof-tplg-v1.9.3/
with "sof-tplg-v1.9.3/" as the top-level directory in the .tar file.

    $0 v1.9.x/v1.9.3

EOFHELP

    exit 1
}

main()
{
    [ "$#" -eq 1 ] || usage

    local path; path=$(dirname "$1")
    local ver; ver=$(basename "$1")
    local sof_tplg_ver=sof-tplg-"$ver"

    local gittop; gittop="$(git rev-parse --show-toplevel)"
    cd "${gittop}"/"$path"

    test -d "$sof_tplg_ver" ||
        die "No %s/%s directory\n" "$(pwd)" "$sof_tplg_ver"

    tarfile="$gittop"/"$sof_tplg_ver".tar.gz
    set -x
    git archive -9 -o "$tarfile" HEAD -- "$sof_tplg_ver"
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
