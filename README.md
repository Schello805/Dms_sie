# Dokumentenmanagementsystem für das IMS

Lokales Dokumentenmanagement für einen unprivilegierten Linux-LXC unter Proxmox.
Planungsumfang: etwa 800 Benutzer, 30 Abteilungen und 1.000 Dokumente.
Django 5.2 und PostgreSQL 16 oder neuer; AD-Integration folgt später.

## Implementierter Stand

- Lokale Anmeldung, CSRF-Schutz und ausschließlich POST für Änderungen.
- Dokumentübersicht mit eigener Dokumentnummer-Spalte und berechtigungsgefilterter
  Volltextsuche in Nummer, Titel und verarbeitetem Dateiinhalt.
- Rollen AUTHOR, REVIEWER, ADMIN und READER: unternehmensweit, abteilungsbezogen
  oder dokumentbezogen; direkt oder über aktive DMS-Gruppen.
- Dokumentbezogene Zugriffslisten für Personen/Gruppen; vertrauliche Fassungen
  verlangen zusätzlich zur Rolle eine ausdrückliche Zugriffsfreigabe; benannte QMBs erhalten zentralen Zugriff.
- Erstellen und Bearbeiten von Entwürfen, private Dateiablage und geprüfte Downloads.
- Prüfzyklen mit Rückgabe: Ein unabhängiger QMB prüft; er selbst oder die benannte QMB-Abteilungsleitung erteilt anschließend die Freigabe.
- SHA-256-Fingerabdruck über Dateien und relevante Versionsmetadaten je Prüfzyklus.
- Neue Major- oder Minor-Revision aus der neuesten freigegebenen Fassung; alte Freigabe bleibt während
  der Überarbeitung wirksam. Dateien können im neuen Entwurf ersetzt werden.
- Normreferenzen je Version, mehrere fachlich betroffene Abteilungen und Filter
  nach verantwortlicher Abteilung und konkreter Normausgabe.
- Periodische Prüfungen mit unveränderlicher Historie und fortgeschriebenem
  Prüftermin ohne Inhaltsversionierung; Übersicht fälliger Prüfungen/Handlungsbedarf.
- Aufgabenübersicht für offene Prüfungen/Freigaben sowie fällige Überprüfungen.
- Dokumentweiter Rückzug und Archivierung ohne automatische Reaktivierung alter Fassungen.
- Zeitgesteuerte Wirksamkeit: Leser sehen die neueste wirksam freigegebene Fassung.
- Unveränderliche freigegebene Versionszeilen und Zuordnungen; Entscheidungen,
  Dateimetadaten und Audit-Ereignisse sind nur ergänzbar.
- Automatische Audit-Ereignisse für die implementierten Dokumentaktionen,
  Ansichten, Downloads, Integritätsfehler und administrative Rollenzuordnung.

Die Anwendung ist ein getesteter Entwicklungsstand, noch kein produktiv
abgenommenes oder als normkonform nachgewiesenes Gesamtsystem.

## Sofortstart mit eigener lokaler Datenbank

```sh
.venv/bin/python scripts/dev.py
```

Benötigt installierte Abhängigkeiten sowie PostgreSQL-Binaries ab Version 16.
Das Skript initialisiert eine eigene Datenbank unter `.local/postgres`, startet
PostgreSQL auf `127.0.0.1:55439` und die Anwendung auf `127.0.0.1:8000`.
Geheimnisse und Daten bleiben unter `.local/` erhalten und sind von Git ausgeschlossen.
Zufällige Zugangsdaten stehen in `.local/access.txt`; Konten: `autor`, `pruefer`,
`freigabe`, `leser`. Vorhandene Passwörter werden beim Neustart nicht zurückgesetzt.
Die Webanwendung verwendet eine eingeschränkte Datenbankrolle.

Synthetische Dokumente sind ausdrücklich als Demonstration gekennzeichnet. Die
Normstammdaten der Demonstration benennen konkrete Ausgaben (9001:2015,
27001:2022, 50001:2018), keine automatische Aussage über die aktuellste oder im
Unternehmen verbindliche Ausgabe. Erläuterungen: [Normreferenzen](docs/standards.md).

`Strg+C` beendet den Webserver. Die separate PostgreSQL-Instanz bleibt verfügbar.
Zum Beenden mit den passenden PostgreSQL-Binaries:

