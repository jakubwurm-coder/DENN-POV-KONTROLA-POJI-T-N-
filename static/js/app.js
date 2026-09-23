let state={results:[],summary:{},sources:{},running:false,progress:{percent:0,phase:'Připraveno',eta_seconds:0}};
let activeFilter='VŠE';

const $=id=>document.getElementById(id);

const filterNames={
  'VŠE':'Všechna vozidla','ACTIVE':'Aktivní ke kontrole','OK_TOTAL':'Pojištění v pořádku','OK_UNIQA':'Pojištění nalezeno','OK_ALLIANZ':'Pojištění nalezeno','MISSING':'Chybí pojištění','ABSENT_INSURED':'Nepřítomné, ale pojištěno','ABSENT_UNINSURED':'Nepřítomné, ale nepojištěno','DEPOSIT':'Nepojištěno, ale depozit','SOLD_UNIQA':'Prodané, ale pojištěno','EXTRA_UNIQA':'Pojištění navíc','UNWANTED_INSURANCE':'Pojištění navíc'
};

function esc(v){return String(v??'').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function displaySpz(r){return (r.spz_tir||r.spz_uniqa||'').trim();}
function resultKey(r){const vin=(r.vin||'').trim().toUpperCase();const spz=displaySpz(r).toUpperCase();return vin||('SPZ:'+spz);}
function badgeClass(r){
  if(r.workflow_status==='VYŘEŠENO'||r.workflow_status==='V POŘÁDKU') return 'badge-ok';
  if(r.workflow_status==='ŘEŠÍ SE'||r.workflow_status==='KONTROLA') return 'badge-warning';
  return ({'OK':'badge-ok','CHYBÍ V UNIQA':'badge-missing','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ':'badge-error','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ':'badge-ok','NEPOJIŠTĚNO, ALE DEPOZIT':'badge-deposit','PRODANÉ, ALE V UNIQA':'badge-sold','NAVÍC V UNIQA':'badge-extra','SPZ NESOUHLASÍ':'badge-warning','NELZE OVĚŘIT':'badge-error'}[r.status_raw]||'badge-error');
}
function visibleSystemText(value){
  return String(value??'')
    .replace(/v ALLIANZ podle SPZ/gi,'v evidenci pojištění')
    .replace(/v ALLIANZ podle VIN/gi,'v evidenci pojištění')
    .replace(/v ALLIANZ/gi,'v evidenci pojištění')
    .replace(/v UNIQA/gi,'v evidenci pojištění')
    .replace(/ALLIANZ/gi,'pojištění')
    .replace(/UNIQA/gi,'pojištění');
}

function source(name,prefix){
  const s=state.sources[name]||{};
  $(prefix+'Dot').className='status-dot '+(s.state||'idle');
  const detail=s.detail?(' · '+visibleSystemText(s.detail)):'';
  $(prefix+'Status').textContent=visibleSystemText(s.status||'Zatím nenačteno')+detail;
  $(prefix+'Detail').textContent='';
}

function hideSources(){const section=$('sourceSection');if(section)section.hidden=true;const btn=$('navSources');if(btn)btn.classList.remove('active');}
function hideBreakdown(){const section=$('breakdownSection');if(section)section.hidden=true;const btn=$('navBreakdown');if(btn)btn.classList.remove('active');}
function hideData(){const section=$('dataSection');if(section)section.hidden=true;}
function hideChanges(){const section=$('changesSection');if(section)section.hidden=true;const btn=$('navChanges');if(btn)btn.classList.remove('active');}
function hideManualHistory(){const section=$('manualHistorySection');if(section)section.hidden=true;const btn=$('navManualHistory');if(btn)btn.classList.remove('active');}
function showData(){hideChanges();hideManualHistory();const section=$('dataSection');if(!section)return;section.hidden=false;section.scrollIntoView({behavior:'smooth',block:'start'});}
function showChanges(){
  hideSources();hideBreakdown();hideManualHistory();hideData();
  const section=$('changesSection');if(!section)return;
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  $('navChanges').classList.add('active');
  renderChanges();
  section.scrollIntoView({behavior:'smooth',block:'start'});
}
function showSources(){
  const section=$('sourceSection');if(!section)return;
  hideBreakdown();hideChanges();hideManualHistory();hideData();
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  $('navSources').classList.add('active');
  section.scrollIntoView({behavior:'smooth',block:'start'});
}
function showBreakdown(){
  const section=$('breakdownSection');if(!section)return;
  hideSources();hideChanges();hideManualHistory();hideData();
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  $('navBreakdown').classList.add('active');
  section.scrollIntoView({behavior:'smooth',block:'start'});
}

async function showManualHistory(){
  hideSources();hideBreakdown();hideChanges();hideData();
  const section=$('manualHistorySection');if(!section)return;
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  $('navManualHistory').classList.add('active');
  section.scrollIntoView({behavior:'smooth',block:'start'});
  const body=$('manualHistoryRows');
  if(body)body.innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Načítám historii…</td></tr>';
  try{
    const r=await fetch('/api/manual-history?limit=500',{cache:'no-store'});
    const d=await r.json();
    const items=Array.isArray(d.history)?d.history:[];
    if($('manualHistoryFooter'))$('manualHistoryFooter').textContent='Záznamů: '+items.length;
    if(!body)return;
    if(!items.length){
      body.innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Zatím nejsou uložené žádné ruční změny.</td></tr>';
      return;
    }
    body.innerHTML=items.map(x=>{
      const status=x.new_workflow_status||'Původní status';
      const note=(x.new_note||'') || ((x.old_note||'')?'Poznámka odstraněna':'—');
      return '<tr><td>'+esc(x.changed_at||'—')+'</td><td>'+esc(x.vin||x.vehicle_key||'—')+'</td><td>'+esc(x.spz||'—')+'</td><td>'+esc(visibleSystemText(x.original_status||'—'))+'</td><td><span class="status-badge '+((status==='VYŘEŠENO'||status==='V POŘÁDKU')?'badge-ok':'badge-warning')+'">'+esc(status)+'</span></td><td>'+esc(note)+'</td></tr>';
    }).join('');
  }catch(e){
    if(body)body.innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Historii se nepodařilo načíst.</td></tr>';
  }
}

function matches(r){
  if(activeFilter==='VŠE')return true;
  if(activeFilter==='ACTIVE')return ['OK','CHYBÍ V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','SPZ NESOUHLASÍ','NELZE OVĚŘIT'].includes(r.status_raw);
  if(activeFilter==='OK_TOTAL')return r.status_raw==='OK'||r.status_raw==='NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ';
  if(activeFilter==='OK_UNIQA')return r.status_raw==='OK'&&r.pojistovna==='UNIQA';
  if(activeFilter==='OK_ALLIANZ')return r.status_raw==='OK'&&r.pojistovna==='ALLIANZ';
  const resolved=['VYŘEŠENO','V POŘÁDKU'].includes(r.workflow_status);
  if(activeFilter==='MISSING')return r.status_raw==='CHYBÍ V UNIQA'&&!resolved;
  if(activeFilter==='ABSENT_INSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'&&!resolved;
  if(activeFilter==='ABSENT_UNINSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ';
  if(activeFilter==='DEPOSIT')return r.status_raw==='NEPOJIŠTĚNO, ALE DEPOZIT';
  if(activeFilter==='SOLD_UNIQA')return r.status_raw==='PRODANÉ, ALE V UNIQA'&&!resolved;
  if(activeFilter==='EXTRA_UNIQA')return r.status_raw==='NAVÍC V UNIQA'&&!resolved;
  if(activeFilter==='UNWANTED_INSURANCE')return ['NAVÍC V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','PRODANÉ, ALE V UNIQA'].includes(r.status_raw)&&!resolved;
  return true;
}

function renderActiveFilter(){const box=$('activeFilter');if(activeFilter==='VŠE'){box.hidden=true;return;}$('activeFilterLabel').textContent=filterNames[activeFilter]||activeFilter;box.hidden=false;}

function renderRows(){
  const q=$('search').value.trim().toUpperCase();
  const rows=state.results.filter(r=>matches(r)&&(!q||Object.values(r).join(' ').toUpperCase().includes(q)));
  $('footerRight').textContent='Zobrazeno: '+rows.length+' z '+state.results.length;renderActiveFilter();
  if(!rows.length){$('rows').innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Žádné výsledky pro zvolený filtr.</td></tr>';return;}
  $('rows').innerHTML=rows.map(r=>{const index=state.results.indexOf(r);return `<tr data-index="${index}"><td><span class="status-badge ${badgeClass(r)}">${esc(visibleSystemText(r.status))}</span></td><td>${esc(r.vin||'—')}</td><td>${esc(displaySpz(r)||'—')}</td><td>${esc(r.vykup||'—')}</td><td>${esc(r.prodej||'—')}</td><td>${esc(visibleSystemText(r.detail||'—'))}</td></tr>`;}).join('');
  document.querySelectorAll('#rows tr[data-index]').forEach(tr=>tr.addEventListener('click',()=>showDetail(state.results[Number(tr.dataset.index)])));
}

function formatEta(seconds){
  const s=Math.max(0,Number(seconds)||0);
  if(!state.running)return state.finished_at?'Dokončeno':'—';
  if(s<60)return 'odhad cca '+Math.max(5,Math.round(s/5)*5)+' s';
  return 'odhad cca '+Math.max(1,Math.round(s/60))+' min';
}

function progressLabel(percent,p){
  if(state.error)return 'Kontrola skončila chybou';
  if(!state.running&&state.finished_at)return 'Kontrola je dokončená a přehled je aktuální';
  if(percent<=8)return 'Ověřuji dostupnost systémů a připojení';
  if(percent<=20)return 'Načítám aktivní vozidla z interní databáze';
  if(percent<=50)return 'Aktualizuji aktivní smlouvy pojištění';
  if(percent<82)return 'Ověřuji chybějící VIN a aktualizuji data pojišťoven';
  if(percent<=94)return 'Porovnávám interní evidenci s evidencí pojištění';
  if(percent<100)return 'Připravuji a ukládám výsledný přehled';
  return p.phase||'Hotovo';
}

function setStageState(id,textId,status,text){
  const el=$(id);
  if(!el)return;
  el.classList.remove('waiting','active','done','error');
  el.classList.add(status||'waiting');
  const target=$(textId);
  if(target)target.textContent=text||'';
}

function primaryIssueCounts(){
  const s=state.summary||{};
  const missing=Number(s.missing)||0;
  const absent=Number(s.absent_insured)||0;
  const sold=Number(s.sold_uniqa)||0;
  const extra=Number(s.extra_uniqa)||0;
  return {missing,absent,sold,extra,unwanted:absent+sold+extra,total:missing+absent+sold+extra};
}

function setStatusCard(cardId,textId,ok,okText,badText){
  const card=$(cardId), textEl=$(textId);
  if(!card||!textEl)return;
  card.classList.toggle('status-ok',ok);
  card.classList.toggle('status-problem',!ok);
  textEl.textContent=ok?okText:badText;
}

function renderProgress(){
  const p=state.progress||{};
  const sources=state.sources||{};
  const tir=sources.tirbazar||{};
  const uniqa=sources.uniqa||{};
  const allianz=sources.allianz||{};
  let percent=Math.max(0,Math.min(100,Number(p.percent)||0));
  if(!state.running&&state.finished_at&&!state.error)percent=100;

  $('progressPercent').textContent=Math.round(percent)+' %';
  $('progressPhase').textContent=progressLabel(percent,p);
  $('progressEta').textContent=state.error?'Kontrola skončila chybou':formatEta(p.eta_seconds);
  $('progressBar').style.width=percent+'%';
  const issues=primaryIssueCounts();
  $('progressBar').style.background=state.error?'#dc2626':(percent===100?(issues.total===0?'#16a34a':'#dc2626'):'#e3072f');

  let headline='Kontrolní systém připraven';
  let detail='Po spuštění ověřím připojení, načtu interní databázi, data pojišťoven a připravím výsledky.';
  if(state.error){
    headline='Kontrola vyžaduje pozornost';
    detail=visibleSystemText(state.error);
  }else if(!state.running&&state.finished_at){
    if(issues.total===0){
      headline='Vše v pořádku';
      detail='Databáze vozidel souhlasí s evidencí pojištění. Nechybí žádné pojištění a není evidované žádné pojištění navíc.';
    }else{
      headline='Kontrola vyžaduje pozornost';
      detail='Zjištěno: chybějící pojištění '+issues.missing+' · pojištění navíc '+issues.unwanted+'.';
    }
  }else if(state.running&&percent<=8){
    headline='Kontroluji připojení';
    detail='Ověřuji dostupnost interní sítě, databáze a kancelářského agenta.';
  }else if(state.running&&percent<=20){
    headline='Načítám interní databázi';
    detail='Aktualizuji seznam aktivních vozidel a připravuji VIN ke kontrole.';
  }else if(state.running&&percent<=82){
    headline='Načítám data z pojišťoven';
    detail='Aktualizuji aktivní smlouvy a ověřuji vozidla v evidenci pojištění.';
  }else if(state.running){
    headline='Vyhodnocuji výsledky';
    detail='Porovnávám VIN, stav pojištění, depozit a výjimky a sestavuji výsledný přehled.';
  }
  if($('progressHeadline'))$('progressHeadline').textContent=headline;
  if($('progressDetail'))$('progressDetail').textContent=detail;

  const finished=!state.running&&!!state.finished_at&&!state.error;
  const connStatus=state.error&&percent<=8?'error':(finished||percent>8?'done':(state.running?'active':'waiting'));
  setStageState('stageConnection','stageConnectionText',connStatus,
    finished||percent>8?'Připojeno a ověřeno':(state.running?'Ověřuji spojení…':'Čeká na spuštění'));

  let dbStatus='waiting';
  if(tir.state==='error')dbStatus='error';
  else if(finished||tir.state==='ok'||percent>20)dbStatus='done';
  else if(state.running&&percent>=8)dbStatus='active';
  setStageState('stageDatabase','stageDatabaseText',dbStatus,
    dbStatus==='error'?'Databáze není dostupná':
    dbStatus==='done'?'Aktivní vozidla načtena':
    dbStatus==='active'?'Načítám a aktualizuji data…':'Načtení aktivních vozidel');

  let insurerStatus='waiting';
  const insurerError=uniqa.state==='error'||allianz.state==='error';
  const insurersDone=(uniqa.state==='ok'&&allianz.state==='ok')||finished||percent>82;
  if(insurerError)insurerStatus='error';
  else if(insurersDone)insurerStatus='done';
  else if(state.running&&percent>=20)insurerStatus='active';
  let insurerText='Evidence pojištění';
  if(insurerStatus==='error')insurerText='Některý zdroj vyžaduje kontrolu';
  else if(insurerStatus==='done')insurerText='Evidence pojištění načtena';
  else if(insurerStatus==='active')insurerText='Načítám a ověřuji smlouvy…';
  setStageState('stageInsurers','stageInsurersText',insurerStatus,insurerText);

  let resultStatus='waiting';
  if(state.error&&percent>=82)resultStatus='error';
  else if(finished)resultStatus=issues.total===0?'done':'error';
  else if(state.running&&percent>=82)resultStatus='active';
  setStageState('stageResults','stageResultsText',resultStatus,
    resultStatus==='error'?(finished?'Nalezen rozdíl mezi databází a pojištěním':'Vyhodnocení nebylo dokončeno'):
    resultStatus==='done'?'Databáze a pojištění jsou v pořádku':
    resultStatus==='active'?'Porovnávám databázi s pojištěním…':'Čekám na vyhodnocení');
}

function renderChanges(){
  const changes=state.changes||{};
  const items=Array.isArray(changes.items)?changes.items:[];
  if($('changesCount'))$('changesCount').textContent=changes.count||items.length||0;
  if($('changesFooter'))$('changesFooter').textContent='Změny: '+(changes.count||items.length||0);
  if($('changesComparedTo'))$('changesComparedTo').textContent=changes.compared_to?'Denní historie navazuje na stav z: '+shortDateTime(changes.compared_to):'Pro dnešní den zatím není výchozí předchozí stav.';
  const body=$('changeRows');if(!body)return;
  if(!items.length){
    body.innerHTML='<tr class="empty-row"><td colspan="5" class="empty">Dnes zatím nebyla zachycena žádná změna.</td></tr>';
    return;
  }
  const typeLabel={NEW:'Nové vozidlo',REMOVED:'Vozidlo zmizelo',STATUS:'Změna stavu',SPZ:'Změna SPZ'};
  body.innerHTML=items.map(x=>{
    const oldValue=x.old_status||x.old_spz||'—';
    const newValue=x.new_status||x.new_spz||'—';
    return '<tr><td><span class="status-badge badge-warning">'+esc(typeLabel[x.type]||x.type||'Změna')+'</span></td><td>'+esc(x.vin||'—')+'</td><td>'+esc(x.spz||'—')+'</td><td>'+esc(visibleSystemText(oldValue))+'</td><td>'+esc(visibleSystemText(newValue))+'</td></tr>';
  }).join('');
}

function shortDateTime(value){
  if(!value)return 'zatím neproběhla';
  const text=String(value).trim();
  const match=text.match(/^(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})/);
  return match?(match[1]+' · '+match[2]):text;
}

function render(){
  const s=state.summary||{};
  const issues=primaryIssueCounts();
  const setText=(id,value)=>{const el=$(id);if(el)el.textContent=value;};
  setText('cActive',s.active||0);setText('cActiveHover',s.active||0);setText('cOkTotal',s.ok_total||0);
  setText('cOkUniqa',s.ok_uniqa||0);setText('cOkAllianz',s.ok_allianz||0);setText('cMissing',issues.missing);
  setText('tipMissingOverall',issues.missing);setText('tipExtraOverall',issues.unwanted);
  setText('cAbsentInsured',s.absent_insured||0);setText('cAbsentInsuredTop',issues.absent);setText('cAbsentUninsured',s.absent_uninsured||0);
  setText('cDeposit',s.deposit||0);setText('cSold',s.sold_uniqa||0);setText('cSoldTop',issues.sold);
  setText('cExtra',s.extra_uniqa||0);setText('cExtraHover',issues.extra);setText('cExtraTop',issues.unwanted);
  setStatusCard('overallCard','overallStatusText',issues.total===0&&!state.error,'Vše v pořádku','Vyžaduje kontrolu');
  setStatusCard('overallCard','overallStatusText',!state.running&&!!state.finished_at&&!state.error&&issues.total===0,'Vše v pořádku',state.running?'Kontrola probíhá':(state.error?'Chyba kontroly':(state.finished_at?'Vyžaduje kontrolu':'Čeká na kontrolu')));
  setStatusCard(document.querySelector('[data-filter="MISSING"]')?.id||'__none','missingStatusText',issues.missing===0,'V pořádku','Vyžaduje kontrolu');
  const missingCard=document.querySelector('.summary-card[data-filter="MISSING"]');if(missingCard){missingCard.classList.toggle('status-ok',issues.missing===0);missingCard.classList.toggle('status-problem',issues.missing>0);}
  const extraCard=document.querySelector('.summary-card[data-filter="UNWANTED_INSURANCE"]');if(extraCard){extraCard.classList.toggle('status-ok',issues.unwanted===0);extraCard.classList.toggle('status-problem',issues.unwanted>0);}
  setText('missingStatusText',issues.missing===0?'V pořádku':'Vyžaduje kontrolu');
  setText('extraStatusText',issues.unwanted===0?'V pořádku':'Vyžaduje kontrolu');
  setText('activeStatusText',state.finished_at?'Evidence načtena':'Čeká na kontrolu');
  source('tirbazar','tir');source('uniqa','uniqa');source('allianz','allianz');renderProgress();
  $('runBtn').disabled=state.running;$('runBtn').innerHTML=state.running?'Kontrola probíhá…':'<span class="play">▶</span> Spustit kontrolu';$('csvBtn').classList.toggle('disabled',!state.csv_available);
  const live=$('liveDot');if(state.running){live.className='status-dot loading';$('liveStatus').textContent='Kontrola probíhá';}else if(state.error){live.className='status-dot error';$('liveStatus').textContent='Chyba kontroly';}else if(state.finished_at){live.className='status-dot ok';$('liveStatus').textContent='Kontrola dokončena';}else{live.className='status-dot idle';$('liveStatus').textContent='Připraveno';}
  const lastCheck=$('lastCheck');if(lastCheck){lastCheck.textContent=state.running?'Kontrola právě probíhá':('Poslední kontrola: '+shortDateTime(state.finished_at));}
  $('footerLeft').textContent=state.finished_at?'Dokončeno: '+state.finished_at:(state.started_at?'Spuštěno: '+state.started_at:'Připraveno');renderRows();renderChanges();
}

async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});state=await r.json();render();if(state.error)toast(visibleSystemText(state.error),true);}catch(e){toast('Nepodařilo se načíst stav aplikace.',true);}}
async function run(){try{const r=await fetch('/api/run',{method:'POST'});const d=await r.json();if(!r.ok)toast(d.message||'Kontrolu se nepodařilo spustit.',true);await refresh();}catch(e){toast('Kontrolu se nepodařilo spustit.',true);}}

