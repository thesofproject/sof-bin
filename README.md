Starting from v1.7 the installation process has been simplified and
the go.sh script is not used anymore. Instead:

```
sudo mv /lib/firmware/intel/sof* some_backup_location/
sudo mv /usr/local/bin/sof-*     some_backup_location/ # optional
sudo ./install.sh v1.N.x/v1.N-rcM
```

The go.sh and install.sh for pre-v1.7 releases have been deleted,
you can find them in the git history.

There is a single git branch now, everything is in the default branch.

You don't have to use install.sh, you can use any recursive copy of
your preference. This is all what install.sh does, example with v1.7.x/v1.7:

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
