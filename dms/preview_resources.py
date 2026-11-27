"""One PDF renderer per document store, with a conservative container memory budget."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError

MIB = 1024 * 1024


def memory_budget():
    budget = 256 * MIB
    for limit_path, current_path in (
        ('/sys/fs/cgroup/memory.max','/sys/fs/cgroup/memory.current'),
        ('/sys/fs/cgroup/memory/memory.limit_in_bytes','/sys/fs/cgroup/memory/memory.usage_in_bytes'),
    ):
        try:
            limit = int(Path(limit_path).read_text().strip())
            used = int(Path(current_path).read_text().strip())
        except (OSError, ValueError):
            continue
        if 0<limit<2**60:
            budget = min(budget, max(0,limit-used-64*MIB))
    if budget<128*MIB:
        raise ValidationError('Für die PDF-Lesefassung ist gerade zu wenig Speicher frei. Bitte das Original herunterladen oder später erneut versuchen.', code='PDF_MEMORY')
    return budget


@contextmanager
def render_slot():
    # Persistent inode, shared across Gunicorn workers; never unlink an active lock.
    settings.MEDIA_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd = os.open(settings.MEDIA_ROOT/'.pdf-render.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValidationError('Eine PDF-Lesefassung wird gerade erstellt. Bitte kurz warten oder das Original herunterladen.', code='PDF_BUSY') from error
        yield memory_budget()
    finally:
        os.close(fd)
