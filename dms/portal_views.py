import io
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import FileResponse,HttpResponse
from django.shortcuts import redirect,render
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.utils import timezone
from . import services as s,portal,evidence
from .policies import is_qmb,is_settings_admin,require_qmb,require_settings_admin
from .portal_forms import DistributionForm,AudienceForm,WorkplaceForm,EvidenceForm,RetentionForm,AuditFilterForm

def home(request):
    from .catalog_views import index
    return index(request)

@login_required
def read_current(request,document_id):
    vid = portal.current_version(request.user,document_id)
    if getattr(request,'reader_only',False):
        from .simple_workflow import open_reading_copy
        return open_reading_copy(request,vid)
    uid,v = s.get_version(request.user,vid)
    s.audit(uid,'READ_CURRENT',vid,'Aktuelle freigegebene Fassung im Mitarbeiterportal geöffnet')
    files = s.query('''SELECT f.id,f.original_name,vf.purpose FROM file_objects f JOIN version_files vf ON vf.file_id=f.id
        WHERE vf.version_id=%s ORDER BY CASE vf.purpose WHEN 'RELEASE' THEN 0 ELSE 1 END,f.id''',[vid])
    for file in files:
        file['previewable'] = Path(file['original_name']).suffix.lower() in ('.pdf','.txt')
    distribution = s.query('SELECT * FROM version_distribution WHERE version_id=%s',[vid])
    assignments = portal.pending_acknowledgements(request.user)
    assignment = next((a for a in assignments if a['version_id']==vid),None)
    bookmarked = bool(s.query('SELECT 1 FROM document_bookmarks WHERE user_id=%s AND document_id=%s',[uid,document_id]))
    return render(request,'dms/reading.html',{'v':v,'files':files,'assignment':assignment,'bookmarked':bookmarked,
        'distribution':distribution[0] if distribution else None,'stable_url':request.build_absolute_uri()})

@login_required
def document_qr(request,document_id):
    portal.current_version(request.user,document_id)
    import qrcode
    from qrcode.image.svg import SvgPathImage
    from django.urls import reverse
    url = request.build_absolute_uri(reverse('read_current',args=[document_id]))
    stream = io.BytesIO()
    qrcode.make(url,image_factory=SvgPathImage).save(stream)
    return HttpResponse(stream.getvalue(),content_type='image/svg+xml')

@login_required
@xframe_options_sameorigin
def preview_pdf(request,version_id,file_id):
    from .previews import reading_pdf
    from django.urls import reverse
    _,v = s.get_version(request.user,version_id)
    url = request.build_absolute_uri(reverse('read_current',args=[v['document_id']]))
    try:
        filename,content = reading_pdf(request.user,version_id,file_id,url)
    except ValidationError as exc:
        return HttpResponse(' '.join(exc.messages),status=409,content_type='text/plain; charset=utf-8')
    response = FileResponse(io.BytesIO(content),as_attachment=request.GET.get('download')=='1',filename=filename,content_type='application/pdf')
    response['Content-Security-Policy'] = "frame-ancestors 'self'; object-src 'self'"
    return response

@login_required
@require_POST
def toggle_bookmark(request,document_id):
    portal.bookmark(request.user,document_id)
    return redirect('read_current',document_id=document_id)

@login_required
@require_POST
def acknowledge(request,assignment_id):
    try:
        portal.acknowledge(request.user,assignment_id,request.POST.get('confirmed')=='on')
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    else:
        messages.success(request,'Kenntnisnahme für diese Version gespeichert.')
    return redirect('home')

