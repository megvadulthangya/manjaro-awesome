# Makefile for xlibre-keyring
# Manage the generation of xlibre.gpg from the .gpg key files.
# Maintainer targets:
#   make update   - import local .gpg files and export combined keyring
#   make install  - install keyring to system (called by PKGBUILD)
#   make uninstall- remove keyring files

V        = 20260709
PREFIX   = /usr
KEYDIR   = $(DESTDIR)$(PREFIX)/share/pacman/keyrings/

# Local ASCII-armored key files (using .gpg to avoid makepkg signature detection)
ARCH_GPG        = xlibre-archlinux.gpg
MANJARO_GPG     = xlibre-manjarolinux.gpg

TEMPHOME = $(shell mktemp -d)

.PHONY: update install uninstall

update:
	@echo "==> Importing Arch XLibre key from $(ARCH_GPG)"
	@gpg --homedir $(TEMPHOME) --import "$(ARCH_GPG)" 2>/dev/null || \
		{ echo "ERROR: Failed to import $(ARCH_GPG)"; exit 1; }

	@echo "==> Importing Manjaro XLibre key from $(MANJARO_GPG)"
	@gpg --homedir $(TEMPHOME) --import "$(MANJARO_GPG)" 2>/dev/null || \
		{ echo "ERROR: Failed to import $(MANJARO_GPG)"; exit 1; }

	@echo "==> Exporting combined keyring to xlibre.gpg"
	@gpg --homedir $(TEMPHOME) --export --armor > xlibre.gpg 2>/dev/null || \
		{ echo "ERROR: Failed to export keyring"; exit 1; }
	@rm -rf $(TEMPHOME)
	@echo "==> Keyring update complete"

install:
	install -dm755 $(KEYDIR)
	install -m0644 xlibre{.gpg,-trusted,-revoked} $(KEYDIR)

uninstall:
	rm -f $(KEYDIR)xlibre{.gpg,-trusted,-revoked}
	rmdir -p --ignore-fail-on-non-empty $(KEYDIR)