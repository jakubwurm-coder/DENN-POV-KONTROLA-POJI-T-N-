let state={results:[],summary:{},sources:{},running:false,progress:{percent:0,phase:'Připraveno',eta_seconds:0}};
let activeFilter='ATTENTION';
let sessionCheckStarted=false;
let initialStateLoaded=false;

const $=id=>document.getElementById(id);

const filterNames={
  'VŠE':'Všechna vozidla','ACTIVE':'Aktivní ke kontrole','OK_TOTAL':'Pojištění v pořádku','OK_UNIQA':'Pojištění nalezeno','OK_ALLIANZ':'Pojištění nalezeno','MISSING':'Chybí pojištění','ABSENT_INSURED':'Nepřítomné, ale pojištěno','ABSENT_UNINSURED':'Nepřítomné, ale nepojištěno','DEPOSIT':'Nepojištěno, ale depozit','DEPOSIT_INSURED':'Depozit, ale pojištěno','SOLD_UNIQA':'Prodané, ale pojištěno','EXTRA_UNIQA':'Pojištění navíc','UNWANTED_INSURANCE':'Pojištění navíc'
};

function esc(v){return String(v??'').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function displaySpz(r){return (r.spz_tir||r.spz_uniqa||'').trim();}
function resultKey(r){const vin=(r.vin||'').trim().toUpperCase();const spz=displaySpz(r).toUpperCase();return vin||('SPZ:'+spz);}
const redInsuranceStatuses=['NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','PRODANÉ, ALE POJIŠTĚNÉ','NAVÍC V UNIQA','DEPOZIT, ALE POJIŠTĚNÉ'];
function isRedInsuranceStatus(r){
  return redInsuranceStatuses.includes(String(r.status_raw||'').toUpperCase());
}
function badgeClass(r){
  const raw=String(r.status_raw||'').toUpperCase();
  const workflow=String(r.workflow_status||'').toUpperCase();
  if(workflow==='VYŘEŠENO') return 'badge-ok';
  if(isRedInsuranceStatus(r)) return 'badge-missing';
  return ({'OK':'badge-ok','CHYBÍ V UNIQA':'badge-missing','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ':'badge-error','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ':'badge-ok','NEPOJIŠTĚNO, ALE DEPOZIT':'badge-ok','DEPOZIT, ALE POJIŠTĚNÉ':'badge-error','PRODANÉ, ALE POJIŠTĚNÉ':'badge-sold','NAVÍC V UNIQA':'badge-extra','SPZ NESOUHLASÍ':'badge-warning','NELZE OVĚŘIT':'badge-error'}[r.status_raw]||'badge-error');
}
function visibleSystemText(value){
  return String(value??'');
}

function rowBadgeClass(r){
  const raw=String(r.status_raw||'').toUpperCase();
  const workflow=String(r.workflow_status||'').toUpperCase();
  const forceExtraRed=(activeFilter==='EXTRA_UNIQA'||activeFilter==='UNWANTED_INSURANCE')
    && (raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'||raw==='NAVÍC V UNIQA'||raw==='DEPOZIT, ALE POJIŠTĚNÉ')
    && workflow!=='VYŘEŠENO';
  return forceExtraRed?'badge-missing':badgeClass(r);
}

function rowPriority(r){
  if(isUnusual(r)) return needsAttention(r)?0:2;
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
function showData(){hideChanges();hideManualHistory();hideHowItWorks();const section=$('dataSection');if(!section)return;section.dataset.userOpened='1';section.hidden=false;section.scrollIntoView({behavior:'smooth',block:'start'});}
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
      return '<tr><td>'+esc(x.changed_at||'—')+'</td><td>'+esc(x.vin||x.vehicle_key||'—')+'</td><td>'+esc(x.spz||'—')+'</td><td>'+esc(visibleSystemText(x.original_status||'—'))+'</td><td><span class="status-badge '+(status==='VYŘEŠENO'?'badge-ok':'badge-warning')+'">'+esc(status)+'</span></td><td>'+esc(note)+'</td></tr>';
    }).join('');
  }catch(e){
    if(body)body.innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Historii se nepodařilo načíst.</td></tr>';
  }
}

