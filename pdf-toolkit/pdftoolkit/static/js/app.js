/* PDF-Toolkit – Oberfläche.
 *
 * Aufbau: ein State-Objekt, eine zentrale request()-Funktion und pro
 * Werkzeug ein Abschnitt. Passwörter für geschützte PDFs bleiben nur im
 * Speicher dieser Seite – sie werden nie im Arbeitsbereich abgelegt.
 */

const state = {
  files: [],          // alles im Arbeitsbereich
  passwords: {},      // fileId -> Passwort, nur zur Laufzeit
  merge: [],          // Reihenfolge fürs Zusammenfügen: {id, pages}
  organize: null,     // {fileId, pages: [{page, rotate, removed}]}
  edit: {fileId: null, page: 1, info: null, items: [], tool: 'text', selected: null},
  forms: {fileId: null, fields: []},
};

const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

// ---------------------------------------------------------------- Grundlagen

function toast(message, kind = 'info', html = null) {
  const node = document.createElement('div');
  node.className = `toast is-${kind}`;
  if (html) node.innerHTML = html; else node.textContent = message;
  $('#toasts').append(node);
  setTimeout(() => node.remove(), kind === 'error' ? 8000 : 5000);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function askPassword(message) {
  return new Promise((resolve) => {
    const dialog = $('#password-dialog');
    $('#password-message').textContent = message || '';
    const input = $('#password-input');
    input.value = '';
    dialog.showModal();
    dialog.addEventListener('close', () => {
      resolve(dialog.returnValue === 'ok' ? input.value : null);
    }, {once: true});
  });
}

/* Zentrale Anfrage. Antwortet der Server mit 423 (gesperrt), wird einmal
   nach dem Passwort gefragt und der Aufruf wiederholt. */
async function request(path, {method = 'GET', json = null, form = null, fileId = null} = {}) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const options = {method, headers: {}};

    if (form) {
      options.body = form;
    } else if (json) {
      const body = {...json};
      if (fileId && state.passwords[fileId]) body.password = state.passwords[fileId];
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }

    let url = path;
    if (!json && !form && fileId && state.passwords[fileId]) {
      url += (url.includes('?') ? '&' : '?') + 'password=' + encodeURIComponent(state.passwords[fileId]);
    }

    const response = await fetch(url, options);
    let data = {};
    try { data = await response.json(); } catch { /* z.B. leere Antwort */ }

    if (response.ok) return data;

    if (response.status === 423 && fileId && attempt === 0) {
      const password = await askPassword(data.error);
      if (password === null) throw new Error('Abgebrochen.');
      state.passwords[fileId] = password;
      continue;
    }

    throw new Error(data.error || `Fehler ${response.status}`);
  }
  throw new Error('Passwort nicht akzeptiert.');
}

/* Umschlag für Knöpfe: sperrt den Knopf, meldet Fehler, lädt die Liste neu. */
async function run(button, action, successMessage) {
  const original = button?.textContent;
  if (button) { button.disabled = true; button.textContent = 'Einen Moment …'; }
  try {
    const result = await action();
    if (result?.file) {
      showResult(result.file, successMessage);
      await loadFiles();
    } else if (successMessage) {
      toast(successMessage, 'ok');
    }
    return result;
  } catch (error) {
    toast(error.message, 'error');
    return null;
  } finally {
    if (button) { button.disabled = false; button.textContent = original; }
  }
}

function showResult(file, message) {
  toast(null, 'ok',
    `<strong>${message || 'Fertig'}</strong><br>${file.name} · ` +
    `<a href="/api/files/${file.id}/download">herunterladen</a>`);
}

// ---------------------------------------------------------------- Dateien

async function loadFiles() {
  const data = await request('/api/files');
  state.files = data.files || [];
  renderFileList();
  renderFileSelects();
  renderMergeList();
  renderImageList();
}

