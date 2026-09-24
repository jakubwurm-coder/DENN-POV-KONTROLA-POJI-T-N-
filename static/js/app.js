let state={results:[],summary:{},sources:{},running:false,progress:{percent:0,phase:'Připraveno',eta_seconds:0}};
let activeFilter='VŠE';
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
    return workflow==='VYŘEŠENO'?'badge-ok':'badge-error';
  }
  if(workflow==='VYŘEŠENO'||workflow==='V POŘÁDKU') return 'badge-ok';
  if(workflow==='ŘEŠÍ SE'||workflow==='KONTROLA') return 'badge-warning';
  return ({'OK':'badge-ok','CHYBÍ V UNIQA':'badge-missing','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ':'badge-error','NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ':'badge-ok','NEPOJIŠTĚNO, ALE DEPOZIT':'badge-deposit','PRODANÉ, ALE V UNIQA':'badge-sold','NAVÍC V UNIQA':'badge-extra','SPZ NESOUHLASÍ':'badge-warning','NELZE OVĚŘIT':'badge-error'}[r.status_raw]||'badge-error');
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

function matches(r){
  if(activeFilter==='VŠE')return true;
  if(activeFilter==='ACTIVE')return ['OK','CHYBÍ V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ','SPZ NESOUHLASÍ','NELZE OVĚŘIT'].includes(r.status_raw);
  if(activeFilter==='OK_TOTAL')return r.status_raw==='OK'||r.status_raw==='NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ';
  if(activeFilter==='OK_UNIQA')return r.status_raw==='OK'&&r.pojistovna==='UNIQA';
  if(activeFilter==='OK_ALLIANZ')return r.status_raw==='OK'&&r.pojistovna==='ALLIANZ';
  const resolved=['VYŘEŠENO','V POŘÁDKU'].includes(r.workflow_status);
  if(activeFilter==='MISSING')return r.status_raw==='CHYBÍ V UNIQA'&&!resolved;
  if(activeFilter==='ABSENT_INSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'&&String(r.workflow_status||'').toUpperCase()!=='VYŘEŠENO';
  if(activeFilter==='ABSENT_UNINSURED')return r.status_raw==='NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ';
  if(activeFilter==='DEPOSIT')return r.status_raw==='NEPOJIŠTĚNO, ALE DEPOZIT';
  if(activeFilter==='SOLD_UNIQA')return r.status_raw==='PRODANÉ, ALE V UNIQA'&&!resolved;
  if(activeFilter==='EXTRA_UNIQA'){
    return ['NAVÍC V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'].includes(r.status_raw);
  }
  if(activeFilter==='UNWANTED_INSURANCE'){
    return ['NAVÍC V UNIQA','NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ'].includes(r.status_raw);
  }
  return true;
}

function renderActiveFilter(){const box=$('activeFilter');if(activeFilter==='VŠE'){box.hidden=true;return;}$('activeFilterLabel').textContent=filterNames[activeFilter]||activeFilter;box.hidden=false;}

function renderRows(){
  renderActiveFilter();

  if(!sessionCheckStarted&&!state.running){
    $('footerRight').textContent='Zobrazeno: 0 z 0';
    $('rows').innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Nejdříve spusťte aktuální kontrolu pojištění.</td></tr>';
    return;
  }

  if(state.running||(sessionCheckStarted&&!state.error&&!state.running&&!!state.finished_at&&connectionVisualPercent<100)){
    $('footerRight').textContent='Zobrazeno: 0 z 0';
    $('rows').innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Kontrola právě probíhá. Výsledky se zobrazí až po jejím dokončení na 100 %.</td></tr>';
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
  if(!rows.length){$('rows').innerHTML='<tr class="empty-row"><td colspan="6" class="empty">Žádné výsledky pro zvolený filtr.</td></tr>';return;}
  $('rows').innerHTML=rows.map(r=>{
    const index=state.results.indexOf(r);
    const badge=rowBadgeClass(r);
    return `<tr data-index="${index}"><td><span class="status-badge ${badge}">${esc(visibleSystemText(r.status))}</span></td><td>${esc(r.vin||'—')}</td><td>${esc(displaySpz(r)||'—')}</td><td>${esc(r.vykup||'—')}</td><td>${esc(r.prodej||'—')}</td><td>${esc(visibleSystemText(r.detail||'—'))}</td></tr>`;
  }).join('');
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

function setStatusCard(cardId,textId,ok,okText,badText){
  const card=$(cardId), textEl=$(textId);
  if(!card||!textEl)return;
  card.classList.toggle('status-ok',ok);
  card.classList.toggle('status-problem',!ok);
  textEl.textContent=ok?okText:badText;
}

const connectionSteps=[
  'Inicializuji kontrolní proces',
  'Ověřuji síťovou konektivitu',
  'Navazuji relaci se SQL serverem',
  'Načítám datovou sadu vozidel',
  'Normalizuji VIN a registrační značky',
  'Aplikuji validační pravidla a výjimky',
  'Filtruji záznamy mimo rozsah kontroly',
  'Navazuji spojení s evidencí pojištění',
  'Synchronizuji aktivní záznamy pojištění',
  'Validuji integritu načtených dat',
  'Páruji záznamy podle VIN',
  'Páruji záznamy podle registrační značky',
  'Provádím křížové porovnání datových sad',
  'Detekuji chybějící pojištění',
  'Detekuji pojištění navíc a výjimky',
  'Vyhodnocuji konflikty a ruční statusy',
  'Finalizuji validační výsledek',
  'Publikuji aktuální přehled'
];
let connectionVisualIndex=0;
let connectionVisualPercent=0;
let connectionFinishAnimating=false;
let connectionUseLocalProgress=false;

function connectionStepIndex(percent){
  const byPercent=Math.floor((Math.max(0,Math.min(99,Number(percent)||0))/100)*connectionSteps.length);
  return Math.max(0,Math.min(connectionSteps.length-1,byPercent));
}


function ensureConnectionDots(percent,finished,error){
  const box=$('connectionStepDots');if(!box)return;
  const total=connectionSteps.length;
  const current=Math.max(0,Math.min(100,Number(percent)||0));
  const filled=finished?total:Math.floor((current/100)*total);

  box.innerHTML=connectionSteps.map((_,i)=>{
    let cls='';
    if(error&&i===Math.max(0,filled-1)) cls='error';
    else if(i<filled) cls='done';
    else if(i===filled&&!finished&&current>0) cls='active';
    return '<span class="'+cls+'"></span>';
  }).join('');
}

function renderProgress(){
  const p=state.progress||{};
  const serverPercent=Math.max(0,Math.min(100,Number(p.percent)||0));
  const finished=sessionCheckStarted&&!state.running&&!!state.finished_at&&!state.error;
  let percent=serverPercent;

  const visual=$('connectionVisual');
  const finalBox=$('connectionFinal');
  const runningBox=$('connectionRunningDetail');

  if(state.running){
    if(connectionVisualPercent<=0){
      connectionVisualIndex=0;
      connectionVisualPercent=connectionUseLocalProgress?1:Math.max(1,serverPercent);
      connectionFinishAnimating=false;
    }
    // Po ručním spuštění v tomto prohlížeči používáme jeden plynulý lokální
    // průběh. Backend může skočit třeba rovnou na 96 %, ale UI se nesmí přeskočit.
    if(!connectionUseLocalProgress){
      connectionVisualPercent=Math.max(connectionVisualPercent,serverPercent);
    }
    percent=Math.min(96,connectionVisualPercent);
    const idx=connectionStepIndex(percent);
    const detail=connectionSteps[idx];

    $('progressPercent').textContent=Math.round(percent)+' %';
    $('progressEta').textContent='Probíhá';
    $('progressHeadline').textContent='Kontrola připojení';
    $('progressPhase').textContent=detail;
    if($('progressDetail'))$('progressDetail').textContent='Průběh jednotlivých kroků kontroly.';
    $('progressBar').style.width=Math.max(3,percent)+'%';

    if(visual){visual.className='connection-visual running';}
    if($('connectionVisualIcon'))$('connectionVisualIcon').textContent='↻';
    if(finalBox)finalBox.hidden=true;
    if(runningBox)runningBox.hidden=false;
    ensureConnectionDots(percent,false,false);
    return;
  }

  if(state.error){
    connectionUseLocalProgress=false;
    $('progressPercent').textContent='!';
    $('progressEta').textContent='Chyba';
    $('progressHeadline').textContent='Kontrola připojení';
    $('progressPhase').textContent='Kontrolu se nepodařilo dokončit.';
    if($('progressDetail'))$('progressDetail').textContent=visibleSystemText(state.error);
    $('progressBar').style.width='100%';
    if(visual)visual.className='connection-visual error';
    if($('connectionVisualIcon'))$('connectionVisualIcon').textContent='!';
    if(finalBox)finalBox.hidden=true;
    if(runningBox)runningBox.hidden=false;
    ensureConnectionDots(percent,false,true);
    return;
  }

  if(finished){
    connectionUseLocalProgress=false;
    connectionFinishAnimating=connectionVisualPercent<100;
    if(connectionFinishAnimating){
      connectionVisualPercent=Math.min(100,connectionVisualPercent+5);
    }else{
      connectionVisualPercent=100;
    }
    percent=connectionVisualPercent;
    $('progressPercent').textContent=Math.round(percent)+' %';
    $('progressEta').textContent=percent<100?'Dokončuji':'Dokončeno';
    $('progressHeadline').textContent='Kontrola připojení';
    $('progressPhase').textContent=percent<100?'Dokončuji kontrolu a připravuji výsledky.':'Kontrola byla úspěšně dokončena.';
    $('progressBar').style.width=percent+'%';
    if(visual)visual.className='connection-visual done';
    if($('connectionVisualIcon'))$('connectionVisualIcon').textContent='✓';
    if(runningBox)runningBox.hidden=percent>=100;
    if(finalBox)finalBox.hidden=percent<100;

    if(percent<100){
      if($('progressDetail'))$('progressDetail').textContent='Dokončuji kontrolu a připravuji výsledný stav.';
      ensureConnectionDots(percent,false,false);
      return;
    }

    if(!document.body.classList.contains('check-finalized')){
      document.body.classList.add('check-finalized');
      setTimeout(render,0);
    }

    const sources=state.sources||{};
    const sourceError=Object.values(sources).some(x=>x&&x.state==='error');
    if($('connectionFinalText'))$('connectionFinalText').textContent=sourceError
      ?'Kontrola připojení dokončena s upozorněním'
      :'Kontrola připojení SQL a pojišťoven v pořádku';
    if($('connectionFinalSub'))$('connectionFinalSub').textContent=sourceError
      ?'Některý datový zdroj vyžaduje kontrolu.'
      :'SQL i evidence pojištění odpověděly a výsledky byly aktualizovány.';
    ensureConnectionDots(100,true,false);
    return;
  }

  connectionVisualPercent=0;
  connectionFinishAnimating=false;
  $('progressPercent').textContent='0 %';
  $('progressEta').textContent='Připraveno';
  $('progressHeadline').textContent='Kontrola připojení';
  $('progressPhase').textContent='Připraveno ke spuštění kontroly.';
  if($('progressDetail'))$('progressDetail').textContent='Po spuštění se ověří interní databáze SQL a evidence dat z pojišťovny.';
  $('progressBar').style.width='0%';
  if(visual)visual.className='connection-visual idle';
  if($('connectionVisualIcon'))$('connectionVisualIcon').textContent='↻';
  if(finalBox)finalBox.hidden=true;
  if(runningBox)runningBox.hidden=false;
  ensureConnectionDots(0,false,false);
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
  const extraOverviewRows=(state.results||[]).filter(r=>{
    const raw=String(r.status_raw||'').toUpperCase();
    return raw==='NAVÍC V UNIQA'||raw==='NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ';
  });
  const extraOverviewCount=extraOverviewRows.length;
  const extraProblemCount=extraOverviewRows.filter(r=>{
    const workflow=String(r.workflow_status||'').trim().toUpperCase();
    return !['VYŘEŠENO','V POŘÁDKU'].includes(workflow);
  }).length;

  const waitingFreshPage=!sessionCheckStarted&&!state.running;
  const visualCompletionPending=sessionCheckStarted&&!state.error&&!state.running&&!!state.finished_at&&connectionVisualPercent<100;
  const suppressFinalResults=waitingFreshPage||state.running||visualCompletionPending;
  const setText=(id,value)=>{const el=$(id);if(el)el.textContent=value;};
  const shown=(value)=>suppressFinalResults?0:(Number(value)||0);
  document.body.classList.toggle('check-running',!!state.running);
  setText('cActive',shown(s.active));setText('cActiveHover',shown(s.active));setText('cActiveOverview',shown(s.active));setText('cOkTotal',shown(s.ok_total));
  setText('cOkUniqa',shown(s.ok_uniqa));setText('cOkAllianz',shown(s.ok_allianz));setText('cMissing',shown(issues.missing));
  setText('tipMissingOverall',shown(issues.missing));setText('tipExtraOverall',shown(issues.unwanted));
  setText('cAbsentInsured',shown(s.absent_insured));setText('cAbsentInsuredTop',shown(issues.absent));setText('cAbsentUninsured',shown(s.absent_uninsured));
  setText('cDeposit',shown(s.deposit));setText('cSold',shown(s.sold_uniqa));setText('cSoldTop',shown(issues.sold));
  setText('cExtra',shown(extraOverviewCount));setText('cExtraHover',shown(issues.extra));setText('cExtraTop',shown(extraOverviewCount));setText('navExtraCount',shown(extraProblemCount));setText('cTodayChanges',shown((state.changes&&state.changes.count)||0));

  const navExtraCount=$('navExtraCount');
  if(navExtraCount){
    const showExtraIndicator=!suppressFinalResults&&sessionCheckStarted&&!!state.finished_at&&!state.error&&extraProblemCount>0;
    navExtraCount.textContent=showExtraIndicator?String(extraProblemCount):'0';
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
  setMetricProblemState('ABSENT_INSURED',issues.absent);
  setMetricProblemState('SOLD_UNIQA',issues.sold);
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
    setStatusCard('overallCard','overallStatusText',!!state.finished_at&&!state.error&&issues.total===0,'Vše v pořádku',state.error?'Chyba kontroly':'Vyžaduje kontrolu');
    const missingCard=document.querySelector('.summary-card[data-filter="MISSING"]');
    if(missingCard){missingCard.classList.toggle('status-ok',issues.missing===0);missingCard.classList.toggle('status-problem',issues.missing>0);}
    const extraCard=document.querySelector('.summary-card[data-filter="UNWANTED_INSURANCE"]');
    if(extraCard){extraCard.classList.toggle('status-ok',extraOverviewCount===0);extraCard.classList.toggle('status-problem',extraOverviewCount>0);}
    setText('missingStatusText',issues.missing===0?'V pořádku':'Vyžaduje kontrolu');
    setText('extraStatusText',extraOverviewCount===0?'V pořádku':'Vyžaduje kontrolu');
    setText('activeStatusText','Evidence načtena');
  }
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
  csvBtn.classList.toggle('disabled',!state.csv_available||state.running);
  csvBtn.classList.toggle('export-ready',exportReady);
  csvBtn.setAttribute('aria-disabled',(!state.csv_available||state.running)?'true':'false');
  const live=$('liveDot');if(state.running){live.className='status-dot loading';$('liveStatus').textContent='Kontrola probíhá';}else if(sessionCheckStarted&&state.error){live.className='status-dot error';$('liveStatus').textContent='Chyba kontroly';}else if(sessionCheckStarted&&state.finished_at){live.className='status-dot ok';$('liveStatus').textContent='Kontrola dokončena';}else{live.className='status-dot idle';$('liveStatus').textContent='Připraveno';}
  const lastCheck=$('lastCheck');if(lastCheck){lastCheck.textContent=state.running?'Právě probíhá':shortDateTime(state.finished_at);}
  $('footerLeft').textContent=state.running&&state.started_at?'Spuštěno: '+state.started_at:(sessionCheckStarted&&state.finished_at?'Dokončeno: '+state.finished_at:'Připraveno');renderRows();renderChanges();
}

async function refresh(){try{
  const r=await fetch('/api/state',{cache:'no-store'});
  state=await r.json();
  if(!initialStateLoaded){
    if(state.running)sessionCheckStarted=true;
    initialStateLoaded=true;
  }
  render();
  if(sessionCheckStarted&&state.error)toast(visibleSystemText(state.error),true);
}catch(e){toast('Nepodařilo se načíst stav aplikace.',true);}}
async function run(){
  sessionCheckStarted=true;
  document.body.classList.remove('check-finalized');
  state.running=true;
  state.summary={};
  state.results=[];
  state.changes={count:0,items:[]};
  connectionVisualIndex=0;
  connectionVisualPercent=1;
  connectionFinishAnimating=false;
  connectionUseLocalProgress=true;
  render();
  try{const r=await fetch('/api/run',{method:'POST'});const d=await r.json();if(!r.ok)toast(d.message||'Kontrolu se nepodařilo spustit.',true);await refresh();}catch(e){toast('Kontrolu se nepodařilo spustit.',true);}}

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
  if(side)side.classList.add('active');else if(filter!=='VŠE'&&$('navOthers'))$('navOthers').classList.add('active');
  renderRows();
}
function clearFilter(){
  hideSources();hideBreakdown();showData();activeFilter='VŠE';$('search').value='';
  document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('selected'));
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  $('navAllVehicles').classList.add('active');renderRows();
}
let lastToast='';function toast(msg,error=false){if(!msg||msg===lastToast)return;lastToast=msg;const t=$('toast');t.textContent=msg;t.className='toast'+(error?' error':'');t.hidden=false;setTimeout(()=>{t.hidden=true;lastToast='';},5000);}

$('runBtn').addEventListener('click',run);$('search').addEventListener('input',renderRows);$('clearBtn').addEventListener('click',clearFilter);$('clearFilterInline').addEventListener('click',clearFilter);$('navAllVehicles').addEventListener('click',clearFilter);$('navOthers').addEventListener('click',showBreakdown);$('navHowItWorks').addEventListener('click',showHowItWorks);$('overviewTodayChanges').addEventListener('click',showChanges);$('overviewManualChanges').addEventListener('click',showManualHistory);$('overviewSources').addEventListener('click',showSources);document.querySelectorAll('[data-filter]').forEach(c=>c.addEventListener('click',()=>setFilter(c.dataset.filter)));$('closeDialog').addEventListener('click',()=>$('detailDialog').close());$('detailDialog').addEventListener('click',e=>{if(e.target===$('detailDialog'))$('detailDialog').close();});
setInterval(()=>{
  if(state.running){
    if(connectionVisualPercent<50) connectionVisualPercent+=1.8;
    else if(connectionVisualPercent<75) connectionVisualPercent+=1.0;
    else if(connectionVisualPercent<90) connectionVisualPercent+=0.55;
    else if(connectionVisualPercent<96) connectionVisualPercent+=0.2;
    connectionVisualPercent=Math.min(96,connectionVisualPercent);
    renderProgress();
  }else if(state.finished_at&&!state.error&&connectionVisualPercent<100){
    renderProgress();
  }
},650);
setInterval(refresh,2000);refresh();
