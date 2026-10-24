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
assert.equal(run('resultLabel(state.results[1])'),'Chybí pojištění');
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
