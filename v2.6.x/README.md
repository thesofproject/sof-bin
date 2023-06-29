# SOF-2.6 prebuilt binaries for Intel cAVS2.5 hardware

**IMPORTANT NOTICE**
This binary release is an opt-in release for select Intel cAVS2.5 hardware
(11th, 12th and 13th Generation Intel® Core™ Mobile Processors).

Notably the Linux kernel requirements of this release are more strict
and the provided set of DSP topology files do not cover all the hardware
that is supported by stable releases.

For a complete release that includes support for all Intel hardware, you MUST
use official release tarballs (currently SOF2.2) found here:

https://github.com/thesofproject/sof-bin/releases

## Requirements

### Linux Kernel

These prebuilt binaries use the new SOF IPC4 host interface
and thus a recent Linux kernel version is required. All the required
patches are submitted to inclusion into mainline Linux kernel and are
queued for later release in Linux 6.5. Before 6.5 is out, following pre-6.5 
kernel snapshots have been validated to work with SOF2.6 release for Intel
cAVS2.5 hardware:

ASoC upstream tree, staging branch for 6.5 (asoc-v6.5)
https://git.kernel.org/pub/scm/linux/kernel/git/broonie/sound.git/commit/?id=2d0cad0473bd1ffbc5842be0b9f2546265acb011

### Hardware Capabilities

This release includes a set of DSP topology files that cover a large
set of systems equipped with a HDA audio codec for headset and speakers,
and a set of digital microphones connected directly to the Platform
Controller Hub (PCH).

## Installing the SOF binaries

Use the install script at sof-bin/install.sh to install
the binaries on your system (or follow the manual instructions
described in the install.sh file).

## Enabling SOF2.6 on cAVS2.5

The SOF driver will by default look for a stable firmware,
so following additional steps are needed to take the new
firmware into use:

```
mkdir -p /lib/firmware/intel/avs /lib/firmware/intel/avs-tplg
ln -s /lib/firmware/intel/sof-v2.6/* /lib/firmware/intel/avs/
ln -s /lib/firmware/intel/sof-tplg-v2.6/* /lib/firmware/intel/avs-tplg/
```

Add the following file to
"/etc/modprobe.d/sof-ipc4-override.conf":

```
# SOF audio driver, enable IPC4 mode
options snd_sof_pci ipc_type=1
options snd_sof_intel_hda_common sof_use_tplg_nhlt=1
```

And then reboot your system (or reload the SOF kernel
modules).

## Switching back to stable SOF2.2

To switch back to stable SOF2.2, restore symbolic
/lib/firmware/intel/sof to point back to
/lib/firmware/intel/sof-v2.2 and remove
"/etc/modprobe.d/sof-ipc4-override.conf".
