// SPDX-License-Identifier: LGPL-2.1-or-later
// Fusion-style palette; only allowlisted FreeCAD native commands.
(() => {
  'use strict';
  const query=new URLSearchParams(location.search);
  if(query.get('fusionMode')==='off'||query.get('designPalette')==='off'||query.get('fusionUI')==='classic') return;
  const groups=[['start','準備'],['sketch','スケッチ'],['solid','ソリッド'],['modify','修正']];
  const items=[
    ['new','新規設計','start','新規ドキュメント','+'],
    ['body','ボディ','start','Part Designボディ','▣'],
    ['sketch','スケッチ開始','start','基準平面または既存面を選択','✎'],
    ['line','線','sketch','L：直線','╱'],
    ['rectangle','長方形','sketch','R：2点長方形','▭'],
    ['circle','円','sketch','C：中心と半径','◯'],
    ['arc','円弧','sketch','円弧を描く','⌒'],
    ['dimension','寸法','sketch','D：寸法拘束','↔'],
    ['trim','トリム','sketch','T：余分な線を削る','✂'],
    ['construction','補助線','sketch','X：作図線切替','⋯'],
    ['leave_sketch','スケッチ終了','sketch','スケッチを閉じて3Dに戻る','✓'],
    ['pad','押し出し','solid','E：スケッチを選択してパッド','▰'],
    ['pad_exact','押し出し（mm）','solid','選択スケッチを入力距離で押し出し','▱'],
    ['pocket_exact','切り取り（mm）','solid','選択スケッチを入力距離で切り取り','⊟'],
    ['pocket','切り取り','solid','スケッチを選択してポケット','⊟'],
    ['revolve','回転','solid','断面を軸回転','◴'],
    ['hole','穴','solid','H：面またはスケッチを選択','⊙'],
    ['fillet','フィレット','modify','F：エッジを選択','◕'],
    ['chamfer','面取り','modify','エッジを選択','◩'],
    ['mirror','ミラー','modify','フィーチャを対称化','◧'],
    ['linear_pattern','矩形状パターン','modify','フィーチャの繰り返し','▦']
  ];
  const allow=new Set(['state','fusion_gui','grid','tree','expand_tree','collapse_tree','length','sketch_dimension',...items.map(x=>x[0])]);
  const out='/tmp/fusion-design-response.json';
  let source=null,state=null,pending=false,ready=false,seq=0,group='start';
  let root,tabs,actions,stage,message,lengthField,lengthButton,gridButton;
  let nativeHidden=false, lastGridSketch=null;
  fetch('./fusion/design-commands.py',{cache:'force-cache'})
    .then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.text();})
    .then(s=>{source=s;})
    .catch(e=>{console.warn('[fusion-design]',e);inform('モデリング機能を読み込めませんでした',true);});
  const canRun=()=>Boolean(window.__fcWorkReady&&window.__fcAppReady&&window.fcInstance?.FS&&
    window.__fcRunPyGuarded&&!window.__fcPyBusy);
  function inform(s,error=false){
    if(!message)return;
    message.textContent=s;
    message.dataset.error=error?'true':'false';
  }
  function hint(s){
    if(!s?.document)return '① 新規設計 → ② スケッチ開始（ボディ自動作成） → ③ 平面選択';
    if(s.sketchEdit)return 'スケッチ：グリッドと寸法拘束を利用できます。';
    if(s.selectionCount)return '対象を選択中：面からスケッチ、押し出し、修正を選べます。';
    return '新規スケッチを作成するか、モデルツリーで対象を選択してください。';
  }
  function enabled(c){
    if(!ready||pending||!state?.available?.[c[0]])return false;
    const [id,,section]=c;
    if(id==='new')return true;
    if(!state.document)return false;
    if(id==='sketch')return !state.sketchEdit;
    if(section==='sketch')return state.sketchEdit;
    if(section==='solid'||section==='modify')return !state.sketchEdit&&state.selectionCount>0;
    return !state.sketchEdit;
  }
  function render(){
    if(!tabs)return;
    // Qt state is polled, but tabs/buttons must keep stable DOM identity.
    // Replacing nodes every five seconds breaks browser focus, user clicks,
    // and automated selectors (stale element IDs).
    if(tabs.dataset.built!=='yes'){
      for(const [id,label] of groups){
        const button=document.createElement('button');
        button.type='button';button.textContent=label;button.dataset.group=id;
        button.addEventListener('click',()=>{group=id;render();});
        tabs.appendChild(button);
      }
      tabs.dataset.built='yes';
    }
    for(const b of tabs.querySelectorAll('button')){
      b.dataset.active=String(b.dataset.group===group);
      b.setAttribute('aria-pressed',String(b.dataset.group===group));
    }
    if(actions.dataset.group!==group){
      actions.replaceChildren();
      for(const c of items.filter(x=>x[2]===group)){
        const b=document.createElement('button');b.type='button';
        b.className='fd-action';b.dataset.action=c[0];
        b.title=c[3];
        const icon=document.createElement('span');
        icon.className='fd-icon';icon.textContent=c[4];
        const label=document.createElement('span');label.textContent=c[1];
        b.append(icon,label);
        b.addEventListener('click',()=>begin(c[0]));
        actions.appendChild(b);
      }
      actions.dataset.group=group;
    }
    for(const b of actions.querySelectorAll('button')){
      const item=items.find(x=>x[0]===b.dataset.action);
      b.disabled=!item||!enabled(item);
    }
    stage.textContent=ready?hint(state):'FreeCADの起動を確認中…';
    if(lengthField){
      lengthField.disabled=pending||!ready;
      lengthField.placeholder=state?.sketchEdit?'線分長さ（mm）':'距離（mm）';
    }
    if(lengthButton){
      lengthButton.disabled=pending||!ready;
      lengthButton.textContent=state?.sketchEdit?'寸法を拘束':'距離を適用';
    }
    if(gridButton){
      gridButton.disabled=pending||!ready||!state?.sketchEdit;
      gridButton.textContent=state?.gridShown?'グリッド：ON':'グリッド：OFF';
    }
  }
  // Body and selected-face ownership are resolved by the native Python broker,
  // so there is never an extra Body added to an existing Pad by the browser UI.
  function begin(action){
    if(action==='pad_exact'||action==='pocket_exact'){
      const value=Number(lengthField?.value);
      if(!Number.isFinite(value)||value<0.01||value>100000){
        inform('0.01〜100000 mmの距離を指定してください。',true);return;
      }
    }
    send(action);
  }
  function send(action,done){

    if(pending||!allow.has(action)||!source||!canRun()){
      if(action!=='state')inform('FreeCADの準備または操作完了を待ってください。',true);
      return;
    }
    pending=true;render();
    if(action!=='state')inform('FreeCADへコマンド送信中…');
    const id=++seq;
    try{
      const fs=window.fcInstance.FS;
      try{fs.unlink(out);}catch(_){}
      const py=source.replace('"__FUSION_DESIGN_REQUEST__"',JSON.stringify(action))
        .replace('__FUSION_DESIGN_ID__',String(id))
        .replace('__FUSION_DESIGN_VALUE__',String(['length','sketch_dimension','pad_exact','pocket_exact'].includes(action)?Number(lengthField?.value):0));
      if(py===source||py.includes('__FUSION_DESIGN_ID__')||py.includes('__FUSION_DESIGN_VALUE__')||
        py.includes('"__FUSION_DESIGN_REQUEST__"'))throw Error('コマンドテンプレートが一致しません');
      window.__fcRunPyGuarded(py);
      let tries=0;
      const timer=setInterval(()=>{
        let result;
        try{result=JSON.parse(new TextDecoder().decode(fs.readFile(out)));}catch(_){}
        if(result&&result.requestId===id){
          clearInterval(timer);pending=false;
          const previous=state?.sketchEdit;
          state=result.state||state;
          // Follow the actual sketch editor: Fusion users can draw immediately
          // after choosing a plane, then see solid tools when closing the sketch.
          if(typeof previous==='boolean'&&previous!==state?.sketchEdit)
            group=state.sketchEdit?'sketch':'solid';
          render();
          if(action!=='state'||!result.ok)inform(result.message||'実行を確認しました。',!result.ok);
          if(result.error)console.warn('[fusion-design]',result.error);
          if(action!=='state')console.info('[fusion-design]',action,result.command||'',result.message);
          if(action==='state'&&!nativeHidden&&result.ok){
            nativeHidden=true;
            document.documentElement.classList.add('fusion-integrated');
            setTimeout(()=>{if(canRun())send('fusion_gui');},350);
          }
          if(action==='state'&&state?.sketchEdit&&state?.activeSketch){
            if(lastGridSketch!==state.activeSketch){
              lastGridSketch=state.activeSketch;
              if(!state.gridShown)setTimeout(()=>{if(canRun()&&!pending)send('grid');},950);
            }
          }
          if(done)done(result);
        }else if(++tries>100){
          clearInterval(timer);pending=false;render();
          inform('FreeCADから応答がありません。操作パネルを確認してください。',true);
        }
      },300);
    }catch(e){pending=false;render();inform(String(e?.message||e),true);}
  }
  function create(){
    if(document.getElementById('fusion-design-palette'))return;
    const sheet=document.createElement('link');
    sheet.rel='stylesheet';sheet.href='./fusion/design-palette.css';
    document.head.appendChild(sheet);
    root=document.createElement('section');
    root.id='fusion-design-palette';
    root.setAttribute('aria-label','Fusion操作の統合ツールバー');
    const header=document.createElement('header');
    const brand=document.createElement('strong');brand.textContent='デザイン';
    tabs=document.createElement('nav');tabs.className='fd-tabs';
    tabs.setAttribute('aria-label','モデリング作業環境');
    const secondary=document.createElement('div');secondary.className='fd-header-tools';
    function utility(label,action){
      const button=document.createElement('button');button.type='button';
      button.textContent=label;button.addEventListener('click',()=>send(action));
      secondary.appendChild(button);return button;
    }
    utility('モデルツリー ⮜⮞','tree');
    utility('展開','expand_tree');
    utility('格納','collapse_tree');
    gridButton=utility('グリッド：OFF','grid');
    const classic=document.createElement('a');
    classic.textContent='標準GUIへ戻す';
    const classicUrl=new URL(location.href);classicUrl.searchParams.set('fusionUI','classic');
    classic.href=classicUrl.toString();
    classic.addEventListener('click',e=>{
      if(!confirm('再読み込みします。編集中のモデルは保存しましたか？'))e.preventDefault();
    });
    secondary.appendChild(classic);
    header.append(brand,tabs,secondary);
    const body=document.createElement('div');body.className='fd-body';
    actions=document.createElement('div');actions.className='fd-actions';
    const dimensions=document.createElement('div');dimensions.className='fd-dimensions';
    const label=document.createElement('label');label.textContent='数値入力 mm';
    lengthField=document.createElement('input');lengthField.type='number';lengthField.step='any';
    lengthField.min='0.01';lengthField.max='100000';lengthField.value='10';
    lengthField.setAttribute('aria-label','距離（mm）');
    label.appendChild(lengthField);
    lengthButton=document.createElement('button');lengthButton.type='button';
    lengthButton.textContent='距離を適用';
    lengthButton.addEventListener('click',()=>{
      const v=Number(lengthField.value);
      if(!Number.isFinite(v)||v<0.01||v>100000){inform('0.01〜100000 mmを入力してください。',true);return;}
      send(state?.sketchEdit?'sketch_dimension':'length');
    });
    dimensions.append(label,lengthButton);
    stage=document.createElement('div');stage.className='fd-stage';
    message=document.createElement('div');message.className='fd-message';
    message.setAttribute('role','status');
    body.append(actions,dimensions);
    root.append(header,body,stage,message);document.body.appendChild(root);
    render();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',create,{once:true});
  else create();
  const start=setInterval(()=>{
    if(!source||!canRun())return;
    clearInterval(start);ready=true;send('state');
  },500);
  setInterval(()=>{
    if(ready&&!pending&&canRun())send('state');
  },5500);
})();
