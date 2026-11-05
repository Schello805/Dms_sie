import getpass
import json
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from dms.services import query

class Command(BaseCommand):
    help = 'Administrative Gruppenverwaltung; benötigt Eigentümerzugang. Keine Änderungen über die Web-Laufzeitrolle.'
    def add_arguments(self,parser):
        parser.add_argument('action',choices=['list','create','enable','disable','add-member','remove-member','grant','revoke'])
        parser.add_argument('name',nargs='?')
        parser.add_argument('--user',help='Lokaler Benutzername')
        parser.add_argument('--role',choices=['READER','AUTHOR','REVIEWER','ADMIN'])
        scope = parser.add_mutually_exclusive_group()
        scope.add_argument('--department',help='Abteilungskürzel oder * für unternehmensweit')
        scope.add_argument('--document',help='Dokumentnummer')
        parser.add_argument('--reason')

    @transaction.atomic
    def handle(self,*args,**options):
        action = options['action']
        if action=='list':
            rows = query('SELECT id,name,active FROM dms_groups ORDER BY name')
            for row in rows:
                self.stdout.write(f"{row['name']} · {'aktiv' if row['active'] else 'deaktiviert'}")
            return
        if not options['name'] or not (options['reason'] or '').strip():
            raise CommandError('Gruppenname und --reason sind für jede Änderung erforderlich.')
        if action=='create':
            query('INSERT INTO dms_groups(name) VALUES (%s) ON CONFLICT DO NOTHING',[options['name']])
        rows = query('SELECT id FROM dms_groups WHERE name=%s FOR UPDATE',[options['name']])
        if not rows:
            raise CommandError('Gruppe nicht vorhanden.')
        gid = rows[0]['id']
        details = {'operator':getpass.getuser(),'group':options['name'],'action':action}
        if action in ('enable','disable'):
            query('UPDATE dms_groups SET active=%s WHERE id=%s',[action=='enable',gid])
        elif action in ('add-member','remove-member'):
            people = query('SELECT u.id,a.id AS auth_id,a.username,a.email FROM auth_user a LEFT JOIN users u ON u.auth_user_id=a.id WHERE a.username=%s',[options['user']])
            if not people:
                raise CommandError('Lokales Benutzerkonto nicht vorhanden; zuerst create_dms_user verwenden.')
            person = people[0]
            uid = person['id']
            if uid is None:
                if action=='remove-member':
                    raise CommandError('Benutzer besitzt noch keine DMS-Zuordnung.')
                uid = query('INSERT INTO users(display_name,email,auth_user_id) VALUES (%s,%s,%s) RETURNING id',[person['username'],person['email'],person['auth_id']])[0]['id']
            if action=='add-member':
                query('INSERT INTO group_memberships(group_id,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING',[gid,uid])
            else:
                query('DELETE FROM group_memberships WHERE group_id=%s AND user_id=%s',[gid,uid])
            details.update(user_id=uid)
        elif action in ('grant','revoke'):
            if not options['role'] or not (options['department'] or options['document']):
                raise CommandError('--role und entweder --department oder --document sind erforderlich.')
            department = document = None
            if options['document']:
                rows = query('SELECT id FROM documents WHERE number=%s',[options['document']])
                if not rows:
                    raise CommandError('Dokument nicht vorhanden.')
                document = rows[0]['id']
            elif options['department']!='*':
                rows = query('SELECT id FROM departments WHERE code=%s',[options['department']])
                if not rows:
                    raise CommandError('Abteilung nicht vorhanden.')
                department = rows[0]['id']
            if action=='grant':
                query('INSERT INTO role_assignments(group_id,role,department_id,document_id) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',[gid,options['role'],department,document])
            else:
                query('DELETE FROM role_assignments WHERE group_id=%s AND role=%s AND department_id IS NOT DISTINCT FROM %s AND document_id IS NOT DISTINCT FROM %s',[gid,options['role'],department,document])
            details.update(role=options['role'],department_id=department,document_id=document)
        query("INSERT INTO audit_events(action,object_type,object_id,reason,details) VALUES ('GROUP_ADMIN','group',%s,%s,%s::jsonb)",[str(gid),options['reason'],json.dumps(details)])
        self.stdout.write(self.style.SUCCESS('Gruppenänderung gespeichert und protokolliert.'))