function renderFileList() {
  const list = $('#file-list');
  list.innerHTML = '';

  if (!state.files.length) {
    list.innerHTML = '<li class="hint">Noch keine Dateien.</li>';
    return;
  }

  for (const file of state.files) {
    const item = document.createElement('li');
    item.className = 'file-item' + (file.kind === 'result' ? ' is-result' : '');
    item.innerHTML = `
      <span title="${file.is_pdf ? 'PDF' : 'Bild'}">${file.is_pdf ? '📄' : '🖼️'}</span>
      <span>
        <span class="file-name"></span>
        <span class="file-meta">${formatSize(file.size)} · ${file.origin}</span>
      </span>
      <span class="file-actions">
        <a class="icon-btn" href="/api/files/${file.id}/download" title="Herunterladen">⤓</a>
        <button class="icon-btn danger" title="Entfernen">✕</button>
      </span>`;
    $('.file-name', item).textContent = file.name;
    $('.icon-btn.danger', item).addEventListener('click', async () => {
      await request(`/api/files/${file.id}`, {method: 'DELETE'});
      if (state.organize?.fileId === file.id) resetOrganize();
      if (state.edit.fileId === file.id) resetEdit();
      await loadFiles();
    });
    list.append(item);
  }
}

/* Alle <select class="file-select"> mit den passenden Dateien füllen und
   dabei die bisherige Auswahl behalten. */
function renderFileSelects() {
  for (const select of $$('.file-select')) {
    const wantsImages = select.id === 'edit-image';
    const options = state.files.filter((file) => (wantsImages ? !file.is_pdf : file.is_pdf));
    const previous = select.value;

    select.innerHTML = options.length
      ? options.map((file) => `<option value="${file.id}">${file.name}</option>`).join('')
      : `<option value="">${wantsImages ? 'Kein Bild vorhanden' : 'Kein PDF vorhanden'}</option>`;

    if (options.some((file) => file.id === previous)) select.value = previous;
    else select.dispatchEvent(new Event('change'));
  }
}

async function uploadFiles(fileList) {
  const form = new FormData();
  let count = 0;
  for (const file of fileList) { form.append('files', file); count += 1; }
  if (!count) return;

  await run(null, async () => {
    await request('/api/upload', {method: 'POST', form});
    await loadFiles();
    toast(`${count} ${count === 1 ? 'Datei' : 'Dateien'} hinzugefügt.`, 'ok');
  });
}

function setupDropzone() {
  const zone = $('#dropzone');
  const input = $('#file-input');

  $('#pick-files').addEventListener('click', () => input.click());
  input.addEventListener('change', () => { uploadFiles(input.files); input.value = ''; });

  for (const type of ['dragenter', 'dragover']) {
    zone.addEventListener(type, (event) => { event.preventDefault(); zone.classList.add('is-over'); });
  }
  for (const type of ['dragleave', 'drop']) {
    zone.addEventListener(type, () => zone.classList.remove('is-over'));
  }
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    uploadFiles(event.dataTransfer.files);
  });

  $('#clear-files').addEventListener('click', async () => {
    if (!confirm('Alle Dateien im Arbeitsbereich löschen?')) return;
    await request('/api/files/clear', {method: 'POST'});
    resetOrganize(); resetEdit();
    state.merge = [];
    await loadFiles();
  });
}

// ---------------------------------------------------------------- Reiter

function setupTabs() {
  $('#tabs').addEventListener('click', (event) => {
    const tab = event.target.closest('.tab');
    if (!tab) return;
    $$('.tab').forEach((item) => item.classList.toggle('is-active', item === tab));
    $$('.panel').forEach((panel) => {
      panel.classList.toggle('is-active', panel.id === `panel-${tab.dataset.panel}`);
    });
  });
}

/* Ziehen zum Umsortieren – wird von Zusammenfügen und Organisieren genutzt. */
function makeSortable(container, itemSelector, onReorder) {
  let dragged = null;

  container.addEventListener('dragstart', (event) => {
    dragged = event.target.closest(itemSelector);
    if (!dragged) return;
    dragged.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', '');
  });

  container.addEventListener('dragend', () => {
    dragged?.classList.remove('is-dragging');
    $$(itemSelector, container).forEach((item) => item.classList.remove('is-over'));
    dragged = null;
  });

  container.addEventListener('dragover', (event) => {
    event.preventDefault();
    const target = event.target.closest(itemSelector);
    if (!target || target === dragged) return;
    $$(itemSelector, container).forEach((item) => item.classList.toggle('is-over', item === target));
  });

  container.addEventListener('drop', (event) => {
    event.preventDefault();
    const target = event.target.closest(itemSelector);
    if (!target || !dragged || target === dragged) return;

    const items = $$(itemSelector, container);
    onReorder(items.indexOf(dragged), items.indexOf(target));
  });
}

// ---------------------------------------------------------------- Zusammenfügen

