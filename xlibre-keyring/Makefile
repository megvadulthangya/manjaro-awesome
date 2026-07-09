# Makefile for xlibre-keyring
# Manage the generation of xlibre.gpg from the .asc key files.
# Maintainer targets:
#   make update   - import local .asc files and export combined keyring
#   make install  - install keyring to system (called by PKGBUILD)
#   make uninstall- remove keyring files

V        = 20260709
PREFIX   = /usr
KEYDIR   = $(DESTDIR)$(PREFIX)/share/pacman/keyrings/

# Key fingerprints (for GPG import selection)
ARCH_KEY_ID     = B97F7C613F359424
MANJARO_KEY_ID  = D1445F51BC0A8969

# Local ASCII-armored key files (must be present next to this Makefile)
ARCH_ASC        = xlibre-archlinux.asc
MANJARO_ASC     = xlibre-manjarolinux.asc

TEMPHOME = $(shell mktemp -d)

.PHONY: update install uninstall

update:
	@echo "==> Importing Arch XLibre key from $(ARCH_ASC)"
	@gpg --homedir $(TEMPHOME) --import "$(ARCH_ASC)" 2>/dev/null || \
		{ echo "ERROR: Failed to import $(ARCH_ASC)"; exit 1; }

	@echo "==> Importing Manjaro XLibre key from $(MANJARO_ASC)"
	@gpg --homedir $(TEMPHOME) --import "$(MANJARO_ASC)" 2>/dev/null || \
		{ echo "ERROR: Failed to import $(MANJARO_ASC)"; exit 1; }

	@echo "==> Exporting combined keyring to xlibre.gpg"
	@gpg --homedir $(TEMPHOME) --export --armor $(ARCH_KEY_ID) $(MANJARO_KEY_ID) > xlibre.gpg
	@rm -rf $(TEMPHOME)
	@echo "==> Keyring update complete"

install:
	install -dm755 $(KEYDIR)
	install -m0644 xlibre{.gpg,-trusted,-revoked} $(KEYDIR)

uninstall:
	rm -f $(KEYDIR)xlibre{.gpg,-trusted,-revoked}
	rmdir -p --ignore-fail-on-non-empty $(KEYDIR)