```sh
pg_ctl -D .local/postgres -m fast stop
```

`DMS_PG_BIN` überschreibt das PostgreSQL-Binärverzeichnis, `DMS_DEV_PG_PORT`
den lokalen Datenbankport. Diese Entwicklungskonfiguration ersetzt den
HTTPS-Betrieb im LXC nicht.

## Lokaler Entwicklungsstart mit vorhandener Datenbank

Voraussetzungen: Python ab 3.12, PostgreSQL ab 16 und eine neue leere Datenbank.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DMS_SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export DMS_DEBUG=1
export PGDATABASE=ims_dms
export PGUSER=ims_dms_owner
export PGHOST=127.0.0.1
# PGPASSWORD sicher in der lokalen Umgebung oder über eine geschützte .pgpass setzen.
.venv/bin/python manage.py migrate
.venv/bin/python manage.py create_dms_user autor
.venv/bin/python manage.py provision_dms autor --role AUTHOR --department IT --department-name IT
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Für einen vollständigen Workflow einen weiteren Benutzer anlegen und in den IT-Einstellungen
als QMB oder QMB-Vertretung benennen. REVIEWER allein erlaubt keine QMB-Freigabe.
Regulär angelegte Konten erhalten READER als Grundrolle. `--department '*'` erlaubt
unternehmensweiten Zugriff. Auch ein Django-Superuser benötigt eine DMS-Zuordnung.
Ein DMS-Konto oder das zugehörige Django-Konto kann deaktiviert werden; beides
verhindert Dokumentzugriffe. Verwaltungsbefehle derzeit nur für Administratoren
mit lokalem Shell- und Datenbankzugriff.

**Migrationen:** Bei einer Neuinstallation ausschließlich `manage.py migrate`
verwenden, nicht zusätzlich die SQL-Dateien manuell ausführen. Die Migrationen
binden die Dateien unter `db/` ein, deshalb das gesamte Projekt ausliefern.
Falls `001_initial.sql` bereits manuell installiert wurde, muss zuerst der
Datenbankstand geprüft und die initiale DMS-Migration gezielt als angewendet
markiert werden. Kein pauschales `--fake` über alle Migrationen verwenden.

## Prüfungen

```sh
.venv/bin/python manage.py check
.venv/bin/python manage.py test dms
```

Die Tests benötigen einen PostgreSQL-Benutzer mit CREATEDB und prüfen echte
Datenbanktrigger, Rollenprüfungen, Selbstfreigabesperre, Prüfzyklen, CSRF,
Dateiintegrität, Revisionen und die Sichtbarkeit wirksamer Fassungen.
Testdatenbank und Dateispeicher sind von Produktivdaten zu trennen.

## LXC-Betrieb

Siehe [Betriebsanleitung](docs/operations.md) und Beispiele unter `deploy/`.
Die Tests wurden lokal gegen PostgreSQL 16 ausgeführt; es erfolgte noch keine
Installation auf deinem Proxmox-Host.

## Interner HTTP-Zugang (ausdrücklich gewählte Konfiguration)

```sh
.venv/bin/python scripts/serve_http_lan.py --address 192.168.1.191
```

Tablet-Adresse: `http://192.168.1.191:8000/`. Das Tablet muss im gleichen
LAN/WLAN sein. Anmeldung, CSRF-Prüfung und Berechtigungen bleiben aktiv,
Django-Debug ist aus. `DMS_INTERNAL_HTTP=1` erlaubt gezielt HTTP ohne HTTPS-Redirect
und ohne Secure-Cookie-Markierung. Passwörter und Dokumente werden dabei im
Netzwerk unverschlüsselt übertragen. Der Datenbankzugang bleibt auf Loopback.
Ohne diese explizite Einstellung bleiben HTTPS-Vorgaben im Nicht-Debug-Betrieb aktiv.

## Optionaler HTTPS-Zugang im lokalen Netzwerk

```sh
.venv/bin/python scripts/serve_lan.py --address 192.168.1.191
```