function renderMergeList() {
  const list = $('#merge-list');
  const pdfs = state.files.filter((file) => file.is_pdf);

  // Auswahl mit dem Arbeitsbereich abgleichen: Neues aufnehmen, Gelöschtes werfen.
  state.merge = state.merge.filter((entry) => pdfs.some((file) => file.id === entry.id));
  for (const file of pdfs) {
    if (!state.merge.some((entry) => entry.id === file.id)) {
      state.merge.push({id: file.id, pages: '', include: file.kind === 'upload'});
    }
  }

  list.innerHTML = '';
  $('#merge-empty').hidden = pdfs.length >= 2;

  for (const entry of state.merge) {
    const file = pdfs.find((item) => item.id === entry.id);
    const row = document.createElement('li');
    row.className = 'merge-item';
    row.draggable = true;
    row.dataset.id = entry.id;
    row.innerHTML = `
      <span class="grip" title="Ziehen zum Sortieren">⠿</span>
      <label class="checkbox"><input type="checkbox" ${entry.include ? 'checked' : ''}>
        <span class="file-name"></span></label>
      <input type="text" placeholder="alle Seiten" value="${entry.pages}" title="Seitenauswahl, z. B. 1-3,7">
      <span class="file-meta">${formatSize(file.size)}</span>`;
    $('.file-name', row).textContent = file.name;
    $('input[type=checkbox]', row).addEventListener('change', (event) => {
      entry.include = event.target.checked;
    });
    $('input[type=text]', row).addEventListener('input', (event) => {
      entry.pages = event.target.value.trim();
    });
    list.append(row);
  }
}

function setupMerge() {
  makeSortable($('#merge-list'), '.merge-item', (from, to) => {
    const [moved] = state.merge.splice(from, 1);
    state.merge.splice(to, 0, moved);
    renderMergeList();
  });

  $('#do-merge').addEventListener('click', (event) => {
    const chosen = state.merge.filter((entry) => entry.include);
    if (chosen.length < 2) { toast('Bitte mindestens zwei PDFs ankreuzen.', 'error'); return; }

    run(event.target, () => request('/api/merge', {
      method: 'POST',
      json: {
        files: chosen.map((entry) => ({
          id: entry.id,
          pages: entry.pages || null,
          password: state.passwords[entry.id] || null,
        })),
        bookmarks: $('#merge-bookmarks').checked,
        name: $('#merge-name').value.trim() || 'zusammengefuegt.pdf',
      },
    }), 'Zusammengefügt');
  });
}

// ---------------------------------------------------------------- Teilen

function setupSplit() {
  const modes = $$('#split-mode input');
  const update = () => {
    const mode = modes.find((input) => input.checked).value;
    $$('[data-mode]').forEach((node) => { node.hidden = node.dataset.mode !== mode; });
  };
  modes.forEach((input) => input.addEventListener('change', update));
  update();

  $('#do-split').addEventListener('click', (event) => {
    const fileId = $('#split-file').value;
    if (!fileId) { toast('Bitte ein PDF wählen.', 'error'); return; }

    const mode = modes.find((input) => input.checked).value;
    const body = {file: fileId, mode};

    if (mode === 'ranges') {
      body.ranges = $('#split-ranges').value.split('\n').map((line) => line.trim()).filter(Boolean);
      if (!body.ranges.length) { toast('Bitte mindestens einen Bereich angeben.', 'error'); return; }
    } else if (mode === 'chunks') {
      body.chunk_size = Number($('#split-chunk').value) || 10;
    } else if (mode === 'extract') {
      body.pages = $('#split-pages').value.trim();
      if (!body.pages) { toast('Bitte die gewünschten Seiten angeben.', 'error'); return; }
    }

    run(event.target, () => request('/api/split', {method: 'POST', json: body, fileId}), 'Geteilt');
  });
}

// ---------------------------------------------------------------- Organisieren

function resetOrganize() {
  state.organize = null;
  $('#organize-grid').innerHTML = '';
  $('#organize-toolbar').hidden = true;
  $('#do-organize').disabled = true;
}

async function loadOrganize(fileId) {
  resetOrganize();
  if (!fileId) return;

  const data = await request(`/api/files/${fileId}/info`, {fileId}).catch((error) => {
    toast(error.message, 'error');
    return null;
  });
  if (!data) return;

  state.organize = {
    fileId,
    pages: data.info.pages.map((page) => ({page: page.number, rotate: 0, removed: false})),
  };
  renderOrganize();
}

