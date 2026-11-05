import os
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

class Command(BaseCommand):
    help = 'Lokale Entwicklungsbenutzer anlegen; bestehende Passwörter unverändert lassen.'
    @transaction.atomic
    def handle(self,*args,**options):
        if os.environ.get('DMS_DEBUG') != '1' or not os.environ.get('DMS_DEMO_PASSWORD'):
            raise CommandError('Nur mit DMS_DEBUG=1 und DMS_DEMO_PASSWORD verwenden.')
        for username,role in [('autor','AUTHOR'),('pruefer','QMB'),('freigabe','AUTHOR'),('qmb_vertretung','QMB'),('leser','READER')]:
            if not get_user_model().objects.filter(username=username).exists():
                get_user_model().objects.create_user(username,password=os.environ['DMS_DEMO_PASSWORD'])
            call_command('provision_dms',username,role=role,department='*',department_name=None,stdout=self.stdout)
        from dms.services import query
        query("DELETE FROM role_assignments WHERE user_id=(SELECT id FROM users WHERE auth_user_id=(SELECT id FROM auth_user WHERE username='freigabe')) AND role='REVIEWER' AND department_id IS NULL AND document_id IS NULL")
        admin,created = get_user_model().objects.get_or_create(username='admin')
        if created:
            admin.set_password(os.environ['DMS_DEMO_PASSWORD'])
            admin.save(update_fields=['password'])
        query('INSERT INTO users(display_name,auth_user_id,settings_admin) VALUES (%s,%s,true) ON CONFLICT (auth_user_id) DO NOTHING',['IMS-Administration',admin.pk])
        query("INSERT INTO role_assignments(user_id,role) SELECT id,'READER' FROM users WHERE auth_user_id=%s ON CONFLICT DO NOTHING",[admin.pk])
        for code,name in [('IT','Informationstechnik'),('PROD','Produktion'),('HR','Personal'),('GF','Geschäftsführung')]:
            query('INSERT INTO departments(code,name) VALUES (%s,%s) ON CONFLICT (code) DO NOTHING',[code,name])
        self.stdout.write('Lokale Konten bereit: autor, pruefer, qmb_vertretung, freigabe, leser, admin.')

        if not query("SELECT 1 FROM audit_events WHERE action='DEV_QMB_TEAM' LIMIT 1"):
            if not query("SELECT 1 FROM users WHERE qmb_role<>'NONE'"):
                for username,profile in [('pruefer','PRIMARY'),('qmb_vertretung','DEPUTY')]:
                    query('UPDATE users SET qmb_role=%s WHERE auth_user_id=(SELECT id FROM auth_user WHERE username=%s)',[profile,username])
            query("INSERT INTO audit_events(action,object_type,object_id,reason) VALUES ('DEV_QMB_TEAM','settings','qmb','Lokales QMB-Demonstrationsteam eingerichtet')")

        # Seed only reference identifiers/labels, never copyrighted standard text.
        references = []
        for name,edition in [('ISO 9001','2015'),('ISO/IEC 27001','2022'),('ISO 50001','2018')]:
            call_command('add_standard_reference',name,edition,'7.5','Dokumentierte Information',stdout=self.stdout)
            references.append(query('SELECT r.id FROM standard_references r JOIN standards s ON s.id=r.standard_id WHERE s.name=%s AND s.edition=%s AND r.reference=%s',[name,edition,'7.5'])[0]['id'])
        from datetime import timedelta
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone
        from dms import services, storage
        department = query("SELECT id FROM departments WHERE code='IT'")[0]['id']
        people = {name:get_user_model().objects.get(username=name) for name in ['autor','pruefer','freigabe']}
        candidates = query('SELECT auth_user_id FROM users WHERE is_qmb(id) AND auth_user_id<>%s ORDER BY id',[people['autor'].pk])
        demo_qmb = get_user_model().objects.get(pk=candidates[0]['auth_user_id']) if candidates else None
        for number,title,publish in [('DEMO-001','Beispiel: Dokumentenlenkung',True),('DEMO-002','Beispiel: Arbeitsanweisung',False),('DEMO-003','Beispiel: IMS-Richtlinie',False),('DEMO-004','Beispiel: Offene Prüfaufgabe',False)]:
            if query('SELECT 1 FROM documents WHERE number=%s',[number]):
                continue
            vid = services.create_document(people['autor'],dict(number=number,title=title,document_type='Prozess',department=department,change_summary='Synthetisches Beispieldokument für den lokalen Funktionstest.',effective_from=timezone.now()-timedelta(days=1),next_review_on=timezone.localdate()-timedelta(days=1),standard_references=references,applicable_departments=[department]))
            storage.upload(people['autor'],vid,SimpleUploadedFile(number+'.txt',('DEMONSTRATION — keine betriebliche Vorgabe.\n'+title+'\nDieser Inhalt dient ausschließlich dem lokalen Funktionstest.').encode()))
            if number=='DEMO-004':
                services.transition(people['autor'],vid,'submit','Demonstration: offene Prüfaufgabe')
            if publish and demo_qmb:
                services.transition(people['autor'],vid,'submit','Lokaler Demonstrationsablauf')
                services.transition(demo_qmb,vid,'accept','Demonstration: fachliche Prüfung')
                services.transition(demo_qmb,vid,'accept','Demonstration: Freigabe')
        from dms import portal,evidence
        if demo_qmb and not query("SELECT 1 FROM documents WHERE number='DEMO-005'"):
            vid = services.create_document(people['autor'],dict(number='DEMO-005',title='Beispiel: Arbeitsanweisung im Mitarbeiterportal',document_type='Arbeitsanweisung',department=department,change_summary='Demonstration von PDF-Vorschau, QR-Code und Kenntnisnahme. Keine betriebliche Vorgabe.',effective_from=timezone.now()-timedelta(days=1),standard_references=references,applicable_departments=[department]))
            storage.upload(people['autor'],vid,SimpleUploadedFile('DEMO-005.txt','DEMONSTRATION — keine betriebliche Vorgabe.\nBeispiel einer Arbeitsanweisung\n1. Aktuelle Fassung im IMS öffnen.\n2. Anweisung lesen und Änderungen beachten.\n3. Bei Rückfragen den verantwortlichen Autor kontaktieren.\n4. Falls angefordert, diese Version zur Kenntnis nehmen.'.encode()))
            portal.save_distribution(people['autor'],vid,'SUBSTANTIAL',True,30,'Arbeitsplatz Einstieg Mitarbeiterportal Anleitung',[],'Synthetischer Portal-Funktionstest')
            services.transition(people['autor'],vid,'submit','Demonstration: QMB-Prüfung anfordern')
            services.transition(demo_qmb,vid,'accept','Demonstration: Inhalt und Lesefassung geprüft')
            services.transition(demo_qmb,vid,'accept','Demonstration: für den lokalen Test freigegeben')
        if demo_qmb and not query("SELECT 1 FROM evidence_records WHERE number='DEMO-N-001'"):
            category = query("SELECT id FROM document_categories WHERE name='Prozess'")[0]['id']
            evidence.create_record(people['autor'],dict(number='DEMO-N-001',title='Beispiel: Abgeschlossenes Prüfprotokoll',category_id=category,department_id=department,occurred_on=timezone.localdate(),retain_until=timezone.localdate()+timedelta(days=365),classification='INTERNAL',reason='Synthetischer Nachweis für den lokalen Funktionstest; keine betriebliche Prüfung.'),SimpleUploadedFile('DEMO-N-001.txt','DEMONSTRATION — synthetisches Prüfprotokoll.\nErgebnis: Funktionstest erfolgreich. Keine betriebliche Aussage.'.encode()))
        self.stdout.write('Synthetische Beispieldokumente, Portal-Aufgaben und Nachweis bereit.')
