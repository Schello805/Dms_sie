import * as pdfjsLib from './pdf.mjs';

const container = document.querySelector('#viewer');
const status = document.querySelector('#status');
const canvas = document.querySelector('#pdf-canvas');
const pageInput = document.querySelector('#page');
const pages = document.querySelector('#pages');
const previous = document.querySelector('#previous');
const next = document.querySelector('#next');
const zoom = document.querySelector('#zoom');
const text = document.querySelector('#page-text');
const assets = new URL('./', new URL(container.dataset.assets, location.href));
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('pdf.worker.mjs', assets).href;

let pdf;
let currentPage = 1;
let revision = 0;
let renderTask;
let queue = Promise.resolve();
function schedule() {
  const request = ++revision;
  renderTask?.cancel();
  queue = queue.catch(() => {}).then(async () => {
    if (request !== revision || !pdf) return;
    const page = await pdf.getPage(currentPage);
    if (request !== revision) return;
    const base = page.getViewport({scale: 1});
    const fit = Math.max(.2, Math.min(2, (container.clientWidth - 32) / base.width));
    const scale = zoom.value === 'auto' ? fit : Number(zoom.value);
    const viewport = page.getViewport({scale});
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    canvas.setAttribute('aria-label', `Dokumentseite ${currentPage} von ${pdf.numPages}`);
    status.textContent = `Seite ${currentPage} von ${pdf.numPages} wird angezeigt …`;
    renderTask = page.render({canvasContext: canvas.getContext('2d'), viewport,
      transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0]});
    await renderTask.promise;
    if (request !== revision) return;
    const content = await page.getTextContent();
    text.textContent = content.items.map(item => item.str + (item.hasEOL ? '\n' : ' ')).join('');
    status.textContent = `Seite ${currentPage} von ${pdf.numPages}`;
    pageInput.value = String(currentPage);
    previous.disabled = currentPage <= 1;
    next.disabled = currentPage >= pdf.numPages;
    canvas.dataset.rendered = 'true';
  }).catch(error => {
    if (error.name !== 'RenderingCancelledException') {
      status.textContent = 'Vorschau konnte nicht angezeigt werden. Bitte PDF herunterladen oder den Autor informieren.';
    }
  });
}
previous.addEventListener('click', () => {if (currentPage > 1) {currentPage--; schedule();}});
next.addEventListener('click', () => {if (pdf && currentPage < pdf.numPages) {currentPage++; schedule();}});
pageInput.addEventListener('change', () => {
  currentPage = Math.max(1, Math.min(pdf?.numPages || 1, Math.trunc(Number(pageInput.value)) || 1));
  schedule();
});
zoom.addEventListener('change', schedule);
window.addEventListener('resize', () => {if (zoom.value === 'auto') schedule();});
try {
  const loading = pdfjsLib.getDocument({url: container.dataset.source,
    cMapUrl: new URL('cmaps/', assets).href, cMapPacked: true,
    standardFontDataUrl: new URL('standard_fonts/', assets).href,
    wasmUrl: new URL('wasm/', assets).href,
    isEvalSupported: false, enableXfa: false, useWasm: false,
    disableAutoFetch: true, disableStream: true});
  pdf = await loading.promise;
  pages.textContent = `/ ${pdf.numPages}`;
  pageInput.max = String(pdf.numPages);
  schedule();
} catch (error) {
  status.textContent = 'PDF-Lesefassung konnte nicht geladen werden. Bitte erneut anmelden oder die PDF herunterladen.';
}