function renderOrganize() {
  const grid = $('#organize-grid');
  grid.innerHTML = '';
  if (!state.organize) return;

  const {fileId, pages} = state.organize;
  const password = state.passwords[fileId];

  pages.forEach((entry, index) => {
    const card = document.createElement('div');
    card.className = 'page-card' + (entry.removed ? ' is-removed' : '');
    card.draggable = !entry.removed;
    card.innerHTML = `
      <img loading="lazy" alt="Seite ${entry.page}"
           class="${entry.rotate % 180 ? 'is-sideways' : ''}"
           src="/api/files/${fileId}/page/${entry.page}.png?width=200${password ? '&password=' + encodeURIComponent(password) : ''}"
           style="--angle: ${entry.rotate}deg; transform: rotate(${entry.rotate}deg)">
      <span class="label">Seite ${entry.page}${entry.rotate ? ` · ${entry.rotate}°` : ''}</span>
      <span class="card-actions">
        <button class="icon-btn" data-do="left" title="Links drehen">↺</button>
        <button class="icon-btn" data-do="right" title="Rechts drehen">↻</button>
        <button class="icon-btn ${entry.removed ? '' : 'danger'}" data-do="toggle"
                title="${entry.removed ? 'Wiederherstellen' : 'Entfernen'}">${entry.removed ? '↩' : '✕'}</button>
      </span>`;

    $$('button', card).forEach((button) => button.addEventListener('click', () => {
      if (button.dataset.do === 'left') entry.rotate = (entry.rotate + 270) % 360;
      if (button.dataset.do === 'right') entry.rotate = (entry.rotate + 90) % 360;
      if (button.dataset.do === 'toggle') entry.removed = !entry.removed;
      renderOrganize();
    }));

    card.dataset.index = String(index);
    grid.append(card);
  });

  const kept = pages.filter((entry) => !entry.removed).length;
  $('#organize-count').textContent = `${kept} von ${pages.length} Seiten bleiben erhalten`;
  $('#organize-toolbar').hidden = false;
  $('#do-organize').disabled = kept === 0;
}

function setupOrganize() {
  $('#organize-file').addEventListener('change', (event) => loadOrganize(event.target.value));
  $('#organize-reset').addEventListener('click', () => loadOrganize($('#organize-file').value));

  makeSortable($('#organize-grid'), '.page-card', (from, to) => {
    const [moved] = state.organize.pages.splice(from, 1);
    state.organize.pages.splice(to, 0, moved);
    renderOrganize();
  });

  $('#organize-toolbar').addEventListener('click', (event) => {
    const button = event.target.closest('[data-all]');
    if (!button || !state.organize) return;
    const delta = button.dataset.all === 'left' ? 270 : 90;
    state.organize.pages.forEach((entry) => { entry.rotate = (entry.rotate + delta) % 360; });
    renderOrganize();
  });

  $('#do-organize').addEventListener('click', (event) => {
    const {fileId, pages} = state.organize;
    const layout = pages.filter((entry) => !entry.removed)
      .map((entry) => ({page: entry.page, rotate: entry.rotate}));

    run(event.target, async () => {
      const result = await request('/api/organize', {method: 'POST', json: {file: fileId, layout}, fileId});
      return result;
    }, 'Seiten organisiert');
  });
}

// ---------------------------------------------------------------- Bearbeiten

const TOOL_DEFAULTS = {
  text: {w: 0.35, h: 0.06}, image: {w: 0.25, h: 0.15}, rect: {w: 0.3, h: 0.1},
  ellipse: {w: 0.25, h: 0.12}, line: {w: 0.3, h: 0.0}, highlight: {w: 0.4, h: 0.035},
  redact: {w: 0.3, h: 0.05},
};

function resetEdit() {
  state.edit = {fileId: null, page: 1, info: null, items: [], tool: state.edit.tool, selected: null};
  $('#edit-stage').innerHTML = '<p class="stage-empty">Wähle oben ein PDF aus.</p>';
  $('#edit-page').innerHTML = '';
  $('#edit-items').innerHTML = '';
  $('#do-edit').disabled = true;
}

async function loadEditDocument(fileId) {
  if (!fileId) { resetEdit(); return; }

  const data = await request(`/api/files/${fileId}/info`, {fileId}).catch((error) => {
    toast(error.message, 'error');
    return null;
  });
  if (!data) { resetEdit(); return; }

  state.edit = {fileId, page: 1, info: data.info, items: [], tool: state.edit.tool, selected: null};
  $('#edit-page').innerHTML = data.info.pages
    .map((page) => `<option value="${page.number}">Seite ${page.number}</option>`).join('');
  renderStage();
  renderEditItems();
}

