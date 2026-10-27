// A rejected JSPI operation can fail after mutating the document. Preserve the
// error and release the call, but never promise an unverified rollback.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../play-gui/freecad-gui.html',import.meta.url),'utf8');
const source = html.slice(html.indexOf('function fcRunPy(m, ptr){'),html.indexOf('window.fcRunPy = fcRunPy;'));
assert.ok(source.startsWith('function fcRunPy'));
const notices=[],freed=[];
const document={volume:42};
const context={window:{fcwebNotify:(...args)=>notices.push(args)},console:{error(){}},
  fcwebCallPy(){document.volume=80;return Promise.reject(new RangeError('Maximum call stack size exceeded'));}};
vm.createContext(context); vm.runInContext(source,context);
await assert.rejects(context.fcRunPy({_free:p=>freed.push(p)},123),RangeError);
await Promise.resolve();
assert.equal(document.volume,80);
assert.deepEqual(freed,[123]);
assert.equal(context.window.__fcPyBusy,false);
assert.match(context.window.__fcPyErrors[0],/RangeError: Maximum call stack/);
assert.equal(notices.length,1);
assert.match(notices[0][0],/may have changed/);
assert.doesNotMatch(notices[0][0],/document is unchanged/);
assert.equal(notices[0][1],'error');
console.log('PASS: rejected Python bridge preserves diagnostics without promising rollback');
