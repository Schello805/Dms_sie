/* Local BPMN 2.0 editing; no diagram is sent to an external service. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('bpmn-config').textContent);
  const byId = id => document.getElementById(id);
  const status = (text, error = false) => {
    byId('bpmn-status').textContent = text;
    byId('bpmn-status').dataset.error = String(error);
  };
  const names = {'Create StartEvent':'Startereignis erstellen','Create EndEvent':'Endereignis erstellen','Create Task':'Aufgabe erstellen','Create expanded SubProcess':'Unterprozess erstellen','Create ExclusiveGateway':'Gateway erstellen','Create Pool/Participant':'Pool erstellen','Activate the hand tool':'Verschieben','Activate the lasso tool':'Mehrfachauswahl','Activate the create/remove space tool':'Abstände ändern','Activate the global connect tool':'Verbindung erstellen','Remove':'Entfernen','Change type':'Typ ändern','Connect using Sequence/MessageFlow or Association':'Verbinden','Append Task':'Aufgabe anhängen','Append EndEvent':'Endereignis anhängen','Append Gateway':'Gateway anhängen','Append Intermediate/Boundary Event':'Zwischenereignis anhängen','Add TextAnnotation':'Notiz hinzufügen'};
  const translate = (text, values) => (names[text] || text).replace(/\{([^}]+)\}/g, (_, key) => values && key in values ? values[key] : '{' + key + '}');
  const editor = new BpmnJS({container:'#bpmn-canvas',textRenderer:{defaultStyle:{fontFamily:'Arial, sans-serif',fontSize:15},externalStyle:{fontSize:13}},bpmnRenderer:{defaultFillColor:'#f7fbfc',defaultStrokeColor:'#386c79',defaultLabelColor:'#173b49'},additionalModules:[{translate:['value',translate]}]});
  let ready = false, dirty = false, busy = false, generation = 0, selected = null, viewSnapshot = null;
  const buttons = ['bpmn-save','bpmn-publish','bpmn-export','bpmn-svg','bpmn-fit','bpmn-zoom-in','bpmn-zoom-out','bpmn-check','bpmn-align','bpmn-size','bpmn-space','bpmn-select-all'];
  const refresh = () => buttons.forEach(id => {if (byId(id)) byId(id).disabled = !ready || busy;});
  const markDirty = () => {dirty = true; generation++; status('Ungespeicherte Änderungen.');};
  const download = (data, extension, type) => {
    const url = URL.createObjectURL(new Blob([data], {type}));
    const link = document.createElement('a');
    link.href = url; link.download = config.code.replace(/[^a-zA-Z0-9_-]/g, '_') + '.' + extension;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const run = async callback => {
    if (busy) return;
    busy = true; refresh();
    try {await callback();} catch (error) {status(error.message || 'Aktion fehlgeschlagen. Bitte den Stand exportieren und erneut versuchen.', true);}
    finally {busy = false; refresh();}
  };
  const canvas = editor.get('canvas');
  const naturalView = () => {
    canvas.resized();canvas.zoom('fit-viewport');
    const inner=canvas.viewbox().inner, width=byId('bpmn-canvas').clientWidth, height=byId('bpmn-canvas').clientHeight;
    const left=config.edit?160:24;
    const scale=Math.min(1.1,Math.max(.05,Math.min((width-left-24)/Math.max(1,inner.width),(height-48)/Math.max(1,inner.height))));
    canvas.viewbox({x:inner.x-left/scale,y:inner.y-(height/scale-inner.height)/2,width:width/scale,height:height/scale});
  };
  let workspaceSize = null;
  const resizeWorkspace = () => {
    const shell=byId('bpmn-shell'),toolbar=shell.querySelector('.bpmn-toolbar'),utility=shell.querySelector('.flow-utility');
    const shellBox=shell.getBoundingClientRect();
    shell.style.setProperty('--flow-tools-height',Math.round(utility.getBoundingClientRect().bottom-shellBox.top)+'px');
    shell.style.setProperty('--flow-menu-height',Math.max(80,shell.clientHeight-toolbar.offsetHeight-20)+'px');
    const width=byId('bpmn-canvas').clientWidth,height=byId('bpmn-canvas').clientHeight;
    if(width<1||height<1)return;
    const changed=!workspaceSize||workspaceSize.width!==width||workspaceSize.height!==height;
    if(changed){const saved=viewSnapshot;workspaceSize={width,height};canvas.resized();if(ready&&saved)canvas.viewbox({x:saved.x-width/saved.zoom/2,y:saved.y-height/saved.zoom/2,width:width/saved.zoom,height:height/saved.zoom});}
    if(ready&&!config.edit&&readerSelected&&!restoring)revealSelection(registry.get(readerSelected));
  };
  const fit = () => canvas.zoom('fit-viewport');
  byId('bpmn-fit').addEventListener('click', fit);
  byId('bpmn-zoom-in').addEventListener('click', () => canvas.zoom(Math.min(3,canvas.zoom() * 1.25)));
  byId('bpmn-zoom-out').addEventListener('click', () => canvas.zoom(Math.max(.05,canvas.zoom() / 1.25)));
  const fullscreen = () => {
    const enabled = byId('bpmn-shell').classList.toggle('is-fullscreen');
    document.body.classList.toggle('flow-fullscreen-open', enabled);
    byId('bpmn-fullscreen').textContent = enabled ? 'Schließen' : 'Vollbild';
    requestAnimationFrame(resizeWorkspace);
  };
  byId('bpmn-fullscreen').addEventListener('click',fullscreen);
  window.addEventListener('keydown',event => {if (event.key === 'Escape' && !byId('flow-preview').open && !byId('flow-info')?.open && byId('bpmn-shell').classList.contains('is-fullscreen')) fullscreen();});
  byId('bpmn-export').addEventListener('click', () => run(async () => download((await editor.saveXML({format:true})).xml, 'bpmn', 'application/xml')));
  byId('bpmn-svg').addEventListener('click', () => run(async () => download((await editor.saveSVG()).svg, 'svg', 'image/svg+xml')));
  const linkIds = BpmnTools.linkIds;
  const targets = element => {
    const ids = linkIds(element);
    return [config.processes.find(item => String(item.id) === ids.PROCESS), (config.documents || []).find(item => String(item.id) === ids.DOCUMENT)].filter(Boolean);
  };
  const registry = editor.get('elementRegistry');
  let readerSelected = null, restoring = true, detailsRequest = null;
  let fingerprint=0;for(const char of config.xml)fingerprint=((fingerprint*31)^char.charCodeAt(0))|0;
  const statePrefix = 'ims-flow:' + document.body.dataset.account + ':';
  const stateKey = statePrefix + config.stateKey + ':' + config.edit + ':' + fingerprint;
  const persist = () => {
    if (!ready || restoring || config.edit) return;
    const box = canvas.viewbox();
    try {
      const keys = Object.keys(sessionStorage).filter(key => key.startsWith(statePrefix));
      while (keys.length > 80) sessionStorage.removeItem(keys.shift());
      sessionStorage.setItem(stateKey,JSON.stringify({x:box.x+box.width/2,y:box.y+box.height/2,zoom:box.scale,selected:readerSelected}));
    } catch (_) { /* Navigation remains usable with disabled browser storage. */ }
  };
  let stateTimer;
  editor.on('canvas.viewbox.changed', event => {const box=event.viewbox||canvas.viewbox();viewSnapshot={x:box.x+box.width/2,y:box.y+box.height/2,zoom:box.scale};clearTimeout(stateTimer);stateTimer=setTimeout(persist,150);});
  window.addEventListener('pagehide',persist);
  window.addEventListener('pageshow',event => {if (event.persisted && ready) restore();});
  const restore = () => {
    if (config.edit) return;
    try {
      const state = JSON.parse(sessionStorage.getItem(stateKey) || 'null');
      if (!state || ![state.x,state.y,state.zoom].every(Number.isFinite) || state.zoom < .01 || state.zoom > 3) return;
      const width = byId('bpmn-canvas').clientWidth / state.zoom, height = byId('bpmn-canvas').clientHeight / state.zoom;
      canvas.viewbox({x:state.x-width/2,y:state.y-height/2,width,height});
      if (state.selected && registry.get(state.selected)) openElement(registry.get(state.selected),false);
    } catch (_) { /* Ignore outdated or malformed view state. */ }
  };
  const focusElement = element => {
    const box=canvas.viewbox();
    const x=element.x ?? element.waypoints?.[0]?.x ?? box.x, y=element.y ?? element.waypoints?.[0]?.y ?? box.y;
    canvas.viewbox({x:x+(element.width||0)/2-box.width/2,y:y+(element.height||0)/2-box.height/2,width:box.width,height:box.height});
  };
  const highlight = element => {
    for (const entry of registry.getAll().filter(item=>registry.getGraphics(item))) for (const marker of ['flow-selected','flow-neighbour','flow-active']) canvas.removeMarker(entry,marker);
    for (const entry of registry.getAll()) {const graphic=registry.getGraphics(entry);if(graphic?.getAttribute('role')==='button')graphic.setAttribute('aria-pressed',String(entry===element));}
    if (!element) return;
    canvas.addMarker(element,'flow-selected');
    for (const edge of registry.getAll().filter(item=>item.type==='bpmn:SequenceFlow' && (item.source===element || item.target===element))) {
      canvas.addMarker(edge,'flow-active');const other=edge.source===element?edge.target:edge.source;
      if (other) canvas.addMarker(other,'flow-neighbour');
    }
  };
  const revealSelection = element => {
    const panel=byId('flow-details');
    if(!element||!panel||panel.hidden)return;
    const node=registry.getGraphics(element)?.getBoundingClientRect();if(!node)return;
    const area=byId('bpmn-canvas').getBoundingClientRect(),details=panel.getBoundingClientRect(),box=canvas.viewbox();
    const bottom=window.matchMedia('(max-width:600px)').matches?details.top:area.bottom;
    const right=window.matchMedia('(max-width:600px)').matches?area.right:details.left;
    let dx=0,dy=0;
    if(node.right>right-12||node.left<area.left+12)dx=(node.left+node.right-area.left-right)/2/box.scale;
    if(node.bottom>bottom-12||node.top<area.top+12)dy=(node.top+node.bottom-area.top-bottom)/2/box.scale;
    if(dx||dy)canvas.viewbox({x:box.x+dx,y:box.y+dy,width:box.width,height:box.height});
  };
  if(byId('flow-info-open'))byId('flow-info-open').addEventListener('click',()=>byId('flow-info').showModal());
  if(byId('flow-info-close'))byId('flow-info-close').addEventListener('click',()=>byId('flow-info').close());
  if(byId('flow-checks-close'))byId('flow-checks-close').addEventListener('click',()=>{byId('flow-checks').hidden=true;});
  const closeDetails = () => {if (detailsRequest) detailsRequest.abort();byId('flow-details').hidden=true;readerSelected=null;highlight(null);persist();};
  if (byId('flow-details-close')) byId('flow-details-close').addEventListener('click',closeDetails);
  if (!config.edit) for (const summary of document.querySelectorAll('.flow-manage > summary,.bpmn-export-menu > summary')) summary.addEventListener('click',()=>{if(!summary.parentElement.open)closeDetails();});
  const preview = item => {
    persist();byId('flow-preview-title').textContent=item.title;
    byId('flow-preview-open').href=item.url;
    byId('flow-preview-frame').src=item.preview_url;
    byId('flow-preview').showModal();
  };
  const closePreview = () => {byId('flow-preview').close();byId('flow-preview-frame').removeAttribute('src');};
  byId('flow-preview-close').addEventListener('click',closePreview);
  byId('flow-preview-open').addEventListener('click',()=>{persist();closePreview();});
  byId('flow-preview').addEventListener('cancel',() => byId('flow-preview-frame').removeAttribute('src'));
  const openElement = (element,move=false) => {
    if (!element || !element.businessObject || element===canvas.getRootElement()) {closeDetails();return;}
    if (detailsRequest) detailsRequest.abort();
    readerSelected=element.id;highlight(element);
    if (move) focusElement(element);
    const panel=byId('flow-details');panel.hidden=false;
    byId('flow-step-title').textContent=element.businessObject.name || 'Prozessschritt';
    const kind=element.type.replace('bpmn:','');
    byId('flow-step-type').textContent=({Task:'Aufgabe',CallActivity:'Verknüpfter Prozess',ExclusiveGateway:'Entscheidung',StartEvent:'Beginn',EndEvent:'Ende',SubProcess:'Unterprozess'})[kind] || 'Prozessschritt';
    const description=byId('flow-step-description');
    description.textContent=(element.businessObject.documentation||[]).filter(doc=>!/^IMS-(PROCESS|DOCUMENT)-ID:/.test(doc.text||'')).map(doc=>doc.textFormat==='text/html'?(doc.text||'').replace(/<[^>]*>/g,' '):doc.text||'').join('\n');
    const actions=byId('flow-step-actions');actions.replaceChildren();
    const ids=linkIds(element);
    const process=config.processes.find(item=>String(item.id)===ids.PROCESS);
    const documentTarget=(config.documents||[]).find(item=>String(item.id)===ids.DOCUMENT);
    const action=(title,item,callback) => {
      const note=document.createElement('p');note.className='flow-target-title';note.textContent=item.title;actions.append(note);
      const button=document.createElement(callback?'button':'a');button.className='button';button.textContent=title;
      if(callback)button.addEventListener('click',callback);else {button.href=item.url;button.addEventListener('click',persist);}
      actions.append(button);
    };
    if(process) {
      action('Unterprozess öffnen',process);
      detailsRequest=new AbortController();
      fetch(process.info_url,{credentials:'same-origin',signal:detailsRequest.signal,cache:'no-store'}).then(response=>response.ok?response.json():null).then(info=>{
        if(info && readerSelected===element.id && !description.textContent) description.textContent=info.description || '';
      }).catch(()=>{});
    }
    if(documentTarget)action(documentTarget.preview_url?'Dokument ansehen':'Dokument öffnen',documentTarget,documentTarget.preview_url?()=>preview(documentTarget):null);
    if((ids.PROCESS&&!process)||(ids.DOCUMENT&&!documentTarget)) {const text=document.createElement('p');text.textContent='Eine Verknüpfung ist derzeit nicht zugänglich.';actions.append(text);}
    if(!process&&!documentTarget&&!Object.keys(ids).length&&!description.textContent)description.textContent='Für diesen Schritt sind noch keine zusätzlichen Informationen hinterlegt.';
    const neighbours=byId('flow-neighbours');neighbours.replaceChildren();
    for(const [label,edges] of [['Vorher',element.incoming||[]],['Danach',element.outgoing||[]]]) {
      const nodes=edges.filter(edge=>edge.type==='bpmn:SequenceFlow').map(edge=>label==='Vorher'?edge.source:edge.target);
      if(nodes.length) {const heading=document.createElement('h3');heading.textContent=label;neighbours.append(heading);}
      for(const node of nodes) {const button=document.createElement('button');button.className='secondary';button.textContent=node.businessObject.name||'Prozessschritt';button.addEventListener('click',()=>openElement(node,true));neighbours.append(button);}
    }
    if(!restoring)revealSelection(element);
    persist();
  };
  byId('flow-back').addEventListener('click',() => {
    persist();
    if (document.referrer && new URL(document.referrer).origin===location.origin && history.length>1) history.back();
    else window.location.assign(config.parent_url || '/processes/');
  });
  let searchTimer;
  const searchResults=document.createElement('div');searchResults.id='flow-find-results';searchResults.className='flow-find-results';searchResults.hidden=true;byId('flow-find').parentElement.after(searchResults);
  byId('flow-find').addEventListener('input',()=>{
    clearTimeout(searchTimer);searchTimer=setTimeout(()=>{
      const term=byId('flow-find').value.trim().toLocaleLowerCase('de');searchResults.replaceChildren();searchResults.hidden=!term;
      if(!term){byId('flow-find-count').textContent='';return;}
      const matches=registry.getAll().filter(e=>!e.labelTarget && e.businessObject && e!==canvas.getRootElement() && BpmnTools.searchable(e,config.processes,config.documents||[]).includes(term));
      const matchedProcesses=new Set(matches.map(e=>linkIds(e).PROCESS));
      const external=config.processes.filter(p=>p.title.toLocaleLowerCase('de').includes(term)&&!matchedProcesses.has(String(p.id)));
      byId('flow-find-count').textContent=(matches.length+external.length)+' Treffer';
      for(const element of matches.slice(0,30)) {const button=document.createElement('button');button.className='secondary';button.textContent=element.businessObject.name||'Prozessschritt';button.addEventListener('click',()=>{focusElement(element);if(config.edit)editor.get('selection').select(element);else openElement(element);searchResults.hidden=true;});searchResults.append(button);}
      for(const item of external.slice(0,Math.max(0,30-matches.length))) {const link=document.createElement('a');link.href=item.url;link.textContent=item.title;link.addEventListener('click',persist);searchResults.append(link);}
      if(!matches.length&&!external.length) {const link=document.createElement('a');link.href='/documents/?q='+encodeURIComponent(term);link.textContent='In der Dokumentenübersicht suchen';searchResults.append(link);}
    },180);
  });
  const annotate = () => {
    const registry = editor.get('elementRegistry');
    editor.get('overlays').remove({type:'ims-link'});
    for (const element of registry.getAll()) {
      if (element.labelTarget || !element.businessObject || element.type === 'bpmn:Process') continue;
      const links = targets(element), graphic = registry.getGraphics(element);
      if (!graphic) continue;
      graphic.classList.toggle('ims-linked',links.length > 0);
      if (!config.edit && element.type!=='bpmn:SequenceFlow') {
        graphic.setAttribute('tabindex','0');graphic.setAttribute('role','button');graphic.setAttribute('aria-label',element.businessObject.name || links[0]?.title || 'Prozessschritt');
        graphic.onkeydown = event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault();openElement(element);byId('flow-step-title').focus();}};
      }
      if (links.length) {
        const badge = document.createElement('span');badge.className = 'flow-link-badge';badge.textContent = linkIds(element).DOCUMENT ? '▤' : '↳';badge.setAttribute('aria-hidden','true');
        editor.get('overlays').add(element,'ims-link',{position:{bottom:16,right:20},html:badge});
      }
    }
  };
  if (config.edit) {
    const properties=document.querySelector('.bpmn-properties');
    const setProperties = enabled => {properties.classList.toggle('is-open',enabled);byId('flow-properties-toggle').setAttribute('aria-expanded',String(enabled));};
    byId('flow-properties-toggle').addEventListener('click',()=>{setProperties(!properties.classList.contains('is-open'));document.querySelector('.flow-edit-menu').open=false;});
    byId('flow-properties-close').addEventListener('click',()=>setProperties(false));
    for (const process of config.processes) byId('bpmn-link').add(new Option(process.title, String(process.id)));
    for (const doc of config.documents || []) byId('bpmn-document').add(new Option(doc.title,String(doc.id)));
    editor.on('commandStack.changed', markDirty);
    const check = () => {
      const found=BpmnTools.issues(registry.getAll(),config.processes,config.documents||[]);
      byId('flow-checks').hidden=false;byId('flow-check-list').replaceChildren();
      if(!found.length)byId('flow-check-list').textContent='Keine strukturellen Hinweise gefunden. Die fachliche Prüfung bleibt erforderlich.';
      for(const issue of found){const button=document.createElement('button');button.className='secondary';button.textContent=issue.text;button.addEventListener('click',()=>{const element=registry.get(issue.id);if(element){focusElement(element);editor.get('selection').select(element);}});byId('flow-check-list').append(button);}
      return found;
    };
    byId('bpmn-check').addEventListener('click',check);
    const layoutSelection = minimum => {
      const shapes=editor.get('selection').get().filter(e=>!e.waypoints&&!e.labelTarget&&!e.host&&e.parent);
      if(shapes.length<minimum || new Set(shapes.map(e=>e.parent)).size>1) {status('Mindestens '+minimum+' Elemente derselben Ebene auswählen.',true);return null;}
      return shapes;
    };
    for(const id of ['bpmn-check','bpmn-align','bpmn-size','bpmn-space','bpmn-new'])byId(id).addEventListener('click',()=>{document.querySelector('.flow-edit-menu').open=false;});
    byId('bpmn-canvas').addEventListener('pointerdown',()=>{document.querySelector('.flow-edit-menu').open=false;});
    byId('bpmn-select-all').addEventListener('click',()=>{const shapes=registry.getAll().filter(e=>e.parent===canvas.getRootElement()&&!e.waypoints&&!e.labelTarget&&!e.host);editor.get('selection').select(shapes);status(shapes.length+' Elemente ausgewählt.');});
    byId('bpmn-align').addEventListener('click',()=>{const shapes=layoutSelection(2);if(shapes)editor.get('alignElements').trigger(shapes,'middle');});
    byId('bpmn-space').addEventListener('click',()=>{const shapes=layoutSelection(3);if(shapes)editor.get('distributeElements').trigger(shapes,'horizontal');});
    function ResizeGroup(modeling){this.preExecute=context=>{for(const shape of context.shapes)modeling.resizeShape(shape,{x:shape.x,y:shape.y,width:context.width,height:context.height});};this.execute=()=>{};this.revert=()=>{};}
    ResizeGroup.$inject=['modeling'];editor.get('commandStack').registerHandler('ims.resize',ResizeGroup);
    byId('bpmn-size').addEventListener('click',()=>{
      const shapes=layoutSelection(2);if(!shapes)return;
      if(shapes.some(e=>!(/Task$/.test(e.type)||e.type==='bpmn:CallActivity'))){status('Gleiche Größe ist für Aufgaben und aufgerufene Prozesse verfügbar.',true);return;}
      editor.get('commandStack').execute('ims.resize',{shapes,width:Math.max(120,shapes[0].width),height:Math.max(80,shapes[0].height)});
    });
    editor.on('selection.changed', event => {
      selected = event.newSelection.length === 1 ? (event.newSelection[0].labelTarget || event.newSelection[0]) : null;
      const usable = !!(selected && selected.businessObject && selected.type.startsWith('bpmn:'));
      if(usable&&window.matchMedia('(max-width:900px)').matches)setProperties(true);
      byId('bpmn-name').disabled = !usable; byId('bpmn-link').disabled = !usable;byId('bpmn-document').disabled = !usable;
      byId('bpmn-selection').textContent = usable ? selected.businessObject.name || 'BPMN-Element' : 'Element im Diagramm auswählen.';
      byId('bpmn-name').value = usable ? selected.businessObject.name || '' : '';
      byId('bpmn-link').value = usable ? linkIds(selected).PROCESS || '' : '';
      byId('bpmn-document').value = usable ? linkIds(selected).DOCUMENT || '' : '';
    });
    byId('bpmn-name').addEventListener('change', event => {
      if (selected) editor.get('modeling').updateProperties(selected, {name:event.target.value});
    });
    const updateLink = (kind,value) => {
      if (!selected) return;
      const marker = new RegExp('^IMS-' + kind + '-ID:\\d+$');
      const docs = (selected.businessObject.documentation || []).filter(doc => !marker.test(doc.text || ''));
      if (value) docs.push(editor.get('moddle').create('bpmn:Documentation',{text:'IMS-' + kind + '-ID:' + value}));
      editor.get('modeling').updateProperties(selected,{documentation:docs});annotate();
    };
    byId('bpmn-link').addEventListener('change', event => updateLink('PROCESS',event.target.value));
    byId('bpmn-document').addEventListener('change', event => updateLink('DOCUMENT',event.target.value));
    for (const [id, publish] of [['bpmn-save',false],['bpmn-publish',true]]) byId(id).addEventListener('click', () => run(async () => {
      if(publish && check().length && !confirm('Es gibt Modellierungshinweise. Trotzdem veröffentlichen?'))return;
      const token = generation;
      const xml = (await editor.saveXML({format:true})).xml;
      const response = await fetch(config.url, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify({xml,expected:config.expected,publish,reason:byId('bpmn-reason').value})});
      let result;
      try {result = await response.json();} catch (_) {throw new Error('Serverantwort ungültig. Sitzung prüfen und vor dem Neuladen BPMN exportieren.');}
      if (!response.ok) throw new Error(result.error || 'Speichern fehlgeschlagen.');
      config.expected = result.version;
      if (generation === token) dirty = false;
      status(result.message + (dirty ? ' Weitere lokale Änderungen sind noch nicht gespeichert.' : ''));
    }));
    byId('bpmn-import').addEventListener('change', event => run(async () => {
      const file = event.target.files[0]; event.target.value = '';
      if (!file) return;
      if (file.size > 2097152) throw new Error('Datei darf höchstens 2 MiB groß sein.');
      if (dirty && !confirm('Ungespeicherten Zeichenstand durch den Import ersetzen?')) return;
      const xml = await file.text();
      if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error('DTD und XML-Entitäten sind nicht erlaubt.');
      const old = (await editor.saveXML({format:true})).xml;
      try {
        const result = await editor.importXML(xml);
        if (result.warnings.length && !confirm('Import enthält ' + result.warnings.length + ' Hinweise. Nicht unterstützte Elemente/Erweiterungen können entfallen. Import trotzdem übernehmen?')) {
          await editor.importXML(old); return;
        }
        fit(); annotate(); markDirty(); status('BPMN importiert. Noch nicht gespeichert.' + (result.warnings.length ? ' Importhinweise: ' + result.warnings.map(w => w.message).join('; ') : ''));
      } catch (error) {
        await editor.importXML(old);
        throw new Error('Import fehlgeschlagen; bisheriges Diagramm wiederhergestellt. ' + error.message);
      }
    }));
    byId('bpmn-new').addEventListener('click', () => run(async () => {
      if (!confirm('Neuen lokalen Zeichenstand beginnen? Vorhandenen Stand bei Bedarf zuerst exportieren.')) return;
      await editor.createDiagram(); fit(); markDirty();
    }));
    window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});
  } else {
    let origin = null, moved = false;
    byId('bpmn-canvas').addEventListener('pointerdown',event => {origin = {x:event.clientX,y:event.clientY};moved = false;},true);
    byId('bpmn-canvas').addEventListener('pointermove',event => {if (origin && Math.hypot(event.clientX-origin.x,event.clientY-origin.y)>8) moved = true;},true);
    editor.on('element.click',event => {if (!moved) openElement(event.element.labelTarget || event.element);});
  }
  const workspaceObserver=new ResizeObserver(()=>requestAnimationFrame(resizeWorkspace));
  for(const element of [document.querySelector('.bpmn-workspace'),document.querySelector('.bpmn-toolbar'),document.querySelector('.flow-utility'),byId('flow-details')].filter(Boolean))workspaceObserver.observe(element);
  resizeWorkspace();
  run(async () => {
    if (!config.xml) {status('Noch keine Prozesse oder veröffentlichten Diagramme vorhanden.'); return;}
    const result = await editor.importXML(config.xml);
    ready = true; naturalView(); annotate(); dirty = false;restore();restoring=false;
    status(result.warnings.length ? 'Diagramm geladen mit Hinweisen: ' + result.warnings.map(w => w.message).join('; ') : config.edit ? 'Editor bereit. Änderungen werden nicht automatisch gespeichert.' : 'Schritte anklicken · Zum Verschieben ziehen · + / − zum Zoomen');
    byId('bpmn-canvas').dispatchEvent(new CustomEvent('bpmn-ready'));
  });
})();
