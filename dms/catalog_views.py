"""Read-only catalogue, sorting and lazy-loading responses.

All visibility decisions remain in services.visible_versions.
"""
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from . import services
from .catalog_columns import COLUMNS

PAGE_SIZE = 30

def index(request):
    sort = request.GET.get('sort','')
    sort = sort if sort in services.CATALOG_SORTS else ''
    direction = 'desc' if request.GET.get('direction')=='desc' else 'asc'
    filters = dict(sort=sort,direction=direction,search=request.GET.get('q',''),status=request.GET.get('status',''),
        department=request.GET.get('department',''),standard=request.GET.get('standard',''),
        due_only=request.GET.get('due')=='1',catalog_only=True)
    first = services.visible_versions(request.user,**filters,limit=1)
    total = first[0]['total_count'] if first else 0
    page = Paginator(range(total),PAGE_SIZE).get_page(request.GET.get('page'))
    versions = services.visible_versions(request.user,**filters,limit=PAGE_SIZE,offset=page.start_index()-1) if total else []
    page_query = request.GET.copy()
    page_query.pop('page',None)
    page_query.pop('fragment',None)
    if request.GET.get('fragment')=='1':
        next_query = page_query.copy()
        next_query['page'] = page.next_page_number() if page.has_next() else ''
        return JsonResponse({'html':render_to_string('dms/document_rows.html',{'versions':versions},request=request),
            'next_url':request.path+'?'+next_query.urlencode() if page.has_next() else None})
    uid = services.actor(request.user) if request.user.is_authenticated else None
    departments = services.query('SELECT d.id,d.name FROM departments d WHERE EXISTS (SELECT 1 FROM effective_role_assignments r WHERE r.user_id=%s AND ((r.document_id IS NULL AND (r.department_id IS NULL OR r.department_id=d.id)) OR EXISTS (SELECT 1 FROM documents doc WHERE doc.id=r.document_id AND doc.responsible_department_id=d.id))) ORDER BY d.name',[uid])
    standards = services.query('SELECT * FROM standards ORDER BY name,edition')
    sort_headers = []
    for key,label,expression in COLUMNS:
        params = page_query.copy()
        params['sort'] = key
        params['direction'] = 'desc' if sort==key and direction=='asc' else 'asc'
        sort_headers.append({'label':label,'url':'?'+params.urlencode(),
            'aria_sort':('ascending' if direction=='asc' else 'descending') if sort==key else 'none',
            'arrow':('↑' if direction=='asc' else '↓') if sort==key else '↕'})
    return render(request,'dms/index.html',{'sort_headers':sort_headers,'sort':sort,'direction':direction,'versions':versions,'page':page,'page_query':page_query.urlencode(),'departments':departments,'standards':standards})

