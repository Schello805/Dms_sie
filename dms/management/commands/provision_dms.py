from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from dms.services import query

class Command(BaseCommand):
    help = 'Vorhandenes lokales Konto einer DMS-Rolle zuordnen (administrativer CLI-Zugriff).'
    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--role', required=True, choices=['READER','AUTHOR','QMB','ADMIN'])
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument('--department',help='Abteilungskürzel; * für unternehmensweiten Zugriff')
        scope.add_argument('--document',help='Dokumentnummer für eine dokumentbezogene Rolle')
        parser.add_argument('--department-name')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options['username'])
        except get_user_model().DoesNotExist:
            raise CommandError('Zuerst Benutzer über create_dms_user anlegen.')
        rows = query('''INSERT INTO users(display_name,email,auth_user_id) VALUES (%s,%s,%s)
            ON CONFLICT (auth_user_id) DO UPDATE SET display_name=EXCLUDED.display_name,email=EXCLUDED.email RETURNING id''', [user.get_full_name() or user.username,user.email,user.pk])
        uid = rows[0]['id']
        query("INSERT INTO role_assignments(user_id,role) VALUES (%s,'READER') ON CONFLICT DO NOTHING",[uid])
        department = document = None
        if options.get('document'):
            docs = query('SELECT id FROM documents WHERE number=%s',[options['document']])
            if not docs:
                raise CommandError('Dokument nicht vorhanden.')
            document = docs[0]['id']
        elif options['department'] != '*':
            department = query('''INSERT INTO departments(code,name) VALUES (%s,%s)
                ON CONFLICT (code) DO UPDATE SET code=EXCLUDED.code RETURNING id''', [options['department'],options['department_name'] or options['department']])[0]['id']
        if options['role']=='QMB':
            if department or document:
                raise CommandError('QMB wird als unternehmensweite Personenberechtigung zugeordnet.')
            query("UPDATE users SET qmb_role='PRIMARY' WHERE id=%s",[uid])
        else:
            query('INSERT INTO role_assignments(user_id,role,department_id,document_id) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING', [uid,options['role'],department,document])
        query("INSERT INTO audit_events(action,object_type,object_id,reason,details) VALUES ('PROVISION','user',%s,'Administrative CLI-Zuordnung',%s::jsonb)", [str(uid), __import__('json').dumps({'role':options['role'],'department':department,'document_id':document})])
        self.stdout.write(self.style.SUCCESS('DMS-Rolle zugeordnet. Django-Superuser allein erhalten keinen Dokumentzugriff.'))
