# E-Mail-Erinnerungen für Dokumentreviews

## Empfänger und Zeitpunkte

Empfänger sind `documents.owner_id`, also der verantwortliche Autor, sowie beide
aktiven benannten QMBs (Hauptverantwortlicher und Vertretung). Eine Person mit beiden
Funktionen erhält pro Anlass nur eine Nachricht. Dieser ist anfangs der anlegende Autor; der Ersteller einer späteren Fassung
ersetzt diese Verantwortung nicht automatisch. Verwendet wird die jeweilige im DMS
hinterlegte E-Mail-Adresse, ersatzweise die lokale Konto-Adresse. Die Administration
kann Adressen unter „Admin-Einstellungen → E-Mail-Adressen der Autoren“ pflegen;
Änderungen werden protokolliert. Eine spätere AD-Synchronisation muss diese
Zuordnung berücksichtigen.

Der globale Vorlauf ist standardmäßig 30 Tage und unter „Verwaltung → Erinnerungen“
zwischen 0 und 3650 Tagen einstellbar. 0 deaktiviert die Voraberinnerung.
Je Fassung, Empfänger und Prüftermin gibt es höchstens eine Vorabmeldung
und eine Fälligkeitsmeldung. Nach einem verpassten Lauf wird innerhalb des
Vorlauffensters beziehungsweise nach Fälligkeit nachgeholt. Es gibt keine tägliche
Wiederholung derselben Überfälligkeitsmeldung. Nach erfolgreichem Review entsteht
für den neuen Prüftermin ein neuer Erinnerungszyklus.

Eine neue Fassung, ein erledigtes Review, Rückzug, Archivierung, geänderte
Verantwortung oder entzogener Zugriff werden vor dem Versand erneut geprüft.
Entfällt die QMB-Zuordnung, werden vorgemerkte QMB-Nachrichten nicht mehr versendet.
Nur die derzeit wirksame Fassung ist relevant. Ohne aktive Kontozuordnung und
aktuelles Leserecht wird keine Dokumentinformation per E-Mail versendet.
Fehlende E-Mail-Adressen erscheinen als Fehler im Versandprotokoll; nach Ergänzung
wird ein solcher Vorgang wieder vorgemerkt.

## SMTP-Einstellungen

Automatik bleibt anfangs deaktiviert. Der QMB verwaltet Vorlauftage und Aktivierung.
Die IT-Administration hinterlegt unter „Admin-Einstellungen“:

- SMTP-Hostname/IP, Port, STARTTLS oder TLS/SSL; optional interner Relay ohne TLS,
- optionalen Benutzernamen und Passwort,
- Absenderadresse und erreichbare DMS-Adresse für Dokumentlinks.

Eine Test-E-Mail verwendet ausschließlich die gespeicherten Einstellungen und
den ausdrücklich angegebenen Testempfänger. Sie aktiviert die Automatik nicht.
Auf dem Entwicklungsrechner wurden bisher nur lokale SMTP-Testserver angesprochen;
ein realer Server muss noch eingetragen und getestet werden.

Das Passwort wird mit Fernet verschlüsselt gespeichert, nicht im Formular
zurückgegeben und nicht in Audit-Einträgen protokolliert. Ein leeres Passwortfeld
behält das gespeicherte Passwort bei; Entfernen erfolgt über eine eigene Checkbox.
Bevorzugt einen stabilen separaten Fernet-Schlüssel über `DMS_SMTP_ENCRYPTION_KEY`
in Web- und Erinnerungsdienst identisch konfigurieren. Ohne diese Variable wird
für den Entwicklungsbetrieb ein separater Schlüssel aus DMS_SECRET_KEY abgeleitet.
Beim Wechsel des zugrunde liegenden Schlüssels das SMTP-Passwort neu hinterlegen.
Die Schlüssel getrennt vom Datenbankbackup sichern.

STARTTLS/TLS prüfen Serverzertifikate. Interne CAs gegebenenfalls im Betriebssystem
vertrauenswürdig einrichten. Die Verschlüsselung in der Datenbank ersetzt keine
Transportverschlüsselung: Der auf Wunsch verwendete HTTP-Webzugang bleibt HTTP.

## Hintergrunddienst und Versandprotokoll

Lokal:

```sh
.venv/bin/python scripts/notifications_local.py
```

Einmaliger Lauf:

```sh
.venv/bin/python scripts/notifications_local.py --once
```

Die lokale Startdatei erzeugt eine eingeschränkte Datenbankrolle. Der Dienst
prüft standardmäßig alle 60 Sekunden und verarbeitet maximal 100 Vorgänge pro
Durchlauf. Er sendet erst bei aktivierter, vollständig eingerichteter SMTP-
Konfiguration. Keine automatische Auswertung externer Zustellbestätigungen/Bounces.

Für den LXC gibt es `deploy/ims-dms-notifications.service`, die Beispielumgebung
`deploy/notifications.env.example` und `db/notification_grants.sql`. Diese Vorlagen
wurden auf dem Mac nicht als Systemdienst installiert. Nach Migrationen die
Rollenrechte erneut vergeben und Web-/Erinnerungsdienst neu starten.
Die Workerrolle kann keine Passwort-Hashes oder Dokumentdatei-/Volltexttabellen
lesen und keine SMTP-Einstellungen ändern.

Das Admin-Versandprotokoll zeigt die letzten 50 Vorgänge mit Status und Fehlerhinweis.
Dokumentnummern werden auch dort nur bei eigenem Dokumentleserecht angezeigt.
Die E-Mail enthält Nummer, Titel, Prüftermin und Dokumentlink, keine Anhänge oder
Volltextauszüge. SMTP-Annahme bedeutet noch keine Zustellung im Zielpostfach.

Eindeutig fehlgeschlagene Sendungen können erneut vorgemerkt werden; passende
Fehler werden nach korrigierten SMTP-Einstellungen automatisch erneut vorgemerkt.
Bei Timeout/Verbindungsabbruch nach möglicher SMTP-Annahme oder unterbrochenem
Worker bleibt das Ergebnis bewusst „unklar“ und wird nicht automatisch wiederholt.
SMTP und Datenbank bilden keine gemeinsame Transaktion; eine mathematische
Exactly-once-Zustellung kann deshalb nicht zugesichert werden. Unklare Fälle
anhand von Postfach/SMTP-Protokoll prüfen. Konfiguration und Versandereignisse
werden ohne SMTP-Passwort auditiert.

Bei parallelen Restore-Tests ausgehenden SMTP blockieren oder die Automatik vor
Start eines Erinnerungsdienstes deaktivieren. `check_restore` startet keinen
Versanddienst und verschickt keine Nachrichten.

Technische Grundlagen: [Django SMTP-Backend](https://docs.djangoproject.com/en/5.2/topics/email/)
und [Fernet](https://cryptography.io/en/stable/fernet/).
