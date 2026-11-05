# Lokaler Volltextbetrieb

## Ablauf und Berechtigungen

Ein Datenbanktrigger legt für neue Dateiobjekte einen Indexauftrag an. Die
Migration übernimmt auch vorhandene Dateien. Der Worker beansprucht einen Auftrag
mit einer zeitlich begrenzten Lease und `FOR UPDATE SKIP LOCKED`. Er prüft Größe
und SHA-256 der Originaldatei, verarbeitet sie in einem Kindprozess und speichert
nur den abgeleiteten Text. Ein abgelaufener Lease wird höchstens bis zum dritten
Versuch erneut beansprucht. Parserfehler bleiben bis zur manuellen Wiederholung
als Fehler sichtbar. Verspätete Ergebnisse einer alten Lease werden verworfen.

Die Indexierung ändert weder Originaldatei noch Freigabefingerabdruck. Der Index
ist abgeleiteter Zustand, kein eigenständiger Freigabenachweis. Geteilte Dateiobjekte
werden einmal indexiert; Suchtreffer werden immer anhand der konkreten Version
mit `can_read_version()` gefiltert. Gruppenentzug, vertrauliche Freigaben,
Gültigkeit, Rückzug und Archivierung gelten damit auch bei der Volltextsuche.

Der Webdienst kann Dateien zur Wiederholung vormerken. Die separate Workerrolle
hat nur SELECT auf Dateiobjekte/Indexaufträge und UPDATE auf Indexaufträge;
sie kann weder Benutzer lesen noch Originaldateien oder Freigaben verändern.
Dynamische Webantworten enthalten `Cache-Control: private, no-store`.

## Formate und Grenzen

- TXT: UTF-8, mit oder ohne BOM.
- PDF: vorhandene Textebene, höchstens 200 Seiten; verschlüsselte Dateien werden abgewiesen.
- DOCX: Haupttext sowie Kopf-/Fußzeilen.
- XLSX: Blattnamen, Zeichenketten, Inline-Texte und gespeicherte Zellwerte;
  Formeln und externe Datenverbindungen werden nicht berechnet.
- ODT: Text aus `content.xml`.

Pro Datei maximal 25 MiB Eingabe, 200.000 gespeicherte Zeichen, bei ZIP-basierten
Formaten maximal 2.000 Einträge / 32 MiB deklarierter entpackter Gesamtumfang und
8 MiB je gelesener XML-Datei. DTDs, Entities und externe XML-Referenzen sind gesperrt.
Gekürzte Texte werden als begrenzt gekennzeichnet. Nur der gespeicherte Anteil
ist durchsuchbar. Dokumente bleiben unabhängig davon über Nummer oder Titel auffindbar; eine
zusätzliche Dateinamensuche ist nicht enthalten.

Der Kindprozess erhält keine geerbten Datenbank-/Anwendungsgeheimnisse, keine
Shellbefehle aus Dokumenten und keine Dateipfade als Extraktionsauftrag. Er erhält
die Bytes auf stdin. Limits: zehn Sekunden CPU, zwanzig Sekunden Laufzeit,
unter Linux zusätzlich 768 MiB Adressraum. Der Mac-Entwicklungsbetrieb hat dieses
Linux-Speicherlimit nicht. Ein Systemd-Beispiel begrenzt den gesamten Worker zusätzlich.

Das ist Prozess-/Ressourcenbegrenzung, **keine vollständige OS-Sandbox** und keine
Malwareprüfung. Die OS-Identität kann weiterhin auf ihr zugängliche Dateien und
das Netzwerk zugreifen. Vor produktivem Betrieb mit untrusted Uploads einen
separaten, gehärteten Parserdienst beziehungsweise passende Container-/OS-
Isolation und Malwareprüfung ergänzen. Python-Pakete und Systembibliotheken pflegen.
Bildbasierte Scans werden ohne Textebene nicht indexiert; OCR bleibt offen.

## Start und LXC

Lokal: `.venv/bin/python scripts/index_local.py`. Einmalig:
`.venv/bin/python scripts/index_local.py --once --limit 100`.
Für Betrieb mit vorhandener Konfiguration:
`.venv/bin/python manage.py process_index`.

Für den LXC eine dedizierte LOGIN-Rolle `ims_dms_index` ohne Eigentümerrechte
anlegen und `db/index_grants.sql` nach Migrationen anwenden. Der OS-Dienstbenutzer
braucht Leserechte auf den privaten Dokumentenspeicher. Geheimnisse in
`/etc/ims-dms-index.env` (root, 0600) gemäß `deploy/index.env.example` konfigurieren.
`deploy/ims-dms-index.service` ist eine Vorlage; sie wurde auf diesem Mac nicht
als Systemdienst installiert. Die lokale Hintergrundverarbeitung wurde gestartet.

Bei einer Wiederherstellung übernimmt der Worker verwaiste RUNNING-Aufträge nach
Ablauf der Lease. Der Index wird mit der Datenbank gesichert. Bei späteren
Änderungen der Parserlogik muss ein kontrollierter Neuaufbau vorgesehen werden.

## Technische Grundlagen

- [PostgreSQL: Volltextsteuerung und sichere Ausgabe von Textauszügen](https://www.postgresql.org/docs/16/textsearch-controls.html)
- [PostgreSQL: gespeicherte Suchvektoren und Indizes](https://www.postgresql.org/docs/16/textsearch-tables.html)
- [pypdf: Textauslese und Speicherbedarf](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md)
- [defusedxml: XML-Schutzmechanismen](https://pypi.org/project/defusedxml/)
