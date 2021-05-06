# SOF Firmware and Topology Binaries

This is the living area and distribution channel for SOF firmware and topology
binaries. It's still very much WiP and may churn a little until things
settle down.

This repo will be frequently rebased in order to keep the size small and is
intended for packagers, release engineers, testers and devlopers.

The intention is to store all pre-compiled (and signed if neccesary) firmware
binaries and pre-compiled topologies for snapshot, stable and LTS releases.

# Installation

The latest SOF release is version 1.7 and is available here. If you want to
install this manually instead of from your distribution then please follow
these instructions

```
git clone https://github.com/thesofproject/sof-bin.git
cd sof-bin
git checkout v1.7 -b local/v1.7
sudo ./go.sh
```

alternatively zip and tar files are available to download.

https://github.com/thesofproject/sof-bin/releases/tag/v1.7

These files can be uncompressed and the go.sh can be executed as above.

At this point please the firmware, topologies are all installed
and available to be used.

You may need to tell the SOF kernel driver about the new firmware and
this ca be done by unloading and reloading the modules as follows.

```
sudo modprobe -r snd_sof_pci
sudo modprobe snd_sof_pci
```
or

```
sudo modprobe -r snd_sof_acpi
sudo modprobe snd_sof_acpi
```

If above does not work then rebooting your device will also reload the
SOF driver.

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

The repository will have a tag for each release e.g. latest vendor snapshots,
nightlies and stable releases.

```
main ------+---> v1.4.2
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

It's possible due to release cadence to have several stable branches in the
repository.