function renderStage() {
  const stage = $('#edit-stage');
  const {fileId, page} = state.edit;
  if (!fileId) return;

  const password = state.passwords[fileId];
  stage.innerHTML = `
    <div class="stage-page">
      <img alt="Seite ${page}" src="/api/files/${fileId}/page/${page}.png?width=900${password ? '&password=' + encodeURIComponent(password) : ''}">
      <div class="stage-overlay"></div>
    </div>`;

  const overlay = $('.stage-overlay', stage);
  overlay.addEventListener('pointerdown', (event) => {
    if (event.target !== overlay) return;   // Klick auf ein Element ist Verschieben
    addEditItem(event, overlay);
  });

  drawEditItems();
}

/* Neues Element dort anlegen, wo geklickt wurde – Position als Anteil der Seite. */
function addEditItem(event, overlay) {
  const bounds = overlay.getBoundingClientRect();
  const tool = state.edit.tool;
  const size = TOOL_DEFAULTS[tool];

  const item = {
    id: Math.random().toString(36).slice(2, 9),
    type: tool,
    page: state.edit.page,
    x: Math.min(Math.max((event.clientX - bounds.left) / bounds.width, 0), 0.98),
    y: Math.min(Math.max((event.clientY - bounds.top) / bounds.height, 0), 0.98),
    w: size.w,
    h: size.h || 0.04,
    color: $('#edit-color').value,
  };

  if (tool === 'text') {
    item.text = $('#edit-text').value || 'Neuer Text';
    item.size = Number($('#edit-size').value) || 14;
    item.font = $('#edit-font').value;
  } else if (tool === 'image') {
    item.image_id = $('#edit-image').value;
    if (!item.image_id) { toast('Lade zuerst ein Bild in den Arbeitsbereich.', 'error'); return; }
  } else if (tool === 'line') {
    item.x2 = Math.min(item.x + size.w, 1);
    item.y2 = item.y;
  } else if ((tool === 'rect' || tool === 'ellipse') && $('#edit-filled').checked) {
    item.fill = item.color;
  } else if (tool === 'highlight') {
    item.color = '#ffe14d';
  } else if (tool === 'redact') {
    item.color = '#000000';
  }

  state.edit.items.push(item);
  state.edit.selected = item.id;
  drawEditItems();
  renderEditItems();
}

function drawEditItems() {
  const overlay = $('.stage-overlay');
  if (!overlay) return;
  overlay.innerHTML = '';

  for (const item of state.edit.items.filter((entry) => entry.page === state.edit.page)) {
    const node = document.createElement('div');
    node.className = 'stage-item' + (item.id === state.edit.selected ? ' is-selected' : '');
    node.dataset.kind = item.type;
    node.dataset.id = item.id;

    const height = item.type === 'line' ? 0.008 : item.h;
    node.style.cssText = `left:${item.x * 100}%;top:${item.y * 100}%;` +
      `width:${(item.type === 'line' ? Math.abs((item.x2 ?? item.x) - item.x) : item.w) * 100}%;` +
      `height:${height * 100}%;`;

    if (item.type === 'text') {
      node.textContent = item.text;
      node.style.color = item.color;
    } else if (item.type === 'image') {
      node.textContent = '🖼️';
    } else if (item.type === 'line') {
      node.style.borderTop = `2px solid ${item.color}`;
      node.style.background = 'transparent';
    } else if (item.type === 'rect' || item.type === 'ellipse') {
      node.style.borderColor = item.color;
      if (item.type === 'ellipse') node.style.borderRadius = '50%';
      if (item.fill) node.style.background = item.fill + '66';
    }

    const handle = document.createElement('span');
    handle.className = 'handle';
    node.append(handle);

    makeDraggable(node, item, overlay, handle);
    overlay.append(node);
  }
}

