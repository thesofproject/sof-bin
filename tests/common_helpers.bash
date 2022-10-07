
set_constants()
{
    TESTS_DIR=$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)
    # shellcheck disable=SC2034
    TOP_DIR=$(cd "${TESTS_DIR}"/.. && pwd)
    REFS="$TESTS_DIR"/refs/
    EXTR_REFS="$TESTS_DIR"/extracted_refs/
    # shellcheck disable=SC2034
    STATIC_REFS="$TESTS_DIR"/static_refs/

    GITHUB_RELEASES='https://github.com/thesofproject/sof-bin/releases/download'
}

# Example: get_release v2.1.1/sof-bin-v2.1.1.tar.gz
get_release()
{
    local tgz; tgz=$(basename "$1")
    set_constants
    local dirname=${tgz%.tar.gz}; dirname=${dirname%.tgz}

    # 1. Do not re-download the same thing over and over again
    # 2. Let the user override for local testing purposes
    if test -d "$EXTR_REFS"/"$dirname"/; then return 0; fi

    ( cd "$REFS"/ || exit 1
      # Same logic as above
      test -e "$tgz" || wget --no-verbose "$GITHUB_RELEASES"/"$1"
    )

    ( cd "$EXTR_REFS"/ || exit 1
      tar xf "$REFS"/"$tgz"
    )
}
