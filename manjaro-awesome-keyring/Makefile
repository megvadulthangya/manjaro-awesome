V=20260117

PREFIX = /usr
TRUSTED= $(shell cat manjaro-awesome-trusted | cut -d: -f1)
REVOKED= $(shell cat manjaro-awesome-revoked)

update:
	gpg --recv-keys $(TRUSTED) $(REVOKED)
	gpg --export --armor $(TRUSTED) $(REVOKED) > manjaro-awesome.gpg

install:
	install -dm755 $(DESTDIR)$(PREFIX)/share/pacman/keyrings/
	install -m0644 manjaro-awesome{.gpg,-revoked} $(DESTDIR)$(PREFIX)/share/pacman/keyrings/
	install -m0644 manjaro-awesome-trusted $(DESTDIR)$(PREFIX)/share/pacman/keyrings/manjaro-awesome-trusted

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/share/pacman/keyrings/manjaro-awesome{.gpg,-revoked,-trusted}
	rmdir -p --ignore-fail-on-non-empty $(DESTDIR)$(PREFIX)/share/pacman/keyrings/