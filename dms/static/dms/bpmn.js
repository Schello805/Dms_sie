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
  let ready = false, dirty = false, busy = false, generation = 0, selected = null;
  const buttons = ['bpmn-save','bpmn-publish','bpmn-export','bpmn-svg','bpmn-fit','bpmn-zoom-in','bpmn-zoom-out'];
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
    canvas.zoom('fit-viewport');
    const inner = canvas.viewbox().inner;
    const width = byId('bpmn-canvas').clientWidth;
    const scale = Math.min(1.1, Math.max(.85, width / (inner.width + 64)));
    if (!config.edit && !byId('bpmn-shell').classList.contains('is-fullscreen')) {
      byId('bpmn-canvas').style.height = Math.round(Math.min(window.innerHeight * .62, Math.max(260, (inner.height + 96) * scale))) + 'px';
      canvas.resized();
    }
    const height = byId('bpmn-canvas').clientHeight;
    canvas.viewbox({x:inner.x - 28,y:inner.y - Math.max(28,(height / scale - inner.height) / 2),width:width / scale,height:height / scale});
  };
  const fit = () => canvas.zoom('fit-viewport');
  byId('bpmn-fit').addEventListener('click', fit);
  byId('bpmn-zoom-in').addEventListener('click', () => canvas.zoom(Math.min(3,canvas.zoom() * 1.25)));
  byId('bpmn-zoom-out').addEventListener('click', () => canvas.zoom(Math.max(.2,canvas.zoom() / 1.25)));
  const fullscreen = () => {
    const enabled = byId('bpmn-shell').classList.toggle('is-fullscreen');
    document.body.classList.toggle('flow-fullscreen-open', enabled);
    byId('bpmn-fullscreen').textContent = enabled ? 'Schließen' : 'Vollbild';
    canvas.resized();
    if (ready) naturalView();
  };
  byId('bpmn-fullscreen').addEventListener('click',fullscreen);
  window.addEventListener('keydown',event => {if (event.key === 'Escape' && byId('bpmn-shell').classList.contains('is-fullscreen')) fullscreen();});
  byId('bpmn-export').addEventListener('click', () => run(async () => download((await editor.saveXML({format:true})).xml, 'bpmn', 'application/xml')));
  byId('bpmn-svg').addEventListener('click', () => run(async () => download((await editor.saveSVG()).svg, 'svg', 'image/svg+xml')));
  const linkIds = element => {
    const result = {};
    for (const doc of element.businessObject && element.businessObject.documentation || []) {
      const match = /^IMS-(PROCESS|DOCUMENT)-ID:(\d+)$/.exec(doc.text || '');
      if (match) result[match[1]] = match[2];
    }
    return result;
  };
  const targets = element => {
    const ids = linkIds(element);
    return [config.processes.find(item => String(item.id) === ids.PROCESS), (config.documents || []).find(item => String(item.id) === ids.DOCUMENT)].filter(Boolean);
  };
  const openElement = element => {
    const available = targets(element);
    const menu = byId('bpmn-link-menu'); menu.replaceChildren(); menu.hidden = true;
    if (available.length === 1) {window.location.assign(available[0].url); return;}
    if (available.length > 1) {
      for (const item of available) {const link = document.createElement('a'); link.href = item.url; link.textContent = item.title; menu.append(link);}
      const close = document.createElement('button'); close.textContent = 'Schließen';close.className = 'secondary';close.addEventListener('click', () => {menu.hidden = true;});menu.append(close);menu.hidden = false;menu.querySelector('a').focus();
    } else if (Object.keys(linkIds(element)).length) status('Die Verknüpfung ist derzeit nicht zugänglich.',true);
  };
  const annotate = () => {
    const registry = editor.get('elementRegistry');
    editor.get('overlays').remove({type:'ims-link'});
    for (const element of registry.getAll()) {
      if (element.labelTarget || !element.businessObject || element.type === 'bpmn:Process') continue;
      const links = targets(element), graphic = registry.getGraphics(element);
      if (!graphic) continue;
      graphic.classList.toggle('ims-linked',links.length > 0);
      if (!config.edit && links.length) {
        graphic.setAttribute('tabindex','0');graphic.setAttribute('role','link');graphic.setAttribute('aria-label',element.businessObject.name || links[0].title);
        graphic.onkeydown = event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault();openElement(element);}};
      }
      if (links.length) {
        const badge = document.createElement('span');badge.className = 'flow-link-badge';badge.textContent = linkIds(element).DOCUMENT ? '▤' : '↳';badge.setAttribute('aria-hidden','true');
        editor.get('overlays').add(element,'ims-link',{position:{bottom:16,right:20},html:badge});
      }
    }
  };
  if (config.edit) {
    for (const process of config.processes) byId('bpmn-link').add(new Option(process.title, String(process.id)));
    for (const doc of config.documents || []) byId('bpmn-document').add(new Option(doc.title,String(doc.id)));
    editor.on('commandStack.changed', markDirty);
    editor.on('selection.changed', event => {
      selected = event.newSelection.length === 1 ? (event.newSelection[0].labelTarget || event.newSelection[0]) : null;
      const usable = !!(selected && selected.businessObject && selected.type.startsWith('bpmn:'));
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
  run(async () => {
    if (!config.xml) {status('Noch keine Prozesse oder veröffentlichten Diagramme vorhanden.'); return;}
    const result = await editor.importXML(config.xml);
    ready = true; naturalView(); annotate(); dirty = false;
    status(result.warnings.length ? 'Diagramm geladen mit Hinweisen: ' + result.warnings.map(w => w.message).join('; ') : config.edit ? 'Editor bereit. Änderungen werden nicht automatisch gespeichert.' : 'Schritte anklicken · Zum Verschieben ziehen · + / − zum Zoomen');
    // CI observes the same editor instance used by the UI, without a second rendering path.
    byId('bpmn-canvas').dispatchEvent(new CustomEvent('bpmn-ready'));
  });
})();
