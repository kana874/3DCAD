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
      await next('direction'); await next('direction'); await next('direction');
      assert.equal(await py("cad_workspace.WORKSPACE.fields['direction'].currentData()"),'two');
      await fill('distance2','5 mm');
      await sleep(700);
      const arrow2=(await state()).widgets.CAD_ExtrudeArrow2;
      assert.ok(arrow2,'two-sided extrusion must show a second arrow');
      const axis2=await py('list(cad_workspace.WORKSPACE.arrow_handle2.axis)');
      await page.mouse.move(arrow2.x,arrow2.y);
      await page.mouse.down();
      await page.mouse.move(arrow2.x+axis2[0]*15,arrow2.y+axis2[1]*15,{steps:6});
      await page.mouse.up();
      await sleep(700);
      const dragged2=await py("cad_workspace.WORKSPACE.value('distance2')");
      assert.ok(dragged2>5.1,'dragging the second arrow changes the opposite distance');
      await click('CAD_Button_accept');
      const result=await py("[(o.Name,o.TypeId,o.Shape.Volume) for o in App.ActiveDocument.Objects if 'SourceFace' in o.PropertiesList]");
      assert.equal(result.length,1,JSON.stringify(result));
      near(result[0][2],1200*(Math.max(10,dragged2)+dragged));
      assert.equal(await py("App.ActiveDocument.getObject('FaceExtrusion').FaceStatus"),'OK');
      assert.equal(await py("App.ActiveDocument.getObject('FaceExtrusion').TwoSides"),true);
      await py('True', "_face_obj=App.ActiveDocument.getObject('FaceExtrusion')\n_face_obj.Length=20\nApp.ActiveDocument.recompute()");
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),1200*(Math.max(10,dragged2)+20));
      assert.ok(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.isValid()"));
      await py('True', "App.ActiveDocument.saveCopy('/tmp/face-probe.FCStd')\nApp.closeDocument('FaceProbe')\nApp.openDocument('/tmp/face-probe.FCStd')\nApp.ActiveDocument.recompute()");
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),1200*(Math.max(10,dragged2)+20));
      await py('True', "App.newDocument('FaceCutProbe')\n_cutbody=App.ActiveDocument.addObject('PartDesign::Body','Body')\n_cutbox=_cutbody.newObject('PartDesign::AdditiveBox','Box')\n_cutbox.Length=40\n_cutbox.Width=30\n_cutbox.Height=10\nApp.ActiveDocument.recompute()\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      await sleep(700);
      const cutFace=await py("next('Face%d' % (i+1) for i,f in enumerate(_cutbox.Shape.Faces) if f.normalAt(0,0).z>0.9)");
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(_cutbox,"+JSON.stringify(cutFace)+")");
      await click('CAD_Action_extrude');
      await next('operation'); await next('direction');
      await fill('distance','5 mm'); await sleep(700);
      await click('CAD_Button_cancel');
      near(await py('_cutbox.Shape.Volume'),12000);
      assert.equal(await py("App.ActiveDocument.getObject('FaceExtrusion') is None"),true);
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(_cutbox,"+JSON.stringify(cutFace)+")");
      await click('CAD_Action_extrude');
      await next('operation'); await next('direction');
      await fill('distance','5 mm'); await sleep(700);
      await click('CAD_Button_accept');
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),6000);
      console.log('PASS face cut reverse and cancellation preserve original');
      await py('True', "import Part\n_throughdoc=App.newDocument('FaceThroughProbe')\n_throughbody=_throughdoc.addObject('PartDesign::Body','Body')\n_throughbase=_throughbody.newObject('PartDesign::Feature','Base')\n_throughbase.Shape=Part.makeBox(40,30,10).fuse(Part.makeBox(10,10,10,App.Vector(10,10,10))).removeSplitter()\n_throughdoc.recompute()\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      await sleep(700);
      const throughFace=await py("next('Face%d' % (i+1) for i,f in enumerate(_throughbase.Shape.Faces) if f.normalAt(0,0).z>0.9 and abs(f.CenterOfMass.z-20)<0.01)");
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(_throughbase,"+JSON.stringify(throughFace)+")");
      await click('CAD_Action_extrude');
      await next('operation'); await next('direction'); await next('extent');
      await sleep(700);
      await click('CAD_Button_accept');
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),11000);
      assert.equal(await py("App.ActiveDocument.getObject('FaceExtrusion').ThroughAll"),true);
      console.log('PASS face cut through-all');
      await py('True', "App.newDocument('PressPullProbe')\n_ppbody=App.ActiveDocument.addObject('PartDesign::Body','Body')\n_ppbox=_ppbody.newObject('PartDesign::AdditiveBox','Box')\n_ppbox.Length=40\n_ppbox.Width=30\n_ppbox.Height=10\nApp.ActiveDocument.recompute()\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      await sleep(700);
      const ppface=await py("next('Face%d' % (i+1) for i,f in enumerate(_ppbox.Shape.Faces) if f.normalAt(0,0).z>0.9)");
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(_ppbox,"+JSON.stringify(ppface)+")");
      await click('CAD_Action_press_pull');
      assert.equal(await py("cad_workspace.WORKSPACE.fields['operation'].currentData()"),'offset');
      await fill('distance','5 mm');
      await sleep(700);
      await click('CAD_Button_accept');
      assert.equal(await py("App.ActiveDocument.getObject('FaceExtrusion').FaceStatus"),'OK');
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),18000);
      console.log('PASS Q selects face offset and preserves native solid geometry');
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(App.ActiveDocument.getObject('FaceExtrusion'),'Edge1')");
      await click('CAD_Action_press_pull');
      assert.equal(await py('cad_workspace.WORKSPACE.native_task_widget is not None'),true,'Q on an edge must open fillet');
      const reject=await py("[(b.mapToGlobal(b.rect().center()).x(),b.mapToGlobal(b.rect().center()).y()) for b in cad_workspace.WORKSPACE.native_task_widget.findChildren(QtWidgets.QAbstractButton) if b.isVisible() and ('Cancel' in b.text() or 'キャンセル' in b.text())]",'from PySide6 import QtWidgets');
      assert.ok(reject.length);
      await page.mouse.click(...reject[0]); await sleep(600);
      assert.equal(await py('not bool(Gui.Control.activeDialog())'),true);
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.Volume"),18000);
      console.log('PASS Q on edge opens cancellable fillet task');
      await py('True', "App.newDocument('StartOffsetProbe')\n_startbody=App.ActiveDocument.addObject('PartDesign::Body','Body')\n_startbox=_startbody.newObject('PartDesign::AdditiveBox','Box')\n_startbox.Length=40\n_startbox.Width=30\n_startbox.Height=10\nApp.ActiveDocument.recompute()\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      await sleep(700);
      const startface=await py("next('Face%d' % (i+1) for i,f in enumerate(_startbox.Shape.Faces) if f.normalAt(0,0).z>0.9)");
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(_startbox,"+JSON.stringify(startface)+")");
      await click('CAD_Action_extrude');
      await next('operation'); await next('operation'); await next('operation');
      assert.equal(await py("cad_workspace.WORKSPACE.fields['operation'].currentData()"),'new');
      await fill('start','5 mm'); await sleep(700);
      await click('CAD_Button_accept');
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.BoundBox.ZMin"),15);
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.BoundBox.ZMax"),25);
      console.log('PASS face extrusion starts at specified offset');
      await py('True', "import Part\n_targetdoc=App.newDocument('TargetFaceProbe')\n_targetbody=_targetdoc.addObject('PartDesign::Body','Body')\n_targetbase=_targetbody.newObject('PartDesign::AdditiveBox','Box')\n_targetbase.Length=40\n_targetbase.Width=30\n_targetbase.Height=10\n_targetobj=_targetdoc.addObject('Part::Feature','Target')\n_targetobj.Shape=Part.makeBox(40,30,5,App.Vector(0,0,30))\n_targetdoc.recompute()\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      await sleep(700);
      const fromFace=await py("next('Face%d' % (i+1) for i,f in enumerate(_targetbase.Shape.Faces) if f.normalAt(0,0).z>0.9)");
      const toFace=await py("next('Face%d' % (i+1) for i,f in enumerate(_targetobj.Shape.Faces) if f.normalAt(0,0).z>0.9)");
      await py('True', "Gui.Selection.clearSelection()\nGui.Selection.addSelection(_targetbase,"+JSON.stringify(fromFace)+")");
      await click('CAD_Action_extrude');
      await next('operation'); await next('operation'); await next('operation');
      await next('extent'); await next('extent');
      await click('CAD_Button_select_target');
      const targetPoint=await py("[_p.x(),_p.y()]", "from PySide6 import QtCore,QtWidgets\n_view=Gui.activeDocument().activeView()\n_mdi=Gui.getMainWindow().findChild(QtWidgets.QMdiArea)\n_viewer=next(w for w in _mdi.activeSubWindow().findChildren(QtWidgets.QWidget) if w.metaObject().className()=='Gui::View3DInventorViewer')\n_pt=_targetobj.Shape.getElement("+JSON.stringify(toFace)+").CenterOfMass\n_xy=_view.getPointOnScreen(_pt)\n_w,_h=_view.getSize()\n_p=_viewer.mapToGlobal(QtCore.QPoint(round(_xy[0]*_viewer.width()/_w),round((_h-1-_xy[1])*_viewer.height()/_h)))");
      await page.mouse.click(...targetPoint);
      await sleep(1000);
      assert.equal(await py("cad_workspace.WORKSPACE.selecting_target"),false);
      near(await py("cad_workspace.WORKSPACE.value('distance')"),25);
      await click('CAD_Button_accept');
      const targetResult=await py("bool(App.ActiveDocument.getObject('FaceExtrusion'))");
      assert.ok(targetResult);
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.BoundBox.ZMax"),35);
      await py('True', "_targetobj.Shape=Part.makeBox(40,30,5,App.Vector(0,0,40))\n_targetdoc.recompute()");
      near(await py("App.ActiveDocument.getObject('FaceExtrusion').Shape.BoundBox.ZMax"),45);
      console.log('PASS target face recomputes when referenced plane moves');
      await py('True', "import cad_core\n_inter_doc=App.newDocument('IntersectionProbe')\n_inter_body=_inter_doc.addObject('PartDesign::Body','Body')\n_inter_box=_inter_body.newObject('PartDesign::AdditiveBox','Box')\n_inter_box.Length=40\n_inter_box.Width=30\n_inter_box.Height=10\n_inter_doc.recompute()\n_inter_sketch=_inter_body.newObject('Sketcher::SketchObject','Sketch')\ncad_core.add_rectangle(App,_inter_sketch,20,15)\n_inter_doc.recompute()\nGui.Selection.clearSelection()\nGui.Selection.addSelection(_inter_sketch)\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      await sleep(700);
      await click('CAD_Action_press_pull');
      await next('operation'); await next('operation');
      assert.equal(await py("cad_workspace.WORKSPACE.fields['operation'].currentData()"),'intersect');
      await fill('distance','5 mm');
      await sleep(700);
      await click('CAD_Button_accept');
      assert.equal(await py("App.ActiveDocument.getObject('SketchIntersection').IntersectionStatus"),'OK');
      near(await py("App.ActiveDocument.getObject('SketchIntersection').Shape.Volume"),1500);
      await py('True', "App.ActiveDocument.getObject('SketchIntersection').Length=8\nApp.ActiveDocument.recompute()");
      near(await py("App.ActiveDocument.getObject('SketchIntersection').Shape.Volume"),2400);
      console.log('PASS Q on sketch -> parametric intersection -> edit');
      const seam=await py("[(i+1,any(e.isSeam(f) for f in _cylinder.Shape.Faces)) for i,e in enumerate(_cylinder.Shape.Edges)]", "import Part\ncad_workspace.WORKSPACE.set_hide_seams(False)\n_cylinder=App.ActiveDocument.addObject('Part::Feature','SeamProbe')\n_cylinder.Shape=Part.makeCylinder(8,20)\n_cylinder.Placement.Base=App.Vector(70,0,0)\n_cylinder.ViewObject.DisplayMode='Flat Lines'\nApp.ActiveDocument.recompute()\nGui.activeDocument().activeView().viewAxonometric()\nGui.activeDocument().activeView().fitAll()");
      console.log('SEAM_TOPOLOGY',JSON.stringify(seam));
      assert.deepEqual(seam,[[1,false],[2,true],[3,false]]);
      // Orient the periodic seam toward the camera; a seam on the back of the
      // cylinder is correctly occluded and cannot produce a pixel difference.
      const seamPoint=await py("_seam_screen", "from PySide6 import QtCore,QtWidgets\n_view=Gui.activeDocument().activeView()\n_mdi=Gui.getMainWindow().findChild(QtWidgets.QMdiArea)\n_viewer=next(w for w in _mdi.activeSubWindow().findChildren(QtWidgets.QWidget) if w.metaObject().className()=='Gui::View3DInventorViewer')\n_seam_screen=[]\nfor _angle in (0,90,180,270):\n _cylinder.Placement.Rotation=App.Rotation(App.Vector(0,0,1),_angle)\n App.ActiveDocument.recompute()\n cad_workspace.WORKSPACE.fit_view()\n _edge=_cylinder.Shape.Edges[1]\n _point=_edge.valueAt((_edge.FirstParameter+_edge.LastParameter)/2)\n _xy=_view.getPointOnScreen(_point)\n _info=_view.getObjectInfo((_xy[0],_xy[1]))\n if _info and _info.get('Object')==_cylinder.Name and _info.get('Component')=='Edge2':\n  _w,_h=_view.getSize()\n  _p=_viewer.mapToGlobal(QtCore.QPoint(round(_xy[0]*_viewer.width()/_w),round((_h-1-_xy[1])*_viewer.height()/_h)))\n  _seam_screen=[_p.x(),_p.y()]\n  break");
      assert.equal(seamPoint.length,2,'test must orient the seam toward the viewer');
      await sleep(500);
      await page.screenshot({path:path.join(output,'seam-before.png')});
      const graph=await py("_graph_paths", "from pivy import coin\n_s=coin.SoSearchAction()\n_s.setType(coin.SoIndexedLineSet.getClassTypeId())\n_s.setInterest(coin.SoSearchAction.ALL)\n_s.apply(_cylinder.ViewObject.RootNode)\n_graph_paths=[]\nfor _path in _s.getPaths():\n _parent=_path.getNode(_path.getLength()-2)\n _graph_paths.append([str(_path.getTail().getTypeId().getName()),[(str(_parent.getChild(i).getTypeId().getName()),str(_parent.getChild(i).getName())) for i in range(_parent.getNumChildren())]])");
      console.log('SEAM_SCENEGRAPH',JSON.stringify(graph));
      await py('True', 'cad_workspace.WORKSPACE.set_hide_seams(True)\ncad_workspace.WORKSPACE.seam_visibility.apply(_cylinder)');
      const seamState=await py("(lambda v:[v['seams'],len(v['original']),len(v['modified']),sum(a!=b for a,b in zip(v['original'],v['modified']))])(cad_workspace.WORKSPACE.seam_visibility.applied[(_cylinder.Document.Name,_cylinder.Name)])");
      assert.equal(seamState[0][0],1);
      assert.equal(seamState[1],seamState[2],'all edge index slots must remain');
      assert.ok(seamState[3]>0,'the seam polyline must collapse');
      assert.equal(await py('len(_cylinder.Shape.Edges)'),3,'render suppression must not change topology');
      await sleep(500);
      await page.screenshot({path:path.join(output,'seam-after.png')});
      const beforePNG=fs.readFileSync(path.join(output,'seam-before.png')).toString('base64');
      const afterPNG=fs.readFileSync(path.join(output,'seam-after.png')).toString('base64');
      const changedPixels=await page.evaluate(async ({beforePNG,afterPNG,seamPoint})=>{
        const loadImage=src=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src='data:image/png;base64,'+src;});
        const [before,after]=await Promise.all([loadImage(beforePNG),loadImage(afterPNG)]);
        const canvas=document.createElement('canvas');canvas.width=before.width;canvas.height=before.height;
        const context=canvas.getContext('2d');context.drawImage(before,0,0);const a=context.getImageData(0,0,canvas.width,canvas.height).data;
        context.drawImage(after,0,0);const b=context.getImageData(0,0,canvas.width,canvas.height).data;
        let count=0;for(let y=Math.max(0,seamPoint[1]-12);y<Math.min(canvas.height,seamPoint[1]+13);y++)for(let x=Math.max(0,seamPoint[0]-8);x<Math.min(canvas.width,seamPoint[0]+9);x++){
          const i=(y*canvas.width+x)*4;if(Math.abs(a[i]-b[i])+Math.abs(a[i+1]-b[i+1])+Math.abs(a[i+2]-b[i+2])>50)count++;
        }
        return count;
      },{beforePNG,afterPNG,seamPoint});
      assert.ok(changedPixels>=5,'seam drawing must visibly disappear around its midpoint');
      const realEdge=await py("_edge_click", "_edge_click=[]\nfor _index in (0,2):\n _edge=_cylinder.Shape.Edges[_index]\n for _n in range(4,32):\n  _pt=_edge.valueAt(_edge.FirstParameter+(_edge.LastParameter-_edge.FirstParameter)*_n/36)\n  _xy=_view.getPointOnScreen(_pt)\n  _info=_view.getObjectInfo((_xy[0],_xy[1]))\n  if _info and _info.get('Object')==_cylinder.Name and _info.get('Component')=='Edge%d' % (_index+1):\n   _p=_viewer.mapToGlobal(QtCore.QPoint(round(_xy[0]*_viewer.width()/_w),round((_h-1-_xy[1])*_viewer.height()/_h)))\n   _edge_click.append([_p.x(),_p.y(),'Edge%d' % (_index+1)])\n if _edge_click: break");
      assert.ok(realEdge.length,'a non-seam circular edge must remain pickable');
      let pickedEdge=false;
      for (const [x,y] of realEdge) {
        await page.mouse.click(x,y); await sleep(200);
        pickedEdge=await py("any(s.Object.Name=='SeamProbe' and any(n.startswith('Edge') for n in s.SubElementNames) for s in Gui.Selection.getSelectionEx())");
        if (pickedEdge) break;
      }
      assert.ok(pickedEdge,'actual circular edge click must select an edge');
      console.log('PASS seam display hidden while shape and edge slots remain intact');
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
