from django.core.management.base import BaseCommand
from django.db import transaction
from dms.services import query

class Command(BaseCommand):
    help = 'Administrativ eine Normausgabe und Referenz aus geprüften Stammdaten ergänzen.'
    def add_arguments(self,parser):
        for name in ['name','edition','reference','label']:
            parser.add_argument(name)
    @transaction.atomic
    def handle(self,*args,**options):
        standard = query('''INSERT INTO standards(name,edition) VALUES (%s,%s)
            ON CONFLICT (name,edition) DO UPDATE SET name=EXCLUDED.name RETURNING id''',[options['name'],options['edition']])[0]['id']
        reference = query('''INSERT INTO standard_references(standard_id,reference,label) VALUES (%s,%s,%s)
            ON CONFLICT (standard_id,reference) DO NOTHING RETURNING id''',[standard,options['reference'],options['label']])
        if reference:
            import json
            query("INSERT INTO audit_events(action,object_type,object_id,reason,details) VALUES ('ADD_REFERENCE','standard_reference',%s,'Administrative Ergänzung geprüfter Stammdaten',%s::jsonb)",[str(reference[0]['id']),json.dumps({key:options[key] for key in ['name','edition','reference','label']})])
        self.stdout.write('Normreferenz vorhanden. Bestehende Referenztexte werden nicht überschrieben.')
