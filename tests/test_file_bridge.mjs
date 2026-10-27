// Exercise browser picker cancellation, successful writes, failure, and download fallback.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync('play-gui/cad/workspace.js','utf8');
const encoder=new TextEncoder();
async function exercise(mode) {
  const timers=[], files=new Map(), writes=[], downloads=[], notices=[], calls=[];
  const vfs={readFile(p){if(!files.has(p))throw new Error('missing');return files.get(p);},unlink(p){files.delete(p);}};
  class TestURL extends URL { static createObjectURL(){return 'blob:test';} static revokeObjectURL(){} }
  const document={currentScript:{src:'https://example.test/cad/workspace.js'},
    body:{appendChild(){}},getElementById(){return null;},
    createElement(){return {click(){downloads.push(this.download);},remove(){}};}};
  const scope={URL:TestURL,URLSearchParams,TextDecoder,TextEncoder,Blob,document,
    location:{search:'',href:'https://example.test/'}, console:{error(){},info(){}},
    fetch:async()=>({ok:true,text:async()=>''}),setInterval:fn=>(timers.push(fn),timers.length),
    clearInterval(){},setTimeout(){},addEventListener(){},__fcPyBusy:false,__cadReady:true,
    fcInstance:{FS:vfs},fcwebNotify:(...a)=>notices.push(a)};
  scope.window=scope;
  scope.__fcRunPyGuarded=code=>{
    calls.push(code);
    const line=code.split('\n').find(x=>x.startsWith('_r=json.loads('));
    const payload=JSON.parse(JSON.parse(line.slice('_r=json.loads('.length,-1)));
    files.set(payload.status,encoder.encode(JSON.stringify(mode==='error'?{ok:false,error:'failed'}:{ok:true})));
    if(mode!=='error')files.set(payload.out,new Uint8Array([1,2,3]));
  };
  if(mode!=='fallback') scope.showSaveFilePicker=async ()=>{
    if(mode==='cancel') {const e=new Error('cancel');e.name='AbortError';throw e;}
    return {createWritable:async()=>({write:async b=>writes.push(Array.from(b)),close:async()=>{}})};
  };
  vm.runInNewContext(source,scope);
  files.set('/tmp/cad-file-request.json',encoder.encode(JSON.stringify({operation:'save',document:'D',label:'Sample',scope:'visible',selected:[]})));
  timers.at(-1)();
  await new Promise(resolve=>setTimeout(resolve,30));
  return {writes,downloads,notices,calls,files};
}
const canceled=await exercise('cancel');
assert.equal(canceled.calls.length,0); assert.equal(canceled.writes.length,0);
const saved=await exercise('success');
assert.equal(saved.calls.length,1); assert.match(saved.calls[0],/saveCopy/); assert.deepEqual(saved.writes,[[1,2,3]]);
const failed=await exercise('error');
assert.equal(failed.writes.length,0); assert.match(failed.notices[0][0],/保存できませんでした/);
const fallback=await exercise('fallback');
assert.deepEqual(fallback.downloads,['Sample.FCStd']);
console.log('PASS: file picker cancellation, successful write, backend failure and download fallback');