Die Adresse muss der privaten LAN-IP des Rechners entsprechen. Der zusätzliche
Zugang läuft ausschließlich per HTTPS auf dieser Adresse, standardmäßig Port 8443;
PostgreSQL und der lokale HTTP-Entwicklungsserver bleiben auf Loopback beschränkt.
Debug ist am LAN-Endpunkt deaktiviert; sichere Cookies und HTTPS-Weiterleitung
bleiben eingeschaltet. Die Zugänge nutzen denselben Dokumentenbestand.

Für die Testinstanz erzeugt das Skript eine private lokale CA mit einem
IP-gebundenen Serverzertifikat. Das öffentliche Zertifikat
`.local/tls/dms-local-ca.cer` muss auf dem Tablet manuell vertrauenswürdig
eingerichtet werden. Keine Zertifikatswarnung umgehen und keine privaten Schlüssel
weitergeben. Details: [Tablet-Zugang](docs/tablet-access.md).

## Versionshistorie

Verantwortliche und Prüfrollen erreichen die Versions- und Freigabehistorie über
die Detailseite. Sie enthält auch zurückgegebene Entscheidungen samt Prüfzyklus
und Inhaltsfingerabdruck. Leser erhalten weiterhin ausschließlich die wirksame
Fassung; die interne Historie bleibt für sie gesperrt.

Bei einer Überarbeitung wählen Autoren Minor (z. B. 1.0 → 1.1) oder Major
(z. B. 1.1 → 2.0) und begründen die Änderung. Beide Varianten durchlaufen den
vollständigen Prüf- und Freigabeprozess. Die inhaltliche Abgrenzung der Varianten
ist eine betriebliche Regel, keine automatische Bewertung durch das System.

## Normstammdaten und periodische Prüfung

Administratoren können geprüfte Normreferenzen mit der Eigentümerrolle ergänzen:

```sh
.venv/bin/python manage.py add_standard_reference "Betriebliche Norm" "Ausgabe" "Referenz" "Kurzbezeichnung"
```

Referenztexte werden nicht überschrieben. Autoren ordnen Referenzen und fachliche
Abteilungen im Entwurf zu; nach Einreichung sind diese Zuordnungen gesperrt.
Der fachliche Geltungsbereich vergibt keine zusätzlichen Leserechte.

Prüfer können die aktuell wirksame Fassung periodisch prüfen; der Ersteller darf
seine Fassung nicht selbst periodisch prüfen. Bei unverändertem Inhalt ist ein
zukünftiger Prüftermin erforderlich. Überarbeitung oder Rückzug bleiben im Filter
„Prüfungen fällig / Handlungsbedarf“ sichtbar und setzen eine Freigabe nicht
automatisch außer Kraft. Ein tatsächlicher Rückzug erfolgt durch die Freigaberolle über den getrennten,
begründeten und bestätigten Lebenszyklusvorgang auf der Detailseite.

## Volltextsuche und Hintergrundverarbeitung

Unterstützt werden UTF-8-TXT, textbasierte PDFs, DOCX, XLSX und ODT. Uploads werden
automatisch vorgemerkt; die neue Hintergrundverarbeitung läuft separat:

```sh
.venv/bin/python scripts/index_local.py
```

Der lokale Starter richtet eine eigene, eingeschränkte PostgreSQL-Workerrolle ein.
Mit `--once --limit 100` wird nur ein begrenzter Durchlauf ausgeführt. Die
Detailseite zeigt Verarbeitungsstatus und begrenzten Textumfang. Autoren können
fehlgeschlagene oder leere Verarbeitungen erneut anfordern.

Die Suche kombiniert Titel-/Nummernsuche mit deutschem PostgreSQL-Volltextindex.
Anführungszeichen suchen nach Wortfolgen. Textauszüge werden als Text escaped;
Suchtreffer und Auszüge unterliegen denselben Rollen-/Zugriffsregeln wie Downloads.
Dynamische Antworten sind nicht für Browser-/Proxy-Zwischenspeicherung freigegeben.

Bei Scans ohne Textebene meldet die Anwendung „Kein extrahierbarer Text“.
OCR ist noch nicht implementiert. Formeln, Makros und externe Office-Verknüpfungen
werden nicht ausgeführt. Details zu Ressourcenlimits und Sicherheitsgrenzen:
[Volltextbetrieb](docs/fulltext.md).

## Rückzug, Archivierung und Aufgaben

