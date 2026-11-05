# Mitarbeiterportal und lokale Entwicklungsabnahme

## Einstieg und Zuständigkeiten

`/` ist das Mitarbeiterportal mit aktuell wirksamen freigegebenen Fassungen.
`/documents/` zeigt die aktuell wirksame freigegebene Fassung und eigene, noch
nicht freigegebene Arbeitsstände des jeweiligen Versionserstellers mit Autorenrolle.
Die Spalte und der Filter „Status“ verwenden ausschließlich „Freigegeben“ und „Entwurf“.
Arbeitsstände in Prüfung bzw. vor Freigabe zählen in dieser Tabelle als „Entwurf“.
Fremde Arbeitsstände erscheinen auch für QMBs nicht in der allgemeinen Tabelle;
QMB-Prüfung und Freigabe erfolgen weiterhin über Aufgaben und Detailansicht.
Archivierte, abgelöste, zurückgezogene und noch nicht wirksame Freigaben werden
hier nicht als aktuelle Freigabe gelistet. Ihre berechtigte Historie bleibt erhalten.
Der Filter „Für meinen Arbeitsplatz“ verwendet Arbeitsplatz-Abteilung und explizite
Zielgruppen; „Alle zugänglichen Lesefassungen“ zeigt den berechtigten Gesamtkatalog.
Zielgruppen ergänzen die Auswahl und Kenntnisnahmepflicht. Sie sind keine Dokument-ACL.
Die gemeinsame `can_read_version()`-Prüfung gilt weiter für Inhalt, Suche, QR und PDF.

Die fachliche Verantwortung einer Abteilung ist von den betroffenen Abteilungen
(`version_departments`) und Zielgruppen (`version_audiences`) getrennt.
QMBs legen unter Verwaltung Zielgruppen an. IT ordnet lokale Mitarbeiter unter
Admin-Einstellungen → Arbeitsplätze und Zielgruppen zu. Standort und Tätigkeit
beschreiben den Arbeitsplatz; für entsprechende Filterung eine Zielgruppe anlegen
und explizit zuordnen, etwa „Maschinenführer Halle 1“.

„Verwaltung“ ist für QMBs und IT auffindbar. Bei QMBs führt der Menüpunkt zu den
Kategoriefristen. IT erhält eine Zuständigkeitsseite mit QMB-Zuordnung und einer
Erklärung der getrennten Rechte. IT kann weiterhin keine fachlichen Fristen ändern.
Lokale Entwicklung: `pruefer` und `qmb_vertretung` sind QMBs, `admin` ist IT.

## Dauerhafte Links, QR und Lesefassungen

`/documents/<document_id>/current/` bleibt bei Revisionen stabil und löst erst beim
Aufruf die aktuell wirksame Fassung auf. Fehlende Rechte, Rückzug oder ein expliziter
Ablauf verhindern den Zugriff; es gibt keinen Rückfall auf eine ältere Fassung.
QR-Codes enthalten diesen Link, keine Inhalte oder Anmeldedaten. Anmeldung bleibt nötig.
Die beim Erzeugen verwendete Adresse muss auf dem Tablet erreichbar sein; QR-Codes
für den Betrieb über den vorgesehenen Hostnamen statt localhost erzeugen.

PDF und TXT können im Browser als abgeleitete PDF-Lesefassung angezeigt werden.
Der lokale Viewer verwendet Mozilla PDF.js 6.5.438 (Legacy-Build, Apache-2.0) mit
Seitenwechsel, Zoom und optionaler Textansicht. Bibliothek, Worker und Ressourcen
liegen lokal im Projekt; keine CDN-Abhängigkeit und kein Browser-Plugin erforderlich.
Paketintegrität und Herkunft stehen in `dms/static/vendor/pdfjs/NOTICE-DMS.txt`.
Nur diese öffentlichen Bibliotheksdateien werden zwischengespeichert; Dokumente
und personenbezogene Seiten bleiben privat und ohne wiederverwendbaren Cache.
Die PDF enthält auf jeder Seite Nummer, Version, Freigabedatum, Seitenzahl und
Rückverweis/QR. Zusätzliche Ränder verhindern, dass der Hinweis Originalinhalt überdeckt.
Vorschauen erzeugt ein separater Prozess mit Zeit-/Dateigrößenlimits, unter Linux
zusätzlich Adressraumlimit. Bis zu 300 PDF-Seiten oder 1 MiB Text pro Vorschau.
PDF-Anmerkungen und zusätzliche Seitenaktionen werden nicht übernommen.
Diese Vorschau ist kein vollständiger Malware-Scanner.

