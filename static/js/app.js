let state={results:[],summary:{},sources:{},running:false,progress:{percent:0,phase:'Připraveno',eta_seconds:0}};
let activeFilter='VŠE';

const $=id=>document.getElementById(id);

const filterNames={
  'VŠE':'Všechna vozidla','ACTIVE':'Aktivní ke kontrole','OK_TOTAL':'Pojištění v pořádku','OK_UNIQA':'OK · UNIQA','OK_ALLIANZ':'OK · Allianz','MISSING':'Chybí pojištění','DEPOSIT':'Nepojištěno, ale depozit','SOLD_UNIQA':'Prodané, ale v UNIQA','EXTRA_UNIQA':'Navíc v UNIQA'
};

function esc(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function resultKey(r){const vin=(r.vin||'').trim().toUpperCase();const spz=(r.spz_tir||r.spz_uniqa||'').trim().toUpperCase();return vin||('SPZ:'+spz);}
function badgeClass(r){
  if(r.workflow_status==='VYŘEŠENO') return 'badge-ok';
  if(r.workflow_status==='ŘEŠÍ SE'||r.workflow_status==='KONTROLA') return 'badge-warning';
  return ({'OK':'badge-ok','CHYBÍ V UNIQA':'badge-missing','NEPOJIŠTĚNO, ALE DEPOZIT':'badge-deposit','PRODANÉ, ALE V UNIQA':'badge-sold','NAVÍC V UNIQA':'badge-extra','SPZ NESOUHLASÍ':'badge-warning','NELZE OVĚŘIT':'badge-error'}[r.status_raw]||'badge-error');
}
function insurerClass(name){if(name==='UNIQA')return'insurer insurer-uniqa';if(name==='ALLIANZ')return'insurer insurer-allianz';return'insurer';}

function source(name,prefix){
  const s=state.sources[name]||{};
  $(prefix+'Dot').className='status-dot '+(s.state||'idle');
  const detail=s.detail?(' · '+s.detail):'';
  $(prefix+'Status').textContent=(s.status||'Zatím nenačteno')+detail;
  $(prefix+'Detail').textContent='';
}

function hideSources(){const section=$('sourceSection');if(section)section.hidden=true;const btn=$('navSources');if(btn)btn.classList.remove('active');}
function showSources(){const section=$('sourceSection');if(!section)return;section.hidden=false;document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));$('navSources').classList.add('active');section.scrollIntoView({behavior:'smooth',block:'start'});}

function matches(r){
  if(activeFilter==='VŠE')return true;
  if(activeFilter==='ACTIVE')return ['OK','CHYBÍ V UNIQA','SPZ NESOUHLASÍ','NELZE OVĚŘIT'].includes(r.status_raw);
  if(activeFilter==='OK_TOTAL')return r.status_raw==='OK';
  if(activeFilter==='OK_UNIQA')return r.status_raw==='OK'&&r.pojistovna==='UNIQA';
  if(activeFilter==='OK_ALLIANZ')return r.status_raw==='OK'&&r.pojistovna==='ALLIANZ';
  if(activeFilter==='MISSING')return r.status_raw==='CHYBÍ V UNIQA';
  if(activeFilter==='DEPOSIT')return r.status_raw==='NEPOJIŠTĚNO, ALE DEPOZIT';
  if(activeFilter==='SOLD_UNIQA')return r.status_raw==='PRODANÉ, ALE V UNIQA';
  if(activeFilter==='EXTRA_UNIQA')return r.status_raw==='NAVÍC V UNIQA';
  return true;
}

function renderActiveFilter(){const box=$('activeFilter');if(activeFilter==='VŠE'){box.hidden=true;return;}$('activeFilterLabel').textContent=filterNames[activeFilter]||activeFilter;box.hidden=false;}

