// SPDX-License-Identifier: LGPL-2.1-or-later
// Real Qt mouse/keyboard input. Python probes only read UI/model state, except
// the explicitly labeled persistence check (save/reopen through native APIs).
// CHROME_PATH=/path/to/chrome node tests/cad_workspace_e2e.cjs _site
const puppeteer = require('puppeteer-core');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const site = path.resolve(process.argv[2] || '_site');
const output = process.env.CAD_TEST_OUTPUT || 'cad-test-output';
fs.mkdirSync(output, {recursive: true});

(async () => {
  const server = spawn('python3', [path.join(__dirname, 'serve_cad_fixture.py'), site, '18791'], {stdio: 'ignore'});
  process.on('exit', () => server.kill());
  let browser;
  const log = [];
  const passed = [];
  try {
    await sleep(700);
    browser = await puppeteer.launch({
      executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--use-gl=angle', '--use-angle=swiftshader',
        '--enable-unsafe-swiftshader', '--js-flags=--max-old-space-size=8192'],
      protocolTimeout: 240000,
    });
    const page = await browser.newPage();
    await page.setViewport({width: 1600, height: 1000});
    await page.evaluateOnNewDocument(() => { Object.defineProperty(window,'showSaveFilePicker',{value:undefined,configurable:true}); });
    page.setDefaultTimeout(60000);
    const downloadDir=path.resolve(output,'downloads');
    fs.mkdirSync(downloadDir,{recursive:true});
    const cdp=await page.createCDPSession();
    await cdp.send('Page.setDownloadBehavior',{behavior:'allow',downloadPath:downloadDir});
    page.on('console', message => log.push(message.text()));
    page.on('pageerror', error => log.push('PAGEERROR: ' + error.message));
    const fundraisingRequests=[];
    page.on('request',request=>{if(/patreon|ko-fi|\/go\/kofi/i.test(request.url()))fundraisingRequests.push(request.url());});
    await page.goto('http://127.0.0.1:18791/', {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => window.__cadReady || window.__cadFailed, {timeout: 240000});
    assert.equal(await page.evaluate(() => window.__cadFailed), undefined);
    assert.doesNotMatch(await page.content(),/vtNudge|vt-nudge|patreon|ko-fi|vt\.support\.nudge/i);
    assert.equal(await page.evaluate(()=>typeof window.vtNudge),'undefined');


    async function probe(name, code) {
      await page.waitForFunction(() => !window.__fcPyBusy, {timeout: 30000});
      await page.evaluate(({code,name}) => {
        const vfs=window.fcInstance.FS, marker='/tmp/occt-probe-'+name;
        try { vfs.unlink(marker); } catch (_) {}
        const source="import Part, FreeCAD as App, traceback\ntry:\n "+code+"\n open('"+marker+"','w').write('OK')\nexcept Exception:\n open('"+marker+"','w').write(traceback.format_exc())\n";
        window.__fcRunPyGuarded(source);
      },{code,name});
      await page.waitForFunction(name => {
        const f=window.fcInstance.FS;
        return f.analyzePath('/tmp/occt-probe-'+name).exists || (window.__fcPyErrors||[]).length>0;
      },{timeout:30000},name);
      const result=await page.evaluate(name=>{
        const f=window.fcInstance.FS, p='/tmp/occt-probe-'+name;
        return {out:f.analyzePath(p).exists?new TextDecoder().decode(f.readFile(p)):null,
                errors:(window.__fcPyErrors||[]).map(String)};
      },name);
      console.log('OCCT_PROBE', name, JSON.stringify(result));
      return result;
    }
    await probe('version', "raise RuntimeError(str(Part.OCC_VERSION))");
    const setup=await probe('setup', "_occt_doc=App.newDocument('TrimProbe'); _occt_obj=_occt_doc.addObject('Part::Box','Box'); _occt_obj.Length=4; _occt_obj.Width=6; _occt_obj.Height=10; _occt_doc.recompute(); _occt_before=(_occt_obj.Shape.Volume,len(_occt_doc.Objects),_occt_doc.UndoCount)");
    assert.equal(setup.out,'OK'); assert.deepEqual(setup.errors,[]);
    const normal=await probe('valid', "_e=Part.ArcOfParabola(Part.Parabola(),0.0,1.0)");
    assert.equal(normal.out,'OK'); assert.deepEqual(normal.errors,[]);
    const invalid=await probe('nan', "_e=Part.ArcOfParabola(Part.Parabola(),float('nan'),1.0)");
    assert.match(invalid.out||'',/Geom_TrimmedCurve::U1 == U2/); assert.deepEqual(invalid.errors,[]);
    const infinity=await probe('inf', "_e=Part.ArcOfParabola(Part.Parabola(),float('inf'),1.0)");
    assert.match(infinity.out||'',/Geom_TrimmedCurve::U1 == U2/); assert.deepEqual(infinity.errors,[]);
    const rollback=await probe('transaction', "with __import__('cad_core').transaction(_occt_doc, 'Invalid curve'): _occt_obj.Length=9; Part.ArcOfParabola(Part.Parabola(),float('nan'),1.0)");
    assert.match(rollback.out||'',/Geom_TrimmedCurve::U1 == U2/); assert.deepEqual(rollback.errors,[]);
    const after=await probe('state', "assert (_occt_obj.Shape.Volume,len(_occt_doc.Objects),_occt_doc.UndoCount)==_occt_before; assert _occt_obj.Shape.isValid()");
    assert.equal(after.out,'OK'); assert.deepEqual(after.errors,[]);
    console.log('OCCT_GUARD_VALIDATED');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode=1; });
