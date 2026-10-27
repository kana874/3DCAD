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
      let model;
      if (!['workflows','regions','catalog','sketchtools'].includes(process.env.CAD_TEST_PHASE)) {
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
      model = await state();
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
      await page.mouse.click(history[0].x, history[0].y, {count: 2, delay: 60}); await sleep(700);
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
      }
      if (!['baseline','catalog','sketchtools'].includes(process.env.CAD_TEST_PHASE)) {
      // Additional fixture setup is explicit: geometry algorithms are tested
      // through the engine; plane/region selection and UI actions use real input.
      if (process.env.CAD_TEST_PHASE !== 'regions') {
      await py('True', "App.newDocument('WorkflowCheck')");
      await sleep(700);
      for (const plane of ['XY', 'YZ', 'XZ']) {
        await click('CAD_Button_create_sketch');
        assert.equal(await py('cad_workspace.WORKSPACE.plane_picker is not None'), true);
        const pixel = await py('_plane_pixel', `
from PySide6 import QtCore,QtWidgets
_picker=cad_workspace.WORKSPACE.plane_picker
_viewer=next(w for w in Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow().findChildren(QtWidgets.QWidget) if w.metaObject().className()=='Gui::View3DInventorViewer' and w.isVisible())
_plane_pixel=None
for _a in (8,20,35,42):
 for _b in (8,20,35,42):
  _xyz={'XY':(_a,_b,0),'YZ':(0,_a,_b),'XZ':(_a,0,_b)}['${plane}']
  _point=_picker.view.getPointOnScreen(App.Vector(*_xyz))
  _x,_y=_point[0],_picker.view.getSize()[1]-1-_point[1]
  if _picker.pick_at(_x,_y)=='${plane}' and _plane_pixel is None:
   _origin=_viewer.mapToGlobal(QtCore.QPoint(0,0))
   _plane_pixel=[_origin.x()+_x,_origin.y()+_y]
`);
        assert.ok(pixel,'the rendered plane must have a visible pick target: '+plane);
        await page.mouse.click(...pixel); await sleep(800);
        assert.ok((await state()).sketch, 'plane click must start a sketch: '+plane);
        const normal = await py('(lambda n:[round(n.x),round(n.y),round(n.z)])(cad_workspace.sketch_in_edit(Gui).Placement.Rotation.multVec(App.Vector(0,0,1)))');
        assert.deepEqual(normal, {XY:[0,0,1],YZ:[1,0,0],XZ:[0,-1,0]}[plane]);
        if (plane === 'XY') {
          await click('CAD_Button_rectangle_center_exact');
          await fill('width','50 mm'); await fill('height','30 mm');
          await click('CAD_Button_add_geometry');
          const bounds = await py('(lambda b:[b.XMin,b.XMax,b.YMin,b.YMax])(cad_workspace.sketch_in_edit(Gui).Shape.BoundBox)');
          assert.deepEqual(bounds, [-25,25,-15,15]);
          await press('l'); await sleep(300);
          for (const p of [[0,0,0],[10,0,0],[10,10,0]]) {
            const q = await py("(lambda w,p:[w.mapToGlobal(QtCore.QPoint(0,0)).x()+p[0],w.mapToGlobal(QtCore.QPoint(0,0)).y()+w.height()-1-p[1]])(next(w for w in Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow().findChildren(QtWidgets.QWidget) if w.metaObject().className()=='Gui::View3DInventorViewer' and w.isVisible()),Gui.activeDocument().activeView().getPointOnScreen(App.Vector("+p.join(',')+")))",'from PySide6 import QtCore,QtWidgets');
            await page.mouse.click(...q); await sleep(250);
          }
          await press('Escape'); await sleep(300);
          assert.ok((await state()).geometryCount>=7,'L must draw a connected polyline through real clicks');

        }
        await click('CAD_Action_finish');
      }
      pass('click all three origin planes; numeric center rectangle keeps its specified center');

      // Close all docks using their titlebar X buttons, then recover from the
      // persistent toolbar menu, without relying on a hidden dock button.
      for (const name of ['CAD_Browser','CAD_Command','CAD_History']) {
        const w = (await state()).widgets[name];
        await page.mouse.click(w.x+w.width/2-10, w.y-w.height/2+10); await sleep(300);
      }
      assert.equal(await py('all(not d.isVisible() for d in (cad_workspace.WORKSPACE.tree_dock,cad_workspace.WORKSPACE.panel_dock,cad_workspace.WORKSPACE.history_dock))'), true);
      await click('CAD_ViewMenu');
      const reset = await py("(lambda m,a:[m.mapToGlobal(m.actionGeometry(a).center()).x(),m.mapToGlobal(m.actionGeometry(a).center()).y()])(QtWidgets.QApplication.activePopupWidget(),cad_workspace.WORKSPACE.actions['layout_reset'])", 'from PySide6 import QtWidgets');
      await page.mouse.click(...reset); await sleep(500);
      assert.equal(await py('all(d.isVisible() for d in (cad_workspace.WORKSPACE.tree_dock,cad_workspace.WORKSPACE.panel_dock,cad_workspace.WORKSPACE.history_dock))'), true);
      pass('close every panel -> toolbar Display menu restores all panels');

      }
      // Exact arrangement: open sketch segment + body section closes two cells.
      await py('True', "import Part,cad_profiles\n_d=App.newDocument('BoundaryCheck')\n_b=_d.addObject('PartDesign::Body','Body')\n_s=_b.newObject('Sketcher::SketchObject','BaseSketch')\ncad_workspace.add_rectangle(App,_s,50,30)\n_pad=_b.newObject('PartDesign::Pad','Pad')\n_pad.Profile=_s\n_pad.Length=10\n_d.recompute()\n_line=_b.newObject('Sketcher::SketchObject','Divider')\n_line.Placement.Base=App.Vector(0,0,10)\n_line.addGeometry(Part.LineSegment(App.Vector(25,0,0),App.Vector(25,30,0)),False)\n_d.recompute()\nGui.Selection.clearSelection()\nGui.Selection.addSelection(_line)\nGui.activeDocument().activeView().viewTop()\ncad_workspace.WORKSPACE.fit_view()");
      await press('e'); await sleep(900);
      const cells = await py('[(k,f.Area) for k,f in cad_workspace.WORKSPACE.session.region_candidates]');
      assert.equal(cells.length,2); near(cells[0][1],750); near(cells[1][1],750);
      const cellPixel = await py("(lambda w,p:[w.mapToGlobal(QtCore.QPoint(0,0)).x()+p[0],w.mapToGlobal(QtCore.QPoint(0,0)).y()+w.height()-1-p[1]])(next(w for w in Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow().findChildren(QtWidgets.QWidget) if w.metaObject().className()=='Gui::View3DInventorViewer' and w.isVisible()),Gui.activeDocument().activeView().getPointOnScreen(App.Vector(12,15,10)))",'from PySide6 import QtCore,QtWidgets');
      await page.mouse.click(...cellPixel); await sleep(700);
      assert.equal(await py('len(cad_workspace.WORKSPACE.session.region_keys)'),1);
      await click('CAD_Button_accept');
      near(await py('App.ActiveDocument.getObject("Pad001").Shape.Volume'),22500);
      await py('True','App.ActiveDocument.saveAs("/tmp/boundary.FCStd")\nApp.closeDocument(App.ActiveDocument.Name)\nApp.openDocument("/tmp/boundary.FCStd")\nApp.ActiveDocument.getObject("Pad001").Length=20\nApp.ActiveDocument.recompute()');
      near(await py('App.ActiveDocument.getObject("Pad001").Shape.Volume'),30000);
      pass('real region click: body section + open segment -> half-area extrusion -> FCStd reload and length edit');

      // Test native task embedding with an explicit selection fixture.
      await py('True','Gui.Selection.clearSelection()\nGui.Selection.addSelection(App.ActiveDocument.getObject("Pad001"),"Edge1")');
      await click('CAD_Action_fillet');
      assert.equal(await py('cad_workspace.WORKSPACE.native_task_widget is not None and cad_workspace.WORKSPACE.native_task_widget.parentWidget()==cad_workspace.WORKSPACE.native_host'),true);
      assert.equal(await py('any(w.isVisible() for w in cad_workspace.WORKSPACE.native_widgets if isinstance(w,QtWidgets.QDockWidget))','from PySide6 import QtWidgets'),false);
      const reject = await py("[(b.mapToGlobal(b.rect().center()).x(),b.mapToGlobal(b.rect().center()).y()) for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QAbstractButton) if b.isVisible() and ('Cancel' in b.text() or 'キャンセル' in b.text())]",'from PySide6 import QtWidgets');
      assert.ok(reject.length,'embedded native task must expose cancellation');
      await page.mouse.click(...reject[0]); await sleep(600);
      assert.equal(await py('not bool(Gui.Control.activeDialog())'),true);
      assert.equal(await py('App.ActiveDocument.getObject("Fillet") is None'),true);
      near(await py('App.ActiveDocument.getObject("Pad001").Shape.Volume'),30000);
      pass('fillet task and Cancel stay inside the dedicated Design panel');
      const geometry = await py('_geometry_result', `
import cad_profiles,cad_core,Part
_d=App.newDocument('GeometryCheck')
_b=_d.addObject('PartDesign::Body','Body')
_s=_b.newObject('Sketcher::SketchObject','Sketch')
cad_core.add_three_point_rectangle(App,_s,0,0,30,40,6,58)
_d.recompute()
_area=Part.makeFace(_s.Shape.Wires,'Part::FaceMakerBullseye').Area
_c=_b.newObject('Sketcher::SketchObject','Circle')
cad_core.add_two_point_circle(App,_c,0,0,10,0)
_c.addGeometry(Part.LineSegment(App.Vector(0,0,0),App.Vector(10,0,0)),False)
_d.recompute()
_cells=cad_profiles.regions(_c)
_p=cad_profiles.make_profile(_b,_c,[],[_cells[0][0]])
_b.Tip=_c
_pad=_b.newObject('PartDesign::Pad','Pad')
_pad.Profile=_p
_pad.Length=10
_d.recompute()
_geometry_result={'rectangleArea':_area,'halfAreas':[f.Area for k,f in _cells],'halfVolume':_pad.Shape.Volume}
_session=cad_core.ExtrusionSession(App,Gui,_c)
_session.region_candidates=_cells
_session.region_keys=[_cells[1][0]]
_new=_session.accept(5,'new')
_geometry_result['newVolume']=_new.Shape.Volume
_geometry_result['originalVolume']=_pad.Shape.Volume
_geometry_result['bodyCount']=len(_d.findObjects('PartDesign::Body'))
_d.saveAs('/tmp/half.FCStd')
App.closeDocument(_d.Name)
_d=App.openDocument('/tmp/half.FCStd')
_d.getObject('RegionProfile').Proxy=None
_geometry_result['repairCount']=cad_profiles.restore_proxies()
_d.getObject('Pad').Length=20
_d.recompute()
_geometry_result['repairedVolume']=_d.getObject('Pad').Shape.Volume
_valid_keys=list(_d.getObject('RegionProfile').RegionKeys)
_geometry_result['validKey']=_valid_keys[0]
_geometry_result['originalY']=_d.getObject('RegionProfile').Shape.CenterOfMass.y
_d.getObject('RegionProfile').RegionKeys=['missing']
_d.recompute()
_geometry_result['missingRegion']=_d.getObject('RegionProfile').Shape.isNull() and _d.getObject('RegionProfile').ProfileStatus.startswith('領域の再選択が必要')
`);
      near(geometry.rectangleArea,1500);
      assert.equal(geometry.halfAreas.length,2);
      for (const area of geometry.halfAreas) near(area,12.5*Math.PI);
      near(geometry.halfVolume,125*Math.PI);
      near(geometry.newVolume,62.5*Math.PI);
      near(geometry.originalVolume,125*Math.PI);
      assert.equal(geometry.bodyCount,2);
      assert.ok(geometry.repairCount>=1);
      near(geometry.repairedVolume,250*Math.PI);
      assert.equal(geometry.missingRegion,true);
      pass('3-point rectangle, diameter-defined circle, split-circle identities, new body, proxy recovery, explicit missing-region failure');
      await sleep(600);
      const partialHistory = await py("(lambda w,i:[w.history.viewport().mapToGlobal(w.history.visualItemRect(i).center()).x(),w.history.viewport().mapToGlobal(w.history.visualItemRect(i).center()).y()])(cad_workspace.WORKSPACE,next(i for i in [cad_workspace.WORKSPACE.history.item(j) for j in range(cad_workspace.WORKSPACE.history.count())] if i.data(QtCore.Qt.UserRole)=='Pad'))",'from PySide6 import QtCore');
      await page.mouse.click(...partialHistory,{count:2,delay:60}); await sleep(500);
      await click('CAD_Button_edit_regions');
      const replacement = await py("(lambda w,i:[w.region_list.viewport().mapToGlobal(w.region_list.visualItemRect(i).topLeft()).x()+9,w.region_list.viewport().mapToGlobal(w.region_list.visualItemRect(i).center()).y()])(cad_workspace.WORKSPACE,next(i for i in [cad_workspace.WORKSPACE.region_list.item(j) for j in range(cad_workspace.WORKSPACE.region_list.count())] if i.data(QtCore.Qt.UserRole)!="+JSON.stringify(geometry.validKey)+"))",'from PySide6 import QtCore');
      await page.mouse.click(...replacement); await sleep(500);
      await click('CAD_Button_apply_regions');
      assert.equal(await py('App.ActiveDocument.getObject("RegionProfile").ProfileStatus'), 'OK');
      assert.ok(await py('App.ActiveDocument.getObject("RegionProfile").Shape.CenterOfMass.y')*geometry.originalY<0);
      near(await py('App.ActiveDocument.getObject("Pad").Shape.Volume'),250*Math.PI);
      pass('history -> reselect region -> repair an invalid profile with real mouse input');


      }
      if (!['baseline','workflows','regions','sketchtools'].includes(process.env.CAD_TEST_PHASE)) {
      await py('True', "App.newDocument('CatalogCheck')");
      await sleep(600);
      await runSearch('workbench_SpreadsheetWorkbench');
      assert.ok(await py("'native_Spreadsheet_CreateSheet' in cad_workspace.WORKSPACE.native_actions"));
      await runSearch('native_Spreadsheet_CreateSheet');
      assert.equal(await py("len(App.ActiveDocument.findObjects('Spreadsheet::Sheet'))"),1);
      assert.equal((await state()).is3DView,false);
      assert.equal(await py('cad_workspace.WORKSPACE.reference_root is None'),true);
      // A1 center in the fixed 1600x1000 spreadsheet viewport.
      const cell = [350,134];
      await page.mouse.click(...cell); await press('F2'); await page.keyboard.type('=2+3'); await press('Enter'); await sleep(600);
      assert.equal(Number(await py("App.ActiveDocument.findObjects('Spreadsheet::Sheet')[0].get('A1')")),5);
      await page.mouse.click(350,165); await page.keyboard.type('Sketch'); await press('Enter'); await sleep(400);
      assert.equal(await py("App.ActiveDocument.findObjects('Spreadsheet::Sheet')[0].get('A2')"),'Sketch');
      await runSearch('workbench_PartDesignWorkbench');
      await runSearch('new_3d_view');
      assert.equal((await state()).is3DView,true);
      assert.equal(await py("any(w.isVisible() for w in Gui.getMainWindow().findChildren(QtWidgets.QToolBar) if not w.objectName().startswith('CAD_'))",'from PySide6 import QtWidgets'),false);
      pass('dedicated catalog -> Spreadsheet workbench -> real cell formula -> PartDesign -> new 3D view');
      }
      if (!['baseline','workflows','regions','catalog'].includes(process.env.CAD_TEST_PHASE)) {
      await py('True', "App.newDocument('SketchToolsCheck')\nApp.ParamGet('User parameter:BaseApp/Preferences/Mod/Sketcher/Tools').SetInt('OnViewParameterVisibility',1)");
      await sleep(500);
      await click('CAD_Button_create_sketch'); await click('CAD_Button_start_sketch');
      assert.equal(await py('cad_workspace.sketch_in_edit(Gui).ViewObject.Visibility'),true);
      await py('True', 'Gui.activeDocument().activeView().getCameraNode().height.setValue(100)');
      await press('r'); await sleep(600);
      assert.equal(await py('cad_workspace.WORKSPACE.native_task_sketch'),true);
      const methods = await py("[(b.objectName(),[b.itemText(i) for i in range(b.count())]) for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QComboBox) if b.isVisible()]",'from PySide6 import QtWidgets');
      const rectangleMethod = await py("(lambda b:[b.mapToGlobal(b.rect().center()).x(),b.mapToGlobal(b.rect().center()).y()])(next(b for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QComboBox) if b.isVisible() and b.count()==4 and any('3' in b.itemText(i) for i in range(b.count()))))",'from PySide6 import QtWidgets');
      assert.ok(methods.length,'native construction methods must be exposed');
      await page.mouse.click(...rectangleMethod);
      const methodRow = await py("(lambda b,i:[b.view().viewport().mapToGlobal(b.view().visualRect(i).center()).x(),b.view().viewport().mapToGlobal(b.view().visualRect(i).center()).y()])(next(b for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QComboBox) if b.isVisible() and b.count()==4 and any('3' in b.itemText(i) for i in range(b.count()))),next(b for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QComboBox) if b.isVisible() and b.count()==4 and any('3' in b.itemText(i) for i in range(b.count()))).model().index(2,0))",'from PySide6 import QtWidgets');
      await page.mouse.click(...methodRow);
      let methodState;
      for (let attempt=0;attempt<20;attempt++) {
        methodState = await py("(lambda b:[b.currentIndex(),QtWidgets.QApplication.activePopupWidget() is None])(next(b for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QComboBox) if b.isVisible() and b.count()==4 and any('3' in b.itemText(i) for i in range(b.count()))))",'from PySide6 import QtWidgets');
        if (methodState[0]===2 && methodState[1]) break;
        await sleep(100);
      }
      assert.deepEqual(methodState,[2,true],'construction mode must be selected before drawing');
      console.log('CONSTRUCTION_STATE',await py("{'combos':[(b.objectName(),b.currentIndex(),[b.itemText(i) for i in range(b.count())]) for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QComboBox) if b.isVisible()], 'checks':[(b.text(),b.isChecked()) for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QCheckBox) if b.isVisible()], 'activeWindow':Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow().windowTitle()}",'from PySide6 import QtWidgets'));
      async function sketchPoint(p, clickPoint=true) {
        const xy = await py("(lambda w,p:[w.mapToGlobal(QtCore.QPoint(0,0)).x()+p[0],w.mapToGlobal(QtCore.QPoint(0,0)).y()+w.height()-1-p[1]])(next(w for w in Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow().findChildren(QtWidgets.QWidget) if w.metaObject().className()=='Gui::View3DInventorViewer'),Gui.activeDocument().activeView().getPointOnScreen(App.Vector("+p.join(',')+")))",'from PySide6 import QtCore,QtWidgets');
        await page.mouse.move(...xy);
        await sleep(120); // Let Qt process motion before the separate button events.
        if (clickPoint) { await page.mouse.down(); await sleep(40); await page.mouse.up(); }
        await sleep(250);
        console.log('DRAW_POINT',p,xy,await py("{'size':Gui.activeDocument().activeView().getSize(),'geometry':cad_workspace.sketch_in_edit(Gui).GeometryCount,'hint':Gui.getMainWindow().statusBar().currentMessage(),'focus':QtWidgets.QApplication.focusWidget().metaObject().className() if QtWidgets.QApplication.focusWidget() else None,'quantities':[(b.objectName(),b.text()) for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QWidget) if b.isVisible() and b.metaObject().className()=='Gui::QuantitySpinBox']}",'from PySide6 import QtWidgets'),await page.evaluate(([x,y])=>document.elementsFromPoint(x,y).slice(0,4).map(e=>({tag:e.tagName,id:e.id,classes:String(e.className)})),xy));
        return xy;
      }
      for (const p of [[-20,-10,0],[-5,-5,0],[-7,5,0]]) await sketchPoint(p);
      await press('Escape'); await sleep(300);
      assert.equal((await state()).geometryCount,4);
      const area = await py("cad_profiles.regions(cad_workspace.sketch_in_edit(Gui))[0][1].Area",'import cad_profiles');
      assert.ok(Math.abs(area-160)<6,'interactive 3-corner construction should follow the three picks');
      await press('c'); await sleep(400);
      await sketchPoint([20,0,0]); await sketchPoint([25,0,0],false);
      await page.screenshot({path:path.join(output,'circle-before-tab.png')});
      await press('Tab');
      await press('Control+A'); await page.keyboard.type('6');
      await press('Control+Enter');
      await sketchPoint([25,0,0]); await press('Escape'); await sleep(300);
      const dimensions = await py("[(c.Type,c.Value) for c in cad_workspace.sketch_in_edit(Gui).Constraints if c.Type in ('Radius','Diameter')]");
      assert.ok(dimensions.some(d=>Math.abs(d[1]-6)<0.001),'on-view entry must create a native circle dimension');
      await click('CAD_Action_finish');
      assert.equal(await py('not bool(Gui.Control.activeDialog()) and Gui.activeDocument().getInEdit() is None'),true);
      pass('embedded sketch controls -> interactive 3-corner construction -> on-view numeric circle dimension');
      }
      if (!process.env.CAD_TEST_PHASE) {
        // Reproduce the visible multi-body/native Start Part state from the report.
        // Import and model construction are explicit fixtures; Body creation and
        // cancellation use the dedicated search UI and real keyboard input.
        await py('True', "import Part\n_d=App.newDocument('NativeBodyCheck')\n_b=_d.addObject('PartDesign::Body','Body')\n_f=_b.newObject('PartDesign::Feature','Base')\n_f.Shape=Part.makeBox(20,30,40)\n_d.recompute()\n_d.saveAs('/tmp/native-body.FCStd')\n_d.mergeProject('/tmp/native-body.FCStd')\n_d.mergeProject('/tmp/native-body.FCStd')\n_d.recompute()\nGui.Selection.clearSelection()");
        const before=await py('[(o.Name,o.Shape.Volume) for o in App.ActiveDocument.findObjects("PartDesign::Body")]');
        assert.equal(before.length,3);
        for (let i=0;i<2;i++) {
          await runSearch('native_PartDesign_Body');
          assert.equal(await py('cad_workspace.WORKSPACE.native_task_active'),false,'completed Body command must not leave a locked task');
          assert.equal((await state()).widgets.CAD_Action_search.enabled,true);
          await press('Escape'); await sleep(600);
        }
        await click('CAD_Action_fit');
        const after=await py('[(o.Name,o.Shape.Volume) for o in App.ActiveDocument.findObjects("PartDesign::Body") if not o.Shape.isNull()]');
        assert.deepEqual(after,before);
        assert.equal(await py('len(App.ActiveDocument.findObjects("PartDesign::Body"))'),5);
        pass('merged bodies -> repeated native Body command -> cancel -> original geometry remains intact');
      }
      if (!process.env.CAD_TEST_PHASE) {
        async function waitDownload(ext) {
          for (let i=0;i<600;i++) {
            const files=fs.readdirSync(downloadDir).filter(n=>n.toLowerCase().endsWith(ext));
            if (files.length && !fs.readdirSync(downloadDir).some(n=>n.endsWith('.crdownload'))) return path.join(downloadDir,files[0]);
            await sleep(100);
          }
          throw new Error('Timed out waiting for '+ext+' browser download');
        }
        assert.equal(await py("not hasattr(App,'_fcweb_saver')"),true,'CAD autosave must not start');
        await click('CAD_Action_save');
        const saved=await waitDownload('.fcstd');
        assert.ok(fs.statSync(saved).size>500,'FCStd was downloaded to disk');
        const chooserPromise=page.waitForFileChooser({timeout:30000});
        await click('CAD_Action_open');
        const chooser=await chooserPromise;
        await chooser.accept([saved]);
        let opened=false;
        for (let i=0;i<80;i++) {
          opened=await py("App.ActiveDocument is not None and App.ActiveDocument.Name!='NativeBodyCheck' and len(App.ActiveDocument.findObjects('PartDesign::Body'))==5");
          if (opened) break;
          await sleep(250);
        }
        assert.equal(opened,true,'downloaded FCStd must reopen through the real file picker');
        assert.equal(await py("sum(1 for o in App.ActiveDocument.findObjects('PartDesign::Body') if not o.Shape.isNull())"),3);
        assert.equal(await py("App.ActiveDocument.FileName.startswith('/tmp/_up/')"),true,'opened CAD data stays in transient storage');
        pass('local FCStd download -> browser file picker -> reopen five bodies without browser CAD autosave');
        await click('CAD_Action_export');
        await next('export_scope'); await next('export_scope'); // all bodies
        await click('CAD_Button_export_step');
        const step=await waitDownload('.step');
        const stepBytes=fs.readFileSync(step);
        assert.ok(stepBytes.length>500,'STEP was downloaded to disk');
        await page.evaluate(bytes=>window.fcInstance.FS.writeFile('/tmp/downloaded.step',new Uint8Array(bytes)),Array.from(stepBytes));
        const info=await py("_step_info","import Part\n_shape=Part.read('/tmp/downloaded.step')\n_step_info={'solids':len(_shape.Solids),'volume':_shape.Volume}");
        assert.equal(info.solids,3);
        near(info.volume,72000);
        pass('STEP export -> browser download -> read back three exact solids');
        const bodyPoint=await py("(lambda w,i:[w.tree.viewport().mapToGlobal(w.tree.visualItemRect(i).center()).x(),w.tree.viewport().mapToGlobal(w.tree.visualItemRect(i).center()).y()])(cad_workspace.WORKSPACE,cad_workspace.WORKSPACE.tree_items['Body'])");
        await page.mouse.click(...bodyPoint); await sleep(400);
        assert.ok(await py("any(o.Name=='Body' for o in Gui.Selection.getSelection())"),'body selected through browser tree');
        const beforeSelected=new Set(fs.readdirSync(downloadDir));
        await click('CAD_Action_export'); await next('export_scope'); await click('CAD_Button_export_step');
        let selectedStep;
        for (let i=0;i<600;i++) {
          selectedStep=fs.readdirSync(downloadDir).find(n=>n.toLowerCase().endsWith('.step')&&!beforeSelected.has(n));
          if (selectedStep && !fs.readdirSync(downloadDir).some(n=>n.endsWith('.crdownload'))) break;
          await sleep(100);
        }
        assert.ok(selectedStep,'selected-body STEP must download');
        await page.evaluate(bytes=>window.fcInstance.FS.writeFile('/tmp/selected.step',new Uint8Array(bytes)),Array.from(fs.readFileSync(path.join(downloadDir,selectedStep))));
        const selectedInfo=await py("_selected_info","import Part\n_selected_shape=Part.read('/tmp/selected.step')\n_selected_info={'solids':len(_selected_shape.Solids),'volume':_selected_shape.Volume}");
        assert.equal(selectedInfo.solids,1); near(selectedInfo.volume,24000);
        await py('True',"_bodies=[o for o in App.ActiveDocument.findObjects('PartDesign::Body') if not o.Shape.isNull()]\n[o.ViewObject.show() for o in _bodies]\n_bodies[1].ViewObject.hide()");
        await sleep(500);
        const beforeVisible=new Set(fs.readdirSync(downloadDir));
        await click('CAD_Action_export'); await click('CAD_Button_export_step');
        let visibleStep;
        for (let i=0;i<600;i++) {
          visibleStep=fs.readdirSync(downloadDir).find(n=>n.toLowerCase().endsWith('.step')&&!beforeVisible.has(n));
          if (visibleStep && !fs.readdirSync(downloadDir).some(n=>n.endsWith('.crdownload'))) break;
          await sleep(100);
        }
        assert.ok(visibleStep,'visible-body STEP must download');
        await page.evaluate(bytes=>window.fcInstance.FS.writeFile('/tmp/visible.step',new Uint8Array(bytes)),Array.from(fs.readFileSync(path.join(downloadDir,visibleStep))));
        const visibleInfo=await py("_visible_info","import Part\n_visible_shape=Part.read('/tmp/visible.step')\n_visible_info={'solids':len(_visible_shape.Solids),'volume':_visible_shape.Volume}");
        assert.equal(visibleInfo.solids,2); near(visibleInfo.volume,48000);
        pass('STEP selection and visibility scopes preserve the intended exact solids');
        // An older recovery copy may be the only copy a user has. Retain it,
        // never reopen it automatically, and let the user explicitly retrieve it.
        const savedBytes=fs.readFileSync(saved);
        await page.evaluate(async bytes=>{
          const vfs=window.fcInstance.FS, dir='/home/web_user/.fcweb-autosave';
          vfs.mkdirTree(dir); vfs.writeFile(dir+'/Legacy.FCStd',new Uint8Array(bytes));
          vfs.mkdirTree('/home/web_user/_up/assembly');
          vfs.writeFile('/home/web_user/_up/assembly/Nested.FCStd',new Uint8Array(bytes));
          await new Promise((resolve,reject)=>vfs.syncfs(false,e=>e?reject(e):resolve()));
        },Array.from(savedBytes));
        assert.deepEqual(await page.evaluate(()=>window.__fcPyErrors||[]),[],'no rejected operations before reload');
        const allowReload=dialog=>dialog.accept();
        page.on('dialog',allowReload);
        await page.reload({waitUntil:'domcontentloaded'});
        page.off('dialog',allowReload);
        await page.waitForFunction(()=>window.__cadReady || window.__cadFailed,{timeout:240000});
        assert.equal(await page.evaluate(()=>window.__cadFailed),undefined);
        assert.equal(await py('len(App.listDocuments())'),0,'old CAD files must not restore automatically');
        assert.equal(await py("not hasattr(App,'_fcweb_saver')"),true);
        await click('CAD_Button_legacy_files');
        await page.waitForSelector('#cad-legacy-files p button');
        const legacyRow='#cad-legacy-files [data-legacy-path="/home/web_user/.fcweb-autosave/Legacy.FCStd"]';
        const nestedRow='#cad-legacy-files [data-legacy-path="/home/web_user/_up/assembly/Nested.FCStd"]';
        assert.ok(await page.$(nestedRow),'previously opened nested files must remain retrievable');
        await page.click(legacyRow+' button');
        const legacyPath=path.join(downloadDir,'Legacy.FCStd');
        for (let i=0;i<300 && !fs.existsSync(legacyPath);i++) await sleep(100);
        assert.deepEqual(fs.readFileSync(legacyPath),savedBytes,'legacy recovery copy downloads unchanged');
        assert.equal(await page.evaluate(()=>window.fcInstance.FS.analyzePath('/home/web_user/.fcweb-autosave/Legacy.FCStd').exists),true);
        page.once('dialog',dialog=>dialog.dismiss());
        await page.click(legacyRow+' button:nth-child(2)');
        assert.equal(await page.evaluate(()=>window.fcInstance.FS.analyzePath('/home/web_user/.fcweb-autosave/Legacy.FCStd').exists),true,'cancel must preserve old data');
        page.once('dialog',dialog=>dialog.accept());
        await page.click(legacyRow+' button:nth-child(2)');
        await page.waitForFunction(selector=>!document.querySelector(selector),{},legacyRow);
        assert.equal(await page.evaluate(()=>window.fcInstance.FS.analyzePath('/home/web_user/.fcweb-autosave/Legacy.FCStd').exists),false);
        assert.equal(await page.evaluate(()=>window.fcInstance.FS.analyzePath('/home/web_user/_up/assembly/Nested.FCStd').exists),true,'deleting one file must preserve other old files');
        pass('old browser recovery stays closed, nested files remain accessible, and deletion requires confirmation');
      }
      assert.deepEqual(fundraisingRequests,[],'no fundraising requests');
      const bridgeErrors=await page.evaluate(()=>window.__fcPyErrors||[]);
      assert.deepEqual(bridgeErrors,[],'no rejected JSPI operations during acceptance flows');
      assert.ok(!log.some(line=>/Maximum call stack size exceeded|PAGEERROR:/.test(line)),'no browser recursion or page errors');
      await page.screenshot({path: path.join(output, 'workspace.png')});
      fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ok: true, passed, model: await state()}, null, 2));
    } catch (error) {
      console.log('FAILURE_STATE',JSON.stringify(await state()));
      await page.screenshot({path: path.join(output, 'failure.png')});
      throw error;
    }
  } finally {
    fs.writeFileSync(path.join(output, 'console.log'), log.join('\n'));
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