Die Freigaberolle kann auf der Detailseite einen dokumentweiten Rückzug oder
die Archivierung einer Fassung mit Begründung und ausdrücklicher Bestätigung
vornehmen. Ein Rückzug sperrt auch vorab genehmigte zukünftige Fassungen.
Erst eine nach dem Rückzug neu erteilte Freigabe kann wieder wirksam werden.

Archivierte Fassungen bleiben für berechtigte Verantwortliche nachvollziehbar.
Die Archivierung einer wirksamen Fassung aktiviert keinen Vorgänger. Eine
archivierte Ausgangsfassung kann als Quelle einer neuen Überarbeitung dienen;
auch diese benötigt den vollständigen Prüf- und Freigabeprozess.

Unter „Aufgaben“ erscheinen nur Entscheidungen, die der angemeldete Benutzer
aufgrund von Rolle, Zugriff und Funktionstrennung treffen darf. Zusätzlich gibt
es die Übersicht fälliger periodischer Prüfungen und offener Maßnahmen.
Die Übersicht versendet keine E-Mails oder externen Nachrichten.

## Sicherung und Wiederherstellung

```sh
.venv/bin/python scripts/manage_local.py backup_dms --destination .local/backups
.venv/bin/python scripts/manage_local.py backup_dms --verify /ABSOLUTER/PFAD/ZUR/SICHERUNG
.venv/bin/python scripts/manage_local.py check_restore /ABSOLUTER/PFAD/ZUR/SICHERUNG
```

Der Backup-Befehl nutzt einen gemeinsamen PostgreSQL-Snapshot für Dump und
Dateiverzeichnis. Jede kopierte Datei wird gegen die Datenbank-Prüfsumme geprüft.
Ein Manifest enthält Migrationen, Kontrollsummen und Datensatzanzahlen; der passende
Anwendungscode wird beigefügt. Geheimnisse und die rohe PostgreSQL-Datenablage
werden nicht mitkopiert. Unvollständige Pakete bleiben als `.partial` markiert.

`check_restore` benötigt CREATEDB: Der Befehl erzeugt eine neue zufällig benannte
Testdatenbank, restauriert dort den Dump, prüft Migrationen/Datensatzbestände und
Dateireferenzen und entfernt ausschließlich diese selbst erzeugte Datenbank.
Das ist ein technischer Restore-Test, keine vollständige betriebliche Abnahme.
Details und Grenzen: [Sicherungsbetrieb](docs/backup.md).

## Gruppen und vertrauliche Dokumente

Gruppen und Mitgliedschaften werden administrativ über den Eigentümerzugang
verwaltet; Beispiel für die lokale Entwicklungsdatenbank:

```sh
.venv/bin/python scripts/manage_local.py manage_group create IT-Leser --reason "Abteilungsgruppe einrichten"
.venv/bin/python scripts/manage_local.py manage_group add-member IT-Leser --user leser --reason "Leser zuordnen"
.venv/bin/python scripts/manage_local.py manage_group grant IT-Leser --role READER --department IT --reason "Abteilungszugriff"
.venv/bin/python scripts/manage_local.py manage_group remove-member IT-Leser --user leser --reason "Zuständigkeit beendet"
```

`enable`/`disable` aktiviert oder deaktiviert eine Gruppe; `grant`/`revoke`
vergibt oder entzieht Rollen. Statt `--department IT` kann `--document DEMO-001`
für eine Dokumentrolle verwendet werden. Auch `provision_dms` unterstützt
`--document` für direkte Benutzerrollen. `manage_group list` zeigt Gruppen an.
Alle Änderungen verlangen eine Begründung und erzeugen einen Audit-Eintrag.
Die Laufzeit-Datenbankrolle besitzt keine Verwaltungsrechte für Gruppen,
Mitgliedschaften oder Rollenzuordnungen.

Auf der Detailseite können Autoren über „Dokumentzugriff verwalten“ zusätzliche
Personen-/Gruppenfreigaben setzen. Diese Freigaben ergänzen die Rollenprüfung;
sie gewähren allein weder Lesen noch Bearbeiten. Der Modus EXPLICIT beschränkt
alle Fassungen eines Dokuments. Die Klassifizierungen CONFIDENTIAL und RESTRICTED
verlangen immer eine ausdrückliche Freigabe, unabhängig vom Modus.

