
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
    test_tarball_multi_single_pre27 v2.1.x v2.1.1
}

@test "tarball_multi_releases single 1.8" {
    test_tarball_multi_single_pre27 v1.8.x v1.8
}

@test "tarball_topologies_only 2.2.1" {
    local ver=v2.2.1
    test_init
    get_release "$ver"/sof-tplg-"$ver".tar.gz
    # These should have never been there.
    # -f needed to run multiple times.
    rm -f "$EXTR_REFS"/sof-tplg-v2.2.1/cavs-*.tplg
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

@test "install 2.1.1" {
    test_install_one_version v2.1.x v2.1.1 v2.1.1
}

@test "install 1.8-rc2" {
    test_install_one_version v1.8.x v1.8-rc2
}

# First official IPC4 release
@test "install ipc4 v2.7" {
    test_install_one_version v2.7.x v2.7
}

test_install_one_version()
{
    local vdir="$1" ver="$2" opt_git_tag="$3"
    test_init

    if false; then # download it
       get_release "$ver"/sof-bin-"$ver".tar.gz
       rsync -a "$EXTR_REFS"/sof-bin-"$ver"  .
    else
        # (re-)build it. No network needed but extra test dependency on
        # tarball_one_version.sh.
        "$TOP_DIR"/tarball_one_version.sh "$vdir"/"$ver" "$opt_git_tag"
        tar xf sof-bin-"$ver".tar.gz
    fi

    # "Upgrade" install.sh to the latest, uncommited version because
    # that's what we're testing here!
    cp "$TOP_DIR"/install.sh ./sof-bin-"$ver"/

    # Work from a $fromdir copy to preserve the extracted tarball pristine, see below.
    # Use some white space in dir names to catch quoting issues.
    local fromdir="./from sof-bin $ver"/
    rsync -a ./sof-bin-"$ver"/ "$fromdir"

    local todir; todir="to installed"

    mkdir "$todir" "$todir"/tools
    pwd
    printf "'%s/install.sh' '%s' (todir='%s')\n" \
           "$fromdir" "$fromdir/$ver" "$todir"
    FW_DEST="$todir" TOOLS_DEST="$todir"/tools "$fromdir"/install.sh "$fromdir/$ver"

    # Before even looking at what we just installed, make sure no
    # unexpected accident polluted our $fromdir copy
    diff -qr  "$fromdir" ./sof-bin-"$ver"/

    local refdir="$fromdir"
    # to compare with the (potentially dirty) git checkout:
#    local refdir="$TOP_DIR/$vdir"

    # At last check that install.sh copied firmware, topologies,...
    # Expected directory structure:
    # https://thesofproject.github.io/latest/getting_started/intel_debug/introduction.html#firmware-binary

    # How many found
    local n_subdirs=0 n_tplg=0

    for from_subdir in "$refdir/sof"*"-$ver"; do
        local from_base; from_base=$(basename "$from_subdir")
        local to_base=${from_base%-"$ver"}
        local to_subdir=$todir/$to_base
        if [[ "$to_base" =~ ^sof.*-tplg$ ]]; then
            : $(( n_tplg++ ))
        fi
        printf 'Comparing installation from "%s" to "%s"\n' \
                 "$from_subdir" "$to_subdir"
        diff -qr "$from_subdir" "$to_subdir"
        : $(( n_subdirs++ ))
    done
    test "$n_subdirs" -eq 2
    test "$n_tplg" -eq 1

    # Check tools install
    diff -qr "$refdir/tools-$ver"/ "$todir"/tools/

    popd || exit 1
}


@test "tarball_multi fake_2_1_1a" {
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

# First real release made this way
@test "tarball_multi 2.2.2" {
    local ver=v2.2.2
    test_init

    get_release "$ver"/sof-bin-"$ver".tar.gz

    "$TOP_DIR"/tarball_multi_releases.bash -d -g "$ver"     \
              v2.2.x/sof-v2.2 v2.2.x/tools-v2.2          \
              v2.2.x/sof-tplg-v2.2.1/ v2.2.x/sof-"$ver"
    tar xf sof-bin-"$ver".tar.gz

    diff -qr "$EXTR_REFS"/sof-bin-"$ver"  "$(pwd)/sof-bin-$ver"/

    popd || exit 1
}

# First release with v2.7
@test "tarball_multi 2023.09" {
    local ver=2023.09
    test_init

    get_release v"$ver"/sof-bin-"$ver".tar.gz

    "$TOP_DIR"/tarball_multi_releases.bash -r $ver \
             v2.2.x/sof-v2.2 v2.2.x/tools-v2.2 \
             v2.2.x/sof-tplg-v2.2.1 v2.2.x/sof-tplg-v2.2.3 v2.2.x/sof-tplg-v2.2.4 \
             v2.2.x/sof-tplg-v2.2.5 v2.2.x/sof-tplg-v2.2.6 v2.2.x/sof-tplg-v2.2.7 \
             v2.7.x/sof-ace-tplg-v2.7 \
             v2.7.x/sof-ipc4-v2.7 \
             v2.7.x/tools-v2.7

    tar xf sof-bin-"$ver".tar.gz

    # install.sh was updated in 2024.03, so it won't match
    # anymore
    git show v2023.12.1:install.sh > "$(pwd)/sof-bin-$ver"/install.sh

    # install.sh was updated in 2025.01, so it won't match
    # anymore
    git show v2023.12.1:README.md > "$(pwd)/sof-bin-$ver"/README.md

    diff -qr "$EXTR_REFS"/sof-bin-"$ver"  "$(pwd)/sof-bin-$ver"/

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
test_tarball_multi_single_pre27()
{
    local vdir="$1"
    local ver="$2"
    test_init
    get_release "$ver"/sof-bin-"$ver".tar.gz

    "$TOP_DIR"/tarball_multi_releases.bash -d -g "$ver" \
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
