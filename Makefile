
#
# This script installs the firmware files in the place where the linux
# firmware loading system expects them - `/lib/firmware`. It supports
# DESTDIR installations for package manager software. You should just
# have to `sudo make install` to put the files in the correct location.
#

VERSION ?= v1.5.1

FIRMWAREDIR ?= $(DESTDIR)/usr/lib/firmware

all:

check:

install:
	mkdir -p $(FIRMWAREDIR)
	cp -rf lib/firmware/intel $(FIRMWAREDIR)/

	mkdir -p $(FIRMWAREDIR)/sof

	ln -s $(VERSION)/sof-bdw-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-bdw.ri
	ln -s $(VERSION)/sof-byt-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-byt.ri
	ln -s $(VERSION)/sof-cht-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-cht.ri

	ln -s $(VERSION)/intel-signed/sof-apl-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-apl.ri
	ln -s $(VERSION)/intel-signed/sof-apl-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-glk.ri
	ln -s $(VERSION)/intel-signed/sof-cnl-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-cfl.ri
	ln -s $(VERSION)/intel-signed/sof-cnl-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-cnl.ri
	ln -s $(VERSION)/intel-signed/sof-cnl-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-cml.ri
	ln -s $(VERSION)/intel-signed/sof-icl-$(VERSION).ri $(FIRMWAREDIR)/intel/sof/sof-icl.ri

	ln -s sof-tplg-$(VERSION) $(FIRMWAREDIR)/intel/sof-tplg