/* Verschieben und Skalieren eines Elements über Pointer-Ereignisse. */
function makeDraggable(node, item, overlay, handle) {
  const start = (event, mode) => {
    event.preventDefault();
    event.stopPropagation();
    state.edit.selected = item.id;
    renderEditItems();

    const bounds = overlay.getBoundingClientRect();
    // Startwerte einfrieren: Maus- und Elementposition zu Beginn der Geste.
    const origin = {
      pointerX: event.clientX, pointerY: event.clientY,
      xStart: item.x, yStart: item.y, wStart: item.w, hStart: item.h,
      x2Start: item.x2 ?? item.x, y2Start: item.y2 ?? item.y,
    };

    const move = (moveEvent) => {
      const dx = (moveEvent.clientX - origin.pointerX) / bounds.width;
      const dy = (moveEvent.clientY - origin.pointerY) / bounds.height;

      if (mode === 'move') {
        // Nicht über den Seitenrand hinaus: das Element bleibt vollständig sichtbar.
        item.x = Math.min(clamp(origin.xStart + dx), Math.max(0, 1 - item.w));
        item.y = Math.min(clamp(origin.yStart + dy), Math.max(0, 1 - item.h));
        if (item.type === 'line') {
          item.x2 = clamp(origin.x2Start + dx);
          item.y2 = clamp(origin.y2Start + dy);
        }
      } else if (item.type === 'line') {
        item.x2 = clamp(origin.x2Start + dx);
        item.y2 = clamp(origin.y2Start + dy);
      } else {
        item.w = Math.max(0.02, Math.min(origin.wStart + dx, 1 - item.x));
        item.h = Math.max(0.01, Math.min(origin.hStart + dy, 1 - item.y));
      }
      drawEditItems();
    };

    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      renderEditItems();
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  };

  node.addEventListener('pointerdown', (event) => {
    if (event.target === handle) return;
    start(event, 'move');
  });
  handle.addEventListener('pointerdown', (event) => start(event, 'resize'));
}

const clamp = (value) => Math.min(Math.max(value, 0), 1);

function renderEditItems() {
  const list = $('#edit-items');
  list.innerHTML = '';
  $('#do-edit').disabled = state.edit.items.length === 0;

  if (!state.edit.items.length) {
    list.innerHTML = '<li class="hint">Noch keine Elemente. Klicke auf die Seite.</li>';
    return;
  }

  const labels = {text: 'Text', image: 'Bild', rect: 'Rahmen', ellipse: 'Ellipse',
                  line: 'Linie', highlight: 'Markierung', redact: 'Schwärzung'};

  for (const item of state.edit.items) {
    const row = document.createElement('li');
    row.className = 'item-row' + (item.id === state.edit.selected ? ' is-selected' : '');
    row.innerHTML = `
      <span><span class="kind">${labels[item.type]} · S.${item.page}</span><br><span class="what"></span></span>
      <button class="icon-btn danger" title="Löschen">✕</button>`;
    $('.what', row).textContent = item.text || (item.type === 'image' ? 'Bilddatei' : '—');

    row.addEventListener('click', (event) => {
      if (event.target.tagName === 'BUTTON') return;
      state.edit.selected = item.id;
      if (item.page !== state.edit.page) {
        state.edit.page = item.page;
        $('#edit-page').value = String(item.page);
        renderStage();
      }
      drawEditItems();
      renderEditItems();
    });

    $('button', row).addEventListener('click', () => {
      state.edit.items = state.edit.items.filter((entry) => entry.id !== item.id);
      drawEditItems();
      renderEditItems();
    });

    list.append(row);
  }
}

function setupEdit() {
  $('#edit-file').addEventListener('change', (event) => loadEditDocument(event.target.value));
  $('#edit-page').addEventListener('change', (event) => {
    state.edit.page = Number(event.target.value);
    renderStage();
  });

  $('#edit-tools').addEventListener('click', (event) => {
    const button = event.target.closest('.tool');
    if (!button) return;
    state.edit.tool = button.dataset.tool;
    $$('.tool').forEach((item) => item.classList.toggle('is-active', item === button));
  });

  $('#edit-clear').addEventListener('click', () => {
    state.edit.items = [];
    drawEditItems();
    renderEditItems();
  });

  $('#do-edit').addEventListener('click', (event) => {
    const {fileId, items} = state.edit;
    const annotations = items.map(({id, ...rest}) => rest);
    run(event.target, () => request('/api/edit', {
      method: 'POST', json: {file: fileId, annotations}, fileId,
    }), 'Bearbeitet');
  });

  $('#do-watermark').addEventListener('click', (event) => {
    const fileId = $('#edit-file').value;
    const text = $('#wm-text').value.trim();
    if (!fileId || !text) { toast('PDF wählen und Text eingeben.', 'error'); return; }

    run(event.target, () => request('/api/watermark', {
      method: 'POST', fileId,
      json: {file: fileId, text, color: $('#wm-color').value,
             opacity: Number($('#wm-opacity').value), angle: Number($('#wm-angle').value)},
    }), 'Wasserzeichen gesetzt');
  });

  $('#do-page-numbers').addEventListener('click', (event) => {
    const fileId = $('#edit-file').value;
    if (!fileId) { toast('Bitte ein PDF wählen.', 'error'); return; }

    run(event.target, () => request('/api/page-numbers', {
      method: 'POST', fileId,
      json: {file: fileId, position: $('#pn-position').value,
             template: $('#pn-template').value || '{page}', start_at: Number($('#pn-start').value)},
    }), 'Seitenzahlen eingefügt');
  });
}

