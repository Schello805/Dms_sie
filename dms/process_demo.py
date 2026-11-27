"""Optional illustrative Sielaff landscape, never imported by an installation/migration."""
from datetime import date, timedelta
from django.db import transaction
from . import processes, process_controls, services as s
from .policies import require_qmb

# Editorial examples; these are not verified internal Sielaff procedures.
BRANCHES = [
 ('Kunden gewinnen und Aufträge klären','Vertrieb',[
  ('Kundenanforderungen klären','Angebot prüfen',['Einsatzort und Automatenkonfiguration aufnehmen','Machbarkeit und Angebot freigeben'],'8.2','Anfrage und Einsatzbedingungen','Abgestimmtes Angebot'),
  ('Auftrag bearbeiten','Auftrag technisch klären',['Auftragsdaten mit Angebot abgleichen','Freigegebenen Auftrag an Planung übergeben'],'8.2','Kundenbestellung','Geklärter Fertigungsauftrag')]),
 ('Automaten und Rücknahmesysteme entwickeln','Entwicklung',[
  ('Produktentwicklung planen','Anforderungen und Entwicklung abstimmen',['Anforderungen an Mechanik und Elektronik festhalten','Entwicklungsprüfungen und Zuständigkeiten planen'],'8.3','Produktidee und Kundenanforderungen','Entwicklungsplan'),
  ('Entwicklung verifizieren und freigeben','Mustergerät bewerten',['Hardware- und Softwarefunktionen am Muster prüfen','Ergebnisse dokumentieren und Änderungen freigeben'],'8.3','Muster und Prüfkriterien','Freigegebener Entwicklungsstand')]),
 ('Material und Komponenten beschaffen','Einkauf',[
  ('Lieferanten steuern','Lieferanten bewerten',['Qualitäts- und Lieferdaten auswerten','Lieferantenmaßnahmen vereinbaren'],'8.4','Lieferdaten und Beanstandungen','Bewerteter Lieferant'),
  ('Beschaffung und Wareneingang sichern','Komponenten annehmen',['Bestellung und angelieferte Teile abgleichen','Prüfergebnis dokumentieren und Teile freigeben'],'8.4','Bestellung und Material','Geprüfte Komponenten')]),
 ('Automaten fertigen und prüfen','Produktion und Qualitätssicherung',[
  ('Montage durchführen','Automat montieren',['Mechanische Baugruppen nach freigegebenen Unterlagen montieren','Elektrik und Software gemäß Auftrag konfigurieren'],'8.5','Freigegebener Auftrag und Komponenten','Montierter Automat'),
  ('Endprüfung und Freigabe durchführen','Automat endprüfen',['Mechanik und elektrische Funktionen prüfen','Funktionsprüfung dokumentieren und Gerät freigeben'],'8.6','Montierter Automat und Prüfvorgaben','Prüfprotokoll und freigegebenes Gerät')]),
 ('Geräte ausliefern und bereitstellen','Logistik',[
  ('Versand vorbereiten','Gerät verpacken',['Geräteidentität und Zubehör abgleichen','Transportschutz und Lieferdokumente prüfen'],'8.5','Freigegebenes Gerät','Versandbereites Gerät'),
  ('Auslieferung koordinieren','Übergabe abschließen',['Liefertermin und Transport abstimmen','Übergabe und Abweichungen dokumentieren'],'8.5','Versandauftrag','Dokumentierte Übergabe')]),
 ('Kunden betreuen und Service leisten','Service',[
  ('Servicefälle bearbeiten','Störung eingrenzen',['Geräte- und Fehlerdaten aufnehmen','Diagnose und Abhilfemaßnahme dokumentieren'],'8.5','Serviceanfrage','Bearbeiteter Servicefall'),
  ('Reklamationen verbessern','Ursachenanalyse durchführen',['Fehlerursache mit Qualitätssicherung bewerten','Korrekturmaßnahme umsetzen und Wirksamkeit prüfen'],'10.2','Beanstandung und Nachweise','Wirksame Korrekturmaßnahme')]),
 ('Qualitätsmanagement führen und verbessern','Geschäftsführung und QMB',[
  ('Qualitätsziele und Prozesse steuern','Managementbewertung vorbereiten',['Prozesskennzahlen und Kundenrückmeldungen bewerten','Ziele, Maßnahmen und Ressourcen beschließen'],'9.3','Kennzahlen und Rückmeldungen','Managemententscheidungen'),
  ('Audits und Verbesserungen steuern','Internes Audit durchführen',['Auditprogramm risikoorientiert planen','Feststellungen verfolgen und Wirksamkeit bewerten'],'9.2','Auditprogramm und Prozessnachweise','Auditbericht und Verbesserungen')]),
 ('Ressourcen und Befähigung bereitstellen','Unterstützende Funktionen',[
  ('Kompetenzen sichern','Qualifizierung organisieren',['Kompetenzbedarf für Montage und Prüfung ermitteln','Unterweisung durchführen und Wirksamkeit bewerten'],'7.2','Aufgaben und Kompetenzbedarf','Nachgewiesene Befähigung'),
  ('Prüfmittel und Infrastruktur sichern','Prüfmittel überwachen',['Prüffrist und Eignung kontrollieren','Prüfmittel freigeben oder sperren'],'7.1.5','Prüfmittelbestand und Fristen','Geeignete freigegebene Prüfmittel')]),
]


