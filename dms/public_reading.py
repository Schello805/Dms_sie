"""Anonymous access is limited to the current released version of active documents."""
from django.core.exceptions import PermissionDenied
from . import services as s

PUBLIC_RELEASE = "NOT (SELECT login_required FROM documents WHERE id=v.document_id) AND v.status='APPROVED' AND v.id=current_release(v.document_id)"


def get_read_version(user,version_id):
    if s.query('SELECT 1 FROM document_versions v WHERE v.id=%s AND '+PUBLIC_RELEASE,[version_id]):
        # Load the same metadata as authorized readers, without granting mutation rights.
        from .document_service import load_version
        actors=s.query('SELECT id FROM users WHERE auth_user_id=%s AND active',[user.pk]) if user.is_authenticated and user.is_active else []
        return actors[0]['id'] if actors else None,load_version(version_id)
    if not user.is_authenticated:
        raise PermissionDenied('Keine aktuelle freigegebene Lesefassung verfügbar.')
    return s.get_version(user,version_id)
