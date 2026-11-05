# Code-Struktur und Änderungen an der Oberfläche

- `dms/catalog_views.py`: Dokumententabelle, Filter, Sortierung und JSON-Antworten beim Nachladen. `PAGE_SIZE` legt die Blockgröße fest.
- `dms/catalog_columns.py`: zentrale Definition der Überschriften und erlaubten SQL-Sortierausdrücke. Neue sortierbare Spalten hier eintragen; keine SQL-Ausdrücke aus Request-Parametern übernehmen.
- `dms/services.py`: Datenbankzugriffe und Dokumentenberechtigungen. Vollständige Tabelle und nachgeladene Zeilen verwenden dieselbe Sichtbarkeitsprüfung.
- `dms/templates/dms/base.html`: Seitenrahmen. Navigation und Meldungen sind eigene Includes (`navigation.html`, `toasts.html`).
- `dms/templates/dms/document_rows.html`: gemeinsames Zeilentemplate für erste Seite und Lazy Loading.
- `dms/static/dms/app.css`, `branding.css`: Layout und Branding; Reihenfolge der Stylesheets beibehalten.
- `dms/static/dms/app.js`: Toasts und Benutzermenü.
- `dms/static/dms/catalog.js`: progressive Erweiterung der serverseitigen Seitennavigation.
- `dms/ui_assets.py`: explizite Allowlist für diese vier lokalen UI-Dateien. Funktioniert auch direkt mit Gunicorn ohne separaten Static-Webserver. Neue Dateien müssen hier freigegeben werden. Dokumentablage niemals darüber ausliefern.

Die Asset-URLs liegen unter `/assets/ui/`. Die bestehende Cache-Middleware verhindert veraltete UI-Dateien. Die Datensicherung nimmt Templates und Assets automatisch mit auf.

## Prüfung

Die PostgreSQL-Tests prüfen auch Filter, Sortierung, Seitengrenzen, Sichtbarkeit von Entwürfen und die Asset-Allowlist. Nach Änderungen zusätzlich im Browser prüfen: Anmeldung, Benutzermenü, Toast-Schließen und die Dokumententabelle. Lazy Loading hat einen manuellen Ladebutton; ohne JavaScript bleibt der normale Seitenlink erhalten.
