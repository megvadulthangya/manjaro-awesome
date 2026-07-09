# Makefile for xlibre-keyring
# Manage the generation of xlibre.gpg from the .gpg key files.
# Maintainer targets:
#   make update   - import local .gpg files and export combined keyring
#   make install  - install keyring to system (called by PKGBUILD)
#   make uninstall- remove keyring files

V        = 20260709
PREFIX   = /usr
KEYDIR   = $(DESTDIR)$(PREFIX)/share/pacman/keyrings/

ARCH_GPG    = xlibre-archlinux.gpg
MANJARO_GPG = xlibre-manjarolinux.gpg

.PHONY: update install uninstall

update:
	@TEMPHOME=$$(mktemp -d); \
	trap 'rm -rf "$$TEMPHOME"' EXIT; \
	echo "==> Importing Arch XLibre key from $(ARCH_GPG)"; \
	gpg --homedir "$$TEMPHOME" --batch --import "$(ARCH_GPG)" || exit 1; \
	echo "==> Importing Manjaro XLibre key from $(MANJARO_GPG)"; \
	gpg --homedir "$$TEMPHOME" --batch --import "$(MANJARO_GPG)" || exit 1; \
	echo "==> Exporting combined keyring to xlibre.gpg"; \
	gpg --homedir "$$TEMPHOME" --batch --export --armor > xlibre.gpg || exit 1; \
	if [ ! -s xlibre.gpg ]; then \
		echo "ERROR: Generated keyring is empty" >&2; \
		exit 1; \
	fi; \
	echo "==> Keyring update complete"

install:
	install -dm755 $(KEYDIR)
	install -m0644 xlibre{.gpg,-trusted,-revoked} $(KEYDIR)

uninstall:
	rm -f $(KEYDIR)xlibre{.gpg,-trusted,-revoked}
	rmdir -p --ignore-fail-on-non-empty $(KEYDIR)