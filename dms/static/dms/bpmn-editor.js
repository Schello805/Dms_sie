/* Basic flowchart tools on the bundled BPMN modeler; all edits use its undo stack. */
(() => {
  'use strict';
  window.BpmnEditor = ({editor, config, getSelection, updateLink, status}) => {
    const byId = id => document.getElementById(id);
    const shell = byId('bpmn-shell'), dialog = byId('flow-link-picker');
    const stack = editor.get('commandStack'), registry = editor.get('elementRegistry');
    let ready = false, busy = false, picker = null, visible = 40;
    const items = kind => kind === 'PROCESS' ? config.processes : config.documents || [];
    const linkable = element => !!element && !element.waypoints && !element.labelTarget &&
      /^bpmn:.*(?:Task|Activity|Event|Gateway|SubProcess)$/.test(element.type);
    const title = (element, kind) => {
      const id = BpmnTools.linkIds(element)[kind];
      if (!id) return kind === 'PROCESS' ? 'Kein Prozess verknüpft.' : 'Kein Dokument verknüpft.';
      return items(kind).find(item => String(item.id) === id)?.title || 'Nicht mehr verfügbare Verknüpfung (ID ' + id + ')';
    };
    const sync = () => {
      const selected = getSelection(), allowed = ready && !busy && linkable(selected);
      for (const [kind, prefix] of [['PROCESS','process'],['DOCUMENT','document']]) {
        byId('flow-' + prefix + '-pick').disabled = !allowed;
        byId('flow-' + prefix + '-current').textContent = selected ? title(selected,kind) : 'Element auswählen.';
      }
      for (const button of shell.querySelectorAll('[data-flow-shape],#flow-connect')) button.disabled = !ready || busy;
      byId('flow-undo').disabled = !ready || busy || !stack.canUndo();
      byId('flow-redo').disabled = !ready || busy || !stack.canRedo();
    };
    byId('bpmn-canvas').addEventListener('bpmn-state', event => {({ready,busy} = event.detail);sync();});
    editor.on('selection.changed', sync);
    editor.on('commandStack.changed', sync);
    const close = () => {dialog.close();picker = null;};
    const apply = id => {
      if (!picker || busy || !ready) return;
      const element = registry.get(picker.element.id);
      if (element !== picker.element || !linkable(element)) {
        close();status('Das Element ist nicht mehr vorhanden. Bitte erneut auswählen.', true);return;
      }
      updateLink(picker.kind, id, element);close();sync();
    };
    const render = () => {
      if (!picker) return;
      const term = byId('flow-link-query').value.trim().toLocaleLowerCase('de');
      const found = items(picker.kind).filter(item =>
        (item.title + ' ' + (item.level || '')).toLocaleLowerCase('de').includes(term));
      const list = byId('flow-link-results');list.replaceChildren();
      const current = BpmnTools.linkIds(picker.element)[picker.kind];
      byId('flow-link-count').textContent = found.length + ' Treffer · ' + Math.min(visible,found.length) + ' angezeigt';
      if (!found.length) {
        const note = document.createElement('p');note.textContent = 'Keine passenden Einträge gefunden.';list.append(note);
      }
      for (const item of found.slice(0,visible)) {
        const button = document.createElement('button');button.type = 'button';button.className = 'secondary flow-link-option';
        button.setAttribute('aria-pressed',String(String(item.id) === current));
        const name = document.createElement('strong');name.textContent = item.title;button.append(name);
        const hint = document.createElement('span');
        hint.textContent = picker.kind === 'DOCUMENT' ? 'Aktuelle freigegebene Fassung' :
          (item.level || 'Prozess') + (item.available === false ? ' · Noch nicht als Lesefassung verfügbar' : '');
        button.append(hint);button.addEventListener('click',() => apply(String(item.id)));list.append(button);
      }
      byId('flow-link-more').hidden = found.length <= visible;
    };
    const open = kind => {
      const element = getSelection();if (!ready || busy || !linkable(element)) return;
      picker = {kind,element};visible = 40;
      byId('flow-link-picker-title').textContent = kind === 'PROCESS' ? 'Prozess auswählen' : 'Dokument auswählen';
      byId('flow-link-picker-step').textContent = 'Für: ' + (element.businessObject.name || 'Unbenannter Schritt');
      byId('flow-link-remove').disabled = !BpmnTools.linkIds(element)[kind];
      byId('flow-link-query').value = '';render();dialog.showModal();byId('flow-link-query').focus();
    };
    byId('flow-process-pick').addEventListener('click',() => open('PROCESS'));
    byId('flow-document-pick').addEventListener('click',() => open('DOCUMENT'));
    byId('flow-link-query').addEventListener('input',() => {visible = 40;render();});
    byId('flow-link-more').addEventListener('click',() => {visible += 40;render();});
    byId('flow-link-picker-close').addEventListener('click',close);
    byId('flow-link-cancel').addEventListener('click',close);
    byId('flow-link-remove').addEventListener('click',() => apply(''));
    dialog.addEventListener('close',() => {picker = null;});
    for (const button of shell.querySelectorAll('[data-flow-shape]')) button.addEventListener('click',event => {
      if (!ready || busy) return;
      const shape = editor.get('elementFactory').createShape({type:button.dataset.flowShape});
      editor.get('create').start(event,shape);
      status('Auf die Zeichenfläche klicken, um das Element zu platzieren. Esc bricht ab.');
    });
    byId('flow-connect').addEventListener('click',() => {
      if (!ready || busy) return;
      editor.get('globalConnect').toggle();status('Ausgangsschritt und anschließend Ziel anklicken. Esc bricht ab.');
    });
    byId('flow-undo').addEventListener('click',() => {if (!busy && stack.canUndo()) stack.undo();});
    byId('flow-redo').addEventListener('click',() => {if (!busy && stack.canRedo()) stack.redo();});
    byId('flow-advanced').addEventListener('click',() => {
      const expanded = shell.classList.toggle('flow-advanced-tools');
      byId('flow-advanced').setAttribute('aria-pressed',String(expanded));
      byId('flow-advanced').textContent = expanded ? 'Grundformen' : 'Weitere Formen';
    });
    sync();
    return {sync};
  };
})();
