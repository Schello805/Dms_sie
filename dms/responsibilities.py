"""QMB reassignment, atomic across the entire selected batch."""
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from . import services as s
from .policies import require_qmb


@transaction.atomic
def transfer(user, previous, successor, documents, reason=''):
    actor = require_qmb(user)
    ids = sorted(set(documents))
    if not ids or len(ids)>5000 or previous==successor:
        raise ValidationError('Dokumente und einen anderen verantwortlichen Autor auswählen.')
    # Match workflow lock order: version, then document/advisory lock.
    s.query('SELECT id FROM document_versions WHERE document_id=ANY(%s::bigint[]) ORDER BY id FOR UPDATE', [ids])
    if len(s.query('SELECT id FROM documents WHERE id=ANY(%s::bigint[]) AND owner_id=%s', [ids,previous]))!=len(ids):
        raise ValidationError('Die Verantwortlichkeit hat sich geändert. Bitte die Liste neu laden.')
    try:
        with transaction.atomic():
            for target in ids:
                s.query('SELECT transfer_document_owner(%s,%s,%s,%s,%s)', [actor,target,previous,successor,s.optional_reason(reason)])
    except DatabaseError as error:
        if getattr(error.__cause__, 'sqlstate', None)=='P0001':
            raise ValidationError('Der neue Verantwortliche braucht ein aktives Autoren- oder QMB-Konto mit Berechtigung für alle ausgewählten Dokumente.') from error
        raise
    return len(ids)
