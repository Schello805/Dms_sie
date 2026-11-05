import time
from django.core.management.base import BaseCommand,CommandError
from django.db import close_old_connections
from dms.notifications import queue_due,dispatch_one

class Command(BaseCommand):
    help = 'Fällige Review-E-Mails vormerken und über die gespeicherten SMTP-Einstellungen versenden.'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
        parser.add_argument('--limit',type=int,default=100)
        parser.add_argument('--poll-seconds',type=float,default=60)
    def handle(self,*args,**options):
        if options['limit']<1 or not 1<=options['poll_seconds']<=3600:
            raise CommandError('Positives Limit und Abfrageintervall zwischen 1 und 3600 Sekunden erforderlich.')
        total = 0
        try:
            while True:
                close_old_connections()
                queue_due()
                for _ in range(options['limit']):
                    if not dispatch_one():
                        break
                    total += 1
                if options['once']:
                    break
                time.sleep(options['poll_seconds'])
        except KeyboardInterrupt:
            pass
        self.stdout.write(f'{total} Versandvorgänge bearbeitet.')
