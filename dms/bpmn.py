"""BPMN interchange with bounded XML parsing and separate draft/publication state."""
from xml.etree.ElementTree import ParseError
from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from . import services as s
from .policies import require_qmb

MAX_BYTES = 2 * 1024 * 1024
BPMN = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
DI = 'http://www.omg.org/spec/BPMN/20100524/DI'
EMPTY = '''<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" id="Definitions_IMS" targetNamespace="https://ims.local/bpmn">
<bpmn:process id="Process_IMS" isExecutable="false"><bpmn:startEvent id="StartEvent_IMS" name="Start"/></bpmn:process>
<bpmndi:BPMNDiagram id="Diagram_IMS"><bpmndi:BPMNPlane id="Plane_IMS" bpmnElement="Process_IMS"><bpmndi:BPMNShape id="Shape_Start" bpmnElement="StartEvent_IMS"><dc:Bounds x="180" y="160" width="36" height="36"/></bpmndi:BPMNShape></bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
</bpmn:definitions>'''


def validate_xml(content):
    if not isinstance(content,str) or len(content.encode('utf-8')) > MAX_BYTES:
        raise ValidationError('BPMN-Datei darf höchstens 2 MiB groß sein.')
    try:
        root = fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ParseError,DefusedXmlException,ValueError) as error:
        raise ValidationError('Ungültige oder unsichere XML-Datei. Erwartet wird BPMN 2.0 ohne DTD oder externe Entitäten.') from error
    if root.tag != '{'+BPMN+'}definitions' or root.find('{'+BPMN+'}process') is None or root.find('{'+DI+'}BPMNDiagram') is None:
        raise ValidationError('BPMN-2.0-Datei mit Prozess und grafischen Diagrammdaten erforderlich.')
    stack=[(root,0)];count=0;ids=set()
    while stack:
        element,depth=stack.pop();count+=1
        if count>10000 or depth>64:raise ValidationError('Diagramm ist zu komplex (höchstens 10.000 XML-Elemente und 64 Ebenen).')
        name=element.tag.rsplit('}',1)[-1].lower()
        if name in ('script','foreignobject','iframe'):
            raise ValidationError('Aktive Skripte und eingebettete Webseiten werden nicht unterstützt.')
        for key,value in element.attrib.items():
            if key.rsplit('}',1)[-1].lower().startswith('on') or (key.rsplit('}',1)[-1].lower() in ('href','src') and not value.startswith('#')):
                raise ValidationError('Externe Ressourcen und aktive Attribute sind nicht erlaubt.')
        identifier=element.get('id')
        if identifier:
            if identifier in ids:raise ValidationError('BPMN-Elementkennungen müssen eindeutig sein.')
            ids.add(identifier)
        stack.extend((child,depth+1) for child in element)
    return content


@transaction.atomic
def save(user,target,xml,expected,publish,reason=''):
    actor=require_qmb(user)
    validate_xml(xml)
    try:
        with transaction.atomic():
            return s.query('SELECT save_process_bpmn(%s,%s,%s,%s,%s,%s) AS version',[actor,target,xml,expected,publish,reason])[0]['version']
    except DatabaseError as error:
        if getattr(error.__cause__,'sqlstate',None) in ('P0001','P0002'):
            raise ValidationError('Diagramm nicht gespeichert. Bei parallelen Änderungen Seite neu laden und vorher den eigenen Stand exportieren. Zum Veröffentlichen müssen der Prozess und alle übergeordneten Ebenen aktiv und veröffentlicht sein.') from error
        raise
