# Betrieb unter Proxmox / LXC

## Zielaufbau

Unprivilegierter LXC, 4 vCPU, zunächst 8 GB RAM, persistenter Dokumentenspeicher.
Das sind Planungswerte; OCR und Lastprofil können Anpassungen erfordern.
PostgreSQL und Gunicorn laufen lokal, Nginx bietet den ausdrücklich gewählten internen HTTP-Zugang an; eine optionale TLS-Vorlage liegt ebenfalls vor.
PostgreSQL und Port 8000 nicht ins Unternehmensnetz veröffentlichen.

## Installation

1. Unterstütztes Debian/Ubuntu mit Python ab 3.12, PostgreSQL ab 16, Nginx,
   Python-venv bereitstellen; für eine optionale TLS-Variante zusätzlich die interne Zertifikatskette.
2. Dedizierten Systembenutzer `ims-dms` anlegen. Projekt samt `db/` nach
   `/opt/ims-dms` kopieren und dort die virtuelle Umgebung installieren.
   Anwendungscode sollte dem Administrator gehören und vom Dienst nur lesbar sein.
3. `/var/lib/ims-dms/files` mit Besitzer `ims-dms` und Modus 0700 anlegen.
   Dieses Verzeichnis auf persistentem, gesichertem Speicher halten.
4. PostgreSQL-Eigentümer `ims_dms_owner`, separate LOGIN-Rolle `ims_dms_app`
   ohne CREATEDB/CREATEROLE/SUPERUSER und Datenbank `ims_dms` mit Eigentümer
   `ims_dms_owner` anlegen. Die App-Rolle darf keine Eigentümerrechte erben.
5. Migrationen mit der Eigentümerrolle ausführen, anschließend als Eigentümer:

   ```sh
   psql -v ON_ERROR_STOP=1 -v runtime_role=ims_dms_app -d ims_dms -f db/runtime_grants.sql
   ```

6. Lokale Konten und DMS-Zuordnungen mit der Eigentümerrolle einrichten, wie
   in der README beschrieben. Migrationszugang nicht im Webdienst hinterlegen.
7. `deploy/http.env.example` nach `/etc/ims-dms.env` übernehmen (interner HTTP-Betrieb). Geheimnisse ersetzen,
   Eigentümer root und Modus 0600 setzen. Dienst verwendet `ims_dms_app`.
   Die Anwendung liest keine `.env` automatisch; systemd lädt EnvironmentFile.
8. `deploy/ims-dms.service` nach `/etc/systemd/system/` übernehmen. `deploy/nginx-http.conf` mit dem tatsächlichen internen DNS-Namen konfigurieren.
   Erst nach `nginx -t` und `manage.py check --deploy` aktivieren.
9. `systemctl daemon-reload` und `systemctl enable --now ims-dms` ausführen.
   Internen HTTP-Zugriff prüfen. Die optionale TLS-Variante verwendet `deploy/env.example` und `deploy/nginx.conf`.

`DMS_TRUST_PROXY=1` nur verwenden, wenn Gunicorn ausschließlich über den lokalen
vertrauenswürdigen Proxy erreichbar ist und dieser X-Forwarded-Proto überschreibt.
Das Beispiel tut dies. HSTS erst nach erfolgreicher TLS-/DNS-Abnahme aktivieren.
Der Login-Endpunkt besitzt im Nginx-Beispiel eine IP-basierte Begrenzung; bei
vielen Benutzern hinter einer NAT-Adresse muss diese passend angepasst werden.

## Betriebsabnahme

Mit separaten Konten Autor → Prüfer → Freigabe durchspielen, Rückgabe und
Wiedereinreichung prüfen, danach Leserzugriff und Abteilungstrennung testen.
Eine zukünftige Freigabe darf die aktuelle Fassung vor ihrem Wirksamkeitsdatum
nicht verdrängen. Eine neue wirksame Fassung verdrängt den Vorgänger für Leser;
Autoren/Prüfer/Freigabeverantwortliche behalten Zugriff auf die Historie.
Abgelaufene Nachfolger lassen alte Fassungen nicht automatisch wieder aufleben.

