# Aktuell gewählter interner HTTP-Zugang

Auf ausdrücklichen Wunsch läuft der Tablet-Zugang unter
`http://192.168.1.191:8000/`. Dafür ist kein Zertifikat nötig.
Zugangsdaten: `.local/access.txt`.

Start: `.venv/bin/python scripts/serve_http_lan.py --address 192.168.1.191`.
PID-Datei: `.local/lan-http.pid`. Der Dienst bindet ausschließlich diese
LAN-Adresse. Debug bleibt aus; Anmeldung und CSRF-Prüfung bleiben aktiv.
HTTP überträgt Passwort und Dokumente unverschlüsselt. Die folgenden Angaben
beschreiben die optional weiterhin verfügbare HTTPS-Startkonfiguration.

# Tablet-Zugriff auf die lokale Entwicklungsinstanz

Der derzeitige LAN-Endpunkt ist `https://192.168.1.191:8443/`.
Tablet und Rechner müssen einander im lokalen Netzwerk erreichen können;
Gäste-WLANs oder Client-Isolation können dies verhindern. Der Rechner muss laufen.
Die IP kann sich bei einer neuen DHCP-Zuweisung ändern; dann den Dienst mit der
neuen IP neu starten. Das Serverzertifikat wird dafür passend neu ausgestellt.

## Zertifikatsvertrauen

Der Endpunkt verwendet HTTPS mit einer privaten CA für diese Testinstallation.
Das öffentliche CA-Zertifikat liegt unter `.local/tls/dms-local-ca.cer`.
Diese Datei auf dem Tablet manuell installieren und nach den Vorgaben des
Geräts als vertrauenswürdig einrichten. Die Installation nimmt der Benutzer
selbst vor. Ohne eingerichtetes Vertrauen ist die Zertifikatswarnung zu erwarten;
die Warnung nicht umgehen und noch keine Zugangsdaten eingeben.

Nur die öffentliche `.cer`-Datei übertragen, niemals `ca.key`, `server.key` oder
`secrets.json`. Das Vertrauen gilt für Zertifikate dieser lokalen CA. Deshalb
CA-Schlüssel privat halten und das Zertifikat nach Ende der Testphase auf dem
Tablet wieder entfernen. Für den späteren LXC-Betrieb die betriebliche PKI und
verwaltete Zertifikatsverteilung verwenden.

Den Fingerabdruck der öffentlichen CA auf dem Rechner anzeigen:

```sh
openssl x509 -in .local/tls/ca.pem -noout -fingerprint -sha256
```

## Betrieb

Der Dienst läuft mit deaktiviertem Django-Debug und sicheren HTTPS-Cookies.
Er verwendet die eingeschränkte App-Datenbankrolle. Ein vorangestellter Router
oder eine Portweiterleitung wird weder eingerichtet noch benötigt.

Starten:

```sh
.venv/bin/python scripts/serve_lan.py --address 192.168.1.191
```

Nach Codeänderungen den dokumentierten Gunicorn-Master neu laden:

```sh
kill -HUP "$(cat .local/lan.pid)"
```

Geordnet stoppen:

```sh
kill -TERM "$(cat .local/lan.pid)"
```

Diese Befehle nur verwenden, wenn die PID-Datei zum gestarteten DMS-Dienst gehört.
Anmeldedaten der lokalen Testkonten stehen in `.local/access.txt`.
Es wurde der HTTPS-Endpunkt vom Rechner aus mit Zertifikatsprüfung getestet;
der physische Zugriff vom Tablet und dessen Zertifikatsinstallation müssen noch
dort geprüft werden. Betriebssystem-Firewall oder WLAN-Isolation werden nicht
automatisch verändert.
