import time
from django.core.management.base import BaseCommand,CommandError
from django.db import close_old_connections
from dms.indexing import process_one

class Command(BaseCommand):
    help = 'Lokale PostgreSQL-Indexwarteschlange verarbeiten.'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true',help='Bis zum Limit verarbeiten, dann beenden')
        parser.add_argument('--limit',type=int,default=100)
        parser.add_argument('--poll-seconds',type=float,default=3)
    def handle(self,*args,**options):
        if options['limit']<1 or not 0.5<=options['poll_seconds']<=30:
            raise CommandError('Limit muss positiv sein; Abfrageintervall 0,5 bis 30 Sekunden.')
        processed = 0
        try:
            while True:
                close_old_connections()
                if process_one():
                    processed += 1
                    if options['once'] and processed>=options['limit']:
                        break
                elif options['once']:
                    break
                else:
                    time.sleep(options['poll_seconds'])
        except KeyboardInterrupt:
            pass
        self.stdout.write(f'{processed} Indexaufträge verarbeitet.')
