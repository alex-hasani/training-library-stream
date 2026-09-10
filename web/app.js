const catalog = document.querySelector('#catalog');
const search = document.querySelector('#search');
const sort = document.querySelector('#sort');
const empty = document.querySelector('#empty');
const status = document.querySelector('#status');
const preview = document.querySelector('#preview');
const previewTitle = document.querySelector('#preview-title');
const viewer = document.querySelector('#viewer');
let library = null;
let progressByPath = {};

const mediaExtensions = new Set(['mp4', 'webm', 'ogv', 'm4v', 'mov']);
const audioExtensions = new Set(['mp3', 'wav', 'ogg', 'm4a', 'flac']);
const imageExtensions = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']);
const embeddedExtensions = new Set(['pdf', 'txt', 'md', 'csv', 'json', 'html', 'htm']);
const icon = item => item.type === 'folder' ? '▸' : mediaExtensions.has(item.extension) ? '▶' : '•';
const fileUrl = item => `/files/${item.relativePath.split('/').map(encodeURIComponent).join('/')}`;
const formatTime = seconds => { const total = Math.floor(seconds || 0); return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`; };
function itemMeta(item) {
  if (item.type !== 'file') return `${item.fileCount} files`;
  const progress = progressByPath[item.relativePath];
  if (!mediaExtensions.has(item.extension) || !progress) return item.extension;
  if (progress.duration && progress.position >= progress.duration - 5) return `${item.extension} · completed`;
  return `${item.extension} · watched ${formatTime(progress.position)}`;
}

function compareItems(a, b) {
  if (sort.value === 'name') return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
  const kindA = a.type === 'folder' ? '0-folder' : `1-${a.extension || 'other'}`;
  const kindB = b.type === 'folder' ? '0-folder' : `1-${b.extension || 'other'}`;
  return kindA.localeCompare(kindB) || a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
}
function hasMatch(item, term) {
  return item.name.toLowerCase().includes(term) || item.relativePath.toLowerCase().includes(term) || (item.children || []).some(child => hasMatch(child, term));
}
function addNode(item, target, term = '') {
  const matches = !term || item.name.toLowerCase().includes(term) || item.relativePath.toLowerCase().includes(term);
  const matchingChildren = (item.children || []).filter(child => matches || hasMatch(child, term)).sort(compareItems);
  if (!matches && !matchingChildren.length) return false;
  const row = document.createElement(item.type === 'folder' ? 'details' : 'button');
  row.className = `tree-item ${item.type}`;
  if (item.type === 'folder') row.open = Boolean(term);
  if (item.type === 'file') { row.type = 'button'; row.addEventListener('click', () => openPreview(item)); }
  const label = document.createElement(item.type === 'folder' ? 'summary' : 'span');
  label.className = 'item-label';
  label.innerHTML = `<span class="icon" aria-hidden="true">${icon(item)}</span><span class="item-name">${escapeHtml(item.name)}</span>${item.type === 'unavailable' ? '<span class="meta">Unavailable</span>' : `<span class="meta">${escapeHtml(itemMeta(item))}</span>`}`;
  row.append(label);
  if (item.type === 'folder' && matchingChildren.length) {
    const children = document.createElement('div'); children.className = 'children';
    matchingChildren.forEach(child => addNode(child, children, term)); row.append(children);
  }
  target.append(row); return true;
}
function escapeHtml(value) { const e = document.createElement('span'); e.textContent = value; return e.innerHTML; }
function render() {
  const term = search.value.trim().toLowerCase(); catalog.replaceChildren();
  let shown = 0;
  [...library.categories].sort(compareItems).forEach(category => { if (addNode(category, catalog, term)) shown++; });
  empty.hidden = shown !== 0;
}
function openPreview(item) {
  const url = fileUrl(item); const ext = item.extension;
  previewTitle.textContent = item.name; preview.hidden = false; viewer.replaceChildren();
  let element;
  if (mediaExtensions.has(ext)) {
    element = document.createElement('video'); element.controls = true; element.autoplay = true; element.preload = 'metadata';
    let lastSaved = 0;
    element.addEventListener('loadedmetadata', () => {
      const saved = progressByPath[item.relativePath];
      if (saved && saved.position > 5 && saved.position < element.duration - 5) element.currentTime = saved.position;
    });
    const save = () => {
      if (!Number.isFinite(element.currentTime) || !Number.isFinite(element.duration)) return;
      lastSaved = element.currentTime;
      progressByPath[item.relativePath] = { position: element.currentTime, duration: element.duration };
      fetch('/api/progress', { method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true, body: JSON.stringify({ relativePath: item.relativePath, position: element.currentTime, duration: element.duration }) }).catch(() => {});
    };
    element.addEventListener('timeupdate', () => { if (element.currentTime - lastSaved >= 5) save(); });
    element.addEventListener('pause', save); element.addEventListener('ended', save);
  }
  else if (audioExtensions.has(ext)) { element = document.createElement('audio'); element.controls = true; element.autoplay = true; }
  else if (imageExtensions.has(ext)) { element = document.createElement('img'); element.alt = item.name; }
  else if (embeddedExtensions.has(ext)) { element = document.createElement('iframe'); element.title = `Preview of ${item.name}`; }
  else { element = document.createElement('div'); element.className = 'unsupported'; element.innerHTML = '<p>This file format is not natively previewed by this browser.</p>'; }
  if (element.tagName !== 'DIV') element.src = url;
  viewer.append(element);
  const open = document.createElement('a'); open.href = url; open.target = '_blank'; open.rel = 'noopener'; open.textContent = 'Open or download file'; open.className = 'open-file'; viewer.append(open);
  preview.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
async function load() {
  status.textContent = 'Refreshing library…';
  try {
    const [response, progressResponse] = await Promise.all([fetch('/api/library', { cache: 'no-store' }), fetch('/api/progress', { cache: 'no-store' })]);
    if (!response.ok) throw new Error('Catalog request failed');
    library = await response.json(); progressByPath = progressResponse.ok ? await progressResponse.json() : {};
    document.querySelector('#category-count').textContent = library.summary.categories;
    document.querySelector('#file-count').textContent = library.summary.files;
    document.querySelector('#updated-at').textContent = `Updated ${new Date(library.generatedAt).toLocaleString()}`;
    status.textContent = 'Live — changes appear automatically.'; render();
  } catch { status.textContent = 'Could not reach the library server.'; }
}
search.addEventListener('input', () => library && render()); sort.addEventListener('change', () => library && render());
document.querySelector('#refresh').addEventListener('click', load); document.querySelector('#close-preview').addEventListener('click', () => { preview.hidden = true; viewer.replaceChildren(); });
const events = new EventSource('/events'); events.addEventListener('library-change', load); events.onerror = () => { status.textContent = 'Live connection paused — retrying…'; };
load();