Zugriffslisten sind operative Berechtigungen und gelten sofort für alle Versionen.
Sie werden getrennt von freigegebenen Inhalten geändert und mit Vorher-/Nachherstand
auditiert. Sie sind bewusst kein Bestandteil des eingefrorenen Inhaltsfingerabdrucks.
Gruppen-/Rollenentzug und Kontodeaktivierung wirken bei jedem weiteren Zugriff,
auch bei bereits angemeldeten Benutzern. Bereits heruntergeladene Dateien kann
das DMS nicht zurückrufen.

## Noch offen

- AD/SSO und Gruppensynchronisation; `external_identities` ist dafür vorbereitet.
- Grafische Gruppen-/Mitgliederverwaltung; administrative Verwaltung ist per CLI vorhanden.
- Vollständiges betriebliches Norm-Mapping und Pflegeoberfläche für Normstammdaten;
  Versionen können vorhandenen Referenzen und mehreren Abteilungen zugeordnet werden.
- OCR für bildbasierte Scans und Malwareprüfung; lokale Volltextverarbeitung ist vorhanden.
- Zusätzliche OS-Sandbox für Parser im produktiven LXC-Betrieb.
- Automatische Auswertung von Zustellbestätigungen/Bounces; SMTP-Erinnerungen und Versandprotokoll sind vorhanden.
- Aufbewahrungsfristen, Löschsperren und kontrollierte Aussonderung.
- Manipulationsschutz und Sicherungsziel außerhalb des Containers sowie betriebliche Restore-Abnahme;
  konsistenter Backup-Befehl, lokaler Restore-Test und Timer-Vorlagen sind vorhanden.
- Last- und Parallelitätstests mit realistischem Nutzungsprofil.

Dateien sind maximal 25 MiB groß. Uploads werden nicht gerendert oder ausgeführt;
Downloads erfolgen als Anhang. Die Dateiendung ist keine Malwareprüfung.
Nicht mehr referenzierte Dateiobjekte werden bis zu einer kontrollierten
Aufbewahrungs-/Bereinigungsfunktion aufbewahrt. Ein Prozessabbruch kann ebenfalls
unreferenzierte Dateien hinterlassen; sie dürfen nicht ungeprüft gelöscht werden.

Die Laufzeitrolle ist ein vertrauenswürdiger Anwendungsdienst mit Zugriff auf die
Datenbank, keine separate Datenbankidentität pro Endbenutzer. Berechtigungsprüfung
und Berechnung des Freigabefingerabdrucks finden in der Anwendung statt. Der
Datenbanktrigger verlangt passende unabhängige Entscheidungen, ersetzt aber
keine vertrauenswürdige Anwendung. Datenbank- und Hostadministratoren benötigen
zusätzliche organisatorische und externe technische Kontrollen.

Für administrative Befehle gegen die vom Sofortstart erzeugte Datenbank:

```sh
.venv/bin/python scripts/manage_local.py check
.venv/bin/python scripts/manage_local.py test dms
```

Der Wrapper nutzt nur die private Entwicklungsdatenbank mit ihrem lokalen
Eigentümerzugang; er ist kein Werkzeug für Produktionsdatenbanken.

## Kategorie-Gültigkeit und letztes Review

In der Übersicht stehen Kategorie, letztes abgeschlossenes Review und
„Gültig bis / Review fällig“. Für die Gültigkeit gilt standardmäßig **24 Monate
(zwei Kalenderjahre)**, mit korrekter Behandlung von Monatsenden und Schaltjahren.
Die bisherigen Dokumenttypen bilden die Kategorien.

Der QMB und seine Vertretung können unter `/management/` die Gültigkeit je Kategorie in
Monaten festlegen. Änderungen benötigen eine Begründung und werden mit
Vorher-/Nachherwert protokolliert. Bereits freigegebene Prüftermine werden nicht
rückwirkend verändert. Neue/bearbeitete Entwürfe erhalten ihre Frist ab
Wirksamkeitsdatum; ein erfolgreiches periodisches Review erhält die aktuelle
Kategoriefrist ab dem Prüftag. Bei erforderlicher Überarbeitung oder Rückzug
bleibt die bisherige Gültigkeit erhalten und der Handlungsbedarf sichtbar.