function renderRows(){
  const q=$('search').value.trim().toUpperCase();
  const rows=state.results.filter(r=>matches(r)&&(!q||Object.values(r).join(' ').toUpperCase().includes(q)));
  $('footerRight').textContent='Zobrazeno: '+rows.length+' z '+state.results.length;renderActiveFilter();
  if(!rows.length){$('rows').innerHTML='<tr class="empty-row"><td colspan="8" class="empty">Žádné výsledky pro zvolený filtr.</td></tr>';return;}
  $('rows').innerHTML=rows.map(r=>{const index=state.results.indexOf(r);const insurer=r.pojistovna?`<span class="${insurerClass(r.pojistovna)}">${esc(r.pojistovna)}</span>`:'—';const note=r.note?` · Pozn.: ${esc(r.note)}`:'';return `<tr data-index="${index}"><td><span class="status-badge ${badgeClass(r)}">${esc(r.status)}</span></td><td>${insurer}</td><td>${esc(r.vin||'—')}</td><td>${esc(r.spz_tir||'—')}</td><td>${esc(r.spz_uniqa||'—')}</td><td>${esc(r.vykup||'—')}</td><td>${esc(r.prodej||'—')}</td><td>${esc(r.detail||'—')}${note}</td></tr>`;}).join('');
  document.querySelectorAll('#rows tr[data-index]').forEach(tr=>tr.addEventListener('click',()=>showDetail(state.results[Number(tr.dataset.index)])));
}

function formatEta(seconds){
  const s=Math.max(0,Number(seconds)||0);
  if(!state.running)return state.finished_at?'Dokončeno':'—';
  if(s<60)return 'odhad cca '+Math.max(5,Math.round(s/5)*5)+' s';
  return 'odhad cca '+Math.max(1,Math.round(s/60))+' min';
}

function renderProgress(){
  const p=state.progress||{};
  let percent=Math.max(0,Math.min(100,Number(p.percent)||0));
  if(!state.running&&state.finished_at&&!state.error)percent=100;
  $('progressPercent').textContent=Math.round(percent)+' %';
  $('progressPhase').textContent=p.phase||(state.running?'Kontrola probíhá':'Připraveno');
  $('progressEta').textContent=state.error?'Kontrola skončila chybou':formatEta(p.eta_seconds);
  $('progressBar').style.width=percent+'%';
  $('progressBar').style.background=state.error?'#dc2626':(percent===100?'#16a34a':'#2563eb');
}

function render(){
  const s=state.summary||{};$('cActive').textContent=s.active||0;$('cOkTotal').textContent=s.ok_total||0;$('cOkUniqa').textContent=s.ok_uniqa||0;$('cOkAllianz').textContent=s.ok_allianz||0;$('cMissing').textContent=s.missing||0;$('cDeposit').textContent=s.deposit||0;$('cSold').textContent=s.sold_uniqa||0;$('cExtra').textContent=s.extra_uniqa||0;
  source('tirbazar','tir');source('uniqa','uniqa');source('allianz','allianz');renderProgress();
  $('runBtn').disabled=state.running;$('runBtn').innerHTML=state.running?'Kontrola probíhá…':'<span class="play">▶</span> Spustit kontrolu';$('csvBtn').classList.toggle('disabled',!state.csv_available);
  const live=$('liveDot');if(state.running){live.className='status-dot loading';$('liveStatus').textContent='Kontrola probíhá';}else if(state.error){live.className='status-dot error';$('liveStatus').textContent='Chyba kontroly';}else if(state.finished_at){live.className='status-dot ok';$('liveStatus').textContent='Kontrola dokončena';}else{live.className='status-dot idle';$('liveStatus').textContent='Připraveno';}
  $('footerLeft').textContent=state.finished_at?'Dokončeno: '+state.finished_at:(state.started_at?'Spuštěno: '+state.started_at:'Připraveno');renderRows();
}

async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});state=await r.json();render();if(state.error)toast(state.error,true);}catch(e){toast('Nepodařilo se načíst stav aplikace.',true);}}
async function run(){try{const r=await fetch('/api/run',{method:'POST'});const d=await r.json();if(!r.ok)toast(d.message||'Kontrolu se nepodařilo spustit.',true);await refresh();}catch(e){toast('Kontrolu se nepodařilo spustit.',true);}}

