#!/usr/bin/env bash

set -e

usage()
{
    cat <<EOF

Combine SOF firmware files from different versions/directories into a
single lib/firmware/intel/sof* release tarball.

- Creates a complete archive from git (to ignore uncommitted binaries)
- Removes all but the given versions from it
- Merges files from the given versions _in the order given on the
  command line_. In case of conflict last on the command line wins.
- Records which file came from which version in manifest.txt

The archive is named after the version number in the last argument,
or the version passed with -r option.

Example:
        $0 -r v2022.09 -g v2.2.6 v2.0.x/tools-v2.0 v2.1.x/sof-tplg-v2.1.1 v2.2.x/sof-v2.2.2 v2.3.x/sof-v2.3

This example will create a sof-bin-v2022.09.tar.gz archive; its files will
extract in directories sof/, tools/, sof-tplg/, ...

Synopsis:
        $0 [ -g optional_git_ref ] dir1 dir2 dir3 ...

The git reference is optional because most files are immutable. Some
tests need -g.

EOF
    exit 1
}

if [ "$(uname)" = 'Darwin' ]; then
    find() { # for -xtype
        gfind "$@"  # brew install findutils
    }
fi

main()
{
    local gittop; gittop="$(git rev-parse --show-toplevel)"

    parse_args "$@"

    printf "Archiving these directories in this order, last one wins: %s\n" "${TOP_DIRS[*]}"

    local last_dir last_ver
    # This is a single-element array slice.
    # shellcheck disable=SC2124
    last_dir="${TOP_DIRS[@]: -1}"
    last_ver=$(parse_version_suffix "$last_dir")

    local archive_name=sof-bin-"$last_ver"
    if test -n "$release_ver"; then
        archive_name=sof-bin-"$release_ver"
    fi

    local ver_suffix_inside_tarball
    if $double_dirversion_inside; then
        ver_suffix_inside_tarball="-$last_ver"
    fi


    if test -e "$archive_name"; then
        die "%s already exists\n" "$archive_name"
    fi

    ( local _pwd; _pwd=$(pwd)
      set -x
      # Start with a clean git archive and the version number in the
      # top-level directory.
      cd "${gittop}" # git archive is painful like that
      git archive -o "${_pwd}"/_.tar --prefix="$archive_name"/ "$GIT_REF"
    )
    tar xf _.tar; rm _.tar

    # Select what we want in the tarball
    rm -rf _selected_versions;  mkdir _selected_versions
    ( set -ex
      local version_dir
      for version_dir in "${TOP_DIRS[@]}"; do
          mv "$archive_name"/"$version_dir"  _selected_versions/
      done
    )
    # Pick up ancillary files
    ( set -e
      local _pwd; _pwd=$(pwd)
      cd "${archive_name:?}"
      rm tarball*sh
      rm -f README-before-1.7.md
      set -x
      mv install.sh README* LICENCE* Notice* "${_pwd}"/_selected_versions/
    )

    # Delete everything else
    rm -rf "${archive_name:?}"/* "${archive_name:?}"/.github

    # Move the selected things back in place
    (set -x; mv _selected_versions/* "$archive_name"/ )
    rmdir _selected_versions

    check_symlinks "$archive_name" ||
        >&2 printf "WARNING: Found some broken symbolic links before combining\n"

    # Now "install" versions in the given order and on top of each
    # other: last one wins. Record the version of each file for the
    # manifest.
    local p ver dir radix
    for p in "${TOP_DIRS[@]}"; do
        topdir=$(basename "$p")
        ver=$(parse_version_suffix "$p")
        radix=${topdir%-"$ver"}
        record_files_version "${archive_name}"  "$topdir"  "${ver}"
        # copy + delete ~= move
        ( set -x
          rsync -a --checksum  "${archive_name}"/"$topdir"/  "${archive_name}/${radix}"-WIP/
        )
        rm -rf               "${archive_name:?}"/"$topdir"/
    done

    check_symlinks "$archive_name" ||
        die "Found some broken symbolic links after combining\n"

    # Rename sof-WIP -> sof-vX.Y, tools-WIP -> tools-vX.Y, ...
    ( cd "${archive_name}"
      set -e
      for d in *-WIP; do
          radix=${d%-WIP}
          ( set -x; mv "$d" "${radix}${ver_suffix_inside_tarball}")
      done
      # For install.sh convenience
      # Kept only for the ability to test releases < v2.7
      [ -z "$ver_suffix_inside_tarball" ] ||
          touch "$last_ver"
    )

    local manifest_file="$archive_name"/manifest.txt
    # Share which version was used for each file in manifest.txt
    for f in "${!FILES_ORIGIN[@]}"; do
        printf '%s\t%s\n' "${FILES_ORIGIN[$f]}" "$f"
    done | sort -V > "$manifest_file"

    printf '\n#   --- symbolic links ---\n\n' >> "$manifest_file"

    for f in "${!SYMLINKS_ORIGIN[@]}"; do
        printf '%s\t%s -> %s\n' \
               "${SYMLINKS_ORIGIN[$f]}" "$f" "${SYMLINKS_TARGET[$f]}"
    done | sort -V >> "$manifest_file"

    for f in "${!FILES_CHKSUM[@]}"; do
        topdir="${FILES_ORIGIN[$f]}"
        ver=$(parse_version_suffix "$topdir")
        radix=${topdir%-"$ver"}
        printf '%s\t%s\n' "${FILES_CHKSUM[$f]}" "${radix}${ver_suffix_inside_tarball}/${f}"
    done | LC_ALL=C sort -k2 > "$archive_name"/sha256sum.txt

    ( cd "${archive_name}"/; set -x
      sha256sum --quiet --check sha256sum.txt
    )

    # Final tarball
    (set -ex
     tar cfz "$archive_name".tar.gz "$archive_name"/
     rm -r "${archive_name:?}"/
    )
}

# vX.Y.Z/tools-v1.2.3   ->  v1.2.3
parse_version_suffix()
{
    local arg="$1" base version

    base=$(basename "$arg")
    # Remove everything before the last '-v'
    version=${base##*-v}

    if [ "$version" = "$base" ]; then
        die 'failed to find a version in "%s"\n' "$base"
    fi

    # Add the 'v' back
    printf 'v%s' "$version"
}

parse_args()
{
    GIT_REF=HEAD
    double_dirversion_inside=false
    release_ver=
    local opt
    while getopts "dg:hr:" opt; do
        case "$opt" in
            # undocumented option to test releases < 2.7
            d) double_dirversion_inside=true;;
            g) GIT_REF=$OPTARG ;;
            h) usage ;;
	    r) release_ver=$OPTARG ;;
            *) exit 1;;
        esac
    done
    shift $((OPTIND-1))

    TOP_DIRS=("$@")
    local dir
    for dir in "${TOP_DIRS[@]}"; do
        test -d "$gittop/$dir" ||
            die "%s is not a directory in %s\n" "$dir" "$gittop"
        # Better fail earlier
        parse_version_suffix "$dir" > /dev/null
    done
}

declare -A FILES_ORIGIN FILES_CHKSUM SYMLINKS_ORIGIN SYMLINKS_TARGET
record_files_version()
{
    local f root="$1" topdir="$2" ver="$3"
    pushd "$root"/"$topdir" > /dev/null

    # shell check is right but the alternatives it suggests do not let
    # us define variables / side-effects. We could probably write to a
    # file and source it... awkward.
    # shellcheck disable=SC2044
    for f in $(find . -type f); do
        FILES_ORIGIN["$f"]="$topdir"
        FILES_CHKSUM["$f"]=$(sha256sum "$f" | awk '{ print $1 }')
    done
    # Keep symbolic links separate
    # shellcheck disable=SC2044
    for f in $(find . -type l); do
        SYMLINKS_ORIGIN["$f"]="$topdir"
        SYMLINKS_TARGET["$f"]="$(readlink "$f")"
    done
    popd > /dev/null
}

# Look for broken symlinks in directory argument. Requires GNU find.
check_symlinks()
{
    local dir="$1"
    if find "${dir}"/ -xtype l | grep -q . ; then
        # Show all symlinks
        find "${dir}"/ -xtype l -exec file {} \;
        return 1
    fi
    return 0
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
