let state={results:[],summary:{},sources:{},running:false,progress:{percent:0,phase:'Připraveno',eta_seconds:0}};
let activeFilter='ATTENTION';
let sessionCheckStarted=false;
let initialStateLoaded=false;

const $=id=>document.getElementById(id);

const filterNames={
  'VŠE':'Všechna vozidla','ACTIVE':'Aktivní ke kontrole','OK_TOTAL':'Pojištění v pořádku','OK_UNIQA':'Pojištění nalezeno','OK_ALLIANZ':'Pojištění nalezeno','MISSING':'Chybí pojištění','ABSENT_INSURED':'Nepřítomné, ale pojištěno','ABSENT_UNINSURED':'Nepřítomné, ale nepojištěno','DEPOSIT':'Nepojištěno, ale depozit','SOLD_UNIQA':'Prodané, ale pojištěno','EXTRA_UNIQA':'Pojištění navíc','UNWANTED_INSURANCE':'Pojištění navíc'
};

function esc(v){return String(v??'').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function displaySpz(r){return (r.spz_tir||r.spz_uniqa||'').trim();}
function resultKey(r){const vin=(r.vin||'').trim().toUpperCase();const spz=displaySpz(r).toUpperCase();return vin||('SPZ:'+spz);}
function badgeClass(r){
  const raw=String(r.status_raw||'').toUpperCase();
  const workflow=String(r.workflow_status||'').toUpperCase();
  if(raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'){
    return workflow==='VYŘEŠENO'?'badge-ok':'badge-missing';
  }
  if(workflow==='VYŘEŠENO'||workflow==='V POŘÁDKU') return 'badge-ok';
  if(workflow==='ŘEŠÍ SE'||workflow==='KONTROLA') return 'badge-warning';
  return ({'OK':'badge-ok','CHYBÍ V UNIQA':'badge-missing','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ':'badge-error','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ':'badge-ok','NEPOJIŠTĚNO, ALE DEPOZIT':'badge-ok','PRODANÉ, ALE V UNIQA':'badge-sold','NAVÍC V UNIQA':'badge-extra','SPZ NESOUHLASÍ':'badge-warning','NELZE OVĚŘIT':'badge-error'}[r.status_raw]||'badge-error');
}
function visibleSystemText(value){
  return String(value??'');
}

function rowBadgeClass(r){
  const raw=String(r.status_raw||'').toUpperCase();
  const workflow=String(r.workflow_status||'').toUpperCase();
  const forceExtraRed=(activeFilter==='EXTRA_UNIQA'||activeFilter==='UNWANTED_INSURANCE')
    && (raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'||raw==='NAVÍC V UNIQA')
    && !['VYŘEŠENO','V POŘÁDKU'].includes(workflow);
  return forceExtraRed?'badge-missing':badgeClass(r);
}

function rowPriority(r){
  const badge=rowBadgeClass(r);
  if(['badge-missing','badge-error','badge-sold','badge-extra'].includes(badge)) return 0;
  if(badge==='badge-warning') return 1;
  if(badge==='badge-deposit') return 2;
  if(badge==='badge-ok') return 3;
  return 2;
}

function source(name,prefix){
  const s=state.sources[name]||{};
  $(prefix+'Dot').className='status-dot '+(s.state||'idle');
  const detail=s.detail?(' · '+visibleSystemText(s.detail)):'';
  $(prefix+'Status').textContent=visibleSystemText(s.status||'Zatím nenačteno')+detail;
  $(prefix+'Detail').textContent='';
}

function hideSources(){const section=$('sourceSection');if(section)section.hidden=true;const btn=$('navSources');if(btn)btn.classList.remove('active');}
function hideBreakdown(){const section=$('breakdownSection');if(section)section.hidden=true;}
function hideData(){const section=$('dataSection');if(section)section.hidden=true;}
function hideChanges(){const section=$('changesSection');if(section)section.hidden=true;const btn=$('navChanges');if(btn)btn.classList.remove('active');}
function hideManualHistory(){const section=$('manualHistorySection');if(section)section.hidden=true;const btn=$('navManualHistory');if(btn)btn.classList.remove('active');}
function hideHowItWorks(){const section=$('howItWorksSection');if(section)section.hidden=true;const btn=$('navHowItWorks');if(btn)btn.classList.remove('active');}
function showHowItWorks(){
  hideSources();hideBreakdown();hideChanges();hideManualHistory();hideData();
  const section=$('howItWorksSection');if(!section)return;
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  const nav=$('navHowItWorks');if(nav)nav.classList.add('active');
  section.scrollIntoView({behavior:'smooth',block:'start'});
}
function showData(){hideChanges();hideManualHistory();hideHowItWorks();const section=$('dataSection');if(!section)return;section.hidden=false;section.scrollIntoView({behavior:'smooth',block:'start'});}
function showChanges(){
  hideSources();hideBreakdown();hideManualHistory();hideHowItWorks();hideData();
  const section=$('changesSection');if(!section)return;
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  const nav=$('navOthers');if(nav)nav.classList.add('active');
  renderChanges();
  section.scrollIntoView({behavior:'smooth',block:'start'});
}
function showSources(){
  const section=$('sourceSection');if(!section)return;
  hideBreakdown();hideChanges();hideManualHistory();hideHowItWorks();hideData();
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  const nav=$('navOthers');if(nav)nav.classList.add('active');
  section.scrollIntoView({behavior:'smooth',block:'start'});
}
function showBreakdown(){
  const section=$('breakdownSection');if(!section)return;
  hideSources();hideChanges();hideManualHistory();hideHowItWorks();hideData();
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  const nav=$('navOthers');if(nav)nav.classList.add('active');
  section.scrollIntoView({behavior:'smooth',block:'start'});
}

async function showManualHistory(){
  hideSources();hideBreakdown();hideChanges();hideHowItWorks();hideData();
  const section=$('manualHistorySection');if(!section)return;
  section.hidden=false;
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  const nav=$('navOthers');if(nav)nav.classList.add('active');
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

const problemStatuses=['CHYBÍ V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','PRODANÉ, ALE V UNIQA','NAVÍC V UNIQA','SPZ NESOUHLASÍ','NELZE OVĚŘIT'];
function needsAttention(r){
  const raw=String(r.status_raw||'').toUpperCase();
  const workflow=String(r.workflow_status||'').toUpperCase();
  const resolved=raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'?workflow==='VYŘEŠENO':['VYŘEŠENO','V POŘÁDKU'].includes(workflow);
  return problemStatuses.includes(raw)&&!resolved;
}
function resultLabel(r){
  return ({'OK':'Pojištění v pořádku','CHYBÍ V UNIQA':'Chybí pojištění','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ':'Nepřítomné · pojištěno','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ':'Nepřítomné · nepojištěno','PRODANÉ, ALE V UNIQA':'Prodané · pojištěno','NAVÍC V UNIQA':'Pojištění navíc','NEPOJIŠTĚNO, ALE DEPOZIT':'Depozit','SPZ NESOUHLASÍ':'SPZ nesouhlasí','NELZE OVĚŘIT':'Nelze ověřit'}[r.status_raw]||r.original_status||r.status_raw||r.status||'—');
}
filterNames.ATTENTION='K řešení';
function matches(r){
  if(activeFilter==='VŠE')return true;
  if(activeFilter==='ATTENTION')return needsAttention(r);
  if(activeFilter==='ACTIVE')return ['OK','CHYBÍ V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ','SPZ NESOUHLASÍ','NELZE OVĚŘIT'].includes(r.status_raw);
  if(activeFilter==='OK_TOTAL'){
    const raw=String(r.status_raw||'').toUpperCase();
    const workflow=String(r.workflow_status||'').toUpperCase();
    if(raw==='OK')return true;
    if(raw==='CHYBÍ V UNIQA')return ['VYŘEŠENO','V POŘÁDKU'].includes(workflow);
    if(raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ')return workflow==='VYŘEŠENO';
    return false;
  }
  if(activeFilter==='OK_UNIQA')return r.status_raw==='OK'&&r.pojistovna==='UNIQA';
  if(activeFilter==='OK_ALLIANZ')return r.status_raw==='OK'&&r.pojistovna==='ALLIANZ';
  const resolved=['VYŘEŠENO','V POŘÁDKU'].includes(r.workflow_status);
  if(activeFilter==='MISSING')return r.status_raw==='CHYBÍ V UNIQA'&&!resolved;
  if(activeFilter==='ABSENT_INSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ';
  if(activeFilter==='ABSENT_UNINSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ';
  if(activeFilter==='DEPOSIT')return r.status_raw==='NEPOJIŠTĚNO, ALE DEPOZIT';
  if(activeFilter==='SOLD_UNIQA')return r.status_raw==='PRODANÉ, ALE V UNIQA';
  if(activeFilter==='EXTRA_UNIQA'){
    return r.status_raw==='NAVÍC V UNIQA';
  }
  if(activeFilter==='UNWANTED_INSURANCE'){
    return ['NAVÍC V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','PRODANÉ, ALE V UNIQA'].includes(r.status_raw)&&needsAttention(r);
  }
  return true;
}

function renderActiveFilter(){const box=$('activeFilter');if(['VŠE','ATTENTION'].includes(activeFilter)){box.hidden=true;return;}$('activeFilterLabel').textContent=filterNames[activeFilter]||activeFilter;box.hidden=false;}

function renderRows(){
  renderActiveFilter();
  document.querySelectorAll('.view-switch button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.filter===activeFilter)));
  $('clearBtn').hidden=!$('search').value;


  if(!sessionCheckStarted&&!state.running){
    $('footerRight').textContent='Zobrazeno: 0 z 0';
    $('rows').innerHTML='<tr class="empty-row"><td colspan="3" class="empty">Nejdříve spusťte aktuální kontrolu pojištění.</td></tr>';
    return;
  }

  if(state.running||(sessionCheckStarted&&!state.error&&!state.running&&!!state.finished_at&&connectionVisualPercent<100)){
    $('footerRight').textContent='Zobrazeno: 0 z 0';
    $('rows').innerHTML='<tr class="empty-row"><td colspan="3" class="empty">Kontrola právě probíhá. Výsledky se zobrazí až po jejím dokončení na 100 %.</td></tr>';
    return;
  }

  const q=$('search').value.trim().toUpperCase();
  const rows=state.results
    .filter(r=>matches(r)&&(!q||Object.values(r).join(' ').toUpperCase().includes(q)))
    .sort((a,b)=>{
      const priority=rowPriority(a)-rowPriority(b);
      if(priority!==0)return priority;
      return String(displaySpz(a)||a.vin||'').localeCompare(String(displaySpz(b)||b.vin||''),'cs',{numeric:true,sensitivity:'base'});
    });
  $('footerRight').textContent='Zobrazeno: '+rows.length+' z '+state.results.length;
  if(!rows.length){$('rows').innerHTML=`<tr class="empty-row"><td colspan="3" class="empty">${activeFilter==='ATTENTION'&&!q?'Žádné případy k řešení.':'Žádná vozidla pro zvolené hledání nebo filtr.'}</td></tr>`;return;}
  $('rows').innerHTML=rows.map(r=>{
    const index=state.results.indexOf(r);
    const badge=badgeClass({...r,workflow_status:''});
    const vehicle=r.vozidlo||[r.znacka,r.model].filter(Boolean).join(' ');
    const workflow=r.workflow_status|| (needsAttention(r)?'Nové':'—');
    const workflowClass=['VYŘEŠENO','V POŘÁDKU'].includes(workflow)?'badge-ok':workflow==='—'?'badge-neutral':'badge-warning';
    const rowClass=(String(r.status_raw||'').toUpperCase()==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ' && String(r.workflow_status||'').toUpperCase()!=='VYŘEŠENO')?'problem-row':'';
    return `<tr class="${rowClass}" data-index="${index}"><td><button class="vehicle-open" type="button" data-index="${index}" aria-label="Otevřít vozidlo ${esc(displaySpz(r)||r.vin)}">${esc(displaySpz(r)||'Bez SPZ')}</button>${vehicle?`<span class="vehicle-name">${esc(vehicle)}</span>`:''}<span class="vehicle-vin">${esc(r.vin||'—')}</span></td><td><span class="status-badge ${badge}">${esc(resultLabel(r))}</span></td><td><span class="status-badge ${workflowClass}">${esc(workflow)}</span>${r.note?'<span class="note-indicator">Poznámka v detailu</span>':''}</td></tr>`;
  }).join('');
  document.querySelectorAll('.vehicle-open').forEach(button=>button.addEventListener('click',event=>{event.stopPropagation();showDetail(state.results[Number(button.dataset.index)]);}));
  document.querySelectorAll('#rows tr[data-index]').forEach(tr=>tr.addEventListener('click',()=>showDetail(state.results[Number(tr.dataset.index)])));
}

function primaryIssueCounts(){
  const s=state.summary||{};
  const missing=Number(s.missing)||0;
  const absent=Number(s.absent_insured)||0;
  const sold=Number(s.sold_uniqa)||0;
  const extra=Number(s.extra_uniqa)||0;
  return {missing,absent,sold,extra,unwanted:absent+sold+extra,total:missing+absent+sold+extra};
}

function categoryBreakdown(rawStatus){
  const rows=(state.results||[]).filter(r=>String(r.status_raw||'').toUpperCase()===rawStatus);
  const isResolved=r=>{
    const workflow=String(r.workflow_status||'').toUpperCase();
    if(rawStatus==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ') return workflow==='VYŘEŠENO';
    return ['VYŘEŠENO','V POŘÁDKU'].includes(workflow);
  };
  const resolved=rows.filter(isResolved).length;
  return {total:rows.length,resolved,open:Math.max(0,rows.length-resolved)};
}

function setStatusCard(cardId,textId,ok,okText,badText){
  const card=$(cardId), textEl=$(textId);
  if(!card||!textEl)return;
  card.classList.toggle('status-ok',ok);
  card.classList.toggle('status-problem',!ok);
  textEl.textContent=ok?okText:badText;
}

let connectionVisualPercent=0;

function renderProgress(){
  const running=!!state.running;
  $('progressPanel').hidden=!running&&!state.error;
  const percent=Math.max(0,Math.min(100,Number((state.progress||{}).percent)||0));
  connectionVisualPercent=running?percent:100;
  $('progressPercent').textContent=state.error?'!':Math.round(percent)+' %';
  $('progressEta').textContent=state.error?'Chyba':'Probíhá';
  $('progressHeadline').textContent=state.error?'Kontrola se nezdařila':'Kontroluji pojištění';
  $('progressPhase').textContent=state.error?'Výsledek není úplný. Zkuste kontrolu znovu nebo otevřete stav datových zdrojů.':((state.progress||{}).phase||'Načítám a porovnávám evidenci vozidel.');
  $('progressBar').style.width=percent+'%';
  const connectionVisual=$('connectionVisual');
  if(connectionVisual) connectionVisual.style.setProperty('--connection-progress',String(percent));
  $('connectionVisual').className='connection-visual '+(state.error?'error':'running');
  $('connectionVisualIcon').textContent=state.error?'!':'↻';
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
  const attention=(state.results||[]).filter(needsAttention).length;
  const sourceError=Object.values(state.sources||{}).some(source=>source&&source.state==='error');
  const absentBreakdown=categoryBreakdown('NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ');
  const soldBreakdown=categoryBreakdown('PRODANÉ, ALE V UNIQA');
  const extraBreakdown=categoryBreakdown('NAVÍC V UNIQA');
  const extraProblemCount=extraBreakdown.open;

  const waitingFreshPage=!sessionCheckStarted&&!state.running;
  const visualCompletionPending=false;
  const suppressFinalResults=waitingFreshPage||state.running||visualCompletionPending;
  const setText=(id,value)=>{const el=$(id);if(el)el.textContent=value;};
  const shown=(value)=>suppressFinalResults?0:(Number(value)||0);
  document.body.classList.toggle('check-running',!!state.running);
  setText('attentionCount',suppressFinalResults?'—':attention);
  setText('allCount',suppressFinalResults?'—':state.results.length);
  setText('cActive',shown(s.active));setText('cActiveHover',shown(s.active));setText('cActiveOverview',shown(s.active));setText('cOkTotal',shown(s.ok_total));
  setText('cOkUniqa',shown(s.ok_total));setText('cOkAllianz',shown(s.ok_allianz));setText('cMissing',shown(issues.missing));
  setText('tipMissingOverall',shown(issues.missing));setText('tipExtraOverall',shown(issues.unwanted));
  setText('cAbsentInsured',shown(absentBreakdown.total));setText('cAbsentInsuredTop',shown(issues.absent));setText('cAbsentUninsured',shown(s.absent_uninsured));
  setText('cAbsentResolved',shown(absentBreakdown.resolved));setText('cAbsentOpen',shown(absentBreakdown.open));
  setText('cDeposit',shown(s.deposit));setText('cSold',shown(soldBreakdown.total));setText('cSoldTop',shown(issues.sold));
  setText('cSoldResolved',shown(soldBreakdown.resolved));setText('cSoldOpen',shown(soldBreakdown.open));
  setText('cExtra',shown(extraBreakdown.total));setText('cExtraResolved',shown(extraBreakdown.resolved));setText('cExtraOpen',shown(extraBreakdown.open));
  setText('cExtraHover',shown(issues.extra));setText('cExtraTop',shown(issues.unwanted));setText('navExtraCount',shown(issues.unwanted));setText('cTodayChanges',shown((state.changes&&state.changes.count)||0));

  const navExtraCount=$('navExtraCount');
  if(navExtraCount){
    const showExtraIndicator=!suppressFinalResults&&sessionCheckStarted&&!!state.finished_at&&!state.error&&issues.unwanted>0;
    navExtraCount.textContent=showExtraIndicator?String(issues.unwanted):'0';
    navExtraCount.classList.toggle('is-alert',showExtraIndicator);
    navExtraCount.classList.toggle('is-hidden',!showExtraIndicator);
    navExtraCount.hidden=!showExtraIndicator;
  }

  const setMetricProblemState=(filter,problemCount)=>{
    const card=document.querySelector('.metric-card[data-filter="'+filter+'"]');
    if(!card)return;
    card.classList.remove('metric-danger','metric-success');
    if(!suppressFinalResults){
      card.classList.add(problemCount>0?'metric-danger':'metric-success');
    }
  };
  setMetricProblemState('ABSENT_INSURED',absentBreakdown.open);
  setMetricProblemState('SOLD_UNIQA',soldBreakdown.open);
  setMetricProblemState('EXTRA_UNIQA',extraProblemCount);

  const overallCounts=$('overallCounts');
  if(overallCounts){
    overallCounts.hidden=suppressFinalResults||!!state.error;
  }

  const summaryCards=document.querySelectorAll('.overview-sticky .summary-card');
  summaryCards.forEach(card=>card.classList.toggle('status-running',!!state.running));
  const missingDot=$('missingStatusDot');
  if(missingDot){
    missingDot.classList.remove('ok','problem','loading');
    if(state.running||visualCompletionPending) missingDot.classList.add('loading');
    else if(sessionCheckStarted) missingDot.classList.add(issues.missing===0?'ok':'problem');
  }

  if(state.running||visualCompletionPending){
    sessionCheckStarted=true;
    const pendingText=state.running?'Probíhá kontrola':'Dokončuji kontrolu';
    setText('overallStatusText',pendingText);
    setText('missingStatusText',pendingText);
    setText('extraStatusText',pendingText);
    setText('activeStatusText',pendingText);
    summaryCards.forEach(card=>{card.classList.remove('status-ok','status-problem');});
  }else if(!sessionCheckStarted){
    setText('overallStatusText','Čeká na kontrolu');
    setText('missingStatusText','Čeká na kontrolu');
    setText('extraStatusText','Čeká na kontrolu');
    setText('activeStatusText','Čeká na kontrolu');
    summaryCards.forEach(card=>{card.classList.remove('status-ok','status-problem');});
  }else{
    setStatusCard('overallCard','overallStatusText',!!state.finished_at&&!state.error&&!sourceError&&attention===0,'Bez otevřených případů',state.error?'Chyba kontroly':sourceError?'Neúplná kontrola':'Vyžaduje řešení');
    const missingCard=document.querySelector('.summary-card[data-filter="MISSING"]');
    if(missingCard){missingCard.classList.toggle('status-ok',issues.missing===0);missingCard.classList.toggle('status-problem',issues.missing>0);}
    const extraCard=document.querySelector('.summary-card[data-filter="UNWANTED_INSURANCE"]');
    if(extraCard){extraCard.classList.toggle('status-ok',issues.unwanted===0);extraCard.classList.toggle('status-problem',issues.unwanted>0);}
    setText('missingStatusText',issues.missing===0?'V pořádku':'Vyžaduje kontrolu');
    setText('extraStatusText',issues.unwanted===0?'V pořádku':'Vyžaduje kontrolu');
    setText('activeStatusText','Evidence načtena');
  }
  setText('overallIcon',state.running?'↻':state.error||sourceError||attention?'!':sessionCheckStarted?'✓':'—');
  source('tirbazar','tir');source('uniqa','uniqa');source('allianz','allianz');renderProgress();
  const runBtn=$('runBtn');
  runBtn.disabled=state.running;
  const runSmall=runBtn.querySelector('.run-check-cta-copy small');
  const runStrong=runBtn.querySelector('.run-check-cta-copy strong');
  const runIcon=runBtn.querySelector('.run-check-cta-icon .play');
  if(runSmall)runSmall.textContent=state.running?'PROBÍHÁ AKTUÁLNÍ OVĚŘENÍ':'SPUSTIT NOVÉ OVĚŘENÍ';
  if(runStrong)runStrong.textContent=state.running?'Kontrola probíhá…':'Spustit kontrolu';
  if(runIcon)runIcon.textContent=state.running?'↻':'▶';
  const csvBtn=$('csvBtn');
  const exportReady=!!state.csv_available&&!state.running&&sessionCheckStarted&&!!state.finished_at&&!state.error;
  const exportDisabled=!sessionCheckStarted||!state.csv_available||state.running||!!state.error;
  csvBtn.classList.toggle('disabled',exportDisabled);
  csvBtn.classList.toggle('export-ready',exportReady);
  csvBtn.setAttribute('aria-disabled',exportDisabled?'true':'false');
  const live=$('liveDot');if(state.running){live.className='status-dot loading';$('liveStatus').textContent='Kontrola probíhá';}else if(sessionCheckStarted&&state.error){live.className='status-dot error';$('liveStatus').textContent='Chyba kontroly';}else if(sessionCheckStarted&&state.finished_at){live.className='status-dot ok';$('liveStatus').textContent='Kontrola dokončena';}else{live.className='status-dot idle';$('liveStatus').textContent='Připraveno';}
  const lastCheck=$('lastCheck');if(lastCheck){lastCheck.textContent=state.running&&sessionCheckStarted?'Právě probíhá':sessionCheckStarted?shortDateTime(state.finished_at):'—';}
  $('footerLeft').textContent=state.running&&state.started_at?'Spuštěno: '+state.started_at:(sessionCheckStarted&&state.finished_at?'Dokončeno: '+state.finished_at:'Připraveno');renderRows();renderChanges();
}

async function refresh(){try{
  const r=await fetch('/api/state',{cache:'no-store'});
  if(!r.ok)throw new Error('Načtení selhalo');
  state=await r.json();
  if(!state.running)connectionVisualPercent=100;
  if(!initialStateLoaded){
    // Nově otevřená stránka začíná vždy čistě. Uložený poslední výsledek
    // zůstává na serveru kvůli historii, ale na dashboardu se neukáže,
    // dokud uživatel v této relaci nespustí novou kontrolu.
    sessionCheckStarted=false;
    if(!state.running)connectionVisualPercent=100;
    initialStateLoaded=true;
  }
  render();
  if(sessionCheckStarted&&state.error)toast(visibleSystemText(state.error),true);
}catch(e){toast('Nepodařilo se načíst stav aplikace.',true);}}
async function run(){
  const previousState=state;
  state={...state};
  sessionCheckStarted=true;
  document.body.classList.remove('check-finalized');
  state.running=true;
  state.summary={};
  state.results=[];
  state.changes={count:0,items:[]};
  connectionVisualPercent=0;
  state.error=null;
  setFilter('ATTENTION');
  render();
  try{const r=await fetch('/api/run',{method:'POST'});const d=await r.json();if(!r.ok)toast(d.message||'Kontrolu se nepodařilo spustit.',true);await refresh();}catch(e){state=previousState;render();toast('Kontrolu se nepodařilo spustit.',true);}}

function kostkaDate(value){
  const match=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/);
  return match?`${match[3]}/${match[2]}/${match[1]}`:(value||'—');
}
function kostkaRows(data){
  const rows=[
    ['Stav v registru',data.StatusNazev],
    ['Tovární značka',data.TovarniZnacka],
    ['Obchodní označení',data.ObchodniOznaceni],
    ['Technická prohlídka do',kostkaDate(data.PravidelnaTechnickaProhlidkaDo)]
  ];
  return rows.map(([label,value])=>`<dt>${esc(label)}</dt><dd>${esc(value||'—')}</dd>`).join('');
}
async function loadKostka(vin){
  const section=$('kostkaSection'),status=$('kostkaStatus');
  if(!section||!status)return;
  status.textContent='Načítám uložené údaje…';
  try{
    for(let attempt=0;attempt<13;attempt++){
      if($('kostkaSection')!==section||!$('detailDialog').open)return;
      const response=await fetch('/api/vehicle-technical/'+encodeURIComponent(vin),{cache:'no-store'});
      const result=await response.json();
      if(!response.ok||!result.ok)throw new Error(result.message||'Údaje se nepodařilo načíst.');
      if($('kostkaSection')!==section||!$('detailDialog').open)return;
      if(result.data){
        const rows=kostkaRows(result.data);
        const vehicleName=[result.data.TovarniZnacka,result.data.ObchodniOznaceni]
          .map(value=>String(value||'').trim())
          .filter(Boolean)
          .join(' ');
        const vehicleDetailValue=$('vehicleDetailValue');
        if(vehicleDetailValue&&vehicleName)vehicleDetailValue.textContent=vehicleName;
        status.textContent='Datová kostka · uloženo '+new Date(result.fetched_at).toLocaleDateString('cs-CZ');
        $('kostkaData').innerHTML=rows?`<dl class="detail-grid kostka-grid">${rows}</dl>`:'';
        return;
      }
      status.textContent=result.message||'Technické údaje zatím nejsou dostupné.';
      if(!result.pending)return;
      if(attempt<12)await new Promise(resolve=>setTimeout(resolve,10000));
    }
    if($('kostkaSection')===section)status.textContent='Údaje zatím nejsou dostupné. Zobrazí se po další kontrole.';
  }catch(error){if($('kostkaSection')===section)status.textContent=error.message||'Načtení se nezdařilo.';}
}
function showDetail(r){
  const original=r.original_status?`<div style="margin-top:5px;color:#64748b;font-size:11px">Původní stav: ${esc(visibleSystemText(r.original_status))}</div>`:'';
  const vehicle=(r.vozidlo||[r.znacka,r.model].filter(Boolean).join(' ')).trim()||'—';
  const spzValue=displaySpz(r)||'—';
  $('detailBody').innerHTML=`<dl class="detail-grid"><dt>Stav</dt><dd><span class="status-badge ${badgeClass(r)}">${esc(visibleSystemText(r.status))}</span>${original}</dd><dt>Vozidlo</dt><dd id="vehicleDetailValue">${esc(vehicle)}</dd><dt>VIN</dt><dd>${esc(r.vin||'—')}</dd><dt>SPZ</dt><dd>${esc(spzValue)}</dd><dt>Datum výkupu</dt><dd>${esc(r.vykup||'—')}</dd><dt>Datum prodeje</dt><dd>${esc(r.prodej||'—')}</dd><dt>Výsledek</dt><dd>${esc(visibleSystemText(r.detail||'—'))}</dd></dl><section id="kostkaSection" class="kostka-section"><div class="kostka-heading"><div><h3>Technické údaje vozidla</h3><p id="kostkaStatus">Načítám uložené údaje…</p></div></div><div id="kostkaData"></div></section><div style="padding:0 22px 22px;border-top:1px solid #eef2f7"><h3 style="margin:16px 0 10px;font-size:14px">Interní poznámka a stav řešení</h3><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">STATUS</label><select id="workflowStatus" style="width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:8px;margin-bottom:12px"><option value="">Původní status</option>${r.status_raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'?'':'<option value="V POŘÁDKU">V pořádku</option>'}<option value="KONTROLA">Kontrola</option><option value="ŘEŠÍ SE">Řeší se</option><option value="VYŘEŠENO">Vyřešeno</option></select><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">POZNÁMKA</label><textarea id="vehicleNote" rows="4" maxlength="2000" placeholder="Např. zrušení pojištění zadáno 14.9., čekáme na potvrzení…" style="width:100%;resize:vertical;padding:9px;border:1px solid #cbd5e1;border-radius:8px;font:inherit">${esc(r.note||'')}</textarea><div style="display:flex;justify-content:flex-end;margin-top:12px"><button id="saveMeta" class="btn btn-primary" type="button">Uložit</button></div></div>`;
  $('workflowStatus').value=r.workflow_status||'';
  $('saveMeta').addEventListener('click',()=>saveMeta(r));
  $('detailDialog').showModal();
  const vin=String(r.vin||'').replace(/\s/g,'').toUpperCase();
  if(/^[A-HJ-NPR-Z0-9]{17}$/.test(vin))loadKostka(vin);
  else $('kostkaStatus').textContent='Vozidlo nemá platné VIN pro vyhledání.';
}

async function saveMeta(r){
  const btn=$('saveMeta');btn.disabled=true;
  try{const res=await fetch('/api/result-meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:resultKey(r),note:$('vehicleNote').value,workflow_status:$('workflowStatus').value})});const d=await res.json();if(!res.ok)throw new Error(d.message||'Uložení selhalo.');toast('Poznámka a status uloženy.');$('detailDialog').close();await refresh();}catch(e){toast(e.message||'Uložení selhalo.',true);}finally{btn.disabled=false;}
}

function setFilter(filter){
  hideSources();hideBreakdown();showData();activeFilter=filter;
  document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('selected',x.dataset.filter===filter));
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  const side=document.querySelector(`.nav-item[data-filter="${filter}"]`);
  if(side)side.classList.add('active');else if(filter==='VŠE')$('navAllVehicles').classList.add('active');else if(filter!=='VŠE'&&$('navOthers'))$('navOthers').classList.add('active');
  renderRows();
}
function clearFilter(){
  hideSources();hideBreakdown();showData();activeFilter='VŠE';$('search').value='';
  document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('selected'));
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  $('navAllVehicles').classList.add('active');renderRows();
}
let lastToast='';function toast(msg,error=false){if(!msg||msg===lastToast)return;lastToast=msg;const t=$('toast');t.textContent=msg;t.className='toast'+(error?' error':'');t.hidden=false;setTimeout(()=>{t.hidden=true;lastToast='';},5000);}

$('runBtn').addEventListener('click',run);$('search').addEventListener('input',renderRows);$('clearBtn').addEventListener('click',()=>{$('search').value='';renderRows();});$('clearFilterInline').addEventListener('click',clearFilter);$('navAllVehicles').addEventListener('click',clearFilter);$('navOthers').addEventListener('click',showBreakdown);$('navHowItWorks').addEventListener('click',showHowItWorks);$('overviewTodayChanges').addEventListener('click',showChanges);$('overviewManualChanges').addEventListener('click',showManualHistory);$('overviewSources').addEventListener('click',showSources);document.querySelectorAll('[data-filter]').forEach(c=>c.addEventListener('click',()=>setFilter(c.dataset.filter)));$('closeDialog').addEventListener('click',()=>$('detailDialog').close());$('detailDialog').addEventListener('click',e=>{if(e.target===$('detailDialog'))$('detailDialog').close();});
$('csvBtn').addEventListener('click',event=>{if($('csvBtn').getAttribute('aria-disabled')==='true')event.preventDefault();});
setInterval(refresh,2000);refresh();
