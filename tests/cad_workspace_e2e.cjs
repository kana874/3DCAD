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
    page.setDefaultTimeout(60000);
    page.on('console', message => log.push(message.text()));
    page.on('pageerror', error => log.push('PAGEERROR: ' + error.message));
    await page.goto('http://127.0.0.1:18791/?workspace=fusion', {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => window.__cadReady || window.__cadFailed, {timeout: 240000});
    assert.equal(await page.evaluate(() => window.__cadFailed), undefined);

    async function py(expression, statements = '') {
      await page.waitForFunction(() => !window.__fcPyBusy);
      const out = '/tmp/cad-e2e-result.json';
      await page.evaluate(({expression, statements, out}) => {
        try { window.fcInstance.FS.unlink(out); } catch (_) {}
        const code = 'import json,traceback\ntry:\n' +
          statements.split('\n').filter(Boolean).map(line => ' ' + line).join('\n') +
          '\n _e2e_result = ' + expression +
          '\nexcept Exception:\n _e2e_result = {"ERROR":traceback.format_exc()}\n' +
          'with open(' + JSON.stringify(out) + ',"w") as _f: json.dump(_e2e_result,_f)\n';
        window.__fcRunPyGuarded(code);
      }, {expression, statements, out});
      await page.waitForFunction(out => {
        try { return !!window.fcInstance.FS.stat(out); } catch (_) { return false; }
      }, {}, out);
      const result = await page.evaluate(out => JSON.parse(new TextDecoder().decode(window.fcInstance.FS.readFile(out))), out);
      assert.ok(!result?.ERROR, result?.ERROR);
      return result;
    }
    const state = () => py('cad_workspace.WORKSPACE.diagnostics()');
    async function press(key) {
      if (key === 'Control+A') {
        await page.keyboard.down('Control'); await page.keyboard.press('A'); await page.keyboard.up('Control');
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
    async function next(name) {
      const widget = (await state()).widgets['CAD_Input_' + name];
      await page.mouse.click(widget.x, widget.y); await press('ArrowDown'); await press('Enter');
      await sleep(400);
    }
    function near(actual, expected) { assert.ok(Math.abs(actual - expected) < 0.01, `${actual} != ${expected}`); }
    function pass(label) { passed.push(label); console.log('PASS', label); }
    try {
      // Fixture setup: an empty document and a dark application palette.
      await py('True', "App.newDocument('ReferenceCheck')");
      await sleep(800);
      assert.equal(await py('cad_workspace.WORKSPACE.reference_root.whichChild.getValue()'), -3);
      assert.equal(await py('len(App.ActiveDocument.Objects)'), 0, 'references must not create model objects');
      const gridButton = await py("(lambda w: [w.mapToGlobal(w.rect().center()).x(), w.mapToGlobal(w.rect().center()).y()])(cad_workspace.WORKSPACE.bar.widgetForAction(cad_workspace.WORKSPACE.actions['grid']))");
      await page.mouse.click(...gridButton); await sleep(400);
      assert.equal(await py('cad_workspace.WORKSPACE.reference_root.whichChild.getValue()'), -1);
      await page.mouse.click(...gridButton); await sleep(400);
      assert.equal(await py('cad_workspace.WORKSPACE.reference_root.whichChild.getValue()'), -3);
      const originalPalette = await py('cad_workspace.WORKSPACE.bar.palette().color(QtGui.QPalette.Window).name()', 'from PySide6 import QtGui');
      await py('True', "_original_palette = Gui.getMainWindow().palette()\n_dark_palette = QtGui.QPalette(_original_palette)\n_dark_palette.setColor(QtGui.QPalette.Window, QtGui.QColor('#242424'))\n_dark_palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor('#eeeeee'))\n_dark_palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor('#eeeeee'))\nGui.getMainWindow().setPalette(_dark_palette)");
      await sleep(500);
      assert.equal(await py('cad_workspace.WORKSPACE.bar.palette().color(QtGui.QPalette.Window).name()'), '#242424');
      await page.screenshot({path: path.join(output, 'empty-grid-dark.png')});
      await py('True', 'Gui.getMainWindow().setPalette(_original_palette)');
      await sleep(500);
      assert.equal(await py('cad_workspace.WORKSPACE.bar.palette().color(QtGui.QPalette.Window).name()'), originalPalette);
      pass('empty document references are visible, model stays empty, toolbar follows dark/light palette');
      await click('CAD_Button_create_sketch');
      await click('CAD_Button_start_sketch');
      assert.equal(await py('cad_workspace.WORKSPACE.reference_root.whichChild.getValue()'), -1, 'Sketcher owns the edit grid');
      await click('CAD_Button_rectangle_exact');
      await fill('width', '50 mm'); await fill('height', '30 mm');
      await click('CAD_Button_add_geometry');
      await press('e'); await sleep(800);
      assert.equal((await state()).session, 'extrude', 'E must route to the dedicated command');
      await click('CAD_Button_accept');
      let model = await state();
      near(model.features.find(o => o.type === 'PartDesign::Pad').volume, 15000);
      pass('numeric sketch -> E -> Pad: 15000 mm3');
      await sleep(900);

      // Pick a real rendered face, not a programmatic selection.
      await page.mouse.click(810, 420); await sleep(400);
      const picked = await py('[(s.Object.Name,list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]');
      assert.ok(picked.some(item => item[1].some(name => name.startsWith('Face'))), JSON.stringify(picked));
      await click('CAD_Action_sketch');
      await click('CAD_Button_circle_exact');
      await fill('x', '25 mm'); await fill('y', '15 mm'); await fill('diameter', '10 mm');
      await click('CAD_Button_add_geometry');
      await press('e'); await sleep(600);
      await next('operation'); await next('direction'); await next('extent');
      await click('CAD_Button_accept');
      near((await state()).features.find(o => o.type === 'PartDesign::Pocket').volume, 15000 - 250 * Math.PI);
      pass('rendered face -> circle -> through cut');

      const history = await py('[{"x":w.history.viewport().mapToGlobal(w.history.visualItemRect(i).center()).x(),"y":w.history.viewport().mapToGlobal(w.history.visualItemRect(i).center()).y()} for i in [w.history.item(j) for j in range(w.history.count())] if i.data(QtCore.Qt.UserRole)=="Pad"]',
        'from PySide6 import QtCore\nw=cad_workspace.WORKSPACE');
      assert.equal(history.length, 1);
      await page.mouse.click(history[0].x, history[0].y);
      await page.mouse.click(history[0].x, history[0].y, {clickCount: 2}); await sleep(500);
      await fill('length', '20 mm'); await click('CAD_Button_apply_length');
      model = await state();
      near(model.features.find(o => o.type === 'PartDesign::Pad').volume, 30000);
      near(model.features.find(o => o.type === 'PartDesign::Pocket').volume, 30000 - 500 * Math.PI);
      near(await py('App.ActiveDocument.getObject("Sketch001").Placement.Base.z'), 20);
      pass('history edit -> attached sketch follows -> through cut recomputes');

      const item = await py('[{"x":w.tree.viewport().mapToGlobal(w.tree.visualItemRect(i).center()).x(),"y":w.tree.viewport().mapToGlobal(w.tree.visualItemRect(i).center()).y()} for i in w.tree.findItems("スケッチ",QtCore.Qt.MatchExactly|QtCore.Qt.MatchRecursive,0)]',
        'from PySide6 import QtCore\nw=cad_workspace.WORKSPACE');
      await page.mouse.click(item[0].x, item[0].y); await press('e'); await sleep(500);
      const before = (await state()).features.length;
      await press('Escape'); await sleep(500);
      assert.equal((await state()).session, null);
      assert.equal((await state()).features.length, before);
      assert.equal(await py('any(o.Name.startswith("CADPreview") for o in App.ActiveDocument.Objects)'), false);
      pass('Esc restores model without a preview object');

      // Persistence check uses FreeCAD's actual FCStd save/restore APIs. It
      // does not claim to test the browser file picker or the download UI.
      await py('True', 'App.ActiveDocument.saveAs("/tmp/cad-e2e.FCStd")\n_name=App.ActiveDocument.Name\nApp.closeDocument(_name)\nApp.openDocument("/tmp/cad-e2e.FCStd")');
      model = await state();
      near(model.features.find(o => o.type === 'PartDesign::Pocket').volume, 30000 - 500 * Math.PI);
      pass('FCStd save/reopen preserves parametric model');
      await page.screenshot({path: path.join(output, 'workspace.png')});
      fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ok: true, passed, model}, null, 2));
    } catch (error) {
      await page.screenshot({path: path.join(output, 'failure.png')});
      throw error;
    }
  } finally {
    fs.writeFileSync(path.join(output, 'console.log'), log.join('\n'));
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