// ---------------------------------------------------------------- Formulare

async function loadForm(fileId) {
  const container = $('#forms-fields');
  container.innerHTML = '';
  $('#forms-actions').hidden = true;
  state.forms = {fileId, fields: []};
  if (!fileId) return;

  const data = await request(`/api/forms/${fileId}`, {fileId}).catch((error) => {
    toast(error.message, 'error');
    return null;
  });
  if (!data) return;

  state.forms.fields = data.fields;

  if (!data.fields.length) {
    container.innerHTML = '<p class="hint">Dieses PDF enthält keine Formularfelder.</p>';
    return;
  }

  for (const field of data.fields) {
    const row = document.createElement('div');
    row.className = 'form-field' + (field.readonly ? ' is-readonly' : '');
    row.innerHTML = `
      <span><span class="name"></span><br><span class="file-meta">Seite ${field.page}</span></span>
      <span class="control"></span>
      <span class="badge">${field.type}</span>`;
    $('.name', row).textContent = field.label || field.name;

    const control = $('.control', row);
    let input;

    if (field.type === 'CheckBox') {
      input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = Boolean(field.value);
    } else if (field.options?.length) {
      input = document.createElement('select');
      input.innerHTML = '<option value=""></option>' +
        field.options.map((option) => {
          const value = Array.isArray(option) ? option[0] : option;
          return `<option value="${value}">${value}</option>`;
        }).join('');
      input.value = field.value ?? '';
    } else {
      input = document.createElement('input');
      input.type = 'text';
      input.value = field.value ?? '';
      input.style.width = '100%';
    }

    input.disabled = field.readonly;
    input.dataset.field = field.name;
    control.append(input);
    container.append(row);
  }

  $('#forms-actions').hidden = false;
}

function collectFormValues() {
  const values = {};
  for (const input of $$('#forms-fields [data-field]')) {
    if (input.disabled) continue;
    values[input.dataset.field] = input.type === 'checkbox' ? input.checked : input.value;
  }
  return values;
}

function setupForms() {
  $('#forms-file').addEventListener('change', (event) => loadForm(event.target.value));

  $('#do-fill').addEventListener('click', (event) => {
    const fileId = state.forms.fileId;
    if (!fileId) { toast('Bitte ein Formular wählen.', 'error'); return; }

    run(event.target, () => request(`/api/forms/${fileId}/fill`, {
      method: 'POST', fileId,
      json: {values: collectFormValues(), flatten: $('#forms-flatten').checked},
    }), 'Formular ausgefüllt');
  });

  $('#do-flatten').addEventListener('click', (event) => {
    const fileId = state.forms.fileId;
    if (!fileId) { toast('Bitte ein Formular wählen.', 'error'); return; }
    run(event.target, () => request(`/api/forms/${fileId}/flatten`, {
      method: 'POST', json: {}, fileId,
    }), 'Formular fixiert');
  });
}

// ---------------------------------------------------------------- Umwandeln

function renderImageList() {
  const list = $('#image-list');
  const images = state.files.filter((file) => !file.is_pdf);
  list.innerHTML = '';
  $('#image-empty').hidden = images.length > 0;

  for (const image of images) {
    const row = document.createElement('li');
    row.className = 'merge-item';
    row.draggable = true;
    row.dataset.id = image.id;
    row.innerHTML = `
      <span class="grip">⠿</span>
      <label class="checkbox"><input type="checkbox" checked> <span class="file-name"></span></label>
      <span></span><span class="file-meta">${formatSize(image.size)}</span>`;
    $('.file-name', row).textContent = image.name;
    list.append(row);
  }
}