Office-Dateien werden nicht layoutgetreu konvertiert. Autoren können im Entwurf
zusätzlich ein PDF mit Dateiverwendung „PDF-Lesefassung“ hochladen; es durchläuft
mit dem Original die Prüfung und Freigabe. Quelldateien bleiben bytegleich und
können für Vorlagen heruntergeladen werden. Eine neue Lesefassung nach Freigabe
benötigt eine Revision. Derivative Vorschauen ersetzen nicht die freigegebene Quelldatei.

## Änderungen und Kenntnisnahmen

Autoren pflegen im Entwurf Art der Änderung, Schlagwörter, Zielgruppen und eine
optionale Kenntnisnahmefrist (Standard 30 Tage). Diese Werte werden mit freigegeben,
sind im Inhaltsfingerabdruck enthalten und ab Einreichung unveränderlich.
Bestehende Versionen ohne Verteilungsdaten behalten ihren bisherigen Fingerabdruck.

Bei aktueller Freigabe werden Aufgaben für alle berechtigten aktiven Mitarbeiter
der Zielgruppen erzeugt, unabhängig davon, ob sie bereits angemeldet waren.
Der zusätzliche Dienst `process_portal` synchronisiert minütlich zukünftige Freigaben,
neue Mitarbeiter und Zuordnungen. Aufgaben werden je Version und Mitarbeiter nur
einmal erzeugt; Frist ab Erstzuordnung. Eine vorherige Bestätigung deckt eine neue
Version nicht ab. Bei Nachfolger, Rückzug, Ablauf oder Rechteentzug wird eine alte
Aufgabe nicht mehr zur Bestätigung angeboten. Der Nachweis bleibt erhalten.

Die persönliche Aufgabe und Änderungszusammenfassung erscheinen im Portal und auf
der Leseseite. Bestätigt wird „gelesen und zur Kenntnis genommen“, kein automatischer
Kompetenznachweis. Ein Download oder bloßer Seitenaufruf löst keine Bestätigung aus.
Benachrichtigungen hierzu erfolgen im Portal; zusätzliche Kenntnisnahme-E-Mails
sind nicht implementiert. Die bisherigen Review-Erinnerungs-E-Mails bleiben separat.

Lokal: `.venv/bin/python scripts/portal_local.py`, einmalig mit `--once`.
LXC-Vorlage: `deploy/ims-dms-portal.service`, dieselbe Anwendungsumgebung wie Web.

## Nachweise und Aufbewahrung

`/records/` verwaltet abgeschlossene, unveränderliche Nachweise separat von Anweisungen
und Vorlagen. Autoren erfassen Datei, Nummer, Kategorie, Datum, Verantwortungsbereich
und optional die zugehörige Dokumentfassung. Interne Nachweise folgen den berechtigten
Leserrollen; vertrauliche Nachweise sind auf Ersteller und QMB begrenzt.
Eine Kategoriefrist wird ab Nachweisdatum berechnet und bei Erfassung festgehalten.
Ohne Kategoriefrist muss ein konkretes Datum angegeben werden; es gibt keine erfundene
pauschale gesetzliche Aufbewahrungsfrist. Datumsangaben gelten einschließlich.

QMB kann Aufbewahrung verlängern und eine Aussonderungssperre setzen oder begründet
aufheben. Entscheidungen werden angehängt; Inhalt und Ursprungseintrag bleiben
unveränderlich. Nach Fristablauf ohne Sperre kann eine Aussonderung zur Prüfung
vorgemerkt werden. Es gibt keine automatische physische Löschung. Das organisations-
und datenträgerspezifische Löschverfahren einschließlich Backups ist vor Produktivbetrieb
noch festzulegen und technisch umzusetzen.

## Audit und Grenzen des Entwicklungsstands

