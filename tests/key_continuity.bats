
# https://bats-core.readthedocs.io/en/stable/tutorial.html

setup()
{
    mkdir -p testruns/
    RUN_DIR=$(mktemp -d testruns/run-XXXXXX)
}

teardown()
{
    test -d "$RUN_DIR"/ || return 1
    rm -rf "${RUN_DIR:?}"/
}

# You MUST call popd at the end
test_init()
{
    pushd "$RUN_DIR"/ || exit 1
    load 'common_helpers.bash';  set_constants
}

# Workaround for https://github.com/koalaman/shellcheck/issues/2431
# shellcheck disable=SC2030
@test "signing key continuity: sof-ipc4-v*" {
    test_init

    local pair
    cd "$TOP_DIR"
    while IFS= read -r pair; do
        test -n "$pair" || continue
        local prev="${pair%% *}" curr="${pair##* }"

        run_compare_signing_keys "$prev" "$curr"

        case "$prev $curr" in

            # No mismatch expected
            *)
                assert_eq_signing_key $status 0;;
        esac
    done < <(discover_point_release_pairs 'sof-ipc4-v*')

    popd || return 1
}

# Workaround for https://github.com/koalaman/shellcheck/issues/2431
# shellcheck disable=SC2030
@test "signing key continuity: sof-ipc4-lib-v*" {
    test_init

    local pair
    cd "$TOP_DIR"
    while IFS= read -r pair; do
        test -n "$pair" || continue
        local prev="${pair%% *}" curr="${pair##* }"

        run_compare_signing_keys "$prev" "$curr"

        case "$prev $curr" in

            # No mismatch expected
            *)
                assert_eq_signing_key $status 0;;
        esac
    done < <(discover_point_release_pairs 'sof-ipc4-lib-v*')

    popd || return 1
}

# For every vX.Y.x directory with 2+ matches of $1 (a glob like
# 'sof-ipc4-v*'), emit every consecutive (prev, curr) pair, one pair per
# line as "prev curr", sorted by version.
discover_point_release_pairs()
{
    local glob_pattern="$1"
    local vdir
    for vdir in v*.x; do
        test -d "$vdir" || continue

        local matches=()
        while IFS= read -r m; do
            matches+=("$m")
        done < <(find "$vdir" -maxdepth 1 -type d -name "$glob_pattern" | sort -V)

        local n=${#matches[@]}
        test "$n" -ge 2 || continue

        local i
        for ((i = 0; i < n - 1; i++)); do
            printf '%s %s\n' "${matches[$i]}" "${matches[$((i + 1))]}"
        done
    done
}

run_compare_signing_keys()
{
    local prev="$1" curr="$2"
    local run_cmd=("$TOP_DIR"/validate_sof_install.py --compare-signing-keys "$prev" "$curr")

    unset BATS_RUN_COMMAND
    run "${run_cmd[@]}"
    # BATS_RUN_COMMAND is not available in bats version 1.2.1
    test -n "$BATS_RUN_COMMAND" || BATS_RUN_COMMAND="${run_cmd[*]}"

    # This is not modifying $output, shellcheck seems wrong
    # shellcheck disable=SC2031
    printf '%s\n' "$output"
    # This is not modifying $status, shellcheck seems wrong
    # shellcheck disable=SC2031
    printf '\n  --- %d returned by %s ---\n\n' \
           $status "$BATS_RUN_COMMAND"
}

assert_eq_signing_key()
{
    local actual=$1 expected=$2

    test "$actual" -eq "$expected" || {
        >&2 printf 'FAIL: expected %d, got %d from %s\n' \
            "$expected" "$actual" "$BATS_RUN_COMMAND"
            false
    }
}
