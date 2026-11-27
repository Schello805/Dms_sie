import json
import re
from pathlib import Path
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe
from . import bpmn, processes, process_demo, process_map, services as s
from .policies import is_qmb, require_qmb

VENDOR = Path(__file__).resolve().parent/'static/vendor/bpmn/18.31.0'
ASSETS = {'modeler.js':'text/javascript','viewer.js':'text/javascript','diagram-js.css':'text/css','bpmn-js.css':'text/css','bpmn-embedded.css':'text/css'}


@require_safe
def asset(request,name):
    if name not in ASSETS:raise Http404
    return FileResponse((VENDOR/name).open('rb'),content_type=ASSETS[name])


@require_http_methods(['GET','HEAD','POST'])
def diagram(request,target=None):
    manager=is_qmb(request.user)
    if request.method=='POST':require_qmb(request.user)
    nodes=processes.nodes(manager,target)
    current=next((node for node in nodes if node['id']==target),None)
    if target is not None and current is None:raise Http404
    if target is None and request.method=='POST':return JsonResponse({'error':'Bitte einen Prozess auswählen.'},status=405)
    if request.method=='POST':
        if len(request.body)>bpmn.MAX_BYTES*6+65536:return JsonResponse({'error':'Datei ist zu groß.'},status=413)
        try:
            data=json.loads(request.body)
            if not isinstance(data,dict) or type(data.get('expected')) is not int or type(data.get('publish')) is not bool or not isinstance(data.get('reason',''),str) or len(data.get('reason',''))>4000:
                raise ValidationError('Ungültige Speicheranfrage.')
            version=bpmn.save(request.user,target,data.get('xml'),data['expected'],data['publish'],data.get('reason',''))
        except (ValueError,UnicodeDecodeError):return JsonResponse({'error':'Ungültige JSON-Anfrage.'},status=400)
        except ValidationError as error:return JsonResponse({'error':' '.join(error.messages)},status=409)
        return JsonResponse({'version':version,'message':'Diagramm veröffentlicht.' if data['publish'] else 'Arbeitsstand gespeichert.'})
    edit=bool(target and manager and request.GET.get('edit')=='1')
    rows=s.query('SELECT * FROM process_bpmn WHERE process_id=%s',[target])
    model=rows[0] if rows else None
    xml=(model['draft_xml'] if edit else model['live_xml']) if model else None
    history=s.query('SELECT r.revision,r.published_at,u.display_name FROM process_bpmn_revisions r JOIN users u ON u.id=r.actor_id WHERE process_id=%s ORDER BY revision DESC',[target]) if manager else []
    choices=[{'id':node['id'],'title':node['code']+' · '+node['data']['title'],'url':reverse('process_detail',args=[node['id']])} for node in nodes if node['id']!=target]
    by_id={node['id']:node for node in nodes}
    crumbs=[by_id[identifier] for identifier in current['path'] if identifier in by_id] if current else []
    search=request.GET.get('q','').strip()[:200] if not current else ''
    children=[node for node in nodes if node['parent_id']==target] if not search else [node for node in nodes if node['search_match']]
    if search:children=[node for node in processes.nodes(manager,None,search) if node['search_match']]
    navigation=not xml and not edit
    if navigation:xml=process_map.build(children) if children else ''
    document_ids=None if edit else set(re.findall(r'IMS-DOCUMENT-ID:(\d+)',xml or ''))
    document_ids=[int(identifier) for identifier in document_ids] if document_ids is not None else None
    uid=s.actor(request.user) if request.user.is_authenticated else None
    documents=s.query('''SELECT d.id,d.number,v.title,l.kind_slug,l.number_slug FROM documents d
        JOIN document_versions v ON v.id=current_release(d.id) JOIN document_links l ON l.document_id=d.id
        WHERE ((NOT d.login_required) OR can_read_version(%s,v.id)) AND (%s OR d.id=ANY(%s::bigint[])) ORDER BY d.number''',[uid,document_ids is None,document_ids or []])
    document_choices=[{'id':d['id'],'title':d['number']+' · '+d['title'],'url':'/d/'+d['kind_slug']+'/'+d['number_slug']+'/'} for d in documents]
    linked_documents=[];references=[]
    if current:
        linked_documents=s.query('''SELECT d.number,v.title,l.kind_slug,l.number_slug FROM documents d JOIN document_versions v ON v.id=current_release(d.id) JOIN document_links l ON l.document_id=d.id WHERE d.id=ANY(%s::bigint[]) AND ((NOT d.login_required) OR can_read_version(%s,v.id)) ORDER BY d.number''',[current['data'].get('documents',[]),uid])
        references=s.query('SELECT s.name,s.edition,r.reference,r.label FROM standard_references r JOIN standards s ON s.id=r.standard_id WHERE r.id=ANY(%s::bigint[]) ORDER BY s.name,r.reference',[current['data'].get('references',[])])
    config={'xml':xml or (bpmn.EMPTY if edit else ''),'edit':edit,'expected':model['edit_version'] if model else 0,'processes':choices,'documents':document_choices,'url':reverse('process_bpmn',args=[target]) if target else request.path,'code':current['code'] if current else 'Prozesslandkarte','navigation':navigation}
    return render(request,'dms/bpmn.html',{'search':search,'demo_state':process_demo.state(),'documents':linked_documents,'references':references,'crumbs':crumbs,'current':current,'manager':manager,'edit':edit,'config':config,'history':history,'has_draft':bool(model and model['draft_xml']!=model['live_xml']),'revision':model['revision'] if model else 0})
