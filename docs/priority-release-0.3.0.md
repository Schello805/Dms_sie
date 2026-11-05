# Ausbaustufe 0.3.0-dev

## Fertig

- Lokale Benutzer im IT-Bereich anlegen, suchen, aktivieren/deaktivieren und Passwörter zurücksetzen; eigene Passwortänderung im Profil.
- Begrenzte, auditierte SQL-Funktionen statt direkter Auth-Tabellenrechte. Kontodeaktivierung und Passwortänderung widerrufen Sitzungen. Selbstdeaktivierung und Deaktivierung des letzten aktiven QMB werden verhindert.
- QMB-Arbeitsliste/Glocke mit Freigaben, Rückgaben und bevorstehenden/überfälligen Reviews. Review-Vorlauf aus den Verwaltungseinstellungen; keine unabhängige Prüfung eigener Dokumente.
- IT-Hinweise für fehlende/veraltete Worker-Lebenszeichen, Sicherungsfehler und knappes Dateisystem. Überwachung ist lokal in der Anwendung, nicht extern per E-Mail.
- Metadaten-/Zuordnungs-/Dateiprüfsummenvergleich zur zugänglichen Vorversion. Kein visueller PDF-Inhaltsvergleich.
- Rückkehrzustand der Tabelle pro Tab, Warnung bei ungespeicherten Formularen, fixierte Tabellenköpfe/Dokumentnummer.
- Installer ohne erforderliche IP/Host-Angabe. Keine Änderung von DHCP, IP-Adressen oder Netzwerkschnittstellen. Zusätzliche DNS-Namen optional. Hostprüfung akzeptiert IP-Literale, localhost, Serverhostname und ausdrücklich konfigurierte Namen; beliebige fremde DNS-Hosts bleiben gesperrt.

## Prüfung

- Vollständiger PostgreSQL-Testlauf: **171 Tests erfolgreich**.
- Installer: **11 Unit-Tests erfolgreich**.
- Praktische lokale HTTP-Abnahme mit neuem, anschließend deaktiviertem synthetischem Leserkonto: Erstellen, Passwortwechsel, Login mit neuem Passwort, Sperre alter Passwörter/Sitzungen, Deaktivieren, Arbeitsliste, Monitoring und Versionsvergleich.
- Wechselnde IP-Hostheader akzeptiert, fremder DNS-Hostname mit HTTP 400 abgewiesen.
- [GitHub Ubuntu-24.04-Abnahme](https://github.com/Schello805/Dms_sie/actions/runs/42090357329): Installation ohne `--host`, am Standardport 80, zwei wechselnde IP-Hostheader, Sicherung und Update erfolgreich.
- JavaScript-Syntax geprüft. Die lokale Browsersteuerung war in den Work-Einstellungen deaktiviert; für diese Ausbaustufe liegt deshalb keine neue visuelle Browserabnahme vor.

## Update bestehender Installationen

Als root zuerst den aktuellen Installer herunterladen, dann aktualisieren:

```bash
curl -fsSL https://raw.githubusercontent.com/Schello805/Dms_sie/main/scripts/install_linux.py -o /tmp/install-ims-dms.py
python3 /tmp/install-ims-dms.py --update
```

Das Update sichert den bisherigen Bestand und wendet Migration 0015 sowie die zugehörigen Laufzeit-Grants an. Bestehende Host-Angaben bleiben zusätzliche Aliase; der Zugang ist nicht mehr an die damalige IP gebunden. Gedruckte QR-Codes und E-Mail-Links sollten für dauerhafte Erreichbarkeit einen stabilen DNS-Namen verwenden.

## Weitere Ausbaustufen

AD/LDAP-Synchronisation, automatische Office-PDF-Erzeugung, OCR, Malwareprüfung und externe Alarmierung sind durch diese priorisierte Ausbaustufe nicht als erledigt anzusehen. Vorhandene Dateien werden weiterhin über die unterstützte PDF-/TXT-Vorschau oder als Originaldownload bereitgestellt. Diese Komponenten benötigen eine eigene Implementierung und Abnahme; die Leseroberfläche bleibt bewusst auf Übersicht, Ansicht und Download beschränkt.
