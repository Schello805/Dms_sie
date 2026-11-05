# Workflow-Prüfung vom 05.11.2026

Geprüfte Bereiche: Leser/Gast, Autor, QMB, IT-Administration, Upload, Entwurf, Prüfung, Rückgabe, erneute Einreichung, unabhängige Freigabe, Revision, periodisches Review, Rückzug/Archivierung, E-Mail-Erinnerungen, Sortierung und blockweises Nachladen.

## Korrigierte Fehler

- Revisionen erhalten ein vorbelegtes, im Entwurf änderbares Wirksamkeitsdatum. Einreichen funktioniert ohne vorgeschaltete Reparatur der Metadaten.
- Ein abgelaufenes historisches `valid_until` verhindert weder das Review einer weiterhin aktuellen Freigabe noch deren Fälligkeits-Erinnerungen. Expliziter Rückzug und Archivierung bleiben maßgeblich für die Verfügbarkeit.
- Öffentlich klassifizierte Metadaten mit expliziter Zugriffsliste erscheinen nicht im Gastkatalog.
- Auch offene ältere Prüfzyklen ohne aktuellen QMB-Qualifikationssnapshot erscheinen wieder in der QMB-Aufgabenliste. Die unabhängige Neuprüfung bei Übernahme bleibt Pflicht.
- Kombinierte Autor-/QMB-Konten bekommen beim eigenen Entwurf die korrekten Einreichungsaktionen.
- Nicht unterstützte Office-Dateien haben keinen defekten PDF-Vorschau-Link mehr.

## Bedienung

- Upload bietet getrennte Aktionen für Entwurf und sofortige QMB-Anfrage.
- QMB-Freigabe und Ablehnung sind explizite Schaltflächen. Ablehnung benötigt weiterhin serverseitig eine Bemerkung; die Oberfläche weist früh darauf hin.
- Rückgabegrund erscheint direkt beim betroffenen Entwurf.
- Validierungsfehler bei Workflow-Entscheidungen behalten eingegebene Bemerkungen bei.
- Entwürfe zeigen noch kein verbindliches Ablaufdatum; dieses wird bei Freigabe festgelegt.
- Bearbeitungsansicht heißt „Entwurf bearbeiten“; erfolgreiche Speicherung wird bestätigt.
- Periodisches Review verlangt eine bewusste Ergebniswahl.
- Mehrfaches Absenden desselben Formulars wird in der Oberfläche abgefangen. Die Datenbankprüfungen bleiben die maßgebliche Absicherung.
- Abmelden führt zur Dokumentenübersicht zurück.

## Verifikation und Grenzen

Regressionstests prüfen unter anderem Revision ohne zusätzliche Bearbeitung, Ablauf/Review, tatsächlichen Versand über einen isolierten SMTP-Testserver, Gastzugriff mit expliziten Berechtigungen, kombinierte Rollen, Rückgaben und Office-Vorschau. Bestehende Tests prüfen Rollen, Selbstfreigabeverbot, unveränderliche Auditdaten, Wiederholungsversuche, Rückzug, Archivierung und Benachrichtigungen.

Lokale Konten bleiben Testbasis. Die produktive AD-/LDAP-Anmeldung und eine Verbindung zum späteren Unternehmens-SMTP sind damit nicht abgenommen. Bestehende freigegebene Inhalte und Entscheidungen werden nicht nachträglich umgeschrieben.

## Ergebnis der Abnahme

- Vollständiger Testlauf: 158 Tests erfolgreich.
- Nach den letzten Formular-/UI-Korrekturen: 26 gezielte Tests erfolgreich, einschließlich einer zusätzlichen Regression für den Erhalt ungültiger Bemerkungen.
- Zwei praktische HTTP-Abnahmen mit lokalen Konten: vollständiger Upload-/Rückgabe-/Freigabeablauf sowie Revision, leere Ablehnung, periodisches Review und Zugriffsschutz der vorherigen Fassung.
- Beispieldokument `DEMO-007` wurde hierfür angelegt und als Revision 1.1 freigegeben; es ist ausdrücklich keine betriebliche Vorgabe.
- Upload und QMB-Entscheidung wurden zusätzlich im Browser geprüft.
