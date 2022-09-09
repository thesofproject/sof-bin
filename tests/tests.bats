
# https://bats-core.readthedocs.io/en/stable/tutorial.html

# Warning: BATS seems able to neither trace nor show errors in setup*()
# functions. Try --no-tempdir-cleanup and inspect logs there.
setup_file()
{
    load 'common_helpers.bash'; set_constants
    mkdir -p "$REFS" "$EXTR_REFS"
}

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

@test "tarball_one_version 2.1.1" {

    pushd "$RUN_DIR"/
    load 'common_helpers.bash';  set_constants

    get_release v2.1.1/sof-bin-v2.1.1.tar.gz

    "$TOP_DIR"/tarball_one_version.sh v2.1.x/v2.1.1
    tar xf sof-bin-v2.1.1.tar.gz
    diff -qr "$EXTR_REFS"/sof-bin-v2.1.1 sof-bin-v2.1.1/
    popd
}

@test "tarball_topologies_only 2.2.1" {

    pushd "$RUN_DIR"/
    load 'common_helpers.bash';  set_constants

    get_release v2.2.1/sof-tplg-v2.2.1.tar.gz

    "$TOP_DIR"/tarball_topologies_only.sh v2.2.x/v2.2.1
    tar xf sof-tplg-v2.2.1.tar.gz
    diff -qr "$EXTR_REFS"/sof-tplg-v2.2.1 sof-tplg-v2.2.1/
    popd
}
