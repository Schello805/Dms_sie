"""Read-only diagnostics with an explicit allowlist; no environment dump."""
import os
import platform
import shutil
from pathlib import Path
import django
from django.conf import settings
from django.db import connection,DatabaseError,transaction
from django.utils import timezone
from . import services as s
from .system_logs import STARTED_AT
from .version import APP_NAME,APP_VERSION


def _number(path):
    try:
        value = Path(path).read_text().strip()
        return int(value) if value.isdigit() else None
    except OSError:
        return None


def snapshot():
    root = Path(settings.MEDIA_ROOT)
    disk = shutil.disk_usage(root if root.exists() else root.parent)
    db_version = 'Nicht verfügbar'
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SHOW server_version')
                db_version = cursor.fetchone()[0]
    except DatabaseError:
        pass
    counts = s.query('''SELECT (SELECT count(*) FROM documents) AS documents,
        (SELECT count(*) FROM document_versions) AS versions,
        (SELECT count(*) FROM users WHERE active) AS users,
        (SELECT count(*) FROM evidence_records) AS records''')[0]
    indexing = s.query("SELECT status,count(*) AS count FROM file_text_indexes GROUP BY status ORDER BY status")
    mail = s.query("SELECT status,count(*) AS count FROM review_notifications GROUP BY status ORDER BY status")
    migrations = s.query("SELECT name FROM django_migrations WHERE app='dms' ORDER BY id DESC LIMIT 1")
    pending_ack = s.query('''SELECT count(*) AS count FROM acknowledgement_assignments a JOIN document_versions v ON v.id=a.version_id
        WHERE NOT EXISTS(SELECT 1 FROM acknowledgement_receipts r WHERE r.assignment_id=a.id)
        AND v.id=current_release(v.document_id) AND (v.valid_until IS NULL OR v.valid_until>now())''')[0]['count']
    log_root = Path(settings.ERROR_LOG_DIR)
    parent = log_root if log_root.exists() else log_root.parent
    return {'app_name':APP_NAME,'app_version':APP_VERSION,'python':platform.python_version(),
        'django':django.get_version(),'postgres':db_version,'system':platform.system(),'release':platform.release(),
        'machine':platform.machine(),'hostname':platform.node(),'pid':os.getpid(),'cpus':os.cpu_count(),
        'started_at':STARTED_AT,'now':timezone.now(),'timezone':settings.TIME_ZONE,
        'database':settings.DATABASES['default']['NAME'],'db_host':settings.DATABASES['default']['HOST'],
        'db_port':settings.DATABASES['default']['PORT'],'db_role':settings.DATABASES['default']['USER'],
        'debug':settings.DEBUG,'internal_http':settings.INTERNAL_HTTP,
        'media_root':str(root),'media_writable':root.is_dir() and os.access(root,os.W_OK),
        'disk_total':disk.total,'disk_free':disk.free,
        'memory_limit':_number('/sys/fs/cgroup/memory.max'),'memory_used':_number('/sys/fs/cgroup/memory.current'),
        'log_root':str(log_root),'log_writable':os.access(parent,os.W_OK),'counts':counts,
        'migration':migrations[0]['name'] if migrations else '—','indexing':indexing,'mail':mail,'pending_ack':pending_ack,
        'mail_enabled':s.query('SELECT enabled FROM notification_settings WHERE id=1')[0]['enabled']}