def state():
    return s.query('SELECT visible,EXISTS(SELECT 1 FROM ims_processes WHERE demo) AS installed FROM process_demo_settings WHERE id')[0]


@transaction.atomic
def toggle(user, visible):
    actor=require_qmb(user)
    s.query('SELECT set_process_demo_visibility(%s,%s)',[actor,visible])


@transaction.atomic
def install(user):
    actor=require_qmb(user)
    s.query("SELECT pg_advisory_xact_lock(hashtext('ims-process-demo'))")
    if state()['installed']:
        toggle(user,True)
        return
    owner=actor
    def create(parent,code,title,role,clause,inputs,outputs,description):
        references=[row['id'] for row in s.query("SELECT r.id FROM standard_references r JOIN standards s ON s.id=r.standard_id WHERE s.name LIKE '%%9001%%' AND s.edition LIKE '%%2015%%' AND r.reference=%s",[clause])]
        data=dict(title=title,owner_id=owner,description='DEMO – unverbindlicher Vorschlag für Sielaff, Herrieden. Keine bestätigte interne Verfahrensanweisung.\n'+description+'\nNormorientierung: DIN EN ISO 9001:2015, '+clause+'. Verwendete Normausgabe und Zuordnung vor Übernahme fachlich prüfen.',inputs=inputs,outputs=outputs,responsibilities='Vorgeschlagene fachliche Zuständigkeit: '+role+'. Demo-Verantwortlicher ist vorläufig der anlegende QMB; vor produktiver Nutzung ersetzen.',documents=[],references=references)
        return processes.save(user,None,parent,code,data,True,True,'Optionale Sielaff-Demoprozesse angelegt.')
    production=None
    for i,(root_title,role,branches) in enumerate(BRANCHES,1):
        root=create(None,f'DEMO-SIE-{i:02}',root_title,role,'4.4','Ergebnisse vorgelagerter Prozesse','Abgestimmte Ergebnisse für nachgelagerte Prozesse','Ziele, Schnittstellen, Risiken und Wirksamkeit dieses Prozessbereichs abstimmen. Die konkret benötigten Nachweise und Verantwortlichkeiten sind betrieblich festzulegen.')
        s.query('SELECT mark_demo_process(%s,%s)',[actor,root])
        for j,(main,single,work,clause,inputs,outputs) in enumerate(branches,1):
            prefix=f'DEMO-SIE-{i:02}-{j:02}'
            main_id=create(root,prefix,main,role,clause,inputs,outputs,'Ablauf planen, Zuständigkeiten festlegen und die Ergebnisse anhand vereinbarter Kriterien bewerten.')
            single_id=create(main_id,prefix+'-01',single,role,clause,inputs,outputs,'Voraussetzungen und gültige Unterlagen prüfen, Tätigkeit durchführen und Abweichungen nachvollziehbar behandeln.')
            for k,title in enumerate(work,1):
                child=create(single_id,prefix+f'-01-{k:02}',title,role,clause,inputs,outputs,'Arbeitsauftrag und gültige Vorgaben prüfen. Tätigkeit entsprechend der Qualifikation durchführen. Ergebnis dokumentieren; bei Abweichungen stoppen und zuständige Stelle einbeziehen. Keine realen Sicherheits- oder Prüfgrenzwerte werden durch dieses Beispiel vorgegeben.')
                if i==4 and j==2 and k==2:production=child
    if production:
        today=date.today()
        risk=dict(title='DEMO: Fehlerhafte Endprüfung',owner_id=owner,description='Unvollständige Prüfschritte könnten dazu führen, dass ein nichtkonformes Gerät ausgeliefert wird.',probability=3,impact=5,action='Prüfumfang und Qualifikation abstimmen; Vollständigkeit der Prüfprotokolle stichprobenartig kontrollieren.',due_on=(today+timedelta(days=30)).isoformat(),status='open',residual_probability=None,residual_impact=None,effectiveness='')
        process_controls.save(user,production,None,'risk',risk,True,0,'Demobeispiel; Bewertung fachlich bestätigen.')
        kpi=dict(title='DEMO: Erstprüfquote',owner_id=owner,description='Ohne Nacharbeit bestandene Endprüfungen / alle Endprüfungen × 100. Zielwert ist ausschließlich ein fiktiver Demowert.',source='Fiktive Endprüfprotokolle',unit='%',direction='gte',target='98',interval_months=1,first_due=today.isoformat())
        process_controls.save(user,production,None,'kpi',kpi,True,0,'Fiktive Demo-Kennzahl ohne echte Betriebsdaten.')
    toggle(user,True)