Eine überschrittene Prüffrist wird als „Review überfällig“ angezeigt. Sie bewirkt
keinen automatischen Dokumentrückzug. Ein separates explizites `valid_until` für
zwingende Ablaufgrenzen bleibt davon unabhängig. Bestehende kürzere Prüftermine
werden übernommen. Die Weboberfläche berechnet neue Fristen automatisch.

Lokal sind `pruefer` (QMB) und `qmb_vertretung` für die fachliche Verwaltung zuständig.
`admin` verwaltet unter `/settings/` die IT-Einstellungen und die QMB-Zuordnung.
Das IT-Administrationsrecht allein erteilt keine fachlichen Prüf- oder Freigaberechte.
Für andere beziehungsweise produktive Konten kann ein Administrator das Recht
über den Eigentümerzugang explizit vergeben oder entziehen:

```sh
.venv/bin/python manage.py settings_admin BENUTZERNAME --reason "IMS-Administration zuweisen"
.venv/bin/python manage.py settings_admin BENUTZERNAME --revoke --reason "Zuständigkeit beendet"
```

## E-Mail-Erinnerungen und SMTP

Unter **Verwaltung → Erinnerungen** konfiguriert der QMB Aktivierung und Vorlauf
(Standard 30 Tage). Unter **Admin-Einstellungen → E-Mail-Erinnerungen & SMTP** verwaltet die IT
SMTP-Server, Port, Verschlüsselung, Benutzername/Passwort,
Absender und DMS-Linkadresse konfigurieren. Eine separate Test-E-Mail kann an
eine ausdrücklich angegebene Adresse gesendet werden. Anfangs bleibt die
Automatik ausgeschaltet; echte SMTP-Daten und Empfängeradressen sind noch einzutragen.

Erinnerungen gehen an den verantwortlichen Autor und beide aktiven benannten QMBs jeweils einmal
im Vorlauffenster und einmal bei Fälligkeit/Überfälligkeit. Vor jedem Versand
werden aktueller Prüftermin, Verantwortung, Kontostatus und Zugriff geprüft.
Adressen pflegt die Administration im verlinkten Bereich „E-Mail-Adressen der Autoren“.
Das Versandprotokoll zeigt Fehler und erfolgreiche SMTP-Annahmen.

Der lokale Hintergrunddienst wird mit
`.venv/bin/python scripts/notifications_local.py` gestartet. Details einschließlich
Passwortverschlüsselung, Wiederholungsregeln und LXC-Servicevorlage:
[E-Mail-Betrieb](docs/email-reminders.md).

## QMB-Verwaltung und Vertretung

Die fachliche Verwaltung unter `/management/` umfasst Gültigkeitsdauer, optionale
Aufbewahrungsfrist und logischen Aufbewahrungsort je Kategorie. Aufbewahrungsfristen
sind Metadaten; automatische Löschung und physisches Verschieben sind nicht implementiert.
Die IT betreibt Dateispeicher, SMTP und Benutzerkontakte. Änderungen werden protokolliert.

Abteilungsleiter mit REVIEWER erhalten keine zentrale Einsicht in vertrauliche Dokumente.
Benannte QMBs und ihre Vertretung erhalten diese ausdrücklich autorisierte Einsicht.
Eigene Dokumente darf ein QMB weder prüfen noch freigeben. Muss der andere QMB nach
abgeschlossener Prüfung übernehmen, startet er einen neuen Prüfzyklus und prüft selbst
erneut vor seiner Freigabe. Historische Entscheidungen bleiben unverändert erhalten.
Offene Altzyklen ohne QMB-Qualifikationsnachweis müssen ebenfalls neu übernommen werden.

## Abteilungsleiter und QMB-Abteilungsleitung

Abteilungsleiter arbeiten regulär mit AUTHOR in ihrem Zuständigkeitsbereich.
Das lokale historische Konto `freigabe` ist deshalb als Autor eingerichtet.
Andere vorhandene Benutzer werden nicht pauschal anhand ihrer Rolle umklassifiziert.
Die IT kann unter `/settings/` zusätzlich die Leitung der QMB-Abteilung benennen.
Diese darf nach erfolgreicher unabhängiger QMB-Prüfung direkt freigeben oder zurückgeben.
Sie darf weder die verpflichtende QMB-Prüfung ersetzen noch eigene/eingereichte Dokumente
freigeben. Ohne weitere Dokumentrechte ist ihr besonderer Zugriff auf fremde Fassungen
im Status „Freigabe ausstehend“ mit nachgewiesener QMB-Prüfung begrenzt, einschließlich
vertraulicher Inhalte. Daraus entstehen keine QMB-Verwaltungsrechte und keine zusätzlichen
QMB-Erinnerungen. Die Freigabeentscheidung protokolliert die Berechtigung zum Entscheidungszeitpunkt.

