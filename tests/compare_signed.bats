
# https://bats-core.readthedocs.io/en/stable/tutorial.html

# Warning: BATS seems able to neither trace nor show errors in setup*()
# functions. Try --no-tempdir-cleanup and inspect logs there.
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


@test "compare signed unsigned v1.*/sof-v*" {
    test_init

    local sofv
    cd "$TOP_DIR"
    # TODO: could we dynamically generate a list of tests from this?
    # Probably not, BATS is likely scanning this source code.
    for sofv in v1.*/sof-v*; do

        run_compare_signed "$sofv"

        case "$sofv" in

            # special cases

            # Missing a few intel-signed/*.ri => one broken glk.ri symlink
            *v1.9.x/sof-v1.9-rc1)
                assert_eq_signed $status 1;;

            # No difference
            *)
                assert_eq_signed $status 0;;
        esac
    done

    popd || return 1
}

# Why does this test triggers this warning while the previous, nearly
# identical one does not? Baffling.
# shellcheck disable=SC2030
@test "compare signed unsigned v2.*/sof-v*" {
    test_init

    local sofv
    cd "$TOP_DIR"
    for sofv in v2.*/sof-v*; do

        run_compare_signed "$sofv"

        case "$sofv" in

            # special cases

            # community/{apl,glk}.ri are Zephyr, everything else is XTOS
            *v2.0.x/sof-v2.0)
                assert_eq_signed $status 2;;
            # 5 community/*.ri files are Zephyr, 2 real + symlinks:
            # apl/glk + cnl/cfl/cml. Everything else is XTOS
            *v2.1.x/sof-v2.1.1)
                assert_eq_signed $status 5;;
            # Dunno what happened there, they're all different! It's
            # only a release candidate, not worth the time analyzing it.
            *v2.2.x/sof-v2.2-rc1)
                assert_eq_signed $status 12;;
            # First RPL release, only 6 broken symbolic links meant to
            # be combined with v2.2
            *v2.2.x/sof-v2.2.2)
                assert_eq_signed $status 6;;
            # First release using Zephyr as RTOS w/ known checksum issue,
            # fixed by Zephyr mainline commit f896fc2306
            *v2.3.x/sof-v2.3)
                assert_eq_signed $status 6;;

            # No difference or error expected
            *)
                assert_eq_signed $status 0;;
        esac
    done

    popd || return 1
}


run_compare_signed()
{
    local sofv="$1"

    run "$TOP_DIR"/compare_signed_unsigned.py "$sofv"
    # This is not modifying $output, shellcheck seems wrong
    # shellcheck disable=SC2031
    printf '%s\n' "$output"
    # This is not modifying $status, shellcheck seems wrong
    # shellcheck disable=SC2031
    printf '\n  --- %d returned by %s ---\n\n' \
           $status "$BATS_RUN_COMMAND"
}

assert_eq_signed()
{
    local actual=$1 expected=$2

    test "$actual" -eq "$expected" || {
        >&2 printf 'Expected %d, got %d from %s\n\n\n' \
            "$expected" "$actual" "$BATS_RUN_COMMAND"
            false
    }
}
