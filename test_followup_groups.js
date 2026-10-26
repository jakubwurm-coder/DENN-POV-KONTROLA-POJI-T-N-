const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname+'/static/js/app.js','utf8');
const context = vm.createContext({});
// Load the real filtering and rendering helpers without starting network polling.
vm.runInContext(source.slice(0,source.indexOf("$('runBtn').addEventListener")),context);
function run(code){return vm.runInContext(code,context);}
run(`state.results=unusualStatuses.flatMap((status_raw,i)=>[
  {vin:'CURRENT'+i,status_raw,workflow_status:'',note:'Keep current note'},
  {vin:'OLDER'+i,status_raw,workflow_status:'VYŘEŠENO',note:'Still to follow up'}
]);state.results.push({vin:'GOOD',status_raw:'OK',workflow_status:'VYŘEŠENO'});`);
const before=run('JSON.stringify(state.results)');
const total=run('unusualStatuses.length');
assert.equal(run("activeFilter='ATTENTION';state.results.filter(matches).length"),total);
assert.equal(run("activeFilter='RESOLVED';state.results.filter(matches).length"),total);
assert.equal(run("activeFilter='VŠE';state.results.filter(matches).length"),total*2+1);
assert.equal(run("activeFilter='OK_TOTAL';state.results.filter(matches).map(r=>r.vin).join(',')"),'GOOD');
assert.equal(run('badgeClass(state.results[1])'),'badge-warning');
assert.equal(run('resultLabel(state.results[1])'),'Nepojištěno');
assert.equal(run('JSON.stringify(state.results)'),before,'filtering must preserve verdicts and notes');
run("state.results[0].workflow_status='VYŘEŠENO';");
assert.equal(run("activeFilter='ATTENTION';state.results.filter(matches).length"),total-1);
assert.equal(run("activeFilter='RESOLVED';state.results.filter(matches).length"),total+1);
assert.equal(run('state.results[0].note'),'Keep current note');
assert.equal(run('state.results[0].status_raw'),'CHYBÍ V UNIQA');
run("state.results[0].workflow_status='';");
assert.equal(run("activeFilter='ATTENTION';state.results.filter(matches).length"),total);
assert.equal(run("activeFilter='RESOLVED';state.results.filter(matches).length"),total);
console.log('Follow-up groups passed: all issue types, separate lists, acknowledge/restore, original verdict and notes preserved, no false OK.');
// Manual approval is independent from an orange acknowledgement, for every verdict.
run(`state.results=unusualStatuses.flatMap((status_raw,i)=>[
 {vin:'NEW'+i,status_raw,workflow_status:''},
 {vin:'FOLLOW'+i,status_raw,workflow_status:'K DOŘEŠENÍ'},
 {vin:'APPROVED'+i,status_raw,workflow_status:'RUČNĚ OK',workflow_updated_by:'alice',workflow_updated_at:'2026-10-25T12:00:00+01:00'},
 {vin:'LEGACY'+i,status_raw,workflow_status:'VYŘEŠENO'}
]);`);
assert.equal(run("activeFilter='ATTENTION';state.results.filter(matches).length"),total);
assert.equal(run("activeFilter='RESOLVED';state.results.filter(matches).length"),total*2);
assert.equal(run("activeFilter='MANUAL_OK';state.results.filter(matches).length"),total);
assert.equal(run('badgeClass(state.results[0])'),'badge-missing');
assert.equal(run('badgeClass(state.results[1])'),'badge-warning');
assert.equal(run('badgeClass(state.results[2])'),'badge-ok');
assert.equal(run('workflowLabel(state.results[2])'),'RUČNĚ OK');
assert.match(run('workflowCredit(state.results[2])'),/alice/);
assert.equal(run("activeFilter='EXTRA_UNIQA';rowBadgeClass(state.results[2])"),'badge-ok');
assert.equal(run('state.results[2].status_raw'),'CHYBÍ V UNIQA');
run("state.results[2].status_raw='OK';");
assert.equal(run("activeFilter='MANUAL_OK';state.results.filter(matches).length"),total-1);
assert.equal(run('badgeClass(state.results[2])'),'badge-ok');
console.log('Manual workflow passed: distinct red/orange/green, legacy preserved, identity shown, approval survives changed automatic verdict.');

run("state.results.push({vin:'LATCH',status_raw:'OK',status:'OK',open_problem_status:'CHYBÍ V UNIQA',workflow_status:''});");
assert.equal(run("activeFilter='ATTENTION';state.results.filter(matches).length"),total);
assert.equal(run("badgeClass(state.results.at(-1))"),'badge-ok');
assert.equal(run("state.results.at(-1).status_raw"),'OK');
console.log('Current OK overrides historical issues without fabricating a manual approval.');

run("state.results.push({vin:'LEGACY_OK',status_raw:'CHYBÍ V UNIQA',workflow_status:'V POŘÁDKU'});");
assert.equal(run('isManualOk(state.results.at(-1))'),true);
assert.equal(run('needsAttention(state.results.at(-1))'),false);
assert.equal(run('workflowLabel(state.results.at(-1))'),'RUČNĚ OK');
assert.equal(run('badgeClass(state.results.at(-1))'),'badge-ok');

// Coverage groups must not depend on purchase dates or manual decisions.
run("state.results=[{status_raw:'NAVÍC V UNIQA',vykup:'',workflow_status:'K DOŘEŠENÍ'},{status_raw:'NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ',vykup:'30.01.2025'},{status_raw:'NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ'},{status_raw:'CHYBÍ V UNIQA',workflow_status:'RUČNĚ OK'},{status_raw:'NELZE OVĚŘIT'},{status_raw:'MIMO POV'}]");
assert.equal(run("activeFilter='INSURED';state.results.filter(matches).length"),2);
assert.equal(run("activeFilter='UNINSURED';state.results.filter(matches).length"),3);
assert.equal(run("activeFilter='UNKNOWN';state.results.filter(matches).length"),1);
assert.equal(run('resultLabel(state.results[0])'),run('resultLabel(state.results[1])'));
assert.equal(run('resultLabel(state.results[3])'),'Nepojištěno');
assert.equal(run("insuranceState({status_raw:'UNRECOGNIZED'})"),'UNKNOWN');
