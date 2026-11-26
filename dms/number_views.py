"""QMB register of permanently assigned numbers and document visibility."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from . import services as s
from .policies import require_qmb


@login_required
def listing(request):
    require_qmb(request.user)
    search = request.GET.get('q', '').strip()[:200]
    active = request.GET.get('active', '')
    active = active if active in ('', '0', '1') else ''
    kind=request.GET.get('type','').strip()[:200]
    usage=request.GET.get('usage','')
    usage=usage if usage in ('','current','former') else ''
    base = '''FROM document_number_registry r JOIN documents d ON d.id=r.document_id
        JOIN document_categories c ON c.name=d.document_type JOIN users u ON u.id=d.owner_id
        JOIN LATERAL (SELECT id,title FROM document_versions WHERE document_id=d.id
          ORDER BY major DESC,minor DESC LIMIT 1) v ON true
        WHERE (%s='' OR r.number ILIKE %s OR d.number ILIKE %s OR v.title ILIKE %s)
          AND (%s='' OR d.active=(%s='1'))
          AND (%s='' OR c.name=%s)
          AND (%s='' OR (r.number=d.number)=(%s='current'))'''
    args = [search, '%'+search+'%', '%'+search+'%', '%'+search+'%', active, active,kind,kind,usage,usage]
    counts=s.query('SELECT count(*) AS n,count(*) FILTER (WHERE r.number=d.number) AS current_count,count(DISTINCT d.id) AS document_count '+base,args)[0]
    total=counts['n']
    page = Paginator(range(total), 25).get_page(request.GET.get('page'))
    rows = s.query('''SELECT r.number,d.number AS document_number,r.document_id,r.created_at,d.active,(r.number=d.number) AS current_number,
        coalesce(c.display_name,c.name) AS kind,v.id AS version_id,v.title,u.display_name AS author '''+
        base+' ORDER BY lower(r.number),r.number,r.document_id LIMIT 25 OFFSET %s', args+[max(page.start_index()-1,0)])
    params = request.GET.copy(); params.pop('page', None)
    return render(request, 'dms/document_numbers.html', {'rows':rows,'page':page,
        'page_query':params.urlencode(),'search':search,'active':active,'kind':kind,'usage':usage,'counts':counts,'former_count':total-counts['current_count'],'types':s.query('SELECT name,coalesce(display_name,name) AS label FROM document_categories ORDER BY label')})


@login_required
@require_POST
def set_active(request, document_id):
    actor = require_qmb(request.user)
    if request.POST.get('active') not in ('0','1'):
        return HttpResponseBadRequest('Status auswählen.')
    if not s.query('SELECT 1 FROM documents WHERE id=%s', [document_id]):
        raise Http404
    enabled = request.POST['active']=='1'
    s.query('SELECT set_document_active(%s,%s,%s)', [actor, document_id, enabled])
    messages.success(request, 'Dokument reaktiviert.' if enabled else 'Dokument deaktiviert. Die Nummer bleibt dauerhaft vergeben.')
    if request.resolver_match.view_name=='document_toggle_active':
        latest=s.query('SELECT id FROM document_versions WHERE document_id=%s ORDER BY major DESC,minor DESC LIMIT 1',[document_id])
        if latest:return redirect('detail',version_id=latest[0]['id'])
    return redirect('document_numbers')


@login_required
def rename(request,document_id):
    from django.core.exceptions import PermissionDenied
    from django.db import DatabaseError,IntegrityError,transaction
    from .policies import is_qmb
    from .forms import DocumentNumberForm
    actor=s.actor(request.user)
    rows=s.query('SELECT * FROM documents WHERE id=%s',[document_id])
    if not rows:raise Http404
    doc=rows[0]
    if not doc['active'] or not (is_qmb(request.user) or (doc['owner_id']==actor and s.allowed(actor,doc['responsible_department_id'],'AUTHOR',document_id))):
        raise PermissionDenied('Nur der verantwortliche Autor oder QMB darf die Dokumentnummer ändern.')
    form=DocumentNumberForm(request.POST or None,initial={'number':doc['number']})
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                s.query('SELECT rename_document(%s,%s,%s,%s)',[actor,document_id,form.cleaned_data['number'],form.cleaned_data['reason']])
        except IntegrityError:
            form.add_error('number','Diese Dokumentnummer ist bereits vergeben oder dauerhaft reserviert.')
        except DatabaseError as error:
            if getattr(error.__cause__,'sqlstate',None)=='P0001':form.add_error(None,'Änderung nicht möglich. Rolle, Dokumentstatus und Nummer prüfen.')
            else:raise
        else:
            messages.success(request,'Dokumentnummer geändert. Der dauerhafte Link bleibt gleich.')
            latest=s.query('SELECT id FROM document_versions WHERE document_id=%s ORDER BY major DESC,minor DESC LIMIT 1',[document_id])[0]['id']
            return redirect('detail',version_id=latest)
    return render(request,'dms/rename_document.html',{'form':form,'document':doc})
