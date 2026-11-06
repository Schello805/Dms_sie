# Erneute Fehlerprüfung: 0.4.2-dev

## Gefunden und korrigiert

| Fehler | Korrektur und Nachweis |
| --- | --- |
| Letzter QMB konnte über Rollenverwaltung entfernt werden | Prüfung unter gemeinsamer Rollensperre in Anwendung und Datenbankfunktion; Tests verhindern Entzug und erlauben geregelte Übergabe an einen weiteren aktiven QMB. |
| Dokumentbezogene Autoren hatten keine Glocke und unsichtbare Rückgaben | Autorenstatus und Recht zum Anlegen neuer Dokumente sind getrennt. Test prüft Glocke, Rückgabe, Rollenanzeige und weiterhin verweigertes Uploadrecht. |
| Profiländerung behob fehlgeschlagene Mails nicht | Migration 0017 ergänzt das begrenzte Profil-Update um Wiederfreigabe ausschließlich bei FAILED/MISSING_EMAIL. SMTP-Test prüft tatsächlichen Versand und keine Wiederholung bei SENT oder UNCERTAIN. |
| Nginx entfernte den Port aus dem Host-Header | Host inklusive Port wird durchgereicht. Installer-Test und Login-Smoke-Test über echten nginx prüfen den Fall, zusätzlich zum HTTPS-Origin-Test. |

Migration 0017 ersetzt ausschließlich zwei begrenzte Datenbankfunktionen. Dokumentinhalte,
Freigabeentscheidungen und historische Versionen werden nicht umgeschrieben. Bestehende
Funktionsrechte bleiben bei CREATE OR REPLACE erhalten.

## Prüfverfahren

Ergebnisse der abschließenden Prüfung:

- Gesamte Anwendungssuite: **190 Tests erfolgreich** (120 Sekunden).
- Zuvor 35 gezielte PostgreSQL-/SMTP-/Proxy-Tests und 14 Installer-Tests erfolgreich.
- 136 lokale HTTP-Aufrufe über Leser-, Autor-, QMB- und Admin-Konten ohne Serverfehler. Fachliche Berechtigungen zusätzlich durch die Testsuite geprüft.
- [Linux-Installation, Update und echte nginx-Login-Tests](https://github.com/Schello805/Dms_sie/actions/runs/42169108617) erfolgreich; HTTPS-Origin und Host mit zusätzlichem Port jeweils vor und nach Update geprüft.
- Sicherung in einer getrennten temporären Datenbank wiederhergestellt; Migrationen und acht Dateireferenzen stimmen überein.
- Alle acht lokalen Dokumentversionen sind nach Migration mit der vorherigen Sicherung identisch.
- Python-Dateien sowie die drei UI-JavaScript-Dateien auf Syntaxfehler geprüft.

Eine visuelle Browserabnahme ist weiterhin offen, weil lokale Browsernutzung in den
Work-Einstellungen deaktiviert ist. Die Tests hier ersetzen außerdem keine Lastprüfung mit
800 Mitarbeitern und keine Abnahme der unternehmensspezifischen Inhalte oder SMTP-Zustellung.

## Aktualisierung

Das aktuelle Installationsskript herunterladen und als root mit `--update` ausführen.
Der Installer erstellt vor der Migration eine Sicherung. Hinterlegte Domainnamen und
Netzwerkeinstellungen bleiben erhalten; es wird keine feste IP vergeben.