function showDetail(r){
  const original=r.original_status?`<div style="margin-top:5px;color:#64748b;font-size:11px">Původní stav: ${esc(visibleSystemText(r.original_status))}</div>`:'';
  const vehicle=(r.vozidlo||[r.znacka,r.model].filter(Boolean).join(' ')).trim()||'—';
  const spzValue=displaySpz(r)||'—';
  $('detailBody').innerHTML=`<dl class="detail-grid"><dt>Stav</dt><dd><span class="status-badge ${badgeClass(r)}">${esc(visibleSystemText(r.status))}</span>${original}</dd><dt>Vozidlo</dt><dd>${esc(vehicle)}</dd><dt>VIN</dt><dd>${esc(r.vin||'—')}</dd><dt>SPZ</dt><dd>${esc(spzValue)}</dd><dt>Datum výkupu</dt><dd>${esc(r.vykup||'—')}</dd><dt>Datum prodeje</dt><dd>${esc(r.prodej||'—')}</dd><dt>Výsledek</dt><dd>${esc(visibleSystemText(r.detail||'—'))}</dd></dl><div style="padding:0 22px 22px;border-top:1px solid #eef2f7"><h3 style="margin:16px 0 10px;font-size:14px">Interní poznámka a stav řešení</h3><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">STATUS</label><select id="workflowStatus" style="width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:8px;margin-bottom:12px"><option value="">Původní status</option><option value="V POŘÁDKU">V pořádku</option><option value="KONTROLA">Kontrola</option><option value="ŘEŠÍ SE">Řeší se</option><option value="VYŘEŠENO">Vyřešeno</option></select><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">POZNÁMKA</label><textarea id="vehicleNote" rows="4" maxlength="2000" placeholder="Např. zrušení pojištění zadáno 14.9., čekáme na potvrzení…" style="width:100%;resize:vertical;padding:9px;border:1px solid #cbd5e1;border-radius:8px;font:inherit">${esc(r.note||'')}</textarea><div style="display:flex;justify-content:flex-end;margin-top:12px"><button id="saveMeta" class="btn btn-primary" type="button">Uložit</button></div></div>`;
  $('workflowStatus').value=r.workflow_status||'';
  $('saveMeta').addEventListener('click',()=>saveMeta(r));
  $('detailDialog').showModal();
}

