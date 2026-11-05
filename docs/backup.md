# Sicherungsbetrieb

## Verfahren

`backup_dms` öffnet eine eigene lesende REPEATABLE-READ-Transaktion und exportiert
deren Snapshot. `pg_dump --snapshot` und die Liste der Dateiobjekte beziehen sich
auf denselben Datenbankstand. Grundlage ist die von PostgreSQL dokumentierte
[Snapshot-Synchronisation](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION).
Der Ansatz setzt voraus, dass gespeicherte Dateiobjekte nicht überschrieben oder
parallel gelöscht werden. Das derzeitige DMS unterstützt keine Dateilöschung.
Eine spätere Aussonderungsfunktion muss mit Sicherungen koordiniert werden.

Das Paket enthält einen PostgreSQL-Custom-Dump ohne Eigentümer/Grants, die zum
Snapshot gehörenden Dateien, Anwendungscode und ein Prüfsummenmanifest. Jede
Datei wird beim Kopieren gegen SHA-256 und Größe aus der Datenbank geprüft.
Die Anwendung darf währenddessen Inhalte bearbeiten; der Snapshot hält den
Datenbankstand konstant. Code-Deployments und Schemaänderungen während der
Sicherung sind dagegen zu vermeiden. Pakete unter `.partial` gelten nie als
vollständige Sicherung. Der Befehl löscht keine alten Sicherungen.

Das Manifest ist eine Integritätskontrolle, keine digitale Signatur: Wer das
gesamte Paket ändern kann, könnte auch das Manifest ändern. Unabhängige Speicherung
und eingeschränkte Lösch-/Schreibrechte bleiben erforderlich.

## Lokal ausgeführter Restore-Test

Mit `check_restore` wurde ein erzeugtes Paket in einer frischen temporären
PostgreSQL-Datenbank restauriert. Migrationsstand, zentrale Datensatzanzahlen und
Dateireferenzen wurden gegen das Manifest geprüft; die Dateiinhalte und die
Dumpstruktur prüft `backup_dms --verify`. Eine absichtlich beschädigte temporäre
Dateikopie wurde erkannt. Die Quelldatenbank und das originale Paket blieben
unverändert.

Der Test stellt weder ein RPO-/RTO-Versprechen noch eine vollständige Abnahme der
Anwendung nach Wiederherstellung dar. Ein isolierter LXC-Test mit Anmeldung,
Dokumentdownload und vollständigem Freigabeworkflow bleibt Teil der Betriebsabnahme.
Nur vertrauenswürdige Sicherungspakete restaurieren.

## Geplanter LXC-Betrieb

- Dedizierte PostgreSQL-LOGIN-Rolle ohne Eigentümerrechte einrichten und die
  Leserechte aus `db/backup_grants.sql` nach Migrationen erneut anwenden.
- Die OS-Dienstidentität braucht Leserechte auf den privaten Dateispeicher.
- `/var/backups/ims-dms` mit Besitzer `ims-dms` und Modus 0700 vorbereiten.
- `deploy/backup.env.example` als `/etc/ims-dms-backup.env` mit korrekten Werten,
  Besitzer root und Modus 0600 einrichten.
- Die Beispiel-Service-/Timerdateien übernehmen. Erst nach einem erfolgreichen
  manuellen Backup und Restore-Test den Timer aktivieren. Der Beispieltermin ist
  täglich 03:15 Uhr Europe/Berlin; dies ist noch keine installierte Zeitplanung.

Auf diesem Entwicklungsrechner wurde kein systemweiter Timer installiert.
Die erste Sicherung liegt lokal unter `.local/backups`; das ist noch kein
unabhängiges Sicherungsziel. Kopieren, Verschlüsselung am unabhängigen Ziel,
Fehlerbenachrichtigung, Fristen und regelmäßige Restore-Abnahme sind betrieblich
noch festzulegen beziehungsweise einzurichten.

## Wiederherstellung eines Systems

Passende Anwendungsversion aus `application/` bereitstellen, eine neue leere
Datenbank mit passendem Eigentümer anlegen und `database.dump` mittels `pg_restore`
restaurieren. Die Dateien aus `files/` in den privaten Dokumentenspeicher übernehmen.
Danach Laufzeitrechte aus `db/runtime_grants.sql` neu vergeben.

Dienstkonfiguration, DMS_SECRET_KEY, Datenbank- und spätere AD-Zugangsdaten werden
bewusst nicht automatisch mitgesichert. Diese Werte getrennt geschützt verwahren
oder bei einer Wiederherstellung neu provisionieren. Ein neuer DMS_SECRET_KEY
macht vorhandene Sitzungen ungültig. Dateirechte, Netzwerkbindung, HTTP-/HTTPS-
Betriebsmodus und Sicherungsziel anhand des tatsächlichen Betriebs prüfen.
