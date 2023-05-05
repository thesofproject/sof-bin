How to make a new release
-------------------------

Proceed very slowly and triple-check everything because everything is
immutable: never overwrite or rename any version of anything already
published: tags, firmware images, directories, tarballs,... Having
actually different versions labelled the exact same is an extremely
confusing, time-consuming and frustrating user experience; it's the very
problem versioning is meant to solve. If a mistake was made and
published, simply create a new release. If the only delta between -rc5
and -rc6 is a fixed typo then you obviously don't need to test -rc6
again.

Build the /lib/firmware/intel/sof/ tree
---------------------------------------

- Make sure `sof/versions.json` has been kept up to date. 

- After validation, create the new git tag in sof.git

- Point the SOF installer to your local sof-bin clone by creating an
  `sof/installer/config.mk` config file like this:

      FW_DESTDIR   := /home/SOF_WS/sof-bin/v1.9.x/
      USER_DESTDIR := /home/SOF_WS/sof-bin/v1.9.x/tools-v1.9-rc1/

  Alternatively, you can define these as environment variables.

- Ask the installer to build and "install" the `/lib/firmware/intel/sof/` tree
  into your sof-bin/ git clone:

      cd sof/installer/
      git status
      make clean && make -j && make rsync

This creates the correct directory structure, including symbolic links.

Building all platforms in parallel takes only a couple minutes.  For
more details about the installer check `sof/installer/README.md` or the
"Build and sign firmware binaries" paragraph in the ["Getting started"
guide in
sof-docs](https://thesofproject.github.io/latest/getting_started/build-guide/build-from-scratch.html#step-3-build-and-sign-firmware-binaries).


Release
-------

- Make sure the names of the directories with the version numbers follow
  the previous patterns (otherwise some scripts won't work), then git
  commit the `/lib/firmware/intel/sof/` community tree that the
  installer just built and "installed" in your sof-bin clone. See git
  log for past examples. Alternative: you don't have to build the
  `/lib/firmware/intel/sof/` community tree yourself, you can also get
  it as a tarball from someone else or from some automated build system
  that you trust. The installer above has a `make tarball` target for
  community-signed firmware and user space tools.

- Add the Intel signed `*.ri` binaries to the empty `intel-signed/`
  subdirectory. Use the `tree` command to make sure all symbolic links
  are resolved and no `*.ri` firmware file is missing. Git commit the
  Intel signed binaries.

- If the `intel-signed/*.ri` files came with some corresponding `*.ldc`
  dictionary files, do not add the corresponding `*.ldc` files to the
  release because they should be exact duplicates of the community
  `*.ldc` files. Instead, make sure they are actually the same; it's a
  useful check. You can use something like this (or any preferred
  comparison tool)

      for i in *.ldc; do diff -s $i intel-signed-release/$i; done

- For pure shell completion convenience, add and commit an empty file,
  for example:

      touch v1.9.x/v1.9-rc1

- Test making a tarball:

      ./tarball_one_version.sh v1.9.x/v1.9-rc1

  To combine multiple subdirectories:

     ./tarball_multi_releases.bash -h

  Extract the tarball you just generated and verify it:

    ./compare_signed_unsigned.py sof-bin-new-version/

  Do not publish this test tarball before your final sof-bin pull
  request has been merged. Extract this test tarball you just generated
  and test its short `./install.sh` script. Move your older firmware
  directories first or override the install destination, see how at the
  top of the script.

- Submit the sof-bin pull request(s). A single pull request is normally
  enough but sometimes you may want to quickly share the community files
  while still waiting for the intel-signed ones. Or pre-release some
  platforms before others.

- Only after the final sof-bin pull request has been merged, generate
  and upload the official release tarball to
  https://github.com/thesofproject/sof-bin/releases This page lets you
  create a new tag. In text box for the release notes, add a link to
  the release notes for the same tag in the other, _sof_ source repo.
  Example:

      See release notes at https://github.com/thesofproject/sof/releases/tag/v1.9

If you realize you made a mistake in something already merged or
released, always increase the version number and start rebuilding
everything from scratch. Never delete or overwrite anything already
released https://git-scm.com/docs/git-tag#_on_re_tagging
