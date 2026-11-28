/* Pure diagram helpers, shared by the browser and offline regression tests. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BpmnTools=api;})(globalThis,()=>{
 'use strict';
 const linkIds=element=>{
  const result={};
  for(const doc of element.businessObject&&element.businessObject.documentation||[]){const match=/^IMS-(PROCESS|DOCUMENT)-ID:(\d+)$/.exec(doc.text||'');if(match)result[match[1]]=match[2];}
  return result;
 };
 const issues=(elements,processes,documents)=>{
  const result=[],p=new Set(processes.filter(item=>item.available!==false).map(item=>String(item.id))),d=new Set(documents.map(item=>String(item.id)));
  const edges=elements.filter(e=>e.type==='bpmn:SequenceFlow');
  for(const element of elements){
   if(element.labelTarget||!element.businessObject)continue;
   const name=element.businessObject.name||element.id;
   const add=text=>result.push({id:element.id,text:name+': '+text});
   const ids=linkIds(element);
   if(ids.PROCESS&&!p.has(ids.PROCESS))add('Unterprozess nicht zugänglich oder nicht vorhanden.');
   if(ids.DOCUMENT&&!d.has(ids.DOCUMENT))add('Dokument nicht freigegeben, nicht zugänglich oder nicht vorhanden.');
   const node=/^bpmn:.*(?:Task|Activity|Event|Gateway|SubProcess)$/.test(element.type);
   if(node&&!edges.some(e=>e.source===element||e.target===element))add('Keine Ablaufverbindung.');
   if(element.type==='bpmn:ExclusiveGateway'||element.type==='bpmn:InclusiveGateway'){
    const outgoing=edges.filter(e=>e.source===element);
    if(outgoing.length>1)for(const edge of outgoing)if(!(edge.businessObject.name||'').trim()&&element.businessObject.default!==edge.businessObject)result.push({id:edge.id,text:name+': Ausgang ohne Beschriftung.'});
   }
  }
  return result;
 };
 const searchable=(element,processes,documents)=>{
  const ids=linkIds(element);
  return [element.businessObject&&element.businessObject.name,processes.find(p=>String(p.id)===ids.PROCESS)?.title,documents.find(d=>String(d.id)===ids.DOCUMENT)?.title].filter(Boolean).join(' ').toLocaleLowerCase('de');
 };
 return {linkIds,issues,searchable};
});
