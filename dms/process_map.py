"""Diagram navigation for process hierarchies; real sequence flows remain explicitly modeled."""
from xml.etree import ElementTree as ET
from . import bpmn
from .demo_diagrams import child


def build(nodes):
    definitions=ET.Element('{'+bpmn.BPMN+'}definitions',{'id':'Definitions_Map','targetNamespace':'https://ims.local/map'})
    process=child(definitions,'bpmn:process',{'id':'Process_Map','isExecutable':'false'})
    plane=child(child(definitions,'bpmndi:BPMNDiagram',{'id':'Diagram_Map'}),'bpmndi:BPMNPlane',{'id':'Plane_Map','bpmnElement':'Process_Map'})
    positions={}
    for index,node in enumerate(nodes):
        identifier='Process_'+str(node['id'])
        code=node['code'];demo=node.get('demo',False)
        if demo and code in [f'DEMO-SIE-{n:02}' for n in range(1,7)]:x=60+(int(code[-2:])-1)*280;y=240
        elif demo and code=='DEMO-SIE-07':x=60;y=60
        elif demo and code=='DEMO-SIE-08':x=60;y=420
        else:x=60+(index%3)*280;y=620+(index//3)*160 if any(n.get('demo') for n in nodes) else 60+(index//3)*160
        item=child(process,'bpmn:callActivity',{'id':identifier,'name':node['data']['title']+(' · Entwurf' if not node['live'] else '')})
        child(item,'bpmn:documentation',text='IMS-PROCESS-ID:'+str(node['id']))
        shape=child(plane,'bpmndi:BPMNShape',{'id':'Shape_'+identifier,'bpmnElement':identifier})
        child(shape,'dc:Bounds',dict(x=str(x),y=str(y),width='220',height='100'))
        positions[code]=(identifier,x,y,demo)
    # An illustrative chain only for the explicitly marked demo, never inferred for real processes.
    for n in range(1,6):
        source=positions.get(f'DEMO-SIE-{n:02}');target=positions.get(f'DEMO-SIE-{n+1:02}')
        if source and target and source[3] and target[3]:
            identifier='DemoFlow_'+str(n)
            child(process,'bpmn:sequenceFlow',{'id':identifier,'sourceRef':source[0],'targetRef':target[0]})
            edge=child(plane,'bpmndi:BPMNEdge',{'id':'Edge_'+identifier,'bpmnElement':identifier})
            for x,y in [(source[1]+220,source[2]+50),(target[1],target[2]+50)]:child(edge,'di:waypoint',{'x':str(x),'y':str(y)})
    return ET.tostring(definitions,encoding='unicode',xml_declaration=True)
