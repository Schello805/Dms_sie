# Stammdatenverwaltung ab 0.4.0-dev

| Bereich | Zuständig | Funktionen |
| --- | --- | --- |
| Kategorien | QMB | Bezeichnung, Gültigkeitsmonate, Aufbewahrung, Aufbewahrungsort, Aktivstatus |
| Abteilungen | QMB | Name, Kürzel, übergeordnete Abteilung, Aktivstatus |
| Aufbewahrungsorte | QMB | Name, Beschreibung, Aktivstatus |
| Normausgaben und Kapitel | QMB | Anlegen, unbenutzte Definitionen bearbeiten, deaktivieren, reaktivieren |
| Gruppen | IT-Admin | Name, Mitglieder, Leser-/Autorenrechte mit Geltungsbereich, Aktivstatus |
| Benutzerprofile | IT-Admin | Anzeigename und E-Mail; Kontenstatus, Passwort und Rollen über bestehende Aktionen |

Listen bieten Suche, Statusfilter und Seitennavigation. Deaktivierung und Reaktivierung erfordern
Speichern; die Begründung ist optional. Ein GET-Link verändert keine Daten. Inaktive Einträge werden bei neuen
Zuordnungen ausgeblendet. Bestehende Zuordnungen und freigegebene Dokumente bleiben erhalten.
Ein Aufbewahrungsort kann nicht deaktiviert werden, solange aktive Kategorien darauf verweisen.
Abteilungshierarchien dürfen keine Zyklen enthalten.

Kategorien behalten einen unveränderlichen technischen Schlüssel; Umbenennen verändert die
Dokumentenreferenzen nicht. Bereits in einem Freigabeverfahren verwendete Normdefinitionen
werden datenbankseitig gesperrt, auch nach Ablehnung und Entfernung der Zuordnung. Neue Ausgaben
benötigen neue Einträge. Bei der Migration werden bestehende Normreferenzen vorsorglich geschützt,
sofern historische Freigabeverfahren existieren: alte Fingerprints erlauben keine vollständige
Rekonstruktion früher entfernter Referenzen. Dabei wird kein historisches Nutzungsdatum erfunden.

Gruppen können ausschließlich Leser-/Autorenrechte vergeben. Direkte Benutzerrechte bleiben beim
Deaktivieren einer Gruppe erhalten. Altgruppen mit erweiterten Rollen lassen sich nicht über die
Weboberfläche neu besetzen oder umschalten; dafür bleibt die administrative CLI erforderlich.
Benutzernamen und technische Authentifizierungsmerkmale werden nicht im Profilformular verändert.

Datenbankfunktionen prüfen Rollen, Eingabefelder, Referenzen und Begründung; der Webdienst erhält
keine allgemeinen Schreibrechte auf Gruppen-, Norm- oder Abteilungstabellen. Änderungen erzeugen
Audit-Einträge. Freigabeentscheidungen und historische Dokumentversionen haben keine Löschfunktion.

## Prüfstand

182 PostgreSQL-Tests bestanden, einschließlich elf gezielter Stammdatenfälle: Rollenabgrenzung,
Bearbeitung, Deaktivierung/Reaktivierung, Hierarchiezyklen, Gruppenrechte, Profiländerungen,
Normsperren und unveränderte freigegebene Versionsfingerprints. Lokale Bestandsversionen wurden
nach Migration zusätzlich direkt mit der vorherigen Datenbanksicherung verglichen.
Eine visuelle Browserabnahme steht aus, da lokale Browsernutzung in den Work-Einstellungen deaktiviert ist.

## Aktualisieren

Als root das aktuelle Installationsskript herunterladen und ausführen:

```bash
curl -fsSL https://raw.githubusercontent.com/Schello805/Dms_sie/main/scripts/install_linux.py -o /tmp/install-ims-dms.py
python3 /tmp/install-ims-dms.py --update
```

Eine feste IP-Adresse wird weder benötigt noch vergeben. Bestehende Netzwerkeinstellungen bleiben erhalten.
