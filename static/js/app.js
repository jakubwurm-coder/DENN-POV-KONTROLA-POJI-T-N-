let state={results:[],summary:{},sources:{},running:false};
let activeFilter='VŠE';

const $=id=>document.getElementById(id);

const filterNames={
  'VŠE':'Všechna vozidla',
  'ACTIVE':'Aktivní ke kontrole',
  'OK_TOTAL':'Pojištění v pořádku',
  'OK_UNIQA':'OK · UNIQA',
  'OK_ALLIANZ':'OK · Allianz',
  'MISSING':'Chybí pojištění',
  'DEPOSIT':'Nepojištěno, ale depozit',
  'SOLD_UNIQA':'Prodané, ale v UNIQA',
  'EXTRA_UNIQA':'Navíc v UNIQA'
};

function esc(v){
  return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function badgeClass(r){
  return ({
    'OK':'badge-ok',
    'CHYBÍ V UNIQA':'badge-missing',
    'NEPOJIŠTĚNO, ALE DEPOZIT':'badge-deposit',
    'PRODANÉ, ALE V UNIQA':'badge-sold',
    'NAVÍC V UNIQA':'badge-extra',
    'SPZ NESOUHLASÍ':'badge-warning',
    'NELZE OVĚŘIT':'badge-error'
  }[r.status_raw]||'badge-error');
}

function insurerClass(name){
  if(name==='UNIQA') return 'insurer insurer-uniqa';
  if(name==='ALLIANZ') return 'insurer insurer-allianz';
  return 'insurer';
}

function source(name,prefix){
  const s=state.sources[name]||{};
  $(prefix+'Dot').className='status-dot '+(s.state||'idle');
  $(prefix+'Status').textContent=s.status||'Zatím nenačteno';
  $(prefix+'Detail').textContent=s.detail||'';
}

function matches(r){
  if(activeFilter==='VŠE')return true;
  if(activeFilter==='ACTIVE')return ['OK','CHYBÍ V UNIQA','NEPOJIŠTĚNO, ALE DEPOZIT','SPZ NESOUHLASÍ','NELZE OVĚŘIT'].includes(r.status_raw);
  if(activeFilter==='OK_TOTAL')return r.status_raw==='OK';
  if(activeFilter==='OK_UNIQA')return r.status_raw==='OK'&&r.pojistovna==='UNIQA';
  if(activeFilter==='OK_ALLIANZ')return r.status_raw==='OK'&&r.pojistovna==='ALLIANZ';
  if(activeFilter==='MISSING')return r.status_raw==='CHYBÍ V UNIQA';
  if(activeFilter==='DEPOSIT')return r.status_raw==='NEPOJIŠTĚNO, ALE DEPOZIT';
  if(activeFilter==='SOLD_UNIQA')return r.status_raw==='PRODANÉ, ALE V UNIQA';
  if(activeFilter==='EXTRA_UNIQA')return r.status_raw==='NAVÍC V UNIQA';
  return true;
}

function renderActiveFilter(){
  const box=$('activeFilter');
  if(activeFilter==='VŠE'){
    box.hidden=true;
    return;
  }
  $('activeFilterLabel').textContent=filterNames[activeFilter]||activeFilter;
  box.hidden=false;
}

function renderRows(){
  const q=$('search').value.trim().toUpperCase();
  const rows=state.results.filter(r=>matches(r)&&(!q||Object.values(r).join(' ').toUpperCase().includes(q)));
  $('footerRight').textContent='Zobrazeno: '+rows.length+' z '+state.results.length;
  renderActiveFilter();

  if(!rows.length){
    $('rows').innerHTML='<tr class="empty-row"><td colspan="8" class="empty">Žádné výsledky pro zvolený filtr.</td></tr>';
    return;
  }

  $('rows').innerHTML=rows.map(r=>{
    const index=state.results.indexOf(r);
    const insurer=r.pojistovna?`<span class="${insurerClass(r.pojistovna)}">${esc(r.pojistovna)}</span>`:'—';
    return `<tr data-index="${index}">
      <td><span class="status-badge ${badgeClass(r)}">${esc(r.status)}</span></td>
      <td>${insurer}</td>
      <td>${esc(r.vin||'—')}</td>
      <td>${esc(r.spz_tir||'—')}</td>
      <td>${esc(r.spz_uniqa||'—')}</td>
      <td>${esc(r.vykup||'—')}</td>
      <td>${esc(r.prodej||'—')}</td>
      <td>${esc(r.detail||'—')}</td>
    </tr>`;
  }).join('');

  document.querySelectorAll('#rows tr[data-index]').forEach(tr=>{
    tr.addEventListener('click',()=>showDetail(state.results[Number(tr.dataset.index)]));
  });
}

function render(){
  const s=state.summary||{};
  $('cActive').textContent=s.active||0;
  $('cOkTotal').textContent=s.ok_total||0;
  $('cOkUniqa').textContent=s.ok_uniqa||0;
  $('cOkAllianz').textContent=s.ok_allianz||0;
  $('cMissing').textContent=s.missing||0;
  $('cDeposit').textContent=s.deposit||0;
  $('cSold').textContent=s.sold_uniqa||0;
  $('cExtra').textContent=s.extra_uniqa||0;

  source('tirbazar','tir');
  source('uniqa','uniqa');
  source('allianz','allianz');

  $('runBtn').disabled=state.running;
  $('runBtn').innerHTML=state.running?'Kontrola probíhá…':'<span class="play">▶</span> Spustit kontrolu';
  $('csvBtn').classList.toggle('disabled',!state.csv_available);

  const live=$('liveDot');
  if(state.running){
    live.className='status-dot loading';
    $('liveStatus').textContent='Kontrola probíhá';
  }else if(state.error){
    live.className='status-dot error';
    $('liveStatus').textContent='Chyba kontroly';
  }else if(state.finished_at){
    live.className='status-dot ok';
    $('liveStatus').textContent='Kontrola dokončena';
  }else{
    live.className='status-dot idle';
    $('liveStatus').textContent='Připraveno';
  }

  $('footerLeft').textContent=state.finished_at?'Dokončeno: '+state.finished_at:(state.started_at?'Spuštěno: '+state.started_at:'Připraveno');
  renderRows();
}

async function refresh(){
  try{
    const r=await fetch('/api/state',{cache:'no-store'});
    state=await r.json();
    render();
    if(state.error)toast(state.error,true);
  }catch(e){
    toast('Nepodařilo se načíst stav aplikace.',true);
  }
}

async function run(){
  try{
    const r=await fetch('/api/run',{method:'POST'});
    const d=await r.json();
    if(!r.ok)toast(d.message||'Kontrolu se nepodařilo spustit.',true);
    await refresh();
  }catch(e){
    toast('Kontrolu se nepodařilo spustit.',true);
  }
}

function showDetail(r){
  const insurer=r.pojistovna?`<span class="${insurerClass(r.pojistovna)}">${esc(r.pojistovna)}</span>`:'—';
  $('detailBody').innerHTML=`<dl class="detail-grid">
    <dt>Stav</dt><dd><span class="status-badge ${badgeClass(r)}">${esc(r.status)}</span></dd>
    <dt>Pojišťovna</dt><dd>${insurer}</dd>
    <dt>VIN</dt><dd>${esc(r.vin||'—')}</dd>
    <dt>SPZ TIRBazar</dt><dd>${esc(r.spz_tir||'—')}</dd>
    <dt>SPZ UNIQA</dt><dd>${esc(r.spz_uniqa||'—')}</dd>
    <dt>Datum výkupu</dt><dd>${esc(r.vykup||'—')}</dd>
    <dt>Datum prodeje</dt><dd>${esc(r.prodej||'—')}</dd>
    <dt>Výsledek</dt><dd>${esc(r.detail||'—')}</dd>
  </dl>`;
  $('detailDialog').showModal();
}

function setFilter(filter){
  activeFilter=filter;
  document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('selected',x.dataset.filter===filter));
  renderRows();
}

function clearFilter(){
  activeFilter='VŠE';
  $('search').value='';
  document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('selected'));
  renderRows();
}

let lastToast='';
function toast(msg,error=false){
  if(!msg||msg===lastToast)return;
  lastToast=msg;
  const t=$('toast');
  t.textContent=msg;
  t.className='toast'+(error?' error':'');
  t.hidden=false;
  setTimeout(()=>{t.hidden=true;lastToast='';},5000);
}

$('runBtn').addEventListener('click',run);
$('search').addEventListener('input',renderRows);
$('clearBtn').addEventListener('click',clearFilter);
$('clearFilterInline').addEventListener('click',clearFilter);
$('navAllVehicles').addEventListener('click',clearFilter);
document.querySelectorAll('[data-filter]').forEach(c=>c.addEventListener('click',()=>setFilter(c.dataset.filter)));
$('closeDialog').addEventListener('click',()=>$('detailDialog').close());
$('detailDialog').addEventListener('click',e=>{if(e.target===$('detailDialog'))$('detailDialog').close();});

setInterval(refresh,2000);
refresh();
