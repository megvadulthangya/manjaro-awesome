# Makefile for xlibre-keyring
# Manage the generation of xlibre.gpg from the .gpg key files.
# Maintainer targets:
#   make update   - import local .gpg files and export combined keyring
#   make install  - install keyring to system (called by PKGBUILD)
#   make uninstall- remove keyring files

V        = 20260709
PREFIX   = /usr
KEYDIR   = $(DESTDIR)$(PREFIX)/share/pacman/keyrings/

# Local ASCII-armored key files (using .gpg extension to avoid makepkg PGP processing)
ARCH_GPG        = xlibre-archlinux.gpg
MANJARO_GPG     = xlibre-manjarolinux.gpg

TEMPHOME = $(shell mktemp -d)

.PHONY: update install uninstall

update:
	@echo "==> Creating temporary GPG home at $(TEMPHOME)"
	@gpg --homedir $(TEMPHOME) --batch --import "$(ARCH_GPG)" ; \
		if [ $$? -ne 0 ]; then \
			echo "ERROR: Failed to import $(ARCH_GPG)"; \
			rm -rf $(TEMPHOME); \
			exit 1; \
		fi

	@gpg --homedir $(TEMPHOME) --batch --import "$(MANJARO_GPG)" ; \
		if [ $$? -ne 0 ]; then \
			echo "ERROR: Failed to import $(MANJARO_GPG)"; \
			rm -rf $(TEMPHOME); \
			exit 1; \
		fi

	@echo "==> Exporting combined keyring to xlibre.gpg"
	@gpg --homedir $(TEMPHOME) --batch --export --armor > xlibre.gpg ; \
		if [ $$? -ne 0 ]; then \
			echo "ERROR: Failed to export keyring"; \
			rm -rf $(TEMPHOME); \
			exit 1; \
		fi

	@if [ ! -s xlibre.gpg ]; then \
		echo "ERROR: Generated xlibre.gpg is empty!"; \
		rm -rf $(TEMPHOME); \
		exit 1; \
	fi

	@rm -rf $(TEMPHOME)
	@echo "==> Keyring update complete"

install:
	install -dm755 $(KEYDIR)
	install -m0644 xlibre{.gpg,-trusted,-revoked} $(KEYDIR)

uninstall:
	rm -f $(KEYDIR)xlibre{.gpg,-trusted,-revoked}
	rmdir -p --ignore-fail-on-non-empty $(KEYDIR)