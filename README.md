Starting from v1.7 the installation process has been simplified and
the go.sh script is not used anymore. Instead:

```
sudo mv /lib/firmware/intel/sof* some_backup_location/
sudo mv /usr/local/bin/sof-*     some_backup_location/ # optional
sudo install.sh v1.7
```

The go.sh script still applies to older releases.

You don't have to use install.sh, you can use any recursive copy of
your preference. This is all what install.sh does:

```
rsync -a sof*v1.7   /lib/firmware/intel/
ln -s sof-v1.7      /lib/firmware/intel/sof
ln -s sof-tplg-v1.7 /lib/firmware/intel/sof-tplg
rsync tools-v1.7/* /usr/local/bin
```

If you don't want the symbolic links:

```
rsync -a sof-v1.7/       /lib/firmware/intel/sof/
rsync -a sof-tplg-v1.7/  /lib/firmware/intel/sof-tplg/
rsync tools-v1.7/        /usr/local/bin/
```

Remember that for rsync (and some versions of `cp`), a trailing slash in
srcdir/ is rougly equivalent to srcdir/*
