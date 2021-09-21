How to make a new release
-------------------------

Build the /lib/firmware/intel/sof/ tree
---------------------------------------

- After validation, create the new git tag.

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
  log for past examples. Note: you don't have to build the
  `/lib/firmware/intel/sof/` community tree yourself, you can also get
  it as a tarball from someone else or from some automated build system
  that you trust.

- Add the Intel signed `*.ri` binaries in the `intel-signed/`
  subdirectory. Use the `tree` command to make sure all symbolic links
  are resolved and no `*.ri` firmware file is missing. Git commit the
  Intel signed binaries.

- For pure shell completion convenience, add and commit an empty file,
  for example:

      touch v1.9.x/v1.9-rc1

- Test making a tarball:

      ./tarball_one_version.sh v1.9.x/v1.9-rc1

  Do not share this test tarball before the final sof-bin pull request
  has been merged, see below why. Extract this test tarball you just
  generated and have a look at its content.

- Submit the sof-bin pull request(s). A single pull request is normally
  enough; sometimes you may want to quickly share the community files
  while waiting for the intel-signed ones or share some platforms before
  others.

- Only after the final sof-bin pull request has been merged, generate
  and upload the tarball to
  https://github.com/thesofproject/sof-bin/releases

Everything is immutable: never overwrite or rename any version of
anything (tags, firmware images, directories, tarballs,...) unless you
want all users to deeply hate you for not knowing which duplicate
version they have. If you screwed up, simply create a new release
candidate. If the only delta between -rc5 and -rc6 is a README file then
you obviously don't need to run tests on -rc6 again.
