"""QMB document register for audit preparation; CSV values cannot become formulas."""
import csv
from django.http import HttpResponse
from django.utils import timezone
from . import services as s
from .policies import require_qmb


def document_register(user, number=''):
    actor = require_qmb(user)
    rows = s.query('''SELECT d.id,d.number,coalesce(c.display_name,c.name) AS kind,dep.name AS department,
        u.display_name AS owner,d.active,d.login_required,v.title,v.major,v.minor,v.status,
        v.approved_at,v.approver,r.last_review_on,r.review_due_on,r.review_result,
        (SELECT '/d/'||kind_slug||'/'||number_slug||'/' FROM document_links WHERE document_id=d.id) AS stable_path,
        (SELECT e.reason FROM audit_events e WHERE (e.object_type='document' AND e.object_id=d.id::text)
            OR (e.object_type='version' AND EXISTS(SELECT 1 FROM document_versions av WHERE av.id::text=e.object_id AND av.document_id=d.id))
            ORDER BY e.id DESC LIMIT 1) AS last_event
        FROM documents d JOIN document_categories c ON c.name=d.document_type
        JOIN departments dep ON dep.id=d.responsible_department_id JOIN users u ON u.id=d.owner_id
        JOIN LATERAL (SELECT dv.*,ad.decided_at AS approved_at,ap.display_name AS approver FROM document_versions dv
            LEFT JOIN LATERAL (SELECT decided_at,actor_id FROM approval_decisions WHERE version_id=dv.id AND stage='APPROVAL' AND decision='ACCEPT' ORDER BY id DESC LIMIT 1) ad ON true
            LEFT JOIN users ap ON ap.id=ad.actor_id WHERE dv.document_id=d.id
            ORDER BY (dv.id=current_release(d.id)) DESC NULLS LAST,dv.major DESC,dv.minor DESC LIMIT 1) v ON true
        JOIN version_review_status r ON r.version_id=v.id
        WHERE (%s='' OR EXISTS(SELECT 1 FROM document_number_registry n WHERE n.document_id=d.id AND lower(n.number)=lower(%s)))
        ORDER BY lower(d.number),d.id''', [number,number])
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="ims-dokumentenregister.csv"'
    response.write('\ufeff')
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Dokumentnummer','Titel','Dokumentenart','Abteilung','Verantwortlich','Version','Status','Aktiv','Anmeldung erforderlich','Freigabe am','Freigegeben durch','Letztes Review','Review fällig','Review-Ergebnis','Dauerhafter Link','Letzter Protokollvermerk'])
    for row in rows:
        values = [row['number'],row['title'],row['kind'],row['department'],row['owner'],f"{row['major']}.{row['minor']}",row['status'],'Ja' if row['active'] else 'Nein','Ja' if row['login_required'] else 'Nein',timezone.localdate(row['approved_at']).isoformat() if row['approved_at'] else '',row['approver'],row['last_review_on'],row['review_due_on'],row['review_result'],row['stable_path'],row['last_event']]
        writer.writerow([("'"+str(v)) if str(v or '').lstrip().startswith(('=','+','-','@')) else str(v if v is not None else '') for v in values])
    s.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'EXPORT_DOCUMENT_REGISTER','settings','audit','Dokumentenregister exportiert',jsonb_build_object('documents',%s))",[actor,len(rows)])
    return response
