from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.debug import sensitive_post_parameters
from . import services
from .forms import ActionForm, DocumentForm, ReviewForm, RevisionForm, AccessForm, LifecycleForm

@login_required
def create(request):
    uid = services.actor(request.user)
    if not services.query("SELECT 1 FROM effective_role_assignments WHERE user_id=%s AND role='AUTHOR' AND document_id IS NULL",[uid]):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Dokumente hochladen erfordert die Autorenrolle.')
    from .forms import DocumentUploadForm
    from .simple_workflow import upload_document
    form = DocumentUploadForm(request.POST or None,request.FILES or None,user=request.user)
    if request.method=='POST' and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            uploaded = data.pop('file')
            intent = data.pop('intent')
            vid = upload_document(request.user,data,uploaded,intent=='submit')
        except ValidationError as exc:
            form.add_error(None,exc)
        except IntegrityError:
            form.add_error(None,'Dokumentnummer bereits vergeben oder Stammdaten ungültig.')
        else:
            messages.success(request,'Dokument hochgeladen.' if intent=='draft' else 'Dokument hochgeladen und QMB-Freigabe angefordert.')
            return redirect('detail',version_id=vid)
    return render(request,'dms/create.html',{'form':form})

@login_required
def detail(request, version_id, action_form=None):
    uid, v = services.get_version(request.user,version_id)
    if getattr(request,'reader_only',False):
        from .simple_workflow import open_reading_copy
        return open_reading_copy(request,version_id)
    services.audit(uid,'VIEW',version_id,'Dokumentansicht')
    editor = any(services.allowed(uid,v['responsible_department_id'],r,v['document_id']) for r in ('AUTHOR','REVIEWER'))
    events = services.query("SELECT e.action,e.reason,e.occurred_at,u.display_name AS actor_name FROM audit_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.object_type='version' AND e.object_id=%s ORDER BY e.id DESC LIMIT 50",[str(version_id)]) if editor else []
    files = services.query('SELECT f.id,f.original_name,i.status AS index_status,i.truncated AS index_truncated,i.error_code FROM file_objects f JOIN version_files vf ON vf.file_id=f.id LEFT JOIN file_text_indexes i ON i.file_id=f.id WHERE vf.version_id=%s ORDER BY f.id',[version_id])
    from pathlib import Path
    for file in files:
        file['previewable'] = Path(file['original_name']).suffix.lower() in ('.pdf','.txt')
    returned = services.query("SELECT comment,decided_at FROM approval_decisions WHERE version_id=%s AND decision='RETURN' ORDER BY id DESC LIMIT 1",[version_id]) if v['status']=='DRAFT' and v['created_by']==uid else []
    mappings = services.query('SELECT s.name,s.edition,r.reference,r.label FROM version_standard_links l JOIN standard_references r ON r.id=l.reference_id JOIN standards s ON s.id=r.standard_id WHERE l.version_id=%s ORDER BY s.name,r.reference',[version_id])
    departments = services.query('SELECT d.name FROM departments d JOIN version_departments vd ON vd.department_id=d.id WHERE vd.version_id=%s ORDER BY d.name',[version_id])
    reviews = services.query('SELECT pr.*,u.display_name AS reviewer_name FROM periodic_reviews pr JOIN users u ON u.id=pr.reviewer_id WHERE version_id=%s ORDER BY pr.id DESC',[version_id]) if editor else []
    can_author = services.allowed(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    from .policies import is_qmb
    qmb = is_qmb(request.user)
    can_review = v['status']=='APPROVED' and uid!=v['created_by'] and qmb and services.query('SELECT current_release(%s) AS id',[v['document_id']])[0]['id']==version_id
    workflow_form = action_form if action_form is not None else ActionForm()
    choices = []
    if v['status']=='DRAFT' and can_author:
        choices = [('submit','Zur Prüfung einreichen')]
    elif v['status'] in ('IN_REVIEW','PENDING_APPROVAL') and qmb and uid!=v['created_by']:
        choices = [('approve','Freigeben'),('reject','Ablehnen / Überarbeitung anfordern')]
    approval_review = services.query("SELECT a.comment,a.decided_at,u.display_name FROM approval_decisions a JOIN workflow_instances w ON w.id=a.workflow_id JOIN users u ON u.id=a.actor_id WHERE w.version_id=%s AND w.closed_at IS NULL AND a.stage='REVIEW' AND a.decision='ACCEPT'",[version_id]) if v['status']=='PENDING_APPROVAL' else []
    workflow_form.fields['action'].choices = choices
    return render(request,'dms/detail.html',{'returned_note':returned[0] if returned else None,'workflow_is_submission':v['status']=='DRAFT','approval_review':approval_review,'v':v,'events':events,'files':files,'mappings':mappings,'departments':departments,'reviews':reviews,'review_form':ReviewForm(),'can_review':can_review,'can_workflow':bool(choices),'form':workflow_form,'can_author':can_author,'revision_form':RevisionForm(),'can_history':editor,'document_withdrawn':bool(services.query('SELECT 1 FROM document_withdrawals WHERE document_id=%s LIMIT 1',[v['document_id']])) and services.query('SELECT current_release(%s) AS id',[v['document_id']])[0]['id'] is None,'lifecycle_form':LifecycleForm(),'can_lifecycle':qmb and v['status']=='APPROVED','can_takeover':False})

@login_required
@require_POST
def action(request, version_id):
    form = ActionForm(request.POST)
    if form.is_valid():
        try:
            if form.cleaned_data['action'] in ('approve','reject'):
                from .simple_workflow import decide
                decide(request.user,version_id,form.cleaned_data['action']=='approve',form.cleaned_data['comment'])
            else:
                services.transition(request.user,version_id,form.cleaned_data['action'],form.cleaned_data['comment'] or ('Autor hat die Freigabe angefordert.' if form.cleaned_data['action']=='submit' else ''))
        except ValidationError as exc:
            form.add_error(None,exc)
            messages.error(request,'Die Aktion konnte nicht gespeichert werden. Bitte prüfe die Hinweise.')
            return detail(request,version_id,action_form=form)
        else:
            messages.success(request,'Statusänderung gespeichert.')
            uid = services.actor(request.user)
            if not services.query('SELECT can_read_version(%s,%s) AS allowed',[uid,version_id])[0]['allowed']:
                return redirect('tasks')
    else:
        messages.error(request,'Bitte prüfe die markierten Felder.')
        return detail(request,version_id,action_form=form)
    return redirect('detail',version_id=version_id)

@login_required
def edit(request,version_id):
    from .forms import EditForm
    from django.core.exceptions import PermissionDenied
    uid,v = services.get_version(request.user,version_id)
    services.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    if v['status'] != 'DRAFT':
        raise PermissionDenied('Nur Entwürfe bearbeiten.')
    initial = dict(v)
    initial['applicable_departments'] = [r['department_id'] for r in services.query('SELECT department_id FROM version_departments WHERE version_id=%s',[version_id])]
    initial['standard_references'] = [r['reference_id'] for r in services.query('SELECT reference_id FROM version_standard_links WHERE version_id=%s',[version_id])]
    form = EditForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:
            services.edit_draft(request.user,version_id,form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Entwurf gespeichert.')
            return redirect('detail',version_id=version_id)
    return render(request,'dms/create.html',{'form':form,'is_edit':True})

@login_required
@require_POST
def revision(request,version_id):
    form = RevisionForm(request.POST)
    if not form.is_valid():
        messages.error(request,'Versionssprung und Änderungsgrund sind erforderlich.')
        return redirect('detail',version_id=version_id)
    try:
        vid = services.new_revision(request.user,version_id,**form.cleaned_data)
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
        return redirect('detail',version_id=version_id)
    return redirect('detail',version_id=vid)

@login_required
@require_POST
def upload(request,version_id):
    from .forms import UploadForm
    from . import storage
    form = UploadForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            storage.upload(request.user,version_id,form.cleaned_data['file'],request.POST.get('purpose','ORIGINAL'))
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
        else:
            messages.success(request,'Datei gespeichert.')
    else:
        messages.error(request,'Bitte eine Datei auswählen.')
    return redirect('detail',version_id=version_id)

@login_required
def download(request,version_id,file_id):
    import io
    from django.http import FileResponse, HttpResponse
    from . import storage
    try:
        f,content = storage.download(request.user,version_id,file_id)
    except ValidationError as exc:
        return HttpResponse(' '.join(exc.messages),status=409,content_type='text/plain')
    return FileResponse(io.BytesIO(content),as_attachment=True,filename=f['original_name'],content_type='application/octet-stream')

@login_required
@require_POST
def remove_file(request,version_id,file_id):
    try:
        services.remove_file(request.user,version_id,file_id,request.POST.get('reason',''))
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    return redirect('detail',version_id=version_id)


@login_required
@require_POST
def review(request,version_id):
    form = ReviewForm(request.POST)
    if form.is_valid():
        try:
            services.record_review(request.user,version_id,**form.cleaned_data)
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
        else:
            messages.success(request,'Periodische Prüfung unveränderlich protokolliert.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request,error)
    return redirect('detail',version_id=version_id)


@login_required
def history(request,version_id):
    v,versions,decisions = services.version_history(request.user,version_id)
    withdrawals = services.query('SELECT w.*,u.display_name AS actor_name FROM document_withdrawals w JOIN users u ON u.id=w.actor_id WHERE document_id=%s ORDER BY w.id DESC',[v['document_id']])
    return render(request,'dms/history.html',{'v':v,'versions':versions,'decisions':decisions,'withdrawals':withdrawals})


@login_required
def access(request,version_id):
    uid,v = services.get_version(request.user,version_id)
    services.require(uid,v['responsible_department_id'],'AUTHOR',v['document_id'])
    policy = services.access_policy(v['document_id'])
    form = AccessForm(request.POST or None,initial={'access_mode':policy['access_mode'],'users':[r['user_id'] for r in policy['users']],'groups':[r['group_id'] for r in policy['groups']]})
    if request.method=='POST' and form.is_valid():
        try:
            services.change_access(request.user,version_id,**form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Dokumentzugriff aktualisiert und protokolliert.')
            return redirect('detail',version_id=version_id)
    return render(request,'dms/access.html',{'v':v,'form':form})


@login_required
@require_POST
def lifecycle(request,version_id):
    form = LifecycleForm(request.POST)
    if form.is_valid():
        try:
            services.lifecycle_action(request.user,version_id,**form.cleaned_data)
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
        else:
            messages.success(request,'Lebenszyklusentscheidung gespeichert und protokolliert.')
    else:
        messages.error(request,'Vorgang, Begründung und Bestätigung sind erforderlich.')
    return redirect('detail',version_id=version_id)

@login_required
def tasks(request):
    from .policies import is_qmb
    from .simple_workflow import returned_tasks
    if not is_qmb(request.user) and not services.query("SELECT 1 FROM users u WHERE u.auth_user_id=%s AND EXISTS(SELECT 1 FROM effective_role_assignments r WHERE r.user_id=u.id AND r.role='AUTHOR')",[request.user.pk]):
        return redirect('index')
    qmb = is_qmb(request.user)
    return render(request,'dms/tasks.html',{'returned':returned_tasks(request.user),'tasks':services.workflow_tasks(request.user) if qmb else [],'due':services.visible_versions(request.user,due_only=True) if qmb else []})


@login_required
@require_POST
def retry_index(request,version_id,file_id):
    from . import indexing
    try:
        indexing.retry_index(request.user,version_id,file_id)
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    else:
        messages.success(request,'Datei wurde erneut zur Volltextverarbeitung vorgemerkt.')
    return redirect('detail',version_id=version_id)


@login_required
def admin_settings(request):
    from .policies import require_qmb,save_category_management
    from .forms import CategorySettingsForm
    require_qmb(request.user)
    form = CategorySettingsForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            save_category_management(request.user,form.intervals(),form.retention(),form.locations(),form.cleaned_data['reason'])
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Kategoriefristen gespeichert. Bestehende freigegebene Prüftermine bleiben erhalten.')
            return redirect('admin_settings')
    return render(request,'dms/admin_settings.html',{'form':form,'category_rows':form.rows()})


@login_required
@sensitive_post_parameters('password')
def mail_settings(request):
    from .policies import require_settings_admin
    from .forms import SMTPSettingsForm,SMTPTestForm
    from . import notifications
    require_settings_admin(request.user)
    config = notifications.load_config()
    form = SMTPSettingsForm(request.POST or None,initial=notifications.public_config(config))
    if request.method=='POST' and form.is_valid():
        try:
            notifications.save_config(request.user,form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'E-Mail- und SMTP-Einstellungen gespeichert.')
            return redirect('mail_settings')
    uid = services.actor(request.user)
    deliveries = services.query('''SELECT n.id,n.status,n.kind,n.recipient_kind,n.due_on,n.recipient_email,n.error_code,n.created_at,n.sent_at,u.display_name,
        CASE WHEN can_read_version(%s,n.version_id) THEN d.number ELSE NULL END AS document_number
        FROM review_notifications n JOIN users u ON u.id=n.recipient_id
        JOIN document_versions v ON v.id=n.version_id JOIN documents d ON d.id=v.document_id
        ORDER BY n.id DESC LIMIT 50''',[uid])
    return render(request,'dms/mail_settings.html',{'form':form,'test_form':SMTPTestForm(),'password_set':bool(config['password_ciphertext']),'deliveries':deliveries})

@login_required
@require_POST
def smtp_test(request):
    from .forms import SMTPTestForm
    from .notifications import send_test
    from .policies import require_settings_admin
    require_settings_admin(request.user)
    form = SMTPTestForm(request.POST)
    if form.is_valid():
        try:
            send_test(request.user,form.cleaned_data['recipient'])
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
        else:
            messages.success(request,'Test-E-Mail wurde vom SMTP-Server angenommen.')
    else:
        messages.error(request,'Gültige Empfängeradresse für den Test angeben.')
    return redirect('mail_settings')

@login_required
@require_POST
def retry_mail(request,notification_id):
    from .notifications import retry_failed
    try:
        retry_failed(request.user,notification_id)
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    return redirect('mail_settings')

@login_required
def contact_emails(request):
    from .policies import require_settings_admin
    from .forms import ContactEmailForm
    from .notifications import set_contact_email
    require_settings_admin(request.user)
    if request.method=='POST':
        form = ContactEmailForm(request.POST)
        if form.is_valid():
            try:
                set_contact_email(request.user,**form.cleaned_data)
            except ValidationError as exc:
                messages.error(request,' '.join(exc.messages))
            else:
                messages.success(request,'E-Mail-Adresse gespeichert und protokolliert.')
                return redirect('contact_emails')
        else:
            messages.error(request,'Gültige E-Mail-Adresse und Begründung sind erforderlich.')
    search = request.GET.get('q','').strip()[:200]
    people = services.query('''SELECT u.id,u.display_name,COALESCE(NULLIF(u.email,''),a.email) AS email FROM users u
        JOIN auth_user a ON a.id=u.auth_user_id WHERE u.active AND a.is_active
        AND (%s='' OR u.display_name ILIKE %s OR a.username ILIKE %s) ORDER BY u.display_name,u.id LIMIT 100''',[search,'%'+search+'%','%'+search+'%'])
    return render(request,'dms/contact_emails.html',{'people':people,'search':search})


@login_required
@require_POST
def takeover(request,version_id):
    try:
        services.takeover_review(request.user,version_id,request.POST.get('reason',''))
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    return redirect('detail',version_id=version_id)

@login_required
def it_settings(request):
    from .policies import require_settings_admin
    require_settings_admin(request.user)
    if request.method!='GET':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET'])
    from .forms import BrandingForm
    from .system_logs import read_events
    errors,log_warning = read_events(limit=5)
    from .system_info import snapshot
    return render(request,'dms/it_settings.html',{'logo_form':BrandingForm(auto_id='branding_%s'),'system_errors':errors,'log_warning':log_warning,'system_info':snapshot()})

@login_required
def storage_locations(request):
    from .policies import require_qmb
    from .forms import StorageLocationForm
    uid = require_qmb(request.user)
    form = StorageLocationForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            from django.db import transaction
            import json
            with transaction.atomic():
                location = services.query('INSERT INTO storage_locations(name,description) VALUES (%s,%s) RETURNING id',[form.cleaned_data['name'],form.cleaned_data['description']])[0]['id']
                services.query("INSERT INTO audit_events(actor_id,action,object_type,object_id,reason,details) VALUES (%s,'CREATE_STORAGE_LOCATION','storage_location',%s,%s,%s::jsonb)",[uid,str(location),form.cleaned_data['reason'],json.dumps({'name':form.cleaned_data['name']})])
        except IntegrityError:
            form.add_error('name','Dieser Aufbewahrungsort existiert bereits.')
        else:
            return redirect('storage_locations')
    return render(request,'dms/storage_locations.html',{'form':form,'locations':services.query('SELECT * FROM storage_locations ORDER BY name')})


@login_required
def reminder_management(request):
    from .policies import require_qmb
    from .notifications import load_config,save_notification_policy
    from .forms import ReminderPolicyForm
    require_qmb(request.user)
    config = load_config()
    form = ReminderPolicyForm(request.POST or None,initial={'enabled':config['enabled'],'reminder_days':config['reminder_days']})
    if request.method=='POST' and form.is_valid():
        try:
            save_notification_policy(request.user,**form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Erinnerungsregeln gespeichert. Autor und aktive QMBs werden berücksichtigt.')
            return redirect('reminder_management')
    return render(request,'dms/reminder_management.html',{'form':form,'smtp_ready':bool(config['smtp_host'] and config['sender_email'] and config['base_url'])})
