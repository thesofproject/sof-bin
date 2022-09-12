
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

# Up to now it's been possible to maintain script compatibility with most
# old releases. When that becomes really too hard then just stop testing
# the oldest versions.
@test "tarball_one_version 2.1.1" {
    test_tarball_one_version v2.1.x v2.1.1	v2.1.1
}
@test "tarball_one_version 2.0" {
    test_tarball_one_version v2.0.x v2.0	v2.0
}
@test "tarball_one_version 1.9.3" {
    test_tarball_one_version v1.9.x v1.9.3	v1.9.3
}
@test "tarball_one_version 1.8" {
    test_tarball_one_version v1.8.x v1.8	v1.8
}

@test "tarball_topologies_only 2.2.1" {
    test_tarball_topologies_only v2.2.x v2.2.1
}

test_tarball_one_version()
{
    local dir="$1" ver="$2"
    local optional_git_tag="$3"

    pushd "$RUN_DIR"/ || exit 1
    load 'common_helpers.bash';  set_constants

    get_release "$ver"/sof-bin-"$ver".tar.gz

    "$TOP_DIR"/tarball_one_version.sh "$dir"/"$ver" "$optional_git_tag"
    tar xf sof-bin-"$ver".tar.gz
    diff -qr "$EXTR_REFS"/sof-bin-"$ver"  sof-bin-"$ver"/
    popd || exit 1
}

test_tarball_topologies_only()
{
    local dir="$1" ver="$2"

    pushd "$RUN_DIR"/ || exit 1
    load 'common_helpers.bash';  set_constants

    get_release "$ver"/sof-tplg-"$ver".tar.gz

    "$TOP_DIR"/tarball_topologies_only.sh "$dir"/"$ver"
    tar xf sof-tplg-"$ver".tar.gz
    diff -qr "$EXTR_REFS"/sof-tplg-"$ver" sof-tplg-"$ver"/
    popd || exit 1
}
