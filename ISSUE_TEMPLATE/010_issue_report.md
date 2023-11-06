---
name: Packaging or installation issue
about: Report a packaging or installation_ issue. No audio issue here!
---

Do NOT report **audio** issues here; search this different tracker instead:
https://github.com/thesofproject/sof/issues

Do NOT git clone this sof-bin repository, use only release tarballs found at https://github.com/thesofproject/sof-bin/releases

To report a package or installation issue answer the following questions:

Describe the bug
----------------
A clear and concise description of what the bug is.

Environment
-----------
1) Version number of the https://github.com/thesofproject/sof-bin/releases
   _Do NOT install from a git clone!_
1) Linux distribution and version
1) Hardware vendor and model
1) Output of the following command: `journalctl -k | grep -C 10 sof.*firmware`
   (or the equivalent if your system does not have `journalctl`.

Reproduction steps
------------------
Steps to reproduce the behavior: (e.g. list commands or actions used to reproduce the bug)

Logs and console outputs
------------------------

Expected behavior
-----------------
A clear and concise description of what you expected to happen.

Impact
------
What impact does this issue have on your progress (e.g., annoyance, showstopper)