QMB erreicht unter Verwaltung → Audit die versionsbezogenen Kenntnisnahmen,
Aufbewahrungsdaten und bis zu 5.000 gefilterte Audit-Ereignisse als CSV.
Die Tabelle zeigt 500 Ereignisse, Kenntnisnahmen bis zu 2.000, Nachweise bis zu 1.000.
CSV-Formelinjektion wird bei Freitext verhindert. Export enthält keine SMTP-Geheimnisse
oder ungefilterten JSON-Konfigurationsdetails. Exporte geschützt aufbewahren.
Das ist kein automatischer, extern versiegelter Audit-Trail.

AD und Installation im Ziel-LXC bleiben auf ausdrücklichen Wunsch während der
Entwicklung inaktiv. Lokale Konten und Rollen dienen der Abnahme. Für den späteren
gewünschten HTTP-Betrieb liegen `deploy/http.env.example` und `deploy/nginx-http.conf`
vor. PDF-Schrift unter Debian/Ubuntu: Paket `fonts-dejavu-core`. Python-Abhängigkeiten
in `requirements.lock.txt`, PostgreSQL-Migration 0011 und anschließende Runtime-Grants
anwenden. Kein Entwicklungs-Seed in Produktivsystemen ausführen.

Grundlage der Viewer-Integration: [Mozilla PDF.js Beispiele](https://mozilla.github.io/pdf.js/examples/).

## Vereinfachter IMS-Ablauf ab 0.2.0-dev

Der normale Einstieg ist ausschließlich die Dokumentenübersicht. Leser sehen nur
aktuell freigegebene Dokumente mit direkter Ansicht und Download. Überfällige
Gültigkeit/Reviews blenden ein Dokument nicht aus; ein ausdrücklicher Rückzug oder
Archivierung weiterhin schon. Die Entscheidung über anonymes Lesen ist offen;
bis dahin bleibt die Anmeldung erforderlich. Das bisherige Portal-Dashboard und
zusätzliche Leserfunktionen werden im normalen Einstieg nicht mehr angeboten.

Autoren laden Metadaten und Datei in einem Schritt hoch und wählen „Entwurf“ oder
„QMB-Freigabe anfordern“. Tatsächlicher Erstupload wird unveränderlich separat
gehalten. „Erstmalig gültig ab“ übernimmt standardmäßig den Uploadzeitpunkt und
ist im Entwurf änderbar. Autorentwürfe bleiben nur im eigenen Katalog sichtbar.

Eine QMB-Entscheidung besteht in der Oberfläche aus Freigeben oder Ablehnen.
Ablehnung erfordert eine Bemerkung und erzeugt die Autoren-Aufgabe mit dieser Notiz.
Bei Freigabe entstehen die revisionsfesten Prüf-/Freigabeentscheidungen gemeinsam
in einer Transaktion. Das Freigabedatum wird separat ergänzt; die Kategoriefrist
(Standard 24 Monate, einschließlich SOP/Vorlage) beginnt an diesem Tag. Ein
unveränderliches `release_validity`-Protokoll hält die angewandte Frist fest. Alte
freigegebene Versionen werden nicht rückwirkend umdatiert. Historische Import- und
Testabläufe können ihre vorhandene Terminberechnung beibehalten; alle Uploads der
neuen Oberfläche verwenden die Freigabedatumsregel. Erneute Richtigkeitsprüfungen
können die nächste Frist wie bisher ab dem Reviewdatum erneuern.

QMBs und Autoren sehen neben dem Profil eine Glocke mit offenen Aufgaben. Mehrere
QMB-Konten sind möglich; eigene Dokumente können nicht selbst freigegeben werden.
Unter Admin-Einstellungen → Benutzer und Rechte werden ausschließlich Autor, QMB
und Admin vergeben. Alle regulär angelegten bzw. importierten Konten erhalten
Leser als Grundrecht. Altdaten können intern historische Rollenmarker behalten;
diese sind keine zusätzlichen auswählbaren Rollen der neuen Oberfläche. Ein alter
QMB-Abteilungsleitungsmarker wird nicht mehr als eigene Freigabeberechtigung genutzt.
Der IT-Admin erhält durch die Systemrolle keine Autoren- oder QMB-Berechtigung.
Die Web-Datenbankrolle erhält keinen direkten Schreibzugriff auf Rollentabellen;
der ausdrücklich begrenzte Rollenwechsel erfolgt über eine geprüfte Datenbankfunktion
und wird auditiert. LDAP-Anmeldung und anonymer Zugriff bleiben weiterhin inaktiv.