Die Ausgangsversion bleibt technisch APPROVED, auch wenn sie für Leser durch
`current_release()` abgelöst wurde. Rückzug und Archivierung stehen inzwischen als getrennte, begründete Vorgänge
für die Freigaberolle bereit. Aktuell ist nur eine laufende Überarbeitung je Dokument
über den Anwendungsdienst vorgesehen.

## Sicherung und Wiederherstellung

Datenbank, Dateispeicher, erforderliche Konfiguration und die zugehörige
Anwendungsversion gemeinsam sichern. Für den ersten Betrieb ein konsistentes
Wartungsfenster verwenden: Webdienst stoppen, Datenbank mittels `pg_dump` sichern,
Dateiverzeichnis sichern, Dienst wieder starten. Backups verschlüsselt auf einem
separaten System mit eingeschränkten Löschrechten und definierten Fristen ablegen.
LXC-Snapshots allein ersetzen dieses Konzept nicht.

Wiederherstellung in einem isolierten Testcontainer regelmäßig prüfen:
Datenbank restaurieren, Dateien und passende Anwendungsversion bereitstellen,
Dateiprüfsummen und einen vollständigen Dokumentenworkflow testen. RPO, RTO und
Aufbewahrungsfristen müssen betrieblich festgelegt werden.

Audit-Ereignisse zusätzlich auf ein getrennt administriertes Ziel übertragen.
Das ist in diesem Stand noch nicht automatisiert. Betriebssystemprotokolle können
Dokument-IDs und Benutzernamen enthalten und brauchen ebenfalls Zugriffsschutz.

## Aktualisierung dieses Entwicklungsstands

Nach neuen Migrationen den Dienst im Wartungsfenster stoppen, die Datenbank mit
Eigentümerzugang migrieren und `db/runtime_grants.sql` erneut anwenden. Die
Laufzeitrolle benötigt seit der Normzuordnungsoberfläche DELETE auf den beiden
Zuordnungstabellen; Trigger erlauben dies ausschließlich für Entwürfe. Danach
den Dienst starten und Berechtigungen sowie Freigabeablauf prüfen.

## Berechtigungsmodell ab Migration 0004

`db/004_access.sql` ergänzt Gruppen, Mitgliedschaften, Dokumentrollen und
Dokumentzugriffslisten. Nach der Migration die Laufzeit-Grants erneut anwenden.
Bestehende Dokumente behalten ihren bisherigen Abteilungszugriff; ihr Process
Owner erhält vorsorglich eine explizite Zuordnung für spätere Klassifizierung.
Bestehende Inhaltsversionen und Freigabeentscheidungen werden nicht verändert.

Die gemeinsame SQL-Funktion `can_read_version()` wird für Suche, Einzelzugriff
und die Filterung der Historie verwendet. Downloads und Mutationen prüfen
zunächst den Einzelzugriff. Gruppen- und Dokumentrollen erweitern keine
vertrauliche Freigabe: Die ausdrückliche Zugriffsbedingung ist zusätzlich nötig.

Gruppenadministration erfolgt über `manage_group` mit administrativem CLI-Zugang.
Keine administrativen Rollenzuordnungen an die Web-Laufzeitrolle vergeben.
Zugriffslisten dürfen Dokumentautoren mit Begründung pflegen. Änderungen wirken
sofort für alle Fassungen, auch wenn Inhalte schon freigegeben sind. Die
Versionsklassifizierung bleibt dagegen Teil des freigabepflichtigen Inhalts.

## Volltext ab Migration 0006

Abhängigkeiten aus `requirements.lock.txt` installieren, Migration ausführen und
Web-/Workerrechte erneut vergeben. Die Migration erzeugt Indexaufträge für alle
vorhandenen Dateiobjekte. Webdienst und Volltext-Worker getrennt starten; ohne
Worker bleibt die Suche in Titel/Dokumentnummer nutzbar, neue Dateiinhalte sind
aber noch nicht durchsuchbar. Formate, Limits und die noch notwendige produktive
Parserisolation stehen in `docs/fulltext.md`.

## Kategoriefristen ab Migration 0007

