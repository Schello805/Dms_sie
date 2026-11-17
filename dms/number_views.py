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
    base = '''FROM document_number_registry r JOIN documents d ON d.id=r.document_id
        JOIN document_categories c ON c.name=d.document_type JOIN users u ON u.id=d.owner_id
        JOIN LATERAL (SELECT id,title FROM document_versions WHERE document_id=d.id
          ORDER BY major DESC,minor DESC LIMIT 1) v ON true
        WHERE (%s='' OR r.number ILIKE %s OR v.title ILIKE %s)
          AND (%s='' OR d.active=(%s='1'))'''
    args = [search, '%'+search+'%', '%'+search+'%', active, active]
    total = s.query('SELECT count(*) AS n '+base, args)[0]['n']
    page = Paginator(range(total), 25).get_page(request.GET.get('page'))
    rows = s.query('''SELECT r.number,r.document_id,r.created_at,d.active,
        coalesce(c.display_name,c.name) AS kind,v.id AS version_id,v.title,u.display_name AS author '''+
        base+' ORDER BY r.created_at DESC,r.document_id DESC LIMIT 25 OFFSET %s', args+[max(page.start_index()-1,0)])
    params = request.GET.copy(); params.pop('page', None)
    return render(request, 'dms/document_numbers.html', {'rows':rows,'page':page,
        'page_query':params.urlencode(),'search':search,'active':active})


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
    return redirect('document_numbers')
