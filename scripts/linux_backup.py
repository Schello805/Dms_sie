#!/usr/bin/env python3
"""Root-owned scheduled backup: read-only DB role plus protected restore secrets."""
import subprocess
import sys
from pathlib import Path
from install_linux import BASE, STATE, BACKUPS, write_private


def main():
    release = (BASE / 'current').resolve(strict=True)
    result = subprocess.run([sys.executable, str(release / 'manage.py'), 'backup_dms',
                             '--destination', str(BACKUPS)], cwd=release, text=True,
                            stdout=subprocess.PIPE, check=True)
    backup = Path(result.stdout.strip().splitlines()[-1]).resolve(strict=True)
    if not backup.is_relative_to(BACKUPS.resolve()) or not (backup / 'manifest.json').is_file():
        raise RuntimeError('Ungültiges Sicherungsziel.')
    write_private(backup / 'install.json', STATE.read_text())
    print(backup)


if __name__ == '__main__':
    main()
