import json
from pathlib import Path
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe
from . import bpmn, processes, services as s
from .policies import is_qmb, require_qmb

VENDOR = Path(__file__).resolve().parent/'static/vendor/bpmn/18.31.0'
ASSETS = {'modeler.js':'text/javascript','viewer.js':'text/javascript','diagram-js.css':'text/css','bpmn-js.css':'text/css','bpmn-embedded.css':'text/css'}


@require_safe
def asset(request,name):
    if name not in ASSETS:raise Http404
    return FileResponse((VENDOR/name).open('rb'),content_type=ASSETS[name])


@require_http_methods(['GET','HEAD','POST'])
def diagram(request,target):
    manager=is_qmb(request.user)
    if request.method=='POST':require_qmb(request.user)
    nodes=processes.nodes(manager,target)
    current=next((node for node in nodes if node['id']==target),None)
    if current is None:raise Http404
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
    edit=manager and request.GET.get('edit')=='1'
    rows=s.query('SELECT * FROM process_bpmn WHERE process_id=%s',[target])
    model=rows[0] if rows else None
    xml=(model['draft_xml'] if edit else model['live_xml']) if model else None
    history=s.query('SELECT r.revision,r.published_at,u.display_name FROM process_bpmn_revisions r JOIN users u ON u.id=r.actor_id WHERE process_id=%s ORDER BY revision DESC',[target]) if manager else []
    choices=[{'id':node['id'],'title':node['code']+' · '+node['data']['title'],'url':reverse('process_bpmn' if node['demo'] and node['has_bpmn'] else 'process_detail',args=[node['id']])} for node in nodes if node['id']!=target]
    by_id={node['id']:node for node in nodes}
    crumbs=[by_id[identifier] for identifier in current['path'] if identifier in by_id]
    config={'xml':xml or (bpmn.EMPTY if edit else ''),'edit':edit,'expected':model['edit_version'] if model else 0,'processes':choices,'url':request.path,'code':current['code']}
    return render(request,'dms/bpmn.html',{'crumbs':crumbs,'current':current,'manager':manager,'edit':edit,'config':config,'history':history,'has_draft':bool(model and model['draft_xml']!=model['live_xml']),'revision':model['revision'] if model else 0})