function setupConvert() {
  const fileOf = () => $('#convert-file').value;
  const pagesOf = () => $('#convert-pages').value.trim() || null;

  $('#do-word').addEventListener('click', (event) => {
    if (!fileOf()) { toast('Bitte ein PDF wählen.', 'error'); return; }
    run(event.target, () => request('/api/convert/word', {
      method: 'POST', fileId: fileOf(), json: {file: fileOf(), pages: pagesOf()},
    }), 'Word-Datei erstellt');
  });

  $('#do-text').addEventListener('click', async (event) => {
    if (!fileOf()) { toast('Bitte ein PDF wählen.', 'error'); return; }
    const result = await run(event.target, () => request('/api/convert/text', {
      method: 'POST', fileId: fileOf(), json: {file: fileOf(), pages: pagesOf()},
    }), 'Text extrahiert');
    if (result?.preview !== undefined) {
      const preview = $('#text-preview');
      preview.textContent = result.preview || '(kein Text gefunden – vermutlich ein Scan)';
      preview.hidden = false;
    }
  });

  $('#do-images').addEventListener('click', (event) => {
    if (!fileOf()) { toast('Bitte ein PDF wählen.', 'error'); return; }
    run(event.target, () => request('/api/convert/images', {
      method: 'POST', fileId: fileOf(),
      json: {file: fileOf(), pages: pagesOf(), dpi: Number($('#convert-dpi').value),
             format: $('#convert-format').value},
    }), 'Bilder erstellt');
  });

  makeSortable($('#image-list'), '.merge-item', (from, to) => {
    const list = $('#image-list');
    const items = $$('.merge-item', list);
    if (from < to) items[to].after(items[from]); else items[to].before(items[from]);
  });

  $('#do-images-to-pdf').addEventListener('click', (event) => {
    const ids = $$('#image-list .merge-item')
      .filter((row) => $('input[type=checkbox]', row).checked)
      .map((row) => row.dataset.id);
    if (!ids.length) { toast('Bitte mindestens ein Bild ankreuzen.', 'error'); return; }

    run(event.target, () => request('/api/convert/images-to-pdf', {
      method: 'POST', json: {files: ids, name: 'bilder.pdf'},
    }), 'PDF aus Bildern erstellt');
  });
}

// ---------------------------------------------------------------- Schützen

function setupProtect() {
  const fileOf = () => $('#protect-file').value;

  $('#do-encrypt').addEventListener('click', (event) => {
    const password = $('#protect-password').value;
    if (!fileOf() || !password) { toast('PDF wählen und Passwort setzen.', 'error'); return; }

    run(event.target, () => request('/api/security/encrypt', {
      method: 'POST', fileId: fileOf(),
      json: {file: fileOf(), user_password: password, allow_printing: $('#protect-print').checked},
    }), 'Verschlüsselt');
  });

  $('#do-decrypt').addEventListener('click', (event) => {
    const password = $('#protect-open').value;
    if (!fileOf() || !password) { toast('PDF wählen und Passwort eingeben.', 'error'); return; }

    run(event.target, () => request('/api/security/decrypt', {
      method: 'POST', json: {file: fileOf(), password},
    }), 'Schutz entfernt');
  });

  $('#do-compress').addEventListener('click', async (event) => {
    if (!fileOf()) { toast('Bitte ein PDF wählen.', 'error'); return; }
    const result = await run(event.target, () => request('/api/compress', {
      method: 'POST', fileId: fileOf(),
      json: {file: fileOf(), quality: Number($('#compress-quality').value)},
    }), 'Verkleinert');

    if (result?.stats) {
      const {before, after, ratio} = result.stats;
      $('#compress-stats').textContent =
        `${formatSize(before)} → ${formatSize(after)} (${Math.round((1 - ratio) * 100)}% kleiner)`;
    }
  });
}

// ---------------------------------------------------------------- Start

document.addEventListener('DOMContentLoaded', async () => {
  setupDropzone();
  setupTabs();
  setupMerge();
  setupSplit();
  setupOrganize();
  setupEdit();
  setupForms();
  setupConvert();
  setupProtect();

  resetEdit();

  try {
    const health = await request('/api/health');
    if (!health.word_export) {
      $('#do-word').disabled = true;
      $('#do-word').title = 'pdf2docx ist nicht installiert';
    }
    await loadFiles();
  } catch (error) {
    toast('Der Server antwortet nicht: ' + error.message, 'error');
  }
});