| Zuständigkeit | Entwurf / Überarbeitung | Pflichtprüfung | Verbindliche Freigabe | Verwaltung |
|---|---|---|---|---|
| Leser | – | – | – | – |
| Autor, regulär Abteilungsleiter | Im zugewiesenen Bereich | – | – | – |
| Benannter QMB / Vertretung | Mit zusätzlicher Autorenrolle | Fremde Dokumente | Nach eigener Prüfung | Fachliche Vorgaben |
| Benannte QMB-Abteilungsleitung | Mit Autorenrolle | Nur mit separater QMB-Benennung | Nach unabhängiger QMB-Prüfung | Nur mit separater QMB-Benennung |
| IT-Admin | Mit separater Autorenrolle | Nur mit separater QMB-Benennung | Nur mit separater fachlicher Berechtigung | IT / SMTP / Zuordnungen |

## Mitarbeiterportal, Kenntnisnahmen und Nachweisregister

Die Startseite zeigt aktuelle freigegebene Lesefassungen mit persönlicher Auswahl,
Favoriten und zuletzt verwendeten Dokumenten. Dauerhafte Links/QR-Codes führen auf
die jeweils aktuelle Fassung. PDF-/TXT-Vorschau und zusätzliche PDF-Lesefassungen
für Office-Quellen, versionsbezogene Kenntnisnahmen, Zielgruppen, unveränderliche
Nachweise sowie QMB-Auditberichte sind implementiert.

Details, konkrete Grenzen und lokale Testkonten: [Mitarbeiterportal](docs/employee-portal.md).
AD und Ziel-LXC bleiben während der Entwicklung inaktiv; interne HTTP-Vorlagen
sowie der zusätzliche Zuordnungsdienst liegen in `deploy/`.

## Anwendungslogo und Softwareversion

Das bereitgestellte Logo liegt unverändert in `dms/static/branding/logo.png`.
Kopfzeile, Anmeldung, PDF-Viewer und Fehlerseiten verwenden diese gemeinsame Marke;
Favicons und Touch-Icons sind daraus abgeleitet. Der gemeinsame Footer zeigt die
Softwareversion aus `dms/version.py` (aktuell `0.2.0-dev`). Diese Versionsnummer ist
unabhängig von den fachlichen Dokumentversionen. Logo und Icons werden lokal über
explizit erlaubte Asset-Namen ausgeliefert und sind im Quellcodebackup enthalten.

## Hauptlogo im IT-Adminpanel ersetzen

Unter Admin-Einstellungen → Hauptlogo kann ein IT-Admin PNG, JPEG oder WebP
hochladen (maximal 5 MiB, nicht animiert, 64–4096 Pixel je Seite). Das Bild wird
validiert, auf maximal 2048 Pixel begrenzt, von Metadaten bereinigt und als PNG
normalisiert. Favicons und Touch-Icons entstehen automatisch ohne Zuschnitt des
Logoinhalts. Jede Änderung benötigt eine Begründung und wird protokolliert.
Vorherige Logos und das mitgelieferte Standardlogo können wiederhergestellt werden.

Eigene Logos liegen mit ihren Icons in unveränderlichen Datenbankrevisionen; eine
atomare Auswahl aktiviert jeweils eine Revision. Versionsgebundene Asset-URLs
verhindern, dass alte Browser-Caches den Logowechsel verdecken. Der unversionierte
Favicon-Endpunkt validiert per ETag neu. Neue Tabellen sind in Sicherung und
Wiederherstellungsprüfung enthalten. Web-Laufzeitrechte nach Migration 0012 erneut
anwenden. Die bisherigen statischen Dateien bleiben das mitgelieferte Standardlogo.

## Fehlerprotokoll, Systeminformationen und AD-/LDAP-Felder