async function saveMeta(r){
  const btn=$('saveMeta');btn.disabled=true;
  try{const res=await fetch('/api/result-meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:resultKey(r),note:$('vehicleNote').value,workflow_status:$('workflowStatus').value})});const d=await res.json();if(!res.ok)throw new Error(d.message||'Uložení selhalo.');toast('Poznámka a status uloženy.');$('detailDialog').close();await refresh();}catch(e){toast(e.message||'Uložení selhalo.',true);}finally{btn.disabled=false;}
}

function setFilter(filter){hideSources();hideBreakdown();showData();activeFilter=filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('selected',x.dataset.filter===filter));document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));const side=document.querySelector(`.nav-item[data-filter="${filter}"]`);if(side)side.classList.add('active');renderRows();}
function clearFilter(){hideSources();hideBreakdown();showData();activeFilter='VŠE';$('search').value='';document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('selected'));document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));$('navAllVehicles').classList.add('active');renderRows();}
let lastToast='';function toast(msg,error=false){if(!msg||msg===lastToast)return;lastToast=msg;const t=$('toast');t.textContent=msg;t.className='toast'+(error?' error':'');t.hidden=false;setTimeout(()=>{t.hidden=true;lastToast='';},5000);}

$('runBtn').addEventListener('click',run);$('search').addEventListener('input',renderRows);$('clearBtn').addEventListener('click',clearFilter);$('clearFilterInline').addEventListener('click',clearFilter);$('navAllVehicles').addEventListener('click',clearFilter);$('navSources').addEventListener('click',showSources);$('navChanges').addEventListener('click',showChanges);$('navManualHistory').addEventListener('click',showManualHistory);$('navBreakdown').addEventListener('click',showBreakdown);document.querySelectorAll('[data-filter]').forEach(c=>c.addEventListener('click',()=>setFilter(c.dataset.filter)));$('closeDialog').addEventListener('click',()=>$('detailDialog').close());$('detailDialog').addEventListener('click',e=>{if(e.target===$('detailDialog'))$('detailDialog').close();});
setInterval(refresh,2000);refresh();