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
  const editor = new BpmnJS({container:'#bpmn-canvas',additionalModules:[{translate:['value',translate]}]});
  let ready = false, dirty = false, busy = false, generation = 0, selected = null;
  const buttons = ['bpmn-save','bpmn-publish','bpmn-export','bpmn-svg','bpmn-fit'];
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
  const fit = () => editor.get('canvas').zoom('fit-viewport');
  byId('bpmn-fit').addEventListener('click', fit);
  byId('bpmn-export').addEventListener('click', () => run(async () => download((await editor.saveXML({format:true})).xml, 'bpmn', 'application/xml')));
  byId('bpmn-svg').addEventListener('click', () => run(async () => download((await editor.saveSVG()).svg, 'svg', 'image/svg+xml')));
  const linkFor = element => {
    const docs = element.businessObject && element.businessObject.documentation || [];
    for (const doc of docs) {
      const match = /^IMS-PROCESS-ID:(\d+)$/.exec(doc.text || '');
      if (match) return match[1];
    }
    return '';
  };
  if (config.edit) {
    for (const process of config.processes) byId('bpmn-link').add(new Option(process.title, String(process.id)));
    editor.on('commandStack.changed', markDirty);
    editor.on('selection.changed', event => {
      selected = event.newSelection.length === 1 ? (event.newSelection[0].labelTarget || event.newSelection[0]) : null;
      const usable = !!(selected && selected.businessObject && selected.type.startsWith('bpmn:'));
      byId('bpmn-name').disabled = !usable; byId('bpmn-link').disabled = !usable;
      byId('bpmn-selection').textContent = usable ? selected.id : 'Element im Diagramm auswählen.';
      byId('bpmn-name').value = usable ? selected.businessObject.name || '' : '';
      byId('bpmn-link').value = usable ? linkFor(selected) : '';
    });
    byId('bpmn-name').addEventListener('change', event => {
      if (selected) editor.get('modeling').updateProperties(selected, {name:event.target.value});
    });
    byId('bpmn-link').addEventListener('change', event => {
      if (!selected) return;
      const docs = (selected.businessObject.documentation || []).filter(doc => !/^IMS-PROCESS-ID:\d+$/.test(doc.text || ''));
      if (event.target.value) docs.push(editor.get('moddle').create('bpmn:Documentation', {text:'IMS-PROCESS-ID:' + event.target.value}));
      editor.get('modeling').updateProperties(selected, {documentation:docs});
    });
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
        fit(); markDirty(); status('BPMN importiert. Noch nicht gespeichert.' + (result.warnings.length ? ' Importhinweise: ' + result.warnings.map(w => w.message).join('; ') : ''));
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
    editor.on('element.dblclick', event => {
      const id = linkFor(event.element);
      if (config.processes.some(process => String(process.id) === id)) window.location.assign('/processes/' + id + '/');
      else if (id) status('Der verknüpfte Prozess ist derzeit nicht zugänglich.', true);
    });
  }
  run(async () => {
    if (!config.xml) {status('Für diesen Prozess wurde noch kein BPMN-Diagramm veröffentlicht.'); return;}
    const result = await editor.importXML(config.xml);
    ready = true; fit(); dirty = false;
    status(result.warnings.length ? 'Diagramm geladen mit Hinweisen: ' + result.warnings.map(w => w.message).join('; ') : config.edit ? 'Editor bereit. Änderungen werden nicht automatisch gespeichert.' : 'Diagramm geladen. Verknüpfte Prozesse öffnen sich per Doppelklick.');
    // CI observes the same editor instance used by the UI, without a second rendering path.
    byId('bpmn-canvas').dispatchEvent(new CustomEvent('bpmn-ready'));
  });
})();