function showDetail(r){
  const insurer=r.pojistovna?`<span class="${insurerClass(r.pojistovna)}">${esc(r.pojistovna)}</span>`:'—';
  const original=r.original_status?`<div style="margin-top:5px;color:#64748b;font-size:11px">Původní výsledek: ${esc(r.original_status)}</div>`:'';
  $('detailBody').innerHTML=`<dl class="detail-grid"><dt>Stav</dt><dd><span class="status-badge ${badgeClass(r)}">${esc(r.status)}</span>${original}</dd><dt>Pojišťovna</dt><dd>${insurer}</dd><dt>VIN</dt><dd>${esc(r.vin||'—')}</dd><dt>SPZ TIRBazar</dt><dd>${esc(r.spz_tir||'—')}</dd><dt>SPZ UNIQA</dt><dd>${esc(r.spz_uniqa||'—')}</dd><dt>Datum výkupu</dt><dd>${esc(r.vykup||'—')}</dd><dt>Datum prodeje</dt><dd>${esc(r.prodej||'—')}</dd><dt>Výsledek</dt><dd>${esc(r.detail||'—')}</dd></dl><div style="padding:0 22px 22px;border-top:1px solid #eef2f7"><h3 style="margin:16px 0 10px;font-size:14px">Interní poznámka a stav řešení</h3><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">STATUS</label><select id="workflowStatus" style="width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:8px;margin-bottom:12px"><option value="">Původní status</option><option value="KONTROLA">Kontrola</option><option value="ŘEŠÍ SE">Řeší se</option><option value="VYŘEŠENO">Vyřešeno</option></select><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">POZNÁMKA</label><textarea id="vehicleNote" rows="4" maxlength="2000" placeholder="Např. zrušení v UNIQA zadáno 14.9., čekáme na potvrzení…" style="width:100%;resize:vertical;padding:9px;border:1px solid #cbd5e1;border-radius:8px;font:inherit">${esc(r.note||'')}</textarea><div style="display:flex;justify-content:flex-end;margin-top:12px"><button id="saveMeta" class="btn btn-primary" type="button">Uložit</button></div></div>`;
  $('workflowStatus').value=r.workflow_status||'';
  $('saveMeta').addEventListener('click',()=>saveMeta(r));
  $('detailDialog').showModal();
}

async function saveMeta(r){
  const btn=$('saveMeta');btn.disabled=true;
  try{const res=await fetch('/api/result-meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:resultKey(r),note:$('vehicleNote').value,workflow_status:$('workflowStatus').value})});const d=await res.json();if(!res.ok)throw new Error(d.message||'Uložení selhalo.');toast('Poznámka a status uloženy.');$('detailDialog').close();await refresh();}catch(e){toast(e.message||'Uložení selhalo.',true);}finally{btn.disabled=false;}
}

function setFilter(filter){hideSources();activeFilter=filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('selected',x.dataset.filter===filter));renderRows();}
function clearFilter(){hideSources();activeFilter='VŠE';$('search').value='';document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('selected'));document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));$('navAllVehicles').classList.add('active');renderRows();}
let lastToast='';function toast(msg,error=false){if(!msg||msg===lastToast)return;lastToast=msg;const t=$('toast');t.textContent=msg;t.className='toast'+(error?' error':'');t.hidden=false;setTimeout(()=>{t.hidden=true;lastToast='';},5000);}

$('runBtn').addEventListener('click',run);$('search').addEventListener('input',renderRows);$('clearBtn').addEventListener('click',clearFilter);$('clearFilterInline').addEventListener('click',clearFilter);$('navAllVehicles').addEventListener('click',clearFilter);$('navSources').addEventListener('click',showSources);document.querySelectorAll('[data-filter]').forEach(c=>c.addEventListener('click',()=>setFilter(c.dataset.filter)));$('closeDialog').addEventListener('click',()=>$('detailDialog').close());$('detailDialog').addEventListener('click',e=>{if(e.target===$('detailDialog'))$('detailDialog').close();});
setInterval(refresh,2000);refresh();
