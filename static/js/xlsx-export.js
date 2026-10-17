/* Percentages come only from counted rows or received bytes; no elapsed-time estimates. */
(() => {
  const el = id => document.getElementById(id);
  const dialog = el('xlsxProgressDialog');
  if (!dialog) return;
  let busy = false, lastJob = null, blobURL = null, retryRefresh = false;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const number = value => Number(value).toLocaleString('cs-CZ');
  const bytes = value => (value / 1048576).toLocaleString('cs-CZ', {maximumFractionDigits:2}) + ' MB';
  const meter = (id, value) => {
    if (value === null) el(id).removeAttribute('value');
    else el(id).value = Math.min(100, Math.max(0, value));
  };
  async function json(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options});
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('Server nevrátil stav exportu. Zkuste to znovu.'); }
    if (response.status === 401) throw new Error('Přihlášení vypršelo. Přihlaste se znovu.');
    if (!response.ok || data.ok === false) throw new Error(data.message || data.error || 'Chyba serveru (' + response.status + ').');
    return data;
  }
  async function refreshAudit() {
    meter('xlsxPrepare', null);
    el('xlsxPrepareText').textContent = 'Čekám na kompletní audit od kancelářského agenta. Procenta nejsou dostupná.';
    let data = await json('/api/audit-export', {method:'POST'});
    const started = Date.now();
    while (data.status === 'pending') {
      if (Date.now() - started > 30 * 60 * 1000) throw new Error('Agent dosud nevrátil audit. Ověřte, že kancelářský agent běží, a zkuste to znovu.');
      await pause(2000);
      data = await json('/api/audit-export');
    }
    if (data.status !== 'ready') throw new Error(data.error || 'Audit není připraven.');
  }
  function transfer(job) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('GET', '/download/xlsx?job=' + encodeURIComponent(job.id));
      xhr.responseType = 'blob';
      xhr.timeout = 10 * 60 * 1000;
      meter('xlsxTransfer', null);
      el('xlsxTransferText').textContent = 'Navazuji spojení pro stažení souboru…';
      xhr.onprogress = event => {
        const measurable = event.lengthComputable && event.total > 0;
        meter('xlsxTransfer', measurable ? event.loaded / event.total * 100 : null);
        el('xlsxTransferText').textContent = measurable
          ? (event.loaded / event.total * 100).toFixed(1) + ' % · ' + bytes(event.loaded) + ' z ' + bytes(event.total)
          : 'Přijato ' + bytes(event.loaded) + ' · celková velikost přenosu není dostupná.';
      };
      xhr.onerror = () => reject(new Error('Síťové stahování selhalo. Zkuste stáhnout připravený soubor znovu.'));
      xhr.ontimeout = () => reject(new Error('Spojení pro stahování vypršelo. Zkuste to znovu.'));
      xhr.onload = () => {
        if (xhr.status !== 200) {
          if ([404, 409, 410].includes(xhr.status)) lastJob = null;
          reject(new Error(xhr.status === 401 ? 'Přihlášení vypršelo. Přihlaste se znovu.' : 'Soubor se nepodařilo stáhnout (' + xhr.status + '). Zkuste to znovu.'));
          return;
        }
        if (!xhr.response.size || !xhr.response.type.includes('spreadsheetml')) {
          reject(new Error('Server nevrátil platný Excel. Zkuste to znovu.')); return;
        }
        if (blobURL) URL.revokeObjectURL(blobURL);
        blobURL = URL.createObjectURL(xhr.response);
        const save = el('xlsxSave');
        save.href = blobURL;
        save.download = job.filename || 'denni_pov_audit.xlsx';
        save.hidden = false;
        save.click();
        meter('xlsxTransfer', 100);
        el('xlsxTransferText').textContent = '100 % · soubor přijat (' + bytes(xhr.response.size) + ') a předán prohlížeči k uložení.';
        resolve();
      };
      xhr.send();
    });
  }
  async function start({refresh = false, resume = false} = {}) {
    if (busy) { if (!dialog.open) dialog.showModal(); return; }
    busy = true;
    let startedTransfer = false;
    el('xlsxClose').textContent = 'Skrýt průběh';
    el('xlsxPrepare').hidden = false;
    el('xlsxTransfer').hidden = false;
    retryRefresh = refresh;
    if (!dialog.open) dialog.showModal();
    el('xlsxError').hidden = true;
    el('xlsxRetry').hidden = true;
    el('xlsxSave').hidden = true;
    meter('xlsxPrepare', null);
    meter('xlsxTransfer', 0);
    el('xlsxPrepareText').textContent = 'Načítám data pro přípravu Excelu…';
    el('xlsxTransferText').textContent = 'Čeká na připravený soubor.';
    try {
      if (!resume) lastJob = null;
      if (refresh && !lastJob) await refreshAudit();
      let job = lastJob || await json('/api/xlsx-export', {method:'POST'});
      lastJob = job;
      const started = Date.now();
      while (job.status === 'running') {
        if (job.phase === 'rows' && Number.isFinite(job.total) && job.total > 0) {
          const percent = job.completed / job.total * 100;
          meter('xlsxPrepare', percent);
          el('xlsxPrepareText').textContent = percent.toFixed(1) + ' % řádků · zapsáno ' + number(job.completed) + ' z ' + number(job.total) + '. Poté proběhne dokončení souboru.';
        } else {
          meter('xlsxPrepare', null);
          el('xlsxPrepareText').textContent = job.phase === 'finalizing'
            ? 'Datové řádky jsou zapsány. Dokončuji a komprimuji XLSX; procenta této fáze nelze změřit.'
            : 'Spouštím přípravu Excelu. Procenta zatím nejsou dostupná.';
        }
        if (Date.now() - started > 30 * 60 * 1000) throw new Error('Příprava stále běží. Tlačítkem Zkusit znovu lze navázat na její stav.');
        await pause(750);
        try { job = await json('/api/xlsx-export/' + encodeURIComponent(job.id)); }
        catch (error) { if (error.message.includes('restartu')) lastJob = null; throw error; }
        lastJob = job;
      }
      if (job.status !== 'ready') { lastJob = null; throw new Error(job.error || 'Příprava Excelu byla přerušena.'); }
      meter('xlsxPrepare', 100);
      el('xlsxPrepareText').textContent = '100 % · Excel je připraven (' + bytes(job.size) + ').';
      startedTransfer = true;
      await transfer(job);
    } catch (error) {
      if (!startedTransfer) el('xlsxPrepare').hidden = true;
      el('xlsxTransfer').hidden = true;
      el('xlsxError').textContent = error.message || 'Export se nezdařil.';
      el('xlsxError').hidden = false;
      el('xlsxRetry').hidden = false;
    } finally { busy = false; el('xlsxClose').textContent = 'Zavřít'; }
  }
  el('xlsxClose').onclick = () => dialog.close();
  el('xlsxRetry').onclick = () => start({refresh:retryRefresh, resume:true});
  const download = el('completeAuditDownload');
  if (download) download.addEventListener('click', event => { event.preventDefault(); start(); });
  window.DenniExport = {start};
})();