Die Migration legt Kategoriefristen mit Standard 24 Monaten an und übernimmt
vorhandene Dokumenttypen als Kategorien. Bestehende Dokumentversionen, Termine
und Inhaltsfingerabdrücke bleiben unverändert. Die neue gemeinsame Sicht
`version_review_status` unterscheidet den letzten Review-Vorgang vom letzten
Review mit bestätigter Richtigkeit. Nur eine bestätigte Richtigkeit verlängert
die Gültigkeit. Die fachliche Erstprüfung wird nach vollständig abgeschlossener
Freigabe als letztes Review berücksichtigt.

Nach der Migration `db/runtime_grants.sql` erneut anwenden. Der Webdienst darf
Kategorieintervalle ändern, aber keine Administrationsrechte vergeben. Die
Administrationsberechtigung ist ein separates, explizites DMS-Recht und wird
mit `settings_admin` über den administrativen CLI-Zugang gepflegt.
Änderungen gelten für spätere Fristberechnungen; bereits freigegebene Termine
werden nicht stillschweigend verschoben. Die gewählten Fristen sind betriebliche
Festlegungen und keine pauschale Anforderung der ISO-Normen.

## Erinnerungen ab Migration 0008

Abhängigkeiten aktualisieren, Migration anwenden und Laufzeit-/Erinnerungsrechte
neu vergeben. SMTP und Vorlauf werden über den gesondert berechtigten Adminbereich
gepflegt. Der Erinnerungsdienst ist separat zu starten; die Standardeinstellung
ist deaktivierter Versand. Erst Absender, erreichbare DMS-Adresse, SMTP und
Empfängeradressen einrichten und einen gezielten Test durchführen, dann aktivieren.
Der SMTP-Passwortschlüssel muss zwischen Web- und Erinnerungsdienst übereinstimmen
und getrennt gesichert werden. Weitere Details stehen in `docs/email-reminders.md`.

## Mitarbeiterportal ab Migration 0011

Nach Migration und Runtime-Grants Webdienst neu starten. Für spätere Wirksamkeit,
neue Mitarbeiter und neue Zielgruppen-Zuordnungen zusätzlich `ims-dms-portal.service`
installieren und aktivieren. Der Dienst verwendet die App-Rolle; Migrationseigentümer
werden nicht benötigt. Vor Aktivierung einmal `manage.py process_portal --once` ausführen.
Unter Debian/Ubuntu `fonts-dejavu-core` für Unicode-Schriften in PDF-Lesefassungen installieren.
Nachweisdaten, Kenntnisnahmen und Verteilungsdaten sind in Datenbankbackup und
Restore-Prüfung enthalten. Die vorhandenen Backup-/Worker-Grants nach jedem Schema-Upgrade
erneut anwenden. Vor Produktivbetrieb werden AD, Malwareprüfung/Parserisolation,
externe Sicherung, Audit-Transport und Lastabnahme separat benötigt.
In der aktuellen Entwicklung werden auf ausdrücklichen Wunsch lokale Konten verwendet.

## Technische Diagnose ab Migration 0013

Migration und Runtime-Grants anwenden, Webdienst neu starten.
`install -d -o ims-dms -g ims-dms -m 0700 /var/lib/ims-dms/logs` ausführen und
`DMS_ERROR_LOG_DIR=/var/lib/ims-dms/logs` in der Web- und bei Bedarf Worker-Umgebung
setzen. Der vorhandene systemd-Webdienst darf unter `/var/lib/ims-dms` schreiben.
Im Adminbereich „Protokollierung testen“ ausführen und den markierten Eintrag prüfen.
Fehlermeldungen enthalten absichtlich weder raw SQL noch Parameter oder vollständige
Exception-Texte; Anfrage-ID und Codezeile dienen zur weiteren Diagnose.
Technische Logdateien liegen außerhalb der Dokumentensicherung; für längerfristige
Aufbewahrung ein separat geschütztes Betriebslog-Ziel einsetzen.

AD-/LDAP-Felder sind ausschließlich vorbereitend. Keine echten LDAP-Zugangsdaten
für lokale Funktionstests erforderlich. `DMS_LDAP_ENCRYPTION_KEY` bzw. DMS_SECRET_KEY
für die spätere produktive Konfiguration stabil halten und separat sichern.
