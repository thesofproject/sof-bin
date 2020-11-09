# SOF Firmware and Topology Binaries

This is the living area and distribution channel for SOF firmware and topology
binaries. It's still very much WiP and may churn a little until things
settle down.

This repo will be frequently rebased in order to keep the size small and is
intended for packagers, release engineers, testers and devlopers.

The intention is to store all pre-compiled (and signed if neccesary) firmware
binaries and pre-compiled topologies for snapshot, stable and LTS releases.

# Repository Layout

There are four types of SOF releases.

1) stable - fully validated release with updates for 6 months. Deleted 3 months
            after updates end.

2) LTS -    fully validated release with updates for 2 years. Deleted 3 months
            after updates end.

3) nightly - unvalidated (may not even boot) high frequency release. Deleted
             immediately upon release of next nightly. Signed with public key
             if necessary.

4) snapshot vendor - unvalidated (may not even boot) high frequency release.
            Deleted immediately upon release of next vendor snapshot. Signed
            with vendor key - less frequent than nightly.

The repository will have a branch for each release e.g. latest vendor snapshots,
nightlies and stable releases.

```
master ----+---> v1.4.2
           |
           +---> v1.5.4
           |
           +---> v1.6.1
           |
           +---> v18032020-intel
           |
           +---> v02032020
           |
           +---> lts-20.10
```

The master branch will not contain any binaries, but will contain all the tools
necessary for release management.

It's possible due to release cadence to have several stable branches in the
repository.

The nightly nightly snapshot branch will have a date tag vDDMMYYYY. The same
date tag format will be used by vendor snapshots too.

Probably you need to clone a specific branch instead of cloning the default master branch.
For example, to clone a stable branch, you can do:
```
git clone -b stable-v1.4.2 https://github.com/thesofproject/sof-bin.git
```
After that, change to the created directory and execute the script:
```
sudo ./go.sh
```
# Archived Releases

Each release currently takes up about 7MB and would quickly fill up and slow
down the repository with old data. Therefore SOF stable releases will be also
available on github whilst nightly and snapshot releases may be available on
vendor servers (in line with any vendor build/signing cadence). Old release
branches will be deleted.

