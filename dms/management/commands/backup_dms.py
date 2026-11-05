from django.core.management.base import BaseCommand,CommandError
from dms.backup import create_backup,verify_backup

class Command(BaseCommand):
    help = 'Konsistente Datenbank-/Dateisicherung erstellen oder ein vorhandenes Paket prüfen. Nur administrativ aufrufen.'
    def add_arguments(self,parser):
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument('--destination',help='Verzeichnis für eine neue Sicherung')
        action.add_argument('--verify',help='Vorhandenes Sicherungspaket prüfen')
        parser.add_argument('--pg-bin',help='Verzeichnis mit pg_dump und pg_restore')
    def handle(self,*args,**options):
        try:
            if options['verify']:
                manifest = verify_backup(options['verify'],options['pg_bin'])
                self.stdout.write(self.style.SUCCESS(f"Manifest, Dumpstruktur und {len(manifest['files'])} Dateien erfolgreich geprüft."))
            else:
                result = create_backup(options['destination'],options['pg_bin'])
                self.stdout.write(self.style.SUCCESS(str(result)))
        except (OSError,ValueError,KeyError) as exc:
            raise CommandError(f'Sicherung unvollständig oder nicht lesbar: {type(exc).__name__}') from exc
