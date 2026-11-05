# Installation von GitHub auf Linux / Proxmox LXC

Der Installer unterstützt einen **dedizierten Ubuntu-24.04-LTS- oder Debian-13-Server mit systemd**, auch als unprivilegierter Proxmox-LXC. Er wird **im Container**, nicht auf dem Proxmox-Host, gestartet. Er verwendet den gewünschten internen HTTP-Betrieb.

Ubuntu 24.04 liefert PostgreSQL 16, Debian 13 PostgreSQL 17. Der Installer setzt PostgreSQL >=16 voraus und verwendet die offiziellen Distributionspakete. Quellen: [Ubuntu-Release-Notes](https://github.com/ubuntu/ubuntu-release-notes/blob/main/docs/24.04/index.md), [Debian-Release-Notes](https://www.debian.org/releases/trixie/release-notes/whats-new.en.html).

## 1. Projekt in dein Repository übernehmen

Das Repository muss die Projektdateien inklusive `scripts/`, `dms/`, `config/`, `db/`, `deploy/` und `requirements.lock.txt` enthalten. `.local/`, `.venv/`, Dokumentenspeicher und echte Zugangsdaten gehören nicht hinein und werden bereits über `.gitignore` ausgeschlossen.

Das Projekt liegt unter [Schello805/Dms_sie](https://github.com/Schello805/Dms_sie). Die Installation benötigt keine feste IP und verändert weder DHCP noch Netzwerkschnittstellen. Für reproduzierbare Installationen einen geprüften Tag oder Commit statt `main` verwenden und beim Download sowie bei `--ref` denselben Stand angeben. Für eigene Forks die Repository- und Download-Adresse entsprechend ersetzen.

## 2. Online installieren

Als root im Zielserver/LXC:

```bash
apt-get update
apt-get install -y curl python3 ca-certificates
curl --fail --show-error --location \
  https://raw.githubusercontent.com/Schello805/Dms_sie/main/scripts/install_linux.py \
  --output /tmp/install-ims-dms.py

# Ablauf unverbindlich ansehen; verändert nichts:
python3 /tmp/install-ims-dms.py --dry-run \
  --repo https://github.com/Schello805/Dms_sie.git \
  --ref main

# Installieren:
python3 /tmp/install-ims-dms.py \
  --repo https://github.com/Schello805/Dms_sie.git \
  --ref main
```

Zusätzliche DNS-Namen sind optional: `--host dms.firma.intern`. Ohne diesen Parameter funktionieren die aktuelle IP (auch nach DHCP-Wechsel), localhost und der Serverhostname. Standardport ist **80**; optional `--port 8080`. DNS muss auf den Server zeigen. Netzwerk-/Proxmox-Firewallregeln und Paketquellen werden nicht verändert. APT-Zugriffe haben begrenzte Netzwerk-Wartezeiten und brechen bei nicht erreichbaren Quellen ab; dann Paketspiegel/Proxy prüfen und erneut starten.

Für private Repositories: Code mit deinem bereits eingerichteten GitHub-Zugang klonen und `sudo python3 scripts/install_linux.py --repo git@github.com:Schello805/Dms_sie.git --source-dir "$PWD"` verwenden. Spätere Online-Updates benötigen einen passenden SSH-Zugang für root oder erneut `--source-dir`. Keine Tokens in Repository-URLs eintragen. Der Installer richtet keine GitHub-Zugangsdaten ein.

## 3. Erste Anmeldung

- URL: `http://SERVER-HOSTNAME/` oder `http://AKTUELLE-SERVER-IP/`
- Benutzer: `admin` (änderbar bei Installation mit `--admin-user`)
- Zufällig erzeugtes Passwort auf dem Server lesen:

```bash
sudo cat /etc/ims-dms/initial-admin-password
```

Der initiale Administrator besitzt IT-Adminrechte, **keine Autor- oder QMB-Rechte und keine Django-Superuser-Rechte**. Das Passwort kann anschließend administrativ geändert werden:

```bash
sudo ims-dms-manage changepassword admin
```

Die Datei enthält nur das ursprüngliche Passwort und wird nach Passwortänderungen nicht aktualisiert. Nicht mehr benötigte initiale Passwortdatei nach erfolgreicher Einrichtung entfernen.

Lokale Benutzer anlegen und zuordnen:

```bash
sudo ims-dms-manage create_dms_user michael
sudo ims-dms-manage provision_dms michael --role QMB --department '*'

sudo ims-dms-manage create_dms_user autor
sudo ims-dms-manage provision_dms autor --role AUTHOR --department IT --department-name Informationstechnik
```

Der zweite Befehl legt die beispielhafte Abteilung IT an. Das Abteilungskürzel und den Namen durch eure echten Stammdaten ersetzen; eine leere Neuinstallation enthält bewusst keine erfundenen Abteilungen. Weitere Normreferenzen lassen sich mit `ims-dms-manage add_standard_reference` ergänzen. Der Installer legt nur die drei im Projekt verwendeten Normausgaben mit der Referenz 7.5 an, keine Normvolltexte.

Benutzer können direkt unter **Admin-Einstellungen → Benutzer und Rollen** angelegt, aktiviert/deaktiviert und mit Rollen versehen werden. Dort sind auch Passwortzurücksetzungen möglich; das eigene Passwort lässt sich im Profilmenü ändern. Die untenstehenden CLI-Befehle bleiben für administrative Einrichtung verfügbar. Fachliche Kategorien und Review-Fristen verwaltet ein QMB. SMTP muss im Adminbereich eingerichtet werden; die fachlichen Erinnerungsregeln liegen beim QMB. AD/LDAP-Produktivanmeldung wird durch den Installer nicht aktiviert.

## 4. Was installiert wird

| Bestandteil | Ort / Dienst |
|---|---|
| Versionierte Quellstände und virtuelle Umgebung | `/opt/ims-dms/releases/…` |
| Aktiver Stand | `/opt/ims-dms/current` |
| Geschützte Konfiguration und Datenbankpasswörter | `/etc/ims-dms/`, root, 0700/0600 |
| Private Dokumente und Fehlerprotokoll | `/var/lib/ims-dms/`, Benutzer `ims-dms` |
| Webanwendung | `ims-dms.service`, Gunicorn nur `127.0.0.1:8000` |
| HTTP-Proxy | Nginx, `/etc/nginx/conf.d/ims-dms.conf` |
| Volltext | `ims-dms-index.service` |
| Review-Erinnerungen | `ims-dms-notifications.service` |
| Tägliche Sicherung, 03:15 Europe/Berlin | `ims-dms-backup.timer` |
| Sicherungen | `/var/backups/ims-dms/` |
| Administrative Kommandos mit Eigentümerzugang | `sudo ims-dms-manage …` |

PostgreSQL verwendet getrennte Rollen für Eigentümer/Migrationen, Webanwendung, Suche, Benachrichtigungen und Sicherung. Der Eigentümerzugang steht nicht in den Web-/Worker-Environment-Dateien. Alle Anwendungsrollen sind ohne Superuser-/CREATEDB-/CREATEROLE-Rechte.

Bei erkanntem LXC werden mount-namespace-basierte systemd-Schutzoptionen nicht gesetzt, damit kein privilegierter Container oder nachträglich aktiviertes Nesting erforderlich ist. Benutzertrennung, Dateirechte und `NoNewPrivileges` bleiben bestehen. Auf normalen Linux-Hosts werden die zusätzlichen Schutzoptionen gesetzt.

Der frühere Kenntnisnahme-/Portal-Worker wird nicht gestartet. Leser verwenden die Dokumentenübersicht.

## 5. Updates

Den Installer zuerst aus dem gewünschten GitHub-Stand neu herunterladen. Damit werden auch Änderungen am Installer selbst (etwa der DHCP-Zugriff) übernommen:

```bash
curl -fsSL https://raw.githubusercontent.com/Schello805/Dms_sie/main/scripts/install_linux.py -o /tmp/install-ims-dms.py
python3 /tmp/install-ims-dms.py --update --ref main
```

Das Update bereitet einen neuen Quellstand und eine neue virtuelle Umgebung vor. Danach werden Web-/Worker-/Backup-Dienste angehalten, eine konsistente Sicherung erstellt, Migrationen und Grants angewendet und erst anschließend auf den neuen Stand umgeschaltet. Nginx bleibt erreichbar, während die Anwendung im Wartungsfenster vorübergehend nicht verfügbar ist. Nach erfolgreicher HTTP-Prüfung starten die Dienste normal weiter. Geheimnisse und Dokumentenspeicher bleiben erhalten.

Das Update überschreibt ausschließlich vom Installer markierte Service-/Nginx-Dateien. Fremde Dateien werden nicht übernommen. Bestehende Datenbanken ohne Installationsstatus werden nicht automatisch migriert. Abgebrochene Erstinstallationen können mit unveränderten Repository-/Host-Parametern erneut aufgerufen werden; generierte Geheimnisse werden wiederverwendet.

**Bei Migrations-/Startfehlern:** Web-/Worker-Dienste bleiben angehalten. Keine automatische Datenbankrückmigration. Erst Protokolle und Sicherung prüfen. Quellcode-Rollback allein stellt einen bereits geänderten Datenbankstand nicht wieder her. Alte Release-Verzeichnisse und Sicherungen werden nicht automatisch gelöscht.

## 6. Kontrolle und Sicherung

```bash
sudo systemctl status ims-dms ims-dms-index ims-dms-notifications
sudo systemctl list-timers ims-dms-backup.timer
sudo journalctl -u ims-dms -n 100 --no-pager
sudo nginx -t
sudo ims-dms-manage check
```

Die täglichen Sicherungen verwenden die bestehende konsistente Datenbank-/Dateisicherung mit Prüfsummen. Die täglichen Sicherungen und Update-Sicherungen erhalten zusätzlich eine private Kopie von `install.json`; darin liegen die für Wiederherstellung und verschlüsselte SMTP-/LDAP-Konfiguration erforderlichen Geheimnisse. Der Sicherungsdienst läuft dafür als root, verbindet sich aber ausschließlich mit der SELECT-berechtigten Datenbank-Sicherungsrolle. Die Konfigurationskopie ist nur für root lesbar. Das lokale Sicherungsverzeichnis ersetzt kein getrenntes Sicherungsziel. Aufbewahrung und Kopie auf ein anderes System müssen betrieblich eingerichtet werden.

## 7. Tests

- Lokal ausführbar: `python3 -m unittest discover -s tests -p 'test_linux_installer.py' -v`.
- PostgreSQL-Tests: `dms.test_installer_bootstrap` prüft initiale Rechte, Wiederholbarkeit und das Verbot der Hochstufung bestehender Benutzer.
- `.github/workflows/linux-install.yml` führt auf GitHub Ubuntu-24.04-Neuinstallation, HTTP-/Dienstprüfung und ein Update mit Sicherung aus; zusätzlich manuell über **Actions → Linux installer → Run workflow** startbar.

Der vollständige Ubuntu-24.04-Lauf wurde am 05.11.2026 erfolgreich auf GitHub ausgeführt: Neuinstallation, Dienst-/HTTP-Prüfung, tägliche Sicherung und Update mit vorheriger Sicherung. [Erfolgreicher CI-Lauf](https://github.com/Schello805/Dms_sie/actions/runs/42077086586). Ein echter Proxmox-LXC und Debian 13 wurden noch nicht vollständig durchinstalliert. Die Wiederherstellungsabnahme und ein vollständiger Rollen-/Freigabetest auf dem Zielserver bleiben Teil der Inbetriebnahme.

## DHCP, Host-Prüfung und vorhandene Nginx-Startseite

Der Installer setzt `DMS_DYNAMIC_HOSTS=1`. Die Anwendung akzeptiert dann gültige IP-Adressen als Host sowie localhost, den Serverhostname und ausdrücklich konfigurierte DNS-Namen; beliebige fremde DNS-Hostheader bleiben gesperrt. Der HTTP-Proxy ist der Defaultserver am gewählten Port. Bei Port 80 wird nur die erkennbare unveränderte Paket-Startseite von Nginx deaktiviert und ihr Verweis unter `/etc/ims-dms/nginx-packaged-default.saved` aufgehoben. Benutzerdefinierte Default-Konfigurationen werden nicht überschrieben.

Für bereits installierte Systeme übernimmt ein Update diese Einstellungen. Bestehende `--host`-Angaben bleiben als zusätzliche Namen erhalten, beschränken den Zugriff aber nicht mehr auf eine alte IP. Der Installer vergibt zu keinem Zeitpunkt eine statische Netzwerkadresse.

## Betriebsüberwachung

Index- und Erinnerungsworker schreiben lokale Lebenszeichen unter `/var/lib/ims-dms/health/`; der tägliche Sicherungsdienst meldet Erfolg oder Fehler. Im IT-Bereich erscheinen Warnungen bei fehlenden/veralteten Rückmeldungen, fehlgeschlagener Sicherung oder knappem Dateispeicher. Ein abgeschalteter Erinnerungsversand erzeugt keine unnötige Workerwarnung. Die Überwachung erfolgt in der Anwendung, ohne externe Alarmnachricht. Betrieblich zusätzlich eine externe Erreichbarkeitsüberwachung und getrennte Sicherung vorsehen.

Für gedruckte QR-Codes und dauerhaft gültige E-Mail-Links einen stabilen DNS-Namen verwenden. Ein QR-Code mit einer früheren IP kann durch einen DHCP-Wechsel nicht automatisch auf die neue IP umgebogen werden.
