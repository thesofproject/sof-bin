#!/bin/sh

set -e

if [ "$(uname)" = 'Darwin' ]; then
    find() { # for -xtype
        gfind "$@"  # brew install findutils
    }
fi

usage()
{
    cat <<EOF
1. Creates a complete git archive from HEAD
2. Removes all but the selected version from it
3. Moves that selected version one level up, to the top-level in the archive

Sample usage:
        $0 v1.7.x/v1.7  [ v1.7 ]

Synopsis:
        $0 directory/version_number  optional_git_tag

The git tag is optional because most files are immutable. It's used by
some tests/.
EOF

    exit 1
}

main()
{
    { [ "$#" -ge 1 ] && [ "$#" -le 2 ]; } || usage

    local path; path=$(dirname "$1")
    local ver; ver=$(basename "$1")
    local archive_name=sof-bin-"$ver"

    local git_tag="${2:-HEAD}"

    local gittop; gittop="$(git rev-parse --show-toplevel)"

    if test -e "$archive_name"; then
        die "%s already exists\n" "$archive_name"
    fi

    set -x
    # Start with a clean git archive
    #
    ( set -e; local _pwd; _pwd=$(pwd)
        cd "${gittop}" # git archive is painful like this
        git archive -o "$_pwd"/_.tar --prefix="$archive_name"/ "$git_tag" "${gittop}"
    )
    tar xf _.tar; rm _.tar

    # Save the selected version
    rm -rf _selected_version;   mkdir _selected_version
    mv "$archive_name"/"$path"/*"$ver"  _selected_version/

    # Select ancillary files
    ( set -e
      local _pwd; _pwd=$(pwd)
      cd "${archive_name:?}"

      rm -f README-before-1.7.md
      mv install.sh README* LICENCE* Notice* "${_pwd}"/_selected_version/
    )

    # Delete everything else
    rm -rf "${archive_name:?}"/* "${archive_name:?}"/.github/

    # Restore the selected version
    mv _selected_version/* "$archive_name"/
    rmdir _selected_version

    ( set +x
      if find "${archive_name}"/ -xtype l | grep -q . ; then
          find "${archive_name}"/ -xtype l -exec file {} \;
          die "Found some broken symbolic links\n"
      fi
    )

    tar cfz "$archive_name".tar.gz "$archive_name"/
    rm -r "${archive_name:?}"/
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
