import getpass
import json
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from dms.services import query

class Command(BaseCommand):
    help = 'Administrativ das Recht zur Pflege der Kategorie-Gültigkeiten vergeben oder entziehen.'
    def add_arguments(self,parser):
        parser.add_argument('username')
        parser.add_argument('--revoke',action='store_true')
        parser.add_argument('--reason',required=True)
    @transaction.atomic
    def handle(self,*args,**options):
        if not options['reason'].strip():
            raise CommandError('Begründung erforderlich.')
        users = query('SELECT id,username FROM auth_user WHERE username=%s',[options['username']])
        if not users:
            raise CommandError('Benutzerkonto ist nicht vorhanden.')
        person = users[0]
        rows = query('INSERT INTO users(display_name,auth_user_id,settings_admin) VALUES (%s,%s,%s) ON CONFLICT (auth_user_id) DO UPDATE SET settings_admin=EXCLUDED.settings_admin RETURNING id',[person['username'],person['id'],not options['revoke']])
        query("INSERT INTO audit_events(action,object_type,object_id,reason,details) VALUES ('SETTINGS_ADMIN','user',%s,%s,%s::jsonb)",[str(rows[0]['id']),options['reason'],json.dumps({'operator':getpass.getuser(),'enabled':not options['revoke']})])
        self.stdout.write('Administrationsrecht aktualisiert und protokolliert.')
