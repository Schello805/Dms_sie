"""Compare only versions independently accessible to the current account."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from . import services as s


@login_required
def compare(request,version_id):
    uid,current=s.get_version(request.user,version_id)
    if not any(s.allowed(uid,current['responsible_department_id'],role,current['document_id']) for role in ('AUTHOR','REVIEWER')):
        raise PermissionDenied('Versionsvergleich erfordert eine fachliche Dokumentenberechtigung.')
    previous=s.query('''SELECT id FROM document_versions WHERE document_id=%s AND (major,minor)<(%s,%s)
        AND can_read_version(%s,id) ORDER BY major DESC,minor DESC LIMIT 1''',[current['document_id'],current['major'],current['minor'],uid])
    before=s.get_version(request.user,previous[0]['id'])[1] if previous else None
    changes=[]
    if before:
        for key,label in [('title','Titel'),('change_summary','Änderungsbeschreibung'),('classification','Klassifizierung'),('effective_from','Wirksam ab')]:
            if before[key]!=current[key]:
                changes.append({'label':label,'before':before[key],'after':current[key]})
        for query,label in [
            ("SELECT f.original_name,f.sha256,vf.purpose FROM version_files vf JOIN file_objects f ON f.id=vf.file_id WHERE vf.version_id=%s ORDER BY f.original_name,f.sha256,vf.purpose",'Dateien (Name, SHA-256 und Verwendung)'),
            ("SELECT sr.reference,s.name,s.edition FROM version_standard_links vl JOIN standard_references sr ON sr.id=vl.reference_id JOIN standards s ON s.id=sr.standard_id WHERE vl.version_id=%s ORDER BY s.name,s.edition,sr.reference",'Normzuordnungen'),
            ("SELECT d.name FROM version_departments vd JOIN departments d ON d.id=vd.department_id WHERE vd.version_id=%s ORDER BY d.name",'Geltungsbereich'),
        ]:
            old=s.query(query,[before['id']]);new=s.query(query,[current['id']])
            if old!=new:
                changes.append({'label':label,'before':'\n'.join(' · '.join(str(v) for v in row.values()) for row in old) or '—','after':'\n'.join(' · '.join(str(v) for v in row.values()) for row in new) or '—'})
    s.audit(uid,'COMPARE_VERSIONS',version_id,'Metadaten und Dateiprüfsummen verglichen')
    return render(request,'dms/compare.html',{'v':current,'before':before,'changes':changes})