Admin-Einstellungen zeigt die letzten technischen Fehler sowie Python-, Django-,
PostgreSQL-Version und freien Dateispeicher. `/settings/system/` bietet weitere
Laufzeit-/Datenbankinformationen, Warteschlangenstände und bis zu 200 Logeinträge
mit Schweregradfilter. Ein ausdrücklich markierter Protokolltest ist per POST möglich.
Diese Seiten sind ausschließlich für IT-Admins zugänglich.

Unbehandelte Webfehler und Sicherheitsablehnungen werden in privaten JSONL-Dateien
unter `DMS_ERROR_LOG_DIR` gespeichert (lokal `.local/logs`). Prozessübergreifende
Dateisperren schützen Schreibzugriffe und Rotation, maximal vier Dateien zu jeweils
etwa 1 MiB. Gespeichert werden Fehlerklasse, Codestelle ohne absolute Pfade,
Routenmuster ohne URL-Parameter, Anfrage-ID und optional die technische Benutzer-ID.
Rohe Logmeldungen, Exception-Texte, Formularwerte, Cookies, Header und Variableninhalte
werden bewusst nicht übernommen. Das technische Rotationslog ersetzt nicht den
fachlichen Audit-Trail und enthält keine vollständige Prozessüberwachung.
Bekannte Volltext-/Mailfehler erscheinen zusätzlich als Warteschlangenstände.

Unter `/settings/directory/` können AD-/LDAP-Anschlussparameter vorbereitet werden:
Verzeichnistyp, Server/Port, LDAPS/StartTLS, Domäne, Suchbasen, Bind-Konto, Benutzer-
und Gruppenfilter, Attribute und Zeitlimit. Bind-Kennwörter werden mit Fernet in
der Datenbank verschlüsselt und nicht erneut im Formular oder Audit ausgegeben.
Leer lassen behält den Wert; Entfernen erfordert eine eigene Checkbox.
Optional `DMS_LDAP_ENCRYPTION_KEY` als separaten stabilen Schlüssel setzen; sonst
wird ein eigener LDAP-Schlüssel aus DMS_SECRET_KEY abgeleitet. Schlüssel außerhalb
der Datenbanksicherung schützen und bei Wiederherstellung identisch bereitstellen.

Die Felder aktivieren keine Anmeldung, Synchronisation oder Netzwerkverbindung.
Auf ausdrücklichen Wunsch bleibt die Entwicklung bei lokalen Benutzern. LDAP-Bind,
Suchfilter-Syntax am echten Verzeichnis, Zertifikatskette und Gruppen-/Rollenmapping
müssen vor der späteren Integration gesondert geprüft und implementiert werden.
Konfigurationsdaten sind seit Migration 0013 Teil von Datenbankbackup und Restore-Prüfung.

## Vereinfachte Oberfläche und Freigabe ab 0.2.0-dev

Die Startseite ist jetzt die Dokumentenübersicht. Leser erhalten ausschließlich
Tabelle, direkte Ansicht und Download freigegebener Dokumente; abgelaufene
Reviewfristen blenden diese nicht aus. Autoren laden Metadaten und Datei in einem
Schritt hoch und wählen Entwurf oder Freigabeanfrage. QMB entscheidet mit einer
Aktion über Freigabe oder Ablehnung mit Bemerkung. Rückgaben erscheinen als
Autorenaufgabe, offene Prüfungen in der Glocke neben dem Profil. Erstupload und
Freigabedatum werden getrennt geführt; neue Fristen beginnen mit der Freigabe.
Unter Admin-Einstellungen → Benutzer und Rechte sind Autor, QMB und Admin
zuordenbar; mehrere QMBs sind möglich, alle anderen regulären Konten sind Leser.
Details und Umgang mit historischen Versionsdaten: [Ablaufbeschreibung](docs/employee-portal.md).
Anonymer Zugriff bleibt bis zur ausdrücklichen Entscheidung deaktiviert.

## Online-Installation auf Linux / Proxmox LXC

Der GitHub-Installer liegt unter `scripts/install_linux.py`. Er unterstützt Ubuntu 24.04 LTS und Debian 13, internen HTTP-Betrieb, getrennte PostgreSQL-Rollen, systemd-Worker und tägliche Sicherungen.

[Installation, Updates und erste Anmeldung](docs/github-installation.md).
