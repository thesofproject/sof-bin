# SOF Firmware and Topology Binaries

This is the living area and distribution channel for SOF firmware and topology
binaries. It's still very much WiP and may churn a little until things
settle down.

This repo will be frequently rebased in order to keep the size small and is
intended for packagers, release engineers, testers and devlopers.

The intention is to store all pre-compiled (and signed if neccesary) firmware
binaries and pre-compiled topologies for snapshot, stable and LTS releases.

# Repository Layout

There are four type of SOF release.

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

The repository will have a directly for each release at the top level with
links for lts, latest vendor snapshots, nightlies and stable releases. e.g.

toplevel --+---> v1.4.2
           |
           +---> v1.5.4
           |
           +---> v1.6.1
           |
           +---> v18032020-de6a4f92
           |
           +---> v02032020-ab36fe91
           |
           +---> lts --(link)--> v1.4.2
           |
           +---> stable-v1.5 --(link)--> v1.5.4
           |
           +---> stable-v1.6 --(link)--> v1.6.1
           |
           +---> nightly --(link)--> v18032020-de6a4f92
           |
           +---> snapshot-signed-intel --(link)--> v0232020-ab36fe91

It's possible due to release cadence to have several stable versions in the
repository and that the "lts" link may also point to release that also has a
"stable" link.

The nightly link will point to a nightly snapshot that will have a date tag
vDDMMYYYY-commit (where commit ID is in the short form). The same date tag
format wil be used by vendor snapshots too.

# Archived Releases

Each release currently takes up about 7MB and would quickly fill up and slow
down the repository with old data. Therefore SOF stable releases will be also
available on github whilst nightly and snapshot releases may be available on
vendor servers (in line with any vendor build/signing cadence).

