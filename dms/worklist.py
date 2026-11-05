"""Shared QMB worklist and bell counts, including approaching review dates."""
from django.utils import timezone
from . import services as s
from .policies import is_qmb
from .simple_workflow import returned_tasks


def tasks_for(user):
    returned = returned_tasks(user)
    pending = s.workflow_tasks(user) if is_qmb(user) else []
    reviews = []
    lead_days = s.query('SELECT reminder_days FROM notification_settings WHERE id=1')[0]['reminder_days']
    if is_qmb(user):
        from datetime import timedelta
        uid = s.actor(user)
        today = timezone.localdate()
        reviews = s.query("""SELECT v.id,v.title,d.number,r.review_due_on,r.review_result,
            (r.review_due_on<=%s) AS review_overdue,(r.review_due_on-%s) AS days_left
            FROM document_versions v JOIN documents d ON d.id=v.document_id
            JOIN version_review_status r ON r.version_id=v.id
            WHERE v.id=current_release(d.id) AND v.status='APPROVED' AND v.created_by<>%s
              AND can_read_version(%s,v.id) AND (r.review_due_on<=%s OR r.review_result IN ('REVISION_REQUIRED','WITHDRAWAL_REQUIRED'))
            ORDER BY r.review_due_on NULLS LAST,d.number,v.id LIMIT 5000""",
            [today,today,uid,uid,today+timedelta(days=lead_days)])
    return {'returned':returned,'tasks':pending,'due':reviews,'lead_days':lead_days,
            'overdue_count':sum(bool(v['review_overdue']) for v in reviews),'review_count':len(reviews),'pending_count':len(pending),'returned_count':len(returned),'work_count':len(returned)+len(pending)+len(reviews)}
