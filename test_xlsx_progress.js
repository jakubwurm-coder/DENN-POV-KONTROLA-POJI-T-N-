// Behavioral tests of the UI controller using counted progress events, without a browser.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = readFileSync(__dirname + '/static/js/xlsx-export.js', 'utf8');
function setup(responses, transfer = 'known') {
  const history = [];
  const nodes = {};
  for (const id of ['xlsxProgressDialog','xlsxPrepare','xlsxTransfer','xlsxPrepareText','xlsxTransferText','xlsxError','xlsxRetry','xlsxSave','xlsxClose','completeAuditDownload']) {
    nodes[id] = {hidden:false, value:0, open:false,
      removeAttribute(name) { delete this[name]; history.push([id, name, null]); },
      showModal() { this.open = true; }, close() { this.open = false; },
      addEventListener() {}, click() { history.push([id, 'click']); }};
    Object.defineProperty(nodes[id], 'textContent', {set(value){history.push([id, 'text', value]); this.text=value;}, get(){return this.text;}});
  }
  let requests = [];
  const context = {window:{}, document:{getElementById:id=>nodes[id]},
    setTimeout:resolve=>resolve(), Date, Number, URL:{createObjectURL:()=> 'blob:test', revokeObjectURL(){}},
    fetch:async (url, opts)=> {
      requests.push([url, opts]);
      const data = responses.shift();
      if (!data) throw new Error('Unexpected request: '+url);
      return {ok:!data.http || data.http<400, status:data.http || 200, json:async()=>data};
    },
    XMLHttpRequest: class {
      open(){} send(){
        if(transfer==='error') { this.onerror(); return; }
        this.onprogress({loaded:50, total:100, lengthComputable:transfer==='known'});
        this.response = {size:100, type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'};
        this.status=200; this.onload();
      }
    }};
  vm.createContext(context); vm.runInContext(source, context);
  return {start:context.window.DenniExport.start,nodes,history,requests};
}
(async()=>{
  const ready={id:'job',status:'ready',size:100,filename:'audit.xlsx'};
  let test=setup([{id:'job',status:'running',phase:'rows',completed:1,total:2},
                  {id:'job',status:'running',phase:'finalizing',completed:2,total:2}, ready]);
  await test.start();
  assert(test.history.some(x=>x[0]==='xlsxPrepareText' && /50.0 % řádků/.test(x[2])));
  assert(test.history.some(x=>x[0]==='xlsxPrepare' && x[2]===null));
  assert(test.history.some(x=>x[0]==='xlsxPrepareText' && /komprimuji/.test(x[2])));
  assert(test.history.some(x=>x[0]==='xlsxTransferText' && /50.0 %/.test(x[2])));
  assert(test.nodes.xlsxTransferText.textContent.includes('předán prohlížeči'));
  assert.equal(test.nodes.xlsxTransfer.value,100);
  assert.equal(test.nodes.xlsxSave.download,'audit.xlsx');
  test=setup([ready],'unknown'); await test.start();
  assert(test.history.some(x=>x[0]==='xlsxTransferText' && /celková velikost.*není dostupná/.test(x[2])));
  assert(!test.history.some(x=>x[0]==='xlsxTransferText' && /50.0 %/.test(x[2])));
  test=setup([ready],'error'); await test.start();
  assert.equal(test.nodes.xlsxError.hidden,false);
  assert.equal(test.nodes.xlsxRetry.hidden,false);
  await test.start({resume:true});
  assert.equal(test.requests.length,1, 'retry reuses completed job');
  test=setup([{http:401,message:'Přihlášení je vyžadováno.'}]); await test.start();
  assert(test.nodes.xlsxError.textContent.includes('Přihlášení vypršelo'));
  test=setup([{status:'pending'}, {status:'ready'}, ready]); await test.start({refresh:true});
  assert(test.history.some(x=>x[0]==='xlsxPrepareText' && /kancelářského agenta/.test(x[2])));
  assert.equal(test.requests[0][0],'/api/audit-export');
  console.log('5 UI scenarios passed: measured rows/bytes, unknown length, network retry, expired login, agent wait.');
})().catch(error=>{console.error(error);process.exitCode=1;});
