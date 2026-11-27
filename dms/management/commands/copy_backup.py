from django.core.management.base import BaseCommand, CommandError
from dms.backup_copy import copy_backup


class Command(BaseCommand):
    help = 'Geprüftes Sicherungspaket atomar auf ein getrenntes eingehängtes Ziel kopieren.'

    def add_arguments(self, parser):
        parser.add_argument('backup')
        parser.add_argument('--destination', required=True)

    def handle(self, *args, **options):
        try:
            result = copy_backup(options['backup'],options['destination'])
        except (ValueError,OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(result))
