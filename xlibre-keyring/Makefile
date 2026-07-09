# Makefile for xlibre-keyring
# Maintainer tooling:
#   make update   - (re)generate xlibre.gpg from local .asc files or via
#                   fallback downloads
#   make install  - install keyring to system (typically used by PKGBUILD)
#   make uninstall- remove keyring files

V        = 20260709
PREFIX   = /usr
KEYDIR   = $(DESTDIR)$(PREFIX)/share/pacman/keyrings/

# Key fingerprints for XLibre repositories
ARCH_KEY_ID     = B97F7C613F359424
MANJARO_KEY_ID  = D1445F51BC0A8969

# URLs to the official key files (primary download source)
ARCH_URL        = https://xlibre-arch.github.io/xlibre-archlinux.asc
MANJARO_URL     = https://xlibre-manjaro.github.io/xlibre-manjarolinux.asc

# Local file names (used if present, otherwise download)
ARCH_ASC        = xlibre-archlinux.asc
MANJARO_ASC     = xlibre-manjarolinux.asc

# Temporary GPG home for import operations
TEMPHOME = $(shell mktemp -d)

.PHONY: update install uninstall

update:
	@echo "==> Obtaining Arch Linux XLibre key ($(ARCH_KEY_ID))"
	@# Try local .asc file first, then fallback chain
	@if [ -f "$(ARCH_ASC)" ]; then \
		echo "   Using local $(ARCH_ASC)"; \
		gpg --homedir $(TEMPHOME) --import "$(ARCH_ASC)" 2>/dev/null; \
	else \
		echo "   Downloading from primary URL..."; \
		curl -fsS $(ARCH_URL) -o $(TEMPHOME)/arch.asc 2>/dev/null && \
		gpg --homedir $(TEMPHOME) --import $(TEMPHOME)/arch.asc 2>/dev/null || \
		(echo "   Primary URL failed, trying keyserver.ubuntu.com..."; \
		 gpg --homedir $(TEMPHOME) --keyserver hkp://keyserver.ubuntu.com --recv-keys $(ARCH_KEY_ID) 2>/dev/null) || \
		(echo "   Ubuntu keyserver failed, trying keys.openpgp.org..."; \
		 gpg --homedir $(TEMPHOME) --keyserver hkps://keys.openpgp.org --recv-keys $(ARCH_KEY_ID) 2>/dev/null) || \
		{ echo "ERROR: Could not obtain Arch key!"; exit 1; }; \
	fi

	@echo "==> Obtaining Manjaro XLibre key ($(MANJARO_KEY_ID))"
	@# Try local .asc file first, then fallback chain
	@if [ -f "$(MANJARO_ASC)" ]; then \
		echo "   Using local $(MANJARO_ASC)"; \
		gpg --homedir $(TEMPHOME) --import "$(MANJARO_ASC)" 2>/dev/null; \
	else \
		echo "   Downloading from primary URL..."; \
		curl -fsS $(MANJARO_URL) -o $(TEMPHOME)/manjaro.asc 2>/dev/null && \
		gpg --homedir $(TEMPHOME) --import $(TEMPHOME)/manjaro.asc 2>/dev/null || \
		(echo "   Primary URL failed, trying keyserver.ubuntu.com..."; \
		 gpg --homedir $(TEMPHOME) --keyserver hkp://keyserver.ubuntu.com --recv-keys $(MANJARO_KEY_ID) 2>/dev/null) || \
		(echo "   Ubuntu keyserver failed, trying keys.openpgp.org..."; \
		 gpg --homedir $(TEMPHOME) --keyserver hkps://keys.openpgp.org --recv-keys $(MANJARO_KEY_ID) 2>/dev/null) || \
		{ echo "ERROR: Could not obtain Manjaro key!"; exit 1; }; \
	fi

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