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

    async function py(expression, statements = '') {
      await page.waitForFunction(() => !window.__fcPyBusy);
      const out = '/tmp/cad-e2e-result.json';
      let dispatched = false;
      while (!dispatched) {
      dispatched = await page.evaluate(({expression, statements, out}) => {
        if (window.__fcPyBusy) return false;
        try { window.fcInstance.FS.unlink(out); } catch (_) {}
        const code = 'import json,traceback\ntry:\n' +
          statements.split('\n').filter(Boolean).map(line => ' ' + line).join('\n') +
          '\n _e2e_result = ' + expression +
          '\nexcept Exception:\n _e2e_result = {"ERROR":traceback.format_exc()}\n' +
          'with open(' + JSON.stringify(out) + ',"w") as _f: json.dump(_e2e_result,_f)\n';
        window.__fcRunPyGuarded(code);
        return true;
      }, {expression, statements, out});
      if (!dispatched) await sleep(50);
      }
      await page.waitForFunction(out => {
        try { return !!window.fcInstance.FS.stat(out); } catch (_) { return false; }
      }, {}, out);
      const result = await page.evaluate(out => JSON.parse(new TextDecoder().decode(window.fcInstance.FS.readFile(out))), out);
      assert.ok(!result?.ERROR, result?.ERROR);
      return result;
    }
    const state = () => py('cad_workspace.WORKSPACE.diagnostics()');
    async function press(key) {
      if (key.startsWith('Control+')) {
        await page.keyboard.down('Control'); await page.keyboard.press(key.slice(8)); await page.keyboard.up('Control');
      } else { await page.keyboard.press(key); }
    }
    async function click(name) {
      await sleep(300);
      const widget = (await state()).widgets[name];
      assert.ok(widget, 'Missing widget: ' + name);
      await page.mouse.click(widget.x, widget.y);
      await sleep(600);
    }
    async function fill(name, value) {
      const widget = (await state()).widgets['CAD_Input_' + name];
      assert.ok(widget, 'Missing input: ' + name);
      await page.mouse.click(widget.x, widget.y);
      await press('Control+A'); await page.keyboard.type(value); await press('Tab');
      await sleep(250);
    }
    async function runSearch(name) {
      await click('CAD_Action_search');
      await fill('search',name);
      await click('CAD_Button_search_run');
      await sleep(600);
    }
    async function next(name) {
      const widget = (await state()).widgets['CAD_Input_' + name];
      await page.mouse.click(widget.x, widget.y); await press('ArrowDown'); await press('Enter');
      await sleep(400);
    }
    function near(actual, expected) { assert.ok(Math.abs(actual - expected) < 0.01, `${actual} != ${expected}`); }
    function pass(label) { passed.push(label); console.log('PASS', label); }
    try {
      await py('True', "App.newDocument('FaceProbe')\n_body=App.ActiveDocument.addObject('PartDesign::Body','Body')\n_box=_body.newObject('PartDesign::AdditiveBox','Box')\n_box.Length=40\n_box.Width=30\n_box.Height=10\nApp.ActiveDocument.recompute()\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      await sleep(1000);
      const top=await py("next('Face%d' % (i+1) for i,f in enumerate(_box.Shape.Faces) if f.normalAt(0,0).z>0.9)");
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(_box,"+JSON.stringify(top)+")");
      await click('CAD_Action_extrude');
      assert.equal((await state()).session,'extrude');
      await sleep(1000);
      const arrow=(await state()).widgets.CAD_ExtrudeArrow;
      assert.ok(arrow,'extrusion arrow must be visible');
      const axis=await py('list(cad_workspace.WORKSPACE.arrow_handle.axis)');
      await page.mouse.move(arrow.x,arrow.y);
      await page.mouse.down();
      await page.mouse.move(arrow.x+axis[0]*24,arrow.y+axis[1]*24,{steps:6});
      await page.mouse.up();
      await sleep(700);
      const dragged=await py("cad_workspace.WORKSPACE.value('distance')");
      assert.ok(dragged>10.1,'dragging the arrow changes the distance input');
      await click('CAD_Button_accept');
      const result=await py("[(o.Name,o.TypeId,o.Shape.Volume) for o in App.ActiveDocument.Objects if 'SourceFace' in o.PropertiesList]");
      assert.equal(result.length,1,JSON.stringify(result));
      near(result[0][2],12000+1200*dragged);
      assert.equal(await py("App.ActiveDocument.getObject('FaceExtrusion').FaceStatus"),'OK');
      await py('True', "_face_obj=App.ActiveDocument.getObject('FaceExtrusion')\n_face_obj.Length=20\nApp.ActiveDocument.recompute()");
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),36000);
      assert.ok(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.isValid()"));
      await py('True', "App.ActiveDocument.saveCopy('/tmp/face-probe.FCStd')\nApp.closeDocument('FaceProbe')\nApp.openDocument('/tmp/face-probe.FCStd')\nApp.ActiveDocument.recompute()");
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),36000);
      assert.deepEqual(await page.evaluate(()=>window.__fcPyErrors||[]),[]);
      console.log('PASS face extrusion -> recompute -> FCStd reopen');
    } catch (error) {
      console.log('FAILURE_STATE',JSON.stringify(await state()));
      await page.screenshot({path:path.join(output,'face-failure.png')});
      throw error;
    }
  } finally {
    fs.writeFileSync(path.join(output, 'face-console.log'), log.join('\n'));
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => {console.error(error);process.exitCode=1;});
