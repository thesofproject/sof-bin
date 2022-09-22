
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

@test "tarball_multi_releases single 2.1.1" {
    test_tarball_multi_single v2.1.x v2.1.1
}

@test "tarball_multi_releases single 1.8" {
    test_tarball_multi_single v1.8.x v1.8
}

@test "tarball_topologies_only 2.2.1" {
    local ver=v2.2.1
    test_init
    get_release "$ver"/sof-tplg-"$ver".tar.gz
    # These should have never been there
    # rm "$EXTR_REFS"/sof-tplg-v2.2.1/cavs-*.tplg
    test_tarball_topologies_only v2.2.x "$ver"
}

@test "tarball_topologies_only 2.1.1a" {
    local ver=v2.1.1a
    test_init
    get_release "$ver"/sof-tplg-"$ver".tar.gz
    test_tarball_topologies_only v2.1.x "$ver"
}

@test "tarball_topologies_only 1.9.3-tplg2" {
    local ver=v1.9.3-tplg2
    test_init
    get_release "$ver"/sof-tplg-"$ver".tar.gz
    test_tarball_topologies_only v1.9.x "$ver"
}

@test "tarball_multi_2_1_1a" {
    test_init

    "$TOP_DIR"/tarball_multi_releases.bash \
      v2.2.x/sof-v2.2  v1.8.x/sof-v1.8-rc2  v1.9.x/tools-v1.9-rc1/ \
      v2.1.x/sof-tplg-v2.1.1a
    tar xf sof-bin-v2.1.1a.tar.gz
    for i in manifest.txt sha256sum.txt; do
        diff -u "$STATIC_REFS"/multi-v2.1.1a/"$i" "$(pwd)/sof-bin-v2.1.1a/$i"
    done
    popd || exit 1
}

# You MUST call popd at the end
test_init()
{
    pushd "$RUN_DIR"/ || exit 1
    load 'common_helpers.bash';  set_constants
}

test_tarball_one_version()
{
    test_init

    local dir="$1" ver="$2"
    local optional_git_tag="$3"

    get_release "$ver"/sof-bin-"$ver".tar.gz

    "$TOP_DIR"/tarball_one_version.sh "$dir"/"$ver" "$optional_git_tag"
    tar xf sof-bin-"$ver".tar.gz
    diff -qr "$EXTR_REFS"/sof-bin-"$ver"  "$(pwd)/sof-bin-$ver"/
    popd || exit 1
}

# Test the ability of the newer "multi" script to recreate older, single
# version releases that were created with the older
# tarball_one_version.sh
test_tarball_multi_single()
{
    local vdir="$1"
    local ver="$2"
    test_init
    get_release "$ver"/sof-bin-"$ver".tar.gz

    "$TOP_DIR"/tarball_multi_releases.bash -g "$ver" \
              "$vdir"/sof-"$ver" "$vdir"/sof-tplg-"$ver" "$vdir"/tools-"$ver"
    tar xf sof-bin-"$ver".tar.gz

    # Cheat a little bit; these files are brand new.
    rm sof-bin-"$ver"/manifest.txt sof-bin-"$ver"/sha256sum.txt

    diff -qr "$EXTR_REFS"/sof-bin-"$ver" sof-bin-"$ver"
    popd || exit 1
}

test_tarball_topologies_only()
{
    local dir="$1" ver="$2"

    "$TOP_DIR"/tarball_topologies_only.sh "$dir"/"$ver"
    tar xf sof-tplg-"$ver".tar.gz
    diff -qr "$EXTR_REFS"/sof-tplg-"$ver" "$(pwd)"/sof-tplg-"$ver"/
    popd || exit 1
}
