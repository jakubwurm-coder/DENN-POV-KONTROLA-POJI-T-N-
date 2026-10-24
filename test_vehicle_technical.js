const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=readFileSync(__dirname+'/static/js/app.js','utf8');
const functions=source.slice(source.indexOf('function kostkaDate('),source.indexOf('function showDetail('));
async function check(result){
  const nodes={kostkaSection:{},kostkaStatus:{},kostkaData:{},detailDialog:{open:true},vehicleDetailValue:{}};
  const context={$:id=>nodes[id],esc:value=>String(value).replace(/</g,'&lt;'),fetch:async()=>({ok:true,json:async()=>result}),Date,Number,encodeURIComponent,setTimeout};
  vm.createContext(context);vm.runInContext(functions,context);
  await context.loadKostka('WVWZZZ1KZ6W000001');
  return nodes;
}
(async()=>{
  let nodes=await check({ok:true,source:'sql',source_label:'SQL Vans Centre',oid:20,data:{TovarniZnacka:'Ford',MotorMaxVykon:'100'}});
  assert.match(nodes.kostkaStatus.textContent,/Zdroj: SQL Vans Centre · OID 20/);
  assert.match(nodes.kostkaData.innerHTML,/Výkon \(kW\).*100/);
  assert.equal(nodes.vehicleDetailValue.textContent,'Ford');
  nodes=await check({ok:true,source:'kostka',source_label:'Datová kostka',fetched_at:'2026-10-24',data:{TovarniZnacka:'<script>'}});
  assert.match(nodes.kostkaStatus.textContent,/Zdroj: Datová kostka/);
  assert(!nodes.kostkaData.innerHTML.includes('<script>'));
  nodes=await check({ok:true,source:'unknown',message:'Čeká na SQL'});
  assert.equal(nodes.kostkaStatus.textContent,'Čeká na SQL');
  console.log('Vehicle technical UI: SQL source/OID, fields, Kostka source, escaping and pending SQL passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