const unusualStatuses=['CHYBÍ V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','PRODANÉ, ALE POJIŠTĚNÉ','NAVÍC V UNIQA','DEPOZIT, ALE POJIŠTĚNÉ','SPZ NESOUHLASÍ','NELZE OVĚŘIT'];
function isUnusual(r){
  return unusualStatuses.includes(String(r.status_raw||'').toUpperCase());
}
function needsAttention(r){
  const raw=String(r.status_raw||'').toUpperCase();
  const workflow=String(r.workflow_status||'').toUpperCase();
  return unusualStatuses.includes(raw)&&workflow!=='VYŘEŠENO';
}
function isResolvedUnusual(r){
  return isUnusual(r)&&!needsAttention(r);
}
function resultLabel(r){
  return ({'OK':'Pojištění v pořádku','CHYBÍ V UNIQA':'Chybí pojištění','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ':'Nepřítomné · pojištěno','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ':'Nepřítomné · nepojištěno','PRODANÉ, ALE POJIŠTĚNÉ':'Prodané · pojištěno','NAVÍC V UNIQA':'Pojištění navíc','NEPOJIŠTĚNO, ALE DEPOZIT':'Depozit','DEPOZIT, ALE POJIŠTĚNÉ':'Depozit · pojištěno','SPZ NESOUHLASÍ':'SPZ nesouhlasí','NELZE OVĚŘIT':'Nelze ověřit'}[r.status_raw]||r.original_status||r.status_raw||r.status||'—');
}
filterNames.ATTENTION='Výjimky kontroly';
filterNames.OPEN='Otevřené případy';
function matches(r){
  if(activeFilter==='VŠE')return true;
  if(activeFilter==='ATTENTION')return isUnusual(r);
  if(activeFilter==='OPEN')return needsAttention(r);
  if(activeFilter==='ACTIVE')return ['OK','CHYBÍ V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ','SPZ NESOUHLASÍ','NELZE OVĚŘIT'].includes(r.status_raw);
  if(activeFilter==='OK_TOTAL'){
    const raw=String(r.status_raw||'').toUpperCase();
    const workflow=String(r.workflow_status||'').toUpperCase();
    if(raw==='OK')return true;
    if(raw==='CHYBÍ V UNIQA')return workflow==='VYŘEŠENO';
    if(raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ')return workflow==='VYŘEŠENO';
    return false;
  }
  if(activeFilter==='OK_UNIQA')return r.status_raw==='OK'&&r.pojistovna==='UNIQA';
  if(activeFilter==='OK_ALLIANZ')return r.status_raw==='OK'&&r.pojistovna==='ALLIANZ';
  if(activeFilter==='MISSING')return r.status_raw==='CHYBÍ V UNIQA';
  if(activeFilter==='ABSENT_INSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ';
  if(activeFilter==='ABSENT_UNINSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ';
  if(activeFilter==='DEPOSIT')return r.status_raw==='NEPOJIŠTĚNO, ALE DEPOZIT';
  if(activeFilter==='DEPOSIT_INSURED')return r.status_raw==='DEPOZIT, ALE POJIŠTĚNÉ';
  if(activeFilter==='SOLD_UNIQA')return r.status_raw==='PRODANÉ, ALE POJIŠTĚNÉ';
  if(activeFilter==='EXTRA_UNIQA'){
    return r.status_raw==='NAVÍC V UNIQA';
  }
  if(activeFilter==='UNWANTED_INSURANCE'){
    return ['NAVÍC V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','PRODANÉ, ALE POJIŠTĚNÉ','DEPOZIT, ALE POJIŠTĚNÉ'].includes(r.status_raw);
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
  if(!rows.length){
    const emptyMessage=activeFilter==='ATTENTION'&&!q?'Kontrola neobsahuje žádné výjimky.':activeFilter==='OPEN'&&!q?'Žádné otevřené případy.':'Žádná vozidla pro zvolené hledání nebo filtr.';
    $('rows').innerHTML=`<tr class="empty-row"><td colspan="3" class="empty">${emptyMessage}</td></tr>`;
    return;
  }
  $('rows').innerHTML=rows.map(r=>{
    const index=state.results.indexOf(r);
    const badge=badgeClass(r);
    const vehicle=(r.vozidlo||[r.znacka,r.model].filter(Boolean).join(' ')||r.obchodni_oznaceni||r.tovarni_znacka||'').trim();
    const workflow=r.workflow_status|| (needsAttention(r)?'Nové':'—');
    const workflowClass=workflow==='VYŘEŠENO'?'badge-ok':workflow==='—'?'badge-neutral':'badge-warning';
    const rowClass=needsAttention(r)?'problem-row':isResolvedUnusual(r)?'resolved-unusual-row':'';
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
  const depositInsured=categoryBreakdown('DEPOZIT, ALE POJIŠTĚNÉ').open;
  return {missing,absent,sold,extra,depositInsured,unwanted:absent+sold+extra+depositInsured,total:missing+absent+sold+extra+depositInsured};
}

function categoryBreakdown(rawStatus){
  const rows=(state.results||[]).filter(r=>String(r.status_raw||'').toUpperCase()===rawStatus);
  const isResolved=r=>String(r.workflow_status||'').toUpperCase()==='VYŘEŠENO';
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
  const progressSteps=[
    [10,'Připravuji kontrolu'],
    [20,'Připojuji se k databázi vozidel'],
    [30,'Načítám aktivní vozidla'],
    [40,'Kontroluji údaje vozidel'],
    [50,'Načítám evidenci pojištění'],
    [60,'Páruji vozidla podle VIN'],
    [70,'Kontroluji stav pojištění vozidel'],
    [80,'Vyhodnocuji výjimky a nesrovnalosti'],
    [90,'Porovnávám a zpracovávám výsledky'],
    [100,'Ukládám a připravuji výsledky']
  ];
  const displayPhase=progressSteps.find(([limit])=>percent<=limit)?.[1]||'Ukládám a připravuji výsledky';
  $('progressPhase').textContent=state.error?'Výsledek není úplný. Zkuste kontrolu znovu nebo otevřete stav datových zdrojů.':displayPhase;
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
  const unusual=(state.results||[]).filter(isUnusual).length;
  const resolvedUnusual=Math.max(0,unusual-attention);
  const sourceError=Object.values(state.sources||{}).some(source=>source&&source.state==='error');
  const absentBreakdown=categoryBreakdown('NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ');
  const soldBreakdown=categoryBreakdown('PRODANÉ, ALE POJIŠTĚNÉ');
  const extraBreakdown=categoryBreakdown('NAVÍC V UNIQA');
  const depositInsuredBreakdown=categoryBreakdown('DEPOZIT, ALE POJIŠTĚNÉ');
  const extraProblemCount=extraBreakdown.open;

  const waitingFreshPage=!sessionCheckStarted&&!state.running;
  const visualCompletionPending=false;
  const suppressFinalResults=waitingFreshPage||state.running||visualCompletionPending;
  const setText=(id,value)=>{const el=$(id);if(el)el.textContent=value;};
  const shown=(value)=>suppressFinalResults?0:(Number(value)||0);
  document.body.classList.toggle('check-running',!!state.running);
  // Po novém otevření stránky zobrazíme jen hlavní kartu se spuštěním kontroly.
  // Vyhledávání, filtry, export a tabulka se objeví až po spuštění kontroly.
  const dataSection=$('dataSection');
  if(dataSection && !dataSection.dataset.userOpened) dataSection.hidden=true;
  setText('attentionCount',suppressFinalResults?'—':unusual);
  setText('openCount',suppressFinalResults?'—':attention);
  setText('resolvedExceptionCount',shown(resolvedUnusual));
  setText('allCount',suppressFinalResults?'—':state.results.length);
  setText('cActive',shown(s.active));setText('cActiveHover',shown(s.active));setText('cActiveOverview',shown(s.active));setText('cOkTotal',shown(s.ok_total));
  setText('cOkUniqa',shown(s.ok_total));setText('cOkAllianz',shown(s.ok_allianz));setText('cMissing',shown(issues.missing));
  setText('tipMissingOverall',shown(issues.missing));setText('tipExtraOverall',shown(issues.unwanted));
  setText('cAbsentInsured',shown(absentBreakdown.total));setText('cAbsentInsuredTop',shown(issues.absent));setText('cAbsentUninsured',shown(s.absent_uninsured));
  setText('cAbsentResolved',shown(absentBreakdown.resolved));setText('cAbsentOpen',shown(absentBreakdown.open));
  setText('cDeposit',shown(s.deposit));setText('cSold',shown(soldBreakdown.total));setText('cSoldTop',shown(issues.sold));
  setText('cSoldResolved',shown(soldBreakdown.resolved));setText('cSoldOpen',shown(soldBreakdown.open));
  setText('cExtra',shown(extraBreakdown.total));setText('cExtraResolved',shown(extraBreakdown.resolved));setText('cExtraOpen',shown(extraBreakdown.open));
  setText('cDepositInsured',shown(depositInsuredBreakdown.total));setText('cDepositInsuredResolved',shown(depositInsuredBreakdown.resolved));setText('cDepositInsuredOpen',shown(depositInsuredBreakdown.open));
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
  setMetricProblemState('DEPOSIT_INSURED',depositInsuredBreakdown.open);

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
  activeFilter='ATTENTION';
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
  $('detailBody').innerHTML=`<dl class="detail-grid"><dt>Stav</dt><dd><span class="status-badge ${badgeClass(r)}">${esc(visibleSystemText(r.status))}</span>${original}</dd><dt>Vozidlo</dt><dd id="vehicleDetailValue">${esc(vehicle)}</dd><dt>VIN</dt><dd>${esc(r.vin||'—')}</dd><dt>SPZ</dt><dd>${esc(spzValue)}</dd><dt>Datum výkupu</dt><dd>${esc(r.vykup||'—')}</dd><dt>Datum prodeje</dt><dd>${esc(r.prodej||'—')}</dd><dt>Výsledek</dt><dd>${esc(visibleSystemText(r.detail||'—'))}</dd></dl><section id="kostkaSection" class="kostka-section"><div class="kostka-heading"><div><h3>Technické údaje vozidla</h3><p id="kostkaStatus">Načítám uložené údaje…</p></div></div><div id="kostkaData"></div></section><div style="padding:0 22px 22px;border-top:1px solid #eef2f7"><h3 style="margin:16px 0 10px;font-size:14px">Interní poznámka a stav řešení</h3><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">STATUS</label><select id="workflowStatus" style="width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:8px;margin-bottom:12px"><option value="">Původní status</option><option value="VYŘEŠENO">Vyřešeno</option></select><label style="display:block;font-size:11px;font-weight:700;color:#64748b;margin-bottom:5px">POZNÁMKA</label><textarea id="vehicleNote" rows="4" maxlength="2000" placeholder="Např. zrušení pojištění zadáno 14.9., čekáme na potvrzení…" style="width:100%;resize:vertical;padding:9px;border:1px solid #cbd5e1;border-radius:8px;font:inherit">${esc(r.note||'')}</textarea><div style="display:flex;justify-content:flex-end;margin-top:12px"><button id="saveMeta" class="btn btn-primary" type="button">Uložit</button></div></div>`;
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
  if(side)side.classList.add('active');else if(filter==='VŠE')$('navAllVehicles').classList.add('active');else if(filter==='OPEN')document.querySelector('.nav-item[data-filter="ATTENTION"]')?.classList.add('active');else if(filter!=='VŠE'&&$('navOthers'))$('navOthers').classList.add('active');
  renderRows();
}
function clearFilter(){
  hideSources();hideBreakdown();showData();activeFilter='VŠE';$('search').value='';
  document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('selected'));
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  $('navAllVehicles').classList.add('active');renderRows();
}
let lastToast='';function toast(msg,error=false){if(!msg||msg===lastToast)return;lastToast=msg;const t=$('toast');t.textContent=msg;t.className='toast'+(error?' error':'');t.hidden=false;setTimeout(()=>{t.hidden=true;lastToast='';},5000);}


$('runBtn').addEventListener('click',run);
const navResultsToggle=$('navResultsToggle');
const navResultsMenu=$('navResultsMenu');
function setResultsMenu(open){
  if(!navResultsToggle||!navResultsMenu)return;
  navResultsMenu.hidden=!open;
  navResultsToggle.setAttribute('aria-expanded',String(open));
  navResultsToggle.classList.toggle('open',open);
}
if(navResultsToggle)navResultsToggle.addEventListener('click',()=>setResultsMenu(navResultsMenu.hidden));
$('search').addEventListener('input',renderRows);$('clearBtn').addEventListener('click',()=>{$('search').value='';renderRows();});$('clearFilterInline').addEventListener('click',clearFilter);$('navAllVehicles').addEventListener('click',clearFilter);$('navOthers').addEventListener('click',showBreakdown);$('navHowItWorks').addEventListener('click',showHowItWorks);$('overviewTodayChanges').addEventListener('click',showChanges);$('overviewManualChanges').addEventListener('click',showManualHistory);$('overviewSources').addEventListener('click',showSources);document.querySelectorAll('[data-filter]').forEach(c=>c.addEventListener('click',()=>setFilter(c.dataset.filter)));$('closeDialog').addEventListener('click',()=>$('detailDialog').close());$('detailDialog').addEventListener('click',e=>{if(e.target===$('detailDialog'))$('detailDialog').close();});
$('csvBtn').addEventListener('click',async event=>{
  event.preventDefault();
  const btn=$('csvBtn');
  if(btn.getAttribute('aria-disabled')==='true')return;
  const original=btn.textContent;
  btn.classList.add('disabled');btn.setAttribute('aria-disabled','true');btn.textContent='Připravuji Excel…';
  try{
    let r=await fetch('/api/audit-export',{method:'POST',headers:{'Content-Type':'application/json'}});
    let data=await r.json();
    for(let attempt=0;attempt<80 && data.status==='pending';attempt++){
      await new Promise(resolve=>setTimeout(resolve,2000));
      r=await fetch('/api/audit-export',{cache:'no-store'});
      data=await r.json();
    }
    if(data.status!=='ready')throw new Error(data.error||'Audit se nepodařilo připravit v časovém limitu.');
    window.location.href='/download/xlsx';
  }catch(e){
    alert(e.message||'Excel se nepodařilo připravit.');
  }finally{
    btn.textContent=original;btn.classList.remove('disabled');btn.setAttribute('aria-disabled','false');
  }
});
setInterval(refresh,2000);refresh();

function lookupStatusClass(text){
  const s=String(text||'').toUpperCase();
  if(s.includes('CHYBÍ')||s.includes('NAVÍC')||s.includes('POJIŠTĚNÉ')&&s.includes('NEPŘÍTOMNÉ'))return 'lookup-state-bad';
  if(s.includes('FILTROVÁNO')||s.includes('DEPOZIT')||s.includes('MIMO POV'))return 'lookup-state-neutral';
  if(s.includes('POŘÁDKU')||s==='OK'||s.includes('ZAŘAZENO'))return 'lookup-state-ok';
  return 'lookup-state-warn';
}
function renderLookupMain(v){
  const panel=$('lookupVehiclePanel'),content=$('lookupVehicleContent');
  if(!panel||!content)return;
  hideSources();hideBreakdown();hideChanges();hideManualHistory();hideHowItWorks();hideData();
  const filter=v.filter||{},ins=v.insurance||{};
  const title=[v.znacka,v.model].filter(Boolean).join(' ')||v.spz||v.vin||'Vozidlo';
  const insuranceStatus=ins.in_last_check?(ins.status||ins.status_raw||'Výsledek nalezen'):(filter.expected==='MIMO POV'?'Nekontrolováno – mimo POV':'Není v posledním výsledku');
  const item=(label,value)=>'<div class="lookup-main-item"><span>'+esc(label)+'</span><strong>'+esc(value||'—')+'</strong></div>';
  content.innerHTML=
    '<div class="lookup-main-head"><div><span class="section-kicker">VYHLEDÁNÍ V TIRBAZAR SQL</span><h2>'+esc(title)+'</h2><div class="lookup-main-ident">'+esc(v.spz||'Bez SPZ')+' · '+esc(v.vin||'Bez VIN')+'</div></div><button type="button" class="lookup-main-close" id="lookupMainClose">×</button></div>'+
    '<div class="lookup-main-status-row">'+
      '<div class="lookup-status-card '+lookupStatusClass(filter.decision)+'"><span>ZAŘAZENÍ DO KONTROLY</span><strong>'+esc(filter.decision||'Neurčeno')+'</strong><small>'+esc(filter.reason||'')+'</small></div>'+
      '<div class="lookup-status-card '+lookupStatusClass(insuranceStatus)+'"><span>POJIŠTĚNÍ</span><strong>'+esc(insuranceStatus)+'</strong><small>'+esc(ins.detail||(ins.last_check?'Poslední kontrola: '+ins.last_check:'V poslední kontrole není k dispozici výsledek.'))+'</small></div>'+
    '</div>'+
    '<div class="lookup-main-grid">'+
      '<article><h3>Vozidlo</h3><div class="lookup-main-items">'+item('VIN',v.vin)+item('SPZ',v.spz)+item('Stav v TIRBazar',v.stav)+item('OID',v.oid)+item('Země původu',v.zeme_puvodu)+'</div></article>'+
      '<article><h3>Evidence</h3><div class="lookup-main-items">'+item('Datum výkupu',v.datum_vykupu)+item('Datum prodeje',v.datum_prodeje)+item('Očekávaný stav POV',filter.expected)+item('Pojišťovna',ins.insurer)+item('SPZ v pojištění',ins.spz_insurance)+'</div></article>'+
    '</div>'+
    (v.poznamky?'<div class="lookup-main-note"><span>POZNÁMKA TIRBAZAR</span><strong>'+esc(v.poznamky)+'</strong></div>':'');
  panel.hidden=false;
  const close=$('lookupMainClose');if(close)close.addEventListener('click',()=>{panel.hidden=true;});
  panel.scrollIntoView({behavior:'smooth',block:'start'});
}
async function runTirLookup(event){
  event.preventDefault();
  const input=$('tirLookupInput'),button=$('tirLookupBtn'),box=$('tirLookupResult');
  const query=String(input?.value||'').trim().toUpperCase();
  if(!query){box.hidden=true;box.textContent='';return;}
  button.disabled=true;button.textContent='Hledám…';box.hidden=false;box.textContent='Dotazuji TIRBazar SQL…';
  try{
    let response=await fetch('/api/vehicle-lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})});
    let data=await response.json();
    for(let attempt=0;attempt<18 && data.status==='pending';attempt++){
      await new Promise(resolve=>setTimeout(resolve,1500));
      response=await fetch('/api/vehicle-lookup/'+encodeURIComponent(query),{cache:'no-store'});
      data=await response.json();
    }
    if(data.status==='pending'){box.innerHTML='<span class="tir-lookup-message">Agent zatím nevrátil výsledek. Zkuste Hledat znovu.</span>';return;}
    if(data.error){box.innerHTML='<span class="tir-lookup-message error">'+esc(data.error)+'</span>';return;}
    if(!data.found||!data.vehicle){box.innerHTML='<span class="tir-lookup-message">V TIRBazar nebylo nalezeno vozidlo pro <strong>'+esc(query)+'</strong>.</span>';return;}
    box.innerHTML='<span class="tir-lookup-message">Nalezeno · detail zobrazen na hlavní stránce.</span>';
    renderLookupMain(data.vehicle);
  }catch(e){box.innerHTML='<span class="tir-lookup-message error">Vyhledání se nepodařilo. Zkuste to znovu.</span>';}
  finally{button.disabled=false;button.textContent='Hledat';}
}
if($('tirLookupForm'))$('tirLookupForm').addEventListener('submit',runTirLookup);
