import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from dms.portal import synchronize_acknowledgements
class Command(BaseCommand):
    help = 'Kenntnisnahmen für alle aktiven Zielgruppen zuordnen, auch ohne Mitarbeiteranmeldung.'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        while True:
            close_old_connections()
            count = synchronize_acknowledgements()
            self.stdout.write(f'Neue Kenntnisnahme-Aufgaben: {count}')
            self.stdout.flush()
            if options['once']:
                return
            time.sleep(60)