@login_required
def distribution(request,version_id):
    uid,v = s.get_version(request.user,version_id)
    s.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status']!='DRAFT':
        raise PermissionDenied('Verteilung nur im Entwurf ändern.')
    existing = s.query('SELECT * FROM version_distribution WHERE version_id=%s',[version_id])
    initial = existing[0] if existing else {'ack_days':30,'change_kind':'SUBSTANTIAL'}
    initial['audiences'] = [r['audience_id'] for r in s.query('SELECT audience_id FROM version_audiences WHERE version_id=%s',[version_id])]
    form = DistributionForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:
            portal.save_distribution(request.user,version_id,**form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Zielgruppen und Änderungsinformation gespeichert; werden mit dieser Version freigegeben.')
            return redirect('detail',version_id=version_id)
    return render(request,'dms/simple_form.html',{'title':f"Zielgruppen und Kenntnisnahme · {v['number']}",'form':form})

@login_required
def management_entry(request):
    if is_qmb(request.user):
        return redirect('admin_settings')
    require_settings_admin(request.user)
    people = s.query("SELECT display_name,qmb_role FROM users WHERE is_qmb(id) ORDER BY qmb_role")
    return render(request,'dms/management_access.html',{'qmb_people':people})

@login_required
def audiences(request):
    require_qmb(request.user)
    form = AudienceForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            portal.create_audience(request.user,**form.cleaned_data)
        except (ValidationError,IntegrityError):
            form.add_error(None,'Zielgruppe konnte nicht angelegt werden; Name bereits vorhanden oder Angaben ungültig.')
        else:
            return redirect('audiences')
    rows = s.query('SELECT g.*,count(m.user_id) AS members FROM audience_groups g LEFT JOIN audience_memberships m ON m.audience_id=g.id GROUP BY g.id ORDER BY g.name')
    return render(request,'dms/audiences.html',{'form':form,'groups':rows})

@login_required
def workplaces(request):
    require_settings_admin(request.user)
    initial = {}
    target = request.GET.get('user','')
    if target.isdigit():
        existing = s.query('SELECT * FROM user_workplaces WHERE user_id=%s',[int(target)])
        if existing:
            initial = dict(existing[0],department=existing[0]['department_id'])
        initial['user_id'] = int(target)
        initial['audiences'] = [g['audience_id'] for g in s.query('SELECT audience_id FROM audience_memberships WHERE user_id=%s',[int(target)])]
    form = WorkplaceForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:
            portal.save_workplace(request.user,**form.cleaned_data)
            portal.synchronize_acknowledgements()
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Arbeitsplatz und Zielgruppen gespeichert. Zugriffsrollen bleiben unverändert.')
            return redirect('workplaces')
    rows = s.query('SELECT u.id,u.display_name,p.site,p.activity,d.name AS department FROM users u LEFT JOIN user_workplaces p ON p.user_id=u.id LEFT JOIN departments d ON d.id=p.department_id ORDER BY u.display_name')
    return render(request,'dms/workplaces.html',{'form':form,'people':rows})

@login_required
def records(request):
    return render(request,'dms/evidence_list.html',{'records':evidence.records(request.user,request.GET.get('q','')[:200])})

@login_required
def new_record(request):
    form = EvidenceForm(request.POST or None,request.FILES or None,user=request.user)
    if request.method=='POST' and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            uploaded = data.pop('file')
            rid = evidence.create_record(request.user,data,uploaded)
        except (ValidationError,IntegrityError) as exc:
            form.add_error(None,' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Nachweisnummer bereits vergeben oder Stammdaten ungültig.')
        else:
            return redirect('record_detail',record_id=rid)
    return render(request,'dms/simple_form.html',{'title':'Nachweis erfassen','form':form,'multipart':True})

@login_required
def record_detail(request,record_id):
    _,record = evidence.get_record(request.user,record_id)
    form = RetentionForm(request.POST or None,initial={'retain_until':record['retention_due'],'legal_hold':record['legal_hold']})
    if request.method=='POST':
        require_qmb(request.user)
        if request.POST.get('action')=='disposal':
            try:
                evidence.request_disposal(request.user,record_id,request.POST.get('reason',''))
            except ValidationError as exc:
                messages.error(request,' '.join(exc.messages))
            else:
                messages.success(request,'Aussonderung zur organisatorischen Prüfung vorgemerkt. Datei weiterhin aufbewahrt.')
            return redirect('record_detail',record_id=record_id)
        if form.is_valid():
            try:
                evidence.change_retention(request.user,record_id,**form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None,exc)
            else:
                return redirect('record_detail',record_id=record_id)
    events = s.query('SELECT e.*,u.display_name FROM evidence_retention_events e JOIN users u ON u.id=e.actor_id WHERE record_id=%s ORDER BY id DESC',[record_id])
    return render(request,'dms/evidence_detail.html',{'record':record,'form':form,'events':events,'can_manage':is_qmb(request.user)})

@login_required
def record_download(request,record_id):
    try:
        file,content = evidence.download_record(request.user,record_id)
    except ValidationError as exc:
        return HttpResponse(' '.join(exc.messages),status=409,content_type='text/plain; charset=utf-8')
    return FileResponse(io.BytesIO(content),as_attachment=True,filename=file['original_name'],content_type='application/octet-stream')

@login_required
def audit_report(request):
    require_qmb(request.user)
    form = AuditFilterForm(request.GET)
    rows = []
    if form.is_valid():
        data = form.cleaned_data
        rows = s.query('''SELECT e.id,e.occurred_at,e.action,e.object_type,e.object_id,e.reason,u.display_name
            FROM audit_events e LEFT JOIN users u ON u.id=e.actor_id
            LEFT JOIN document_versions av ON e.object_type='version' AND e.object_id=av.id::text
            LEFT JOIN documents ad ON ad.id=av.document_id
            WHERE (%s='' OR ad.number=%s) AND (%s::date IS NULL OR (e.occurred_at AT TIME ZONE 'Europe/Berlin')::date >= %s::date)
            AND (%s::date IS NULL OR (e.occurred_at AT TIME ZONE 'Europe/Berlin')::date <= %s::date)
            AND (%s='' OR e.action=%s) ORDER BY e.id DESC LIMIT 5000''',
            [data['document_number'],data['document_number'],data['since'],data['since'],data['until'],data['until'],data['action'],data['action']])
    if request.GET.get('export')=='csv' and form.is_valid():
        import csv
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="ims-audit.csv"'
        response.write('\ufeff')
        writer = csv.writer(response,delimiter=';')
        writer.writerow(['ID','Zeitpunkt','Aktion','Objektart','Objekt-ID','Person','Begründung'])
        def safe(value):
            value = str(value or '')
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        for row in rows:
            writer.writerow([safe(row[k]) for k in ['id','occurred_at','action','object_type','object_id','display_name','reason']])
        return response
    acknowledgements = s.query('''SELECT a.id,a.due_on,d.number,v.title,v.major,v.minor,u.display_name,r.acknowledged_at,r.content_fingerprint,
        (v.id=current_release(v.document_id) AND (v.valid_until IS NULL OR v.valid_until>now())) AS is_current
        FROM acknowledgement_assignments a JOIN document_versions v ON v.id=a.version_id
        JOIN documents d ON d.id=v.document_id JOIN users u ON u.id=a.user_id
        LEFT JOIN acknowledgement_receipts r ON r.assignment_id=a.id WHERE (%s='' OR d.number=%s) ORDER BY a.id DESC LIMIT 2000''',[form.cleaned_data.get('document_number','') if form.is_valid() else '',form.cleaned_data.get('document_number','') if form.is_valid() else ''])
    if request.GET.get('export')=='acknowledgements' and form.is_valid():
        import csv
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="ims-kenntnisnahmen.csv"'
        response.write('\ufeff')
        writer = csv.writer(response,delimiter=';')
        writer.writerow(['Zuordnung','Dokumentnummer','Version','Mitarbeiter','Fällig','Bestätigt','Aktuelle Fassung','Inhaltsfingerabdruck'])
        for task in acknowledgements:
            values = [task['id'],task['number'],f"{task['major']}.{task['minor']}",task['display_name'],task['due_on'],task['acknowledged_at'],'Aktuell' if task['is_current'] else 'Abgelöst / nicht wirksam',task['content_fingerprint']]
            writer.writerow([("'"+str(value)) if str(value or '').lstrip().startswith(('=','+','-','@')) else str(value or '') for value in values])
        return response
    return render(request,'dms/audit_report.html',{'form':form,'events':rows[:500],'total':len(rows),'acknowledgements':acknowledgements,'records':evidence.records(request.user)})


@login_required
@xframe_options_sameorigin
def pdf_viewer(request,version_id,file_id):
    _,version = s.get_version(request.user,version_id)
    files = s.query('SELECT f.original_name FROM file_objects f JOIN version_files vf ON vf.file_id=f.id WHERE vf.version_id=%s AND f.id=%s',[version_id,file_id])
    if not files or Path(files[0]['original_name']).suffix.lower() not in ('.pdf','.txt'):
        return HttpResponse('Bitte eine PDF-Lesefassung hinterlegen oder die Originaldatei herunterladen.',status=409,content_type='text/plain; charset=utf-8')
    response = render(request,'dms/pdf_viewer.html',{'v':version,'file_id':file_id})
    response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'self'; base-uri 'none'"
    return response


def pdfjs_asset(request,asset):
    from django.conf import settings
    from pathlib import PurePosixPath
    from django.http import Http404
    import mimetypes
    relative = PurePosixPath(asset)
    if relative.is_absolute() or '..' in relative.parts or (len(relative.parts)>1 and relative.parts[0] not in ('cmaps','standard_fonts','wasm')):
        raise Http404
    root = settings.BASE_DIR/'dms/static/vendor/pdfjs'
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
        raise Http404
    response = FileResponse(path.open('rb'),content_type=('text/javascript' if path.suffix=='.mjs' else mimetypes.guess_type(path.name)[0] or 'application/octet-stream'))
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    return response
