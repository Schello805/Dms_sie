#!/usr/bin/env python3
"""Install/update IMS-DMS from GitHub on a dedicated Debian/Ubuntu systemd host.

No third-party Python modules are required by the installer itself.
Run --help or --dry-run before installing. Secrets are never command arguments.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

BASE = Path('/opt/ims-dms')
CONFIG = Path('/etc/ims-dms')
STATE = CONFIG / 'install.json'
DATA = Path('/var/lib/ims-dms')
BACKUPS = Path('/var/backups/ims-dms')
SERVICES = ('ims-dms', 'ims-dms-index', 'ims-dms-notifications')
ROLES = ('owner', 'app', 'index', 'notify', 'backup')
MARKER = '# Managed by IMS-DMS install_linux.py'
APT_OPTIONS = ['-o', 'Acquire::Retries=2', '-o', 'Acquire::http::Timeout=20',
               '-o', 'Acquire::https::Timeout=20', '-o', 'APT::Update::Error-Mode=any']


def run(args, *, env=None, text=None, capture=False, cwd=None):
    return subprocess.run([str(a) for a in args], input=text, text=True, check=True,
                          env=env, cwd=cwd, stdout=subprocess.PIPE if capture else None)


def validate_repo(value):
    if not re.fullmatch(r'(https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', value):
        raise ValueError('Repository als https://github.com/OWNER/REPO oder git@github.com:OWNER/REPO angeben; keine Tokens in der URL.')
    return value


def validate_ref(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,199}', value) or '..' in value:
        raise ValueError('Ungültiger Branch, Tag oder Commit.')
    return value


def validate_host(value):
    if len(value) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in value.split('.')):
        raise ValueError('Host ohne http://, Port oder Pfad angeben (DNS-Name oder IPv4).')
    return value.lower()


def validate_port(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError('Port muss zwischen 1 und 65535 liegen.')
    return port


def write_private(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        with temporary.open('x') as file:
            temporary.chmod(0o600)
            file.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_state(state):
    write_private(STATE, json.dumps(state, indent=2) + '\n')


def environment(state, role):
    return {
        'DMS_SECRET_KEY': state['secret'], 'DMS_DEBUG': '0',
        'DMS_INTERNAL_HTTP': '1', 'DMS_ALLOWED_HOSTS': ','.join(state['hosts'] + ['localhost', '127.0.0.1']),
        'DMS_TRUST_PROXY': '1', 'DMS_DYNAMIC_HOSTS': '1', 'DMS_MEDIA_ROOT': str(DATA / 'files'),
        'DMS_HEALTH_DIR': str(DATA / 'health'), 'DMS_ERROR_LOG_DIR': str(DATA / 'logs'), 'PYTHONDONTWRITEBYTECODE': '1',
        'PGDATABASE': 'ims_dms', 'PGUSER': 'ims_dms_' + role,
        'PGPASSWORD': state['passwords'][role], 'PGHOST': '127.0.0.1', 'PGPORT': '5432',
    }


def manage(release, state, role, *arguments, capture=False):
    return run([release / '.venv/bin/python', release / 'manage.py', *arguments],
               env=dict(os.environ, **environment(state, role)), cwd=release, capture=capture)


def psql(text, database='postgres', capture=False):
    # Credentials are stdin-only; psql does not echo statements without -a/-e.
    return run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-q', '-A', '-t',
                '-h', '/var/run/postgresql', '-U', 'postgres', '-p', '5432',
                '-v', 'ON_ERROR_STOP=1', '-d', database], text=text, capture=capture,
               env={key: value for key,value in os.environ.items() if not key.startswith('PG')})


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def setup_database(state):
    for role in ROLES:
        name = 'ims_dms_' + role
        found = psql('SELECT 1 FROM pg_roles WHERE rolname=' + sql_literal(name), capture=True).stdout.strip()
        if not found:
            psql(f'CREATE ROLE {name} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {sql_literal(state["passwords"][role])};')
    owner = psql("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='ims_dms';", capture=True).stdout.strip()
    if not owner:
        psql("CREATE DATABASE ims_dms OWNER ims_dms_owner ENCODING 'UTF8' TEMPLATE template0;")
    elif owner != 'ims_dms_owner':
        raise RuntimeError('Vorhandene Datenbank besitzt einen anderen Eigentümer; keine Änderung vorgenommen.')


def apply_grants(release):
    for filename, variable, role in (
        ('runtime_grants.sql', 'runtime_role', 'app'),
        ('index_grants.sql', 'index_role', 'index'),
        ('notification_grants.sql', 'notification_role', 'notify'),
        ('backup_grants.sql', 'backup_role', 'backup'),
    ):
        text = (release / 'db' / filename).read_text()
        psql('\\set database_name ims_dms\n' + f'\\set {variable} ims_dms_{role}\n' + text, 'ims_dms')


def prepare_release(args, state):
    directory = BASE / 'releases' / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    directory.parent.mkdir(parents=True, exist_ok=True)
    BASE.chmod(0o755)
    directory.parent.chmod(0o755)
    if args.source_dir:
        source = args.source_dir.resolve()
        if source == BASE or BASE.is_relative_to(source):
            raise ValueError('Quellverzeichnis darf /opt/ims-dms nicht enthalten.')
        shutil.copytree(source, directory, ignore=shutil.ignore_patterns('.git', '.local', '.venv', '__pycache__', '*.pyc', '.env', 'media', 'staticfiles'))
    else:
        run(['git', 'clone', '--no-checkout', '--', state['repo'], directory])
        run(['git', '-C', directory, 'fetch', '--depth', '1', 'origin', state['ref']])
        run(['git', '-C', directory, 'checkout', '--detach', 'FETCH_HEAD'])
    for required in ('manage.py', 'requirements.lock.txt', 'db/runtime_grants.sql'):
        if not (directory / required).is_file():
            raise ValueError('Repository enthält kein vollständiges IMS-DMS: ' + required)
    run(['python3', '-m', 'venv', directory / '.venv'])
    run([directory / '.venv/bin/python', '-m', 'pip', 'install', '--disable-pip-version-check', '-r', directory / 'requirements.lock.txt'])
    # Runtime account can read code but cannot modify it. Venv paths remain stable.
    run(['chmod', '-R', 'u=rwX,go=rX', directory])
    return directory


def service_unit(command, env_name, container):
    hardening = '' if container else f'PrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths={DATA} {BACKUPS}\n'
    return f'''{MARKER}
[Unit]
Description=IMS-DMS {env_name}
After=network.target postgresql.service
[Service]
User=ims-dms
Group=ims-dms
WorkingDirectory={BASE}/current
EnvironmentFile={CONFIG}/{env_name}.env
ExecStart={BASE}/current/.venv/bin/{command}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
{hardening}
[Install]
WantedBy=multi-user.target
'''


def nginx_config(state):
    return f'''{MARKER}
limit_req_zone $binary_remote_addr zone=ims_dms_login:10m rate=120r/m;
server {{
    listen {state['port']} default_server;
    server_name {' '.join(state['hosts']) or '_'};
    client_max_body_size 30m;
    location = /login/ {{
        limit_req zone=ims_dms_login burst=100 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
    }}
    location / {{
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 60s;
    }}
}}
'''


def managed_file(path, content):
    path = Path(path)
    if path.exists() and MARKER not in path.read_text().splitlines()[:2]:
        raise RuntimeError(f'Fremde Konfiguration wird nicht überschrieben: {path}')
    path.write_text(content)
    path.chmod(0o644)


def configure_services(state, container):
    for name, role in (('web', 'app'), ('index', 'index'), ('notifications', 'notify'), ('backup', 'backup')):
        write_private(CONFIG / (name + '.env'), ''.join(f'{key}={value}\n' for key, value in environment(state, role).items()))
    for name, command, env_name in (
        ('ims-dms', 'gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60 --access-logfile - --error-logfile -', 'web'),
        ('ims-dms-index', 'python manage.py process_index', 'index'),
        ('ims-dms-notifications', 'python manage.py process_notifications', 'notifications'),
    ):
        managed_file('/etc/systemd/system/' + name + '.service', service_unit(command, env_name, container))
    unit = service_unit('python scripts/linux_backup.py', 'backup', container)
    # Root adds the private restore secrets; PostgreSQL still uses the SELECT-only backup role.
    unit = unit.replace('User=ims-dms\nGroup=ims-dms', 'User=root\nGroup=root')
    unit = unit.replace('Restart=on-failure\nRestartSec=5', 'Type=oneshot')
    managed_file('/etc/systemd/system/ims-dms-backup.service', unit)
    managed_file('/etc/systemd/system/ims-dms-backup.timer', f'''{MARKER}
[Unit]
Description=Daily IMS-DMS backup
[Timer]
OnCalendar=*-*-* 03:15:00 Europe/Berlin
Persistent=true
[Install]
WantedBy=timers.target
''')
    # A dedicated server's packaged welcome page would otherwise win for DHCP IPs.
    default = Path('/etc/nginx/sites-enabled/default')
    if state['port']==80 and default.exists():
        target = default.resolve()
        content = target.read_text()
        if not default.is_symlink() or target != Path('/etc/nginx/sites-available/default') or 'Default server configuration' not in content or 'server_name _;' not in content:
            raise RuntimeError('Vorhandenen benutzerdefinierten Nginx-Defaultserver zuerst prüfen; nicht überschrieben.')
        default.rename(CONFIG / 'nginx-packaged-default.saved')
    managed_file('/etc/nginx/conf.d/ims-dms.conf', nginx_config(state))
    run(['nginx', '-t'])
    run(['systemctl', 'daemon-reload'])


def health_check(state):
    request = urllib.request.Request(f'http://127.0.0.1:{state["port"]}/', headers={'Host': 'localhost'})
    for _ in range(30):
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200 and response.geturl() == request.full_url and '<h1>Dokumentenübersicht</h1>' in response.read().decode():
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('HTTP-Abnahme fehlgeschlagen. journalctl -u ims-dms und nginx -t prüfen.')


def install(args):
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise RuntimeError('Installation als root auf einem unterstützten Linux-Server ausführen; --dry-run funktioniert auch lokal.')
    os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    distro = (os_release.get('ID', '').strip('"'), os_release.get('VERSION_ID', '').strip('"'))
    if distro not in (('ubuntu', '24.04'), ('debian', '13')):
        raise RuntimeError('Unterstützt werden Ubuntu 24.04 LTS und Debian 13.')
    if not Path('/run/systemd/system').exists():
        raise RuntimeError('systemd als Init-System ist erforderlich; im LXC ausführen, nicht auf dem Proxmox-Host.')
    with Path('/run/lock/ims-dms-install.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _install_locked(args)


def configure_hosts(args, state):
    """Ask before making changes; unattended installs must opt out explicitly."""
    if state is not None or args.host or args.non_interactive:
        return
    if not sys.stdin.isatty():
        raise RuntimeError('Domain-Abfrage benötigt ein Terminal. --host dms.firma.de oder --non-interactive für reinen IP-Zugriff angeben.')
    print('Unter welchem Domainnamen soll das DMS erreichbar sein?')
    print('Bei Reverse Proxy dessen Domain angeben, z. B. dms.firma.de. Ohne https:// oder Pfad.')
    print('Mehrere Namen mit Komma trennen. Leer lassen: nur lokale IP / Serverhostname. Keine feste IP wird vergeben.')
    while True:
        try:
            answer = input('Domainname(n): ').strip()
        except EOFError:
            raise RuntimeError('Domain-Abfrage abgebrochen; keine Installation gestartet.') from None
        if not answer:
            args.host = []
            return
        try:
            hosts = [validate_host(value.strip().lower()) for value in answer.split(',')]
        except ValueError as error:
            print('Ungültige Eingabe: ' + str(error))
            continue
        args.host = list(dict.fromkeys(hosts))
        return


def _install_locked(args):
    exists = STATE.exists()
    if args.update and not exists:
        raise RuntimeError('Keine verwaltete Installation vorhanden.')
    state = json.loads(STATE.read_text()) if exists else None
    if state and state.get('complete') and not args.update:
        raise RuntimeError('Bereits installiert. Für Aktualisierung --update verwenden.')
    if exists and not args.update and ((args.repo and args.repo != state['repo']) or (args.host and args.host != state['hosts'])):
        raise RuntimeError('Abgebrochene Installation nur mit unveränderten Repository-/Host-Einstellungen fortsetzen.')
    if not exists:
        for path in (BASE, CONFIG, DATA):
            if path.exists() and any(path.iterdir()):
                raise RuntimeError(f'{path} ist bereits belegt; vorhandene Installation nicht überschrieben.')
    if not exists and not args.repo:
        raise ValueError('Neuinstallation benötigt --repo; --host ist optional.')
    configure_hosts(args, state)
    hosts = args.host if args.host is not None else (state['hosts'] if state else [])
    print('Zugelassene Domainnamen: ' + (', '.join(hosts) if hosts else 'keine zusätzlichen; lokale IP / Serverhostname'))
    print('1/7 Systempakete installieren', flush=True)
    run(['apt-get', *APT_OPTIONS, 'update'])
    run(['apt-get', *APT_OPTIONS, 'install', '-y', 'python3', 'python3-venv', 'python3-dev', 'build-essential', 'libffi-dev', 'libssl-dev', 'git', 'curl', 'ca-certificates', 'postgresql', 'postgresql-client', 'nginx', 'fonts-dejavu-core'], env=dict(os.environ, DEBIAN_FRONTEND='noninteractive'))
    run(['systemctl', 'enable', '--now', 'postgresql'])
    version = int(psql('SHOW server_version_num;', capture=True).stdout.strip())
    if version < 160000:
        raise RuntimeError('PostgreSQL >=16 erforderlich.')
    if state is None:
        occupied = psql("SELECT rolname FROM pg_roles WHERE rolname ~ '^ims_dms_' UNION ALL SELECT datname FROM pg_database WHERE datname='ims_dms';", capture=True).stdout.strip()
        if occupied:
            raise RuntimeError('Vorhandene IMS-Datenbank/Rollen ohne Installationsstatus gefunden. Manuell prüfen; keine Übernahme.')
        state = {'repo': args.repo, 'ref': args.ref or 'main', 'hosts': args.host or [], 'port': args.port or 80,
                 'admin_user': args.admin_user or 'admin', 'secret': secrets.token_urlsafe(64),
                 'passwords': {role: secrets.token_urlsafe(36) for role in ROLES}, 'complete': False}
        save_state(state)
    state['ref'] = args.ref or state['ref']
    if args.repo:
        state['repo'] = args.repo
    if args.host:
        state['hosts'] = args.host
    if args.port:
        state['port'] = args.port
    save_state(state)
    if subprocess.run(['id', 'ims-dms'], capture_output=True).returncode != 0:
        run(['useradd', '--system', '--home-dir', str(DATA), '--shell', '/usr/sbin/nologin', '--user-group', 'ims-dms'])

    for directory in (DATA, DATA / 'files', DATA / 'logs', DATA / 'health', BACKUPS):
        run(['install', '-d', '-o', 'ims-dms', '-g', 'ims-dms', '-m', '0700', directory])
    print('2/7 Quellstand und virtuelle Umgebung vorbereiten', flush=True)
    release = prepare_release(args, state)
    previous = (BASE / 'current').resolve() if (BASE / 'current').exists() else None
    print('3/7 Datenbank und Sicherung vorbereiten', flush=True)
    setup_database(state)
    stopped = False
    migrating = False
    try:
        if previous:
            run(['systemctl', 'stop', *SERVICES, 'ims-dms-backup.timer', 'ims-dms-backup.service'])
            stopped = True
            backup = manage(previous, state, 'backup', 'backup_dms', '--destination', str(BACKUPS), capture=True).stdout.strip().splitlines()[-1]
            write_private(Path(backup) / 'install.json', json.dumps(state, indent=2))
            state['last_backup'] = backup
            save_state(state)
            print('Update-Sicherung: ' + backup, flush=True)
        print('4/7 Migrationen und getrennte Datenbankrechte anwenden', flush=True)
        migrating = True
        manage(release, state, 'owner', 'migrate', '--noinput')
        apply_grants(release)
        if not state['complete']:
            for name, edition in [('ISO 9001','2015'), ('ISO/IEC 27001','2022'), ('ISO 50001','2018')]:
                manage(release, state, 'owner', 'add_standard_reference', name, edition, '7.5', 'Dokumentierte Information')
            password_file = CONFIG / 'initial-admin-password'
            if not password_file.exists():
                write_private(password_file, secrets.token_urlsafe(24) + '\n')
            manage(release, state, 'owner', 'bootstrap_admin', state['admin_user'], '--password-file', str(password_file))
        manage(release, state, 'app', 'check')
        print('5/7 systemd und internen HTTP-Zugang konfigurieren', flush=True)
        container = subprocess.run(['systemd-detect-virt', '--container'], capture_output=True, text=True).stdout.strip() == 'lxc'
        configure_services(state, container)
        link = BASE / ('current-' + uuid.uuid4().hex)
        link.symlink_to(release)
        link.replace(BASE / 'current')
        wrapper = Path('/usr/local/sbin/ims-dms-manage')
        managed_file(wrapper, '#!/bin/sh\n' + MARKER + f'\nexec /usr/bin/python3 {BASE}/current/scripts/linux_manage.py "$@"\n')
        wrapper.chmod(0o750)
        print('6/7 Dienste starten', flush=True)
        run(['systemctl', 'enable', '--now', *SERVICES, 'ims-dms-backup.timer', 'nginx'])
        run(['systemctl', 'restart', *SERVICES])
        run(['systemctl', 'reload', 'nginx'])
        print('7/7 HTTP-Funktionsprüfung', flush=True)
        health_check(state)
        state.update(complete=True, active_release=str(release))
        save_state(state)
    except Exception:
        if stopped and not migrating:
            run(['systemctl', 'start', *SERVICES, 'ims-dms-backup.timer'])
        elif migrating:
            subprocess.run(['systemctl', 'stop', *SERVICES], check=False)
            print('Installation/Update angehalten. Keine Daten gelöscht. Migrationen NICHT automatisch zurückrollen; Sicherung und systemd-Protokolle prüfen.', file=sys.stderr)
        raise
    port = '' if state['port'] == 80 else ':' + str(state['port'])
    address = state['hosts'][0] if state['hosts'] else 'SERVER-HOSTNAME-ODER-AKTUELLE-IP'
    print(f'Bereit: http://{address}{port}/\nAdmin: {state["admin_user"]}\nInitiales Passwort (nur root): {CONFIG}/initial-admin-password\nVerwaltung: sudo ims-dms-manage <Django-Kommando>')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--repo', type=validate_repo)
    result.add_argument('--ref', type=validate_ref, help='Branch, Tag oder Commit (Standard: main bzw. bisheriger Ref)')
    result.add_argument('--host', action='append', type=validate_host, help='Optionaler zusätzlicher DNS-Name; IP/DHCP wird nicht festgelegt')
    result.add_argument('--non-interactive', action='store_true', help='Keine Domain-Abfrage; ohne --host nur IP/Serverhostname (für automatisierte Installation)')
    result.add_argument('--port', type=validate_port, metavar='1..65535')
    result.add_argument('--admin-user', help='Initialer IT-Administrator (Standard: admin)')
    result.add_argument('--update', action='store_true')
    result.add_argument('--source-dir', type=Path, help='Lokale vertrauenswürdige Quellen statt Git-Download (für CI/Offline-Kopie)')
    result.add_argument('--dry-run', action='store_true', help='Nur Ablauf anzeigen, keine Zugriffe/Änderungen')
    return result


def main():
    args = parser().parse_args()
    if args.admin_user and not re.fullmatch(r'[A-Za-z0-9_.@+-]{1,150}', args.admin_user):
        raise ValueError('Ungültiger Admin-Benutzername.')
    if args.dry_run:
        print(json.dumps({'mode': 'update' if args.update else 'install', 'repo': args.repo, 'ref': args.ref,
                          'hosts': args.host, 'port': args.port or 80,
                          'steps': ['apt', 'release + venv', 'database + backup', 'migrate + grants', 'systemd + nginx', 'services', 'HTTP health check']}, indent=2))
        return
    install(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print('Abgebrochen: ' + str(exc), file=sys.stderr)
        sys.exit(1)
