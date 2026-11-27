"""Editorial example flows for demo data, never inferred for real company processes."""
from xml.etree import ElementTree as ET
from django.db import transaction
from . import bpmn, services as s
from .policies import require_qmb

NS = {'bpmn':bpmn.BPMN,'bpmndi':bpmn.DI,'dc':'http://www.omg.org/spec/DD/20100524/DC','di':'http://www.omg.org/spec/DD/20100524/DI'}
for prefix, uri in NS.items():ET.register_namespace(prefix,uri)


def child(parent, kind, attrs=None, text=None):
    prefix, name = kind.split(':')
    node = ET.SubElement(parent,'{'+NS[prefix]+'}'+name,attrs or {})
    if text is not None:node.text=text
    return node


def build(node, children):
    """Explicit demo recipe: child handoffs, or an illustrative work/check/rework loop."""
    definitions = ET.Element('{'+bpmn.BPMN+'}definitions',{'id':'Definitions_Demo','targetNamespace':'https://ims.local/demo'})
    process = child(definitions,'bpmn:process',{'id':'DemoProcess','isExecutable':'false','name':'DEMO · '+node['title']})
    child(process,'bpmn:documentation',text='Unverbindlicher Demo-Ablauf für Sielaff, Herrieden. Reihenfolge und Prüfschritte sind redaktionelle Beispiele, keine bestätigten Unternehmensabläufe. Fachlich prüfen, bevor dieser Ablauf produktiv verwendet wird.')
    plane = child(child(definitions,'bpmndi:BPMNDiagram',{'id':'Diagram_Demo'}),'bpmndi:BPMNPlane',{'id':'Plane_Demo','bpmnElement':'DemoProcess'})
    bounds = {}
    def shape(kind,identifier,title,x,y,width=180,height=90,link=None):
        item = child(process,'bpmn:'+kind,{'id':identifier,'name':title})
        if link:child(item,'bpmn:documentation',text='IMS-PROCESS-ID:'+str(link))
        attrs={'id':'Shape_'+identifier,'bpmnElement':identifier}
        if kind=='subProcess':attrs['isExpanded']='false'
        visual=child(plane,'bpmndi:BPMNShape',attrs)
        child(visual,'dc:Bounds',dict(x=str(x),y=str(y),width=str(width),height=str(height)))
        if kind=='exclusiveGateway':
            label=child(visual,'bpmndi:BPMNLabel')
            child(label,'dc:Bounds',{'x':str(x-45),'y':str(y-55),'width':'140','height':'40'})
        bounds[identifier]=(x,y,width,height)
    def flow(identifier,source,target,label='',points=None):
        attrs={'id':identifier,'sourceRef':source,'targetRef':target}
        if label:attrs['name']=label
        child(process,'bpmn:sequenceFlow',attrs)
        edge=child(plane,'bpmndi:BPMNEdge',{'id':'Edge_'+identifier,'bpmnElement':identifier})
        if points is None:
            x,y,w,h=bounds[source];tx,ty,tw,th=bounds[target]
            points=[(x+w,y+h/2),(tx,ty+th/2)]
        for x,y in points:child(edge,'di:waypoint',{'x':str(x),'y':str(y)})
        if label:
            # Explicit label bounds keep branch decisions readable in exported diagrams.
            label_node=child(edge,'bpmndi:BPMNLabel')
            px,py=points[0];qx,qy=points[1]
            child(label_node,'dc:Bounds',{'x':str((px+qx)/2-35),'y':str((py+qy)/2-25),'width':'70','height':'20'})
    shape('startEvent','Start','Auftrag / Bedarf',60,157,36,36)
    previous='Start'
    if children:
        for index,item in enumerate(children):
            identifier='Step_'+str(index+1)
            shape('callActivity',identifier,item['title'],160+index*260,130,210,90,item['id'])
            flow('Flow_'+str(index+1),previous,identifier)
            previous=identifier
        end_x=160+len(children)*260
        shape('endEvent','End','Ergebnis übergeben',end_x,157,36,36)
        flow('Flow_End',previous,'End')
    else:
        shape('task','Prepare','Auftrag und freigegebene Vorgaben prüfen',160,130)
        shape('task','Work',node['title'],410,130)
        shape('exclusiveGateway','Decision','Ergebnis in Ordnung?',660,150,50,50)
        shape('task','Rework','Abweichung klären und korrigieren',410,340)
        shape('task','Record','Ergebnis dokumentieren und übergeben',800,130)
        shape('endEvent','End','Abgeschlossen',1050,157,36,36)
        flow('Flow_Prepare','Start','Prepare')
        flow('Flow_Work','Prepare','Work')
        flow('Flow_Check','Work','Decision')
        flow('Flow_Yes','Decision','Record','Ja')
        flow('Flow_End','Record','End')
        flow('Flow_No','Decision','Rework','Nein',[(685,200),(685,385),(590,385)])
        flow('Flow_Retry','Rework','Work','Erneut prüfen',[(500,340),(500,220)])
    return ET.tostring(definitions,encoding='unicode',xml_declaration=True)


@transaction.atomic
def ensure(user):
    """Fill only absent models; a saved draft counts as user work and is never replaced."""
    require_qmb(user)
    s.query("SELECT pg_advisory_xact_lock(hashtext('ims-process-demo-diagrams'))")
    rows=s.query("SELECT id,parent_id,code,level,live->>'title' AS title FROM ims_processes WHERE demo AND active AND live IS NOT NULL ORDER BY code")
    by_id={row['id']:row for row in rows}
    existing={row['process_id'] for row in s.query('SELECT process_id FROM process_bpmn')}
    made=0
    for node in rows:
        # Never republish or reactivate a deliberately deactivated ancestor.
        parent=node['parent_id'];eligible=True
        while parent:
            if parent not in by_id:eligible=False;break
            parent=by_id[parent]['parent_id']
        if not eligible or node['id'] in existing:continue
        children=[row for row in rows if row['parent_id']==node['id']]
        xml=build(node,children)
        bpmn.save(user,node['id'],xml,0,True,'Fehlendes Demo-Flussdiagramm ergänzt; Ablauf ist ein unverbindliches Beispiel.')
        made+=1
    return made
