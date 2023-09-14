## Notice on Platform Coverage

WARNING: starting with v2.2, older Intel products are not supported by
the main SOF development branch anymore. To avoid duplication and
confusion in this sof-bin git repository, older product generations are
now intentionally MISSING from sof-bin subdirectories v2.x/sof-v2.2/ and
above.

For a complete release that includes all Intel products including older
ones you MUST use official release tarballs found here:

  https://github.com/thesofproject/sof-bin/releases

Installing directly from the sof-bin git repo should still work but it
will only install a subset.

Tarballs are now a combination of several sof-bin subdirectories
generated by a new release script. They include a new manifest.txt
describing that combination. For more details see Github issue #90.

## Release specific notes

Some releases have version specific notes on installation.
E.g. SOF v2.5 binaries require extra steps to configure the Linux
kernel to use new IPC variant. Please see v2.5.x/README.md

## Install process with install.sh - release tarballs

To install the release just perform a recursive copy. You can also try
the convenience ``./install.sh`` script:

```
tar zxf sof-bin-2023.09.tar.gz
cd sof-bin-2023.09
sudo mv /lib/firmware/intel/sof* some_backup_location/
sudo mv /usr/local/bin/sof-*     some_backup_location/ # optional
sudo ./install.sh
```

## Install process with install.sh (sof-bin git tree)

To run install from sof-bin git checkout:

```
sudo mv /lib/firmware/intel/sof* some_backup_location/
sudo mv /usr/local/bin/sof-*     some_backup_location/ # optional
sudo ./install.sh v1.N.x/v1.N-rcM
```

## Install with manual steps (without install.sh)

Again you don't have to use `install.sh`, you can use any recursive copy of
your preference. This is all what install.sh does, example with
v1.7.x/v1.7:

```
cd v1.7.x
rsync -a sof*v1.7   /lib/firmware/intel/
ln -s sof-v1.7      /lib/firmware/intel/sof
ln -s sof-tplg-v1.7 /lib/firmware/intel/sof-tplg
rsync tools-v1.7/*  /usr/local/bin
```

If you don't want the symbolic links:

```
rsync -a sof-v1.7/       /lib/firmware/intel/sof/
rsync -a sof-tplg-v1.7/  /lib/firmware/intel/sof-tplg/
rsync tools-v1.7/        /usr/local/bin/
```

Remember that for `rsync` (and some versions of `cp`), a trailing slash
in `srcdir/` is roughly equivalent to `srcdir/*` + `srcdir/.??*`  This
is how a recursive `rsync` is always idempotent while a recursive `cp`
is typically not.
