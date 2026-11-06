# Dokumentenmanagementsystem für das IMS

Lokales Dokumentenmanagement für das integrierte Managementsystem im Unternehmen.
Planungsumfang: etwa 800 Benutzer, 30 Abteilungen und 1.000 Dokumente.
Die Anwendung verwendet Django 5.2 und PostgreSQL ab Version 16.

## Aktueller Stand

- Der Code und der Linux-Installer sind in [Schello805/Dms_sie](https://github.com/Schello805/Dms_sie) veröffentlicht.
- Neuinstallation, HTTP-Zugriff, Hintergrunddienste, tägliche Sicherung und Update mit vorheriger Sicherung wurden auf Ubuntu 24.04 erfolgreich [in GitHub Actions geprüft](https://github.com/Schello805/Dms_sie/actions/runs/42077086586).
- **Die Installation auf dem Zielsystem läuft laut Rückmeldung des Betreibers.** Das ist kein noch offener Entwicklungspunkt.
- Der Dokumentenworkflow wurde automatisiert und zusätzlich mit lokalen Konten praktisch geprüft; Details im [Prüfbericht](docs/workflow-review-2026-11-05.md).
- Die fachliche Betriebsabnahme und die tatsächlich im Unternehmen verbindlichen Normausgaben legt der Betreiber fest. Eine laufende Installation allein ist keine abgeschlossene fachliche Abnahme.

## Installation und Updates

Unterstützt werden Ubuntu 24.04 LTS und Debian 13 mit systemd, auch im Proxmox-LXC.
Den Installer **im Linux-Server/LXC**, nicht auf dem Proxmox-Host, ausführen.
Der gewählte Betrieb verwendet intern **HTTP**. PostgreSQL und Gunicorn bleiben auf Loopback.

Als root ausführen. Es wird keine feste IP benötigt oder vergeben; DHCP bleibt unverändert:

```bash
apt-get update
apt-get install -y curl python3 ca-certificates
curl -fsSL https://raw.githubusercontent.com/Schello805/Dms_sie/main/scripts/install_linux.py -o install-dms.py
python3 install-dms.py --repo https://github.com/Schello805/Dms_sie.git
```

Erste Anmeldung: Benutzer `admin`; das zufällig erzeugte Passwort steht nur auf dem Server:

```bash
cat /etc/ims-dms/initial-admin-password
```

Update als root:

```bash
curl -fsSL https://raw.githubusercontent.com/Schello805/Dms_sie/main/scripts/install_linux.py -o /tmp/install-ims-dms.py
python3 /tmp/install-ims-dms.py --update
```

[Ausführliche Installationsanleitung](docs/github-installation.md): Voraussetzungen,
private Repositories, weitere Benutzer, Services, Sicherungen und Fehlerbehandlung.
Die Installer-Tests auf GitHub prüfen Ubuntu 24.04; daraus folgt keine vollständige Abnahme aller Debian-/LXC-Konfigurationen.

## Bedienung und Rollen

| Rolle | Funktionen |
|---|---|
| Leser | Dokumentenübersicht, freigegebene Dokumente ansehen und herunterladen; überfällige Reviews blenden Dokumente nicht aus. |
| Autor | Hochladen, eigenen Entwurf in der Tabelle sehen, bearbeiten, Freigabe anfordern und neue Revisionen beginnen. |
| QMB | Aufgaben über die Glocke, unabhängige Prüfung, Freigabe oder begründete Rückgabe; fachliche Verwaltung. Mehrere QMB-Konten sind möglich. |
| IT-Admin | Systemeinstellungen, SMTP, Logo, Systeminformationen und Rollenzuordnung. Keine fachlichen Dokumentenrechte allein durch die Adminrolle. |

Autoren, QMB und Admin werden unter **Admin-Einstellungen → Benutzer und Rollen** zugeordnet.
Regulär angelegte Konten erhalten Leserrechte als Grundrolle. Ein Konto kann mehrere Rollen besitzen;
Selbstprüfung und Selbstfreigabe bleiben gesperrt.
Die alten technischen Rollen-/Qualifikationsfelder bleiben für historische Nachweise erhalten,
sind aber keine zusätzlichen auswählbaren Benutzerrollen. Eine gesonderte Freigaberolle
„QMB-Abteilungsleitung“ gehört nicht zum aktuellen Drei-Rollen-Modell.

### Dokumentenablauf

1. Autor lädt Metadaten und Datei gemeinsam hoch: **Als Entwurf hochladen** oder **Hochladen und an QMB senden**.
2. Nach Einreichung ist der Stand gegen Bearbeitung gesperrt. Ein unabhängiger QMB erhält eine Aufgabe.
3. Der QMB sieht Dateien und Metadaten und entscheidet über **Freigabe** oder **Ablehnung mit Bemerkung**.
4. Bei Rückgabe erscheint die Bemerkung direkt am Entwurf und als Autorenaufgabe. Nach Korrektur kann erneut eingereicht werden.
5. Mit Freigabe beginnt die Kategoriefrist, standardmäßig **24 Monate**. Erstupload, Wirksamkeitsdatum, Freigabedatum und letztes Review werden getrennt geführt.
6. Ein erfolgreiches periodisches Review verlängert die Frist ab Prüftag. Erforderliche Überarbeitung bleibt als Handlungsbedarf sichtbar; Rückzug/Archivierung erfolgen ausdrücklich und mit Begründung.
7. Bei einer neuen Major-/Minor-Revision bleibt die bisherige Freigabe bis zur Wirksamkeit des Nachfolgers verfügbar. Danach erhalten Leser die neue aktuelle Fassung.

Der QMB verwaltet Kategorienfristen, Aufbewahrungsmetadaten, logische Aufbewahrungsorte und Erinnerungsregeln unter **Verwaltung**.
Die IT pflegt SMTP und Benutzerkontakte. Vorab- und Fälligkeitserinnerungen gehen an den verantwortlichen Autor und die aktiven zuständigen QMBs; Wiederholungs- und Zugriffsprüfungen verhindern unberechtigten oder doppelten Versand.

### Zugriff ohne Anmeldung

Die Startseite ist die Dokumentenübersicht, keine Weiterleitung zum Login.
Ohne Anmeldung erscheinen nur aktuelle freigegebene **öffentliche Metadaten** ohne explizite Zugriffsbeschränkung.
Interne/vertrauliche Dokumente und alle Dateizugriffe erfordern eine Anmeldung.
Eine allgemein anonyme Lesefreigabe für Unternehmensdokumente ist nicht aktiviert.

## Bereits implementiert

- Sortierbare Dokumententabelle, Volltextsuche, Filter und Lazy Loading in Blöcken von 30 Dokumenten; Berechtigungen gelten auch beim Nachladen.
- Private Dateiablage, SHA-256-Integritätsprüfung, Major-/Minor-Versionen, eingefrorene Freigabestände und ergänzende Audit-Ereignisse.
- Dokumentbezogene Personen-/Gruppenzugriffe; vertrauliche Dokumente erfordern zusätzliche ausdrückliche Freigaben. Benannte QMBs besitzen den vorgesehenen zentralen Prüfzugriff.
- Normreferenzen je Version, Geltungsbereich nach Abteilungen, periodische Reviews sowie Rückzug und Archivierung ohne Wiederbelebung alter Fassungen.
- Lokale PDF-/TXT-Vorschau und zusätzliche PDF-Lesefassungen für Office-Quellen. Dauerhafte Links und QR-Codes führen zur aktuellen Freigabe.
- Volltextextraktion aus TXT, textbasierten PDFs, DOCX, XLSX und ODT. Formeln und Makros werden nicht ausgeführt.
- Konfigurierbare SMTP-Erinnerungen mit Warteschlange, Wiederholungsregeln und Versandprotokoll.
- Austauschbares Logo/Favicon, Softwareversion im Footer, Toast-Meldungen und Benutzermenü mit Rollen.
- IT-Fehlerprotokoll, Systeminformationen und gespeicherte AD-/LDAP-Anschlussparameter.
- Konsistente Datenbank-/Dateisicherungen mit Prüfsummen, passendem Quellstand und technischer Restore-Prüfung. Der Linux-Installer ergänzt geschützte Wiederherstellungsgeheimnisse.

Zielgruppen, Kenntnisnahmen und ein Nachweisregister sind zusätzlich im Code vorhanden.
Das Nachweisregister enthält unter anderem unveränderliche Nachweise, Aufbewahrungsverlängerungen,
Löschsperren und Aussonderungsanträge. Diese Funktionen sind **nicht Teil der vereinfachten Leseroberfläche**;
der frühere Portal-/Kenntnisnahme-Worker wird vom Installer nicht gestartet.

## Neu: Benutzerverwaltung, QMB-Arbeitsliste und Betriebsüberwachung

[Ausbaustufe 0.3.0-dev und Prüfstand](docs/priority-release-0.3.0.md).

- IT-Admins können lokale Benutzer direkt anlegen, Konten aktivieren/deaktivieren und Passwörter zurücksetzen. Benutzer können ihr eigenes Passwort ändern. Bestehende Sitzungen werden bei Deaktivierung oder Passwortwechsel beendet; Änderungen werden ohne Passwortdaten auditiert.
- Die QMB-Arbeitsliste und Glocke berücksichtigen Freigabeanfragen sowie bevorstehende/überfällige Reviews gemäß dem konfigurierten Vorlauf. Eigene Dokumente bleiben von unabhängigen Prüfaufgaben ausgeschlossen.
- Die IT sieht Lebenszeichen der Worker, den Nachweis der letzten Sicherung und Hinweise bei knappem Speicher. Lokale Hinweise ersetzen keine externe Alarmierung.
- Versionsvergleich für Metadaten, Norm-/Abteilungszuordnungen und Dateiprüfsummen; kein visueller PDF-Inhaltsvergleich.
- Rückkehr zur Tabelle behält Filter, Sortierung und Scrollposition pro Tab. Ungespeicherte Formulare warnen beim Verlassen. Tabellenkopf und Dokumentnummer bleiben beim Scrollen sichtbar.
- Der Installer fragt bei interaktiver Neuinstallation nach dem Domainnamen; leer bedeutet lokalen IP-Zugriff. Automatisiert sind `--host` oder `--non-interactive` erforderlich. Er legt keine Netzwerkkonfiguration an. Wechselnde IP-Adressen funktionieren; zusätzliche DNS-Namen sind optional über `--host` angebbar.

## Änderungsgründe überall optional (0.4.5-dev)

Allgemeine Begründungen und Änderungsbeschreibungen sind in allen Bereichen optional:
Dokumentänderungen und Revisionen, Stammdaten, Gruppen, Systemeinstellungen, Logos,
Aufbewahrung, Prüfbegründungen und Benutzerverwaltung. Ohne Eingabe protokolliert das System
„Keine zusätzliche Begründung angegeben.“; Ausführender, Aktion und Zeitpunkt bleiben erhalten.
Pflichtentscheidungen, Berechtigungen, Bestätigungen und die Rückmeldung bei Ablehnung bleiben
bestehen. Freitext wird zentral über `audit_text.py` verarbeitet; vorhandene Audit-Einträge
werden nicht verändert.

## Kompaktere Oberfläche und eindeutige Rollenanzeige (0.4.3-dev)

Kopfzeile, Logo, Formulare und Tabellen benötigen weniger Platz. Auf Touch-Geräten bleiben
Bedienelemente mindestens 44 Pixel hoch. Die tatsächlichen Zusatzrollen stehen direkt unter
dem Benutzernamen; „Leser“ wird nur angezeigt, wenn keine Zusatzrolle besteht. Gespeicherte
Rollenänderungen wirken auch bei einer bestehenden Anmeldung beim nächsten Seitenaufruf.

## Upload für Autoren und QMB (0.4.3-dev)

Autoren und aktive QMBs sehen direkt über der Dokumententabelle **Dokument hochladen** (`/new/`). QMBs benötigen dafür
keine zusätzliche Autorenrolle. Sie können ihre Dokumente als Entwurf speichern, bearbeiten und
zur Freigabe senden. Eigene Dokumente müssen durch einen anderen QMB freigegeben werden.
Die QMB-Rolle allein erlaubt keine Bearbeitung fremder Autorenentwürfe.

## Benutzerverwaltung: optionale Begründung (0.4.3-dev)

Bei Benutzeranlage, Profil-/Kontaktänderungen, Rollenänderungen, Aktivierung/Deaktivierung und
Passwortänderungen ist die Begründung optional. Die Aktion, der ausführende Benutzer und der
Zeitpunkt werden weiterhin auditiert. Ohne Freitext wird „Keine zusätzliche Begründung angegeben.“
protokolliert. Pflichtangaben für Dokumentfreigaben und andere fachliche Vorgänge bleiben erhalten.

## Fehlerkorrekturen aus der erneuten Prüfung (0.4.2-dev)

- Der letzte aktive QMB kann über die Benutzerrollenverwaltung nicht mehr entfernt werden; die Datenbankfunktion schützt ebenfalls davor.
- Autoren mit Rechten für einzelne Dokumente sehen ihre Aufgabenglocke, Rückgaben und Autorenrolle. Ein Uploadrecht für neue Dokumente wird dadurch nicht erteilt.
- Eine im Benutzerprofil ergänzte E-Mail-Adresse gibt Erinnerungen mit Fehler „fehlende Adresse“ erneut frei. Bereits versandte oder unklare Sendungen werden nicht wiederholt.
- Nginx erhält den ursprünglichen Host einschließlich Port. Damit bleibt die CSRF-Prüfung auch beim HTTP-Zugriff über einen zusätzlichen Port korrekt.

Prüfumfang und Grenzen: [Fehlerprüfung 0.4.2](docs/error-review-0.4.2.md).

## Proxy-Login-Korrektur (0.4.1-dev)

Hinterlegte Domainnamen werden automatisch als erlaubte HTTPS-Ursprünge für die CSRF-Prüfung
verwendet. Damit funktioniert HTTPS am Reverse Proxy bei internem HTTP, ohne den CSRF-Schutz
abzuschalten. Bestehende Systeme mit dem aktuellen Installer aktualisieren; siehe
[Reverse-Proxy-Hinweise](docs/github-installation.md#https-am-reverse-proxy-und-internes-http).

## Neu: Stammdatenverwaltung (0.4.0-dev)

Unter **Verwaltung → Stammdaten** verwaltet der QMB Kategorien einschließlich Reviewfristen,
Abteilungen, Aufbewahrungsorte, Normausgaben und Kapitelreferenzen. Einträge lassen sich anlegen,
suchen, bearbeiten, deaktivieren und wieder aktivieren. Bestehende Dokumentzuordnungen bleiben erhalten.

Unter **Admin → Gruppen** verwaltet die IT Gruppen, Mitglieder und Leser-/Autorenrechte.
Benutzerprofile können in der Benutzerverwaltung bearbeitet werden; QMB- und Adminrechte werden
weiterhin gezielt einzelnen Konten zugewiesen. Geschützte Altgruppen mit erweiterten Rollen
bleiben bezüglich Mitgliedschaften und Aktivstatus der administrativen CLI vorbehalten.

Bereits im Freigabeverfahren verwendete Normdefinitionen bleiben unveränderlich; neue Ausgaben
werden als neue Einträge angelegt. Physisches Löschen referenzierter Stammdaten ist bewusst
nicht vorgesehen. Änderungen einschließlich Begründung werden auditiert.

Details und Prüfstand: [Stammdatenverwaltung](docs/masterdata.md).

## Noch offen: technische Erweiterungen

Diese Punkte sind tatsächliche fehlende oder unvollständige Funktionen, keine Aussage darüber, ob die Installation läuft:

- [ ] **AD-/LDAP-Anmeldung, SSO und Benutzer-/Gruppensynchronisation.** Die Einstellungsfelder sind vorhanden, aktivieren aber noch keine Verzeichnisverbindung oder Anmeldung.
- [ ] **OCR und Malwareprüfung.** Scans ohne Textebene sind derzeit nicht per Volltext durchsuchbar; Dateiendungen und Integritätsprüfung ersetzen keinen Virenscanner.
- [ ] **Zusätzliche Betriebssystem-Isolation der Dokumentparser.** Ressourcenlimits bestehen bereits; eine weitergehende Parser-Sandbox ist nicht vollständig umgesetzt.
- [ ] **Automatische Verarbeitung von Bounces und Zustellbestätigungen.** SMTP-Annahme/Fehler werden protokolliert; eine SMTP-Annahme beweist keine Zustellung im Postfach.
- [ ] **Kontrollierter Löschvollzug und Bereinigung unreferenzierter Dokumentdateien.** Aufbewahrungsmetadaten und Teile der Nachweisverwaltung bestehen bereits; automatische Dokumentlöschung ist nicht implementiert.

Ob Kenntnisnahmen, Favoriten und das Nachweisregister wieder in die Benutzeroberfläche aufgenommen werden sollen,
ist eine fachliche Produktentscheidung, kein Fehler der aktuellen Leseransicht.

## Noch zu prüfen oder einzurichten: Unternehmensbetrieb

Die folgenden Aufgaben werden nicht durch die Softwareinstallation oder den CI-Test erledigt.
Ihr konkreter Stand auf dem Zielserver ist außerhalb der gemeldeten erfolgreichen Installation noch nicht bestätigt:

- [ ] Echte Benutzer, Abteilungen, Autoren-/QMB-/Admin-Zuordnungen und Empfängeradressen prüfen.
- [ ] Kategoriefristen, Aufbewahrungsregeln und das unternehmensspezifische Norm-Mapping fachlich festlegen.
- [ ] Unternehmens-SMTP konfigurieren und Vorab-/Überfälligkeitsmeldungen tatsächlich an Autor und QMB zustellen.
- [ ] Sicherungen auf ein getrenntes Ziel übertragen, Schutz vor Veränderung/Löschung und Aufbewahrung festlegen; Wiederherstellung auf dem Zielsystem abnehmen.
- [ ] Realistische Last-/Parallelitätstests mit dem vorgesehenen Nutzungsprofil durchführen.
- [ ] Den vollständigen Freigabeablauf mit repräsentativen Unternehmensdokumenten fachlich abnehmen.
- [ ] Entscheiden, ob der anonyme Zugriff über die derzeit öffentlichen Metadaten hinaus erweitert werden soll.

## Lokale Entwicklung

Einmalig eine virtuelle Umgebung erstellen und die festgeschriebenen Abhängigkeiten installieren:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
.venv/bin/python scripts/dev.py
```

Benötigt Python ab 3.12 und PostgreSQL-Binaries ab Version 16.
Der Starter legt die private Entwicklungsdatenbank unter `.local/postgres` an und startet PostgreSQL
auf `127.0.0.1:55439` sowie die Anwendung auf `http://127.0.0.1:8000/`.
Entwicklungszugänge stehen in `.local/access.txt`; vorhandene Passwörter bleiben erhalten.
Der Linux-Installer legt diese Demo-Konten und Demo-Dokumente **nicht** an.
`.local/`, `.venv/`, `.env` und Dokumentenspeicher sind von Git ausgeschlossen.

### Prüfungen

```bash
.venv/bin/python scripts/manage_local.py check
python3 -m unittest discover -s tests -p 'test_linux_installer.py' -v
```

Die Django-Tests (`manage.py test dms`) benötigen eine **separate PostgreSQL-Testumgebung**
mit CREATEDB. Sie prüfen echte Trigger und Berechtigungen. Nicht gegen eine Produktionsdatenbank ausführen.
Die Service-Datenbankrollen des Linux-Installers haben bewusst kein CREATEDB-Recht.

Neue lokale Produktionskonten werden administrativ angelegt, zum Beispiel:

```bash
sudo ims-dms-manage create_dms_user michael
sudo ims-dms-manage provision_dms michael --role QMB --department '*'
sudo ims-dms-manage create_dms_user autor
sudo ims-dms-manage provision_dms autor --role AUTHOR --department IT --department-name Informationstechnik
```

Migrationen ausschließlich über `manage.py migrate` anwenden, nicht zusätzlich die SQL-Dateien manuell ausführen.
Nach Migrationen müssen die Datenbank-Grants passen; der Linux-Updater erledigt beides.

## Weiterführende Dokumentation

- [Installation von GitHub und Updates](docs/github-installation.md)
- [Betrieb unter Linux / Proxmox LXC](docs/operations.md)
- [Workflow-Prüfung und Fehlerkorrekturen](docs/workflow-review-2026-11-05.md)
- [Aktuelle Oberfläche und historische Portalmodule](docs/employee-portal.md)
- [Normreferenzen](docs/standards.md)
- [Volltextverarbeitung](docs/fulltext.md)
- [E-Mail-Erinnerungen](docs/email-reminders.md)
- [Sicherung und Wiederherstellung](docs/backup.md)
- [Code-Struktur](docs/code-structure.md)

Uploads sind maximal 25 MiB groß. Unreferenzierte Dateien bleiben erhalten und dürfen nicht ungeprüft gelöscht werden.
Dateien liegen nicht in einer öffentlichen MEDIA-Ablage. Bereits heruntergeladene Dateien können nicht zurückgerufen werden.
Datenbank-/Hostadministratoren benötigen zusätzliche betriebliche Kontrollen; der Audit-Trail ersetzt keinen externen Manipulationsschutz.
