// SPDX-License-Identifier: LGPL-2.1-or-later
// Fusion-style palette; only allowlisted FreeCAD native commands.
(() => {
  'use strict';
  const query=new URLSearchParams(location.search);
  if(query.get('fusionMode')==='off'||query.get('designPalette')==='off') return;
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
    ['pocket','切り取り','solid','スケッチを選択してポケット','⊟'],
    ['revolve','回転','solid','断面を軸回転','◴'],
    ['hole','穴','solid','H：面またはスケッチを選択','⊙'],
    ['fillet','フィレット','modify','F：エッジを選択','◕'],
    ['chamfer','面取り','modify','エッジを選択','◩'],
    ['mirror','ミラー','modify','フィーチャを対称化','◧'],
    ['linear_pattern','矩形状パターン','modify','フィーチャの繰り返し','▦']
  ];
  const allow=new Set(['state',...items.map(x=>x[0])]);
  const out='/tmp/fusion-design-response.json';
  let source=null,state=null,pending=false,ready=false,seq=0,group='start';
  let root,tabs,actions,stage,message;
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
    if(!s?.document)return '① 新規設計 → ② スケッチ開始 → ③ 平面選択';
    if(s.sketchEdit)return 'スケッチ編集中：形状と寸法を作り、「スケッチ終了」。';
    if(s.selectionCount)return '対象を選択中：押し出し・切り取り・修正が使えます。';
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
    tabs.replaceChildren();
    for(const [id,label] of groups){
      const b=document.createElement('button');b.type='button';b.textContent=label;
      b.dataset.active=String(id===group);b.setAttribute('aria-pressed',String(id===group));
      b.addEventListener('click',()=>{group=id;render();});tabs.appendChild(b);
    }
    actions.replaceChildren();
    for(const c of items.filter(x=>x[2]===group)){
      const b=document.createElement('button');b.type='button';b.className='fd-action';
      b.title=c[3];b.disabled=!enabled(c);
      const icon=document.createElement('span');icon.className='fd-icon';icon.textContent=c[4];
      const label=document.createElement('span');label.textContent=c[1];
      b.append(icon,label);b.addEventListener('click',()=>send(c[0]));actions.appendChild(b);
    }
    stage.textContent=ready?hint(state):'FreeCADの起動を確認中…';
  }
  function send(action){
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
        .replace('__FUSION_DESIGN_ID__',String(id));
      if(py===source||py.includes('__FUSION_DESIGN_ID__')||
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
        }else if(++tries>100){
          clearInterval(timer);pending=false;render();
          inform('FreeCADから応答がありません。操作パネルを確認してください。',true);
        }
      },300);
    }catch(e){pending=false;render();inform(String(e?.message||e),true);}
  }
  function create(){
    if(document.getElementById('fusion-design-palette'))return;
    const stylesheet=document.createElement('link');stylesheet.rel='stylesheet';
    stylesheet.href='./fusion/design-palette.css';document.head.appendChild(stylesheet);
    root=document.createElement('section');root.id='fusion-design-palette';
    root.dataset.collapsed='false';root.setAttribute('aria-label','Fusion風のスケッチと3Dモデリング');
    const shell=document.createElement('div');shell.className='fd-shell';
    const head=document.createElement('header'),title=document.createElement('strong');
    title.textContent='デザイン｜Fusion操作';
    const sub=document.createElement('span');sub.className='fd-subtitle';sub.textContent='作成・修正';
    const collapse=document.createElement('button');collapse.type='button';
    collapse.className='fd-collapse';collapse.textContent='最小化';
    collapse.addEventListener('click',()=>{
      root.dataset.collapsed=String(root.dataset.collapsed!=='true');
      collapse.textContent=root.dataset.collapsed==='true'?'開く':'最小化';
    });
    head.append(title,sub,collapse);
    const body=document.createElement('div');body.className='fd-body';
    tabs=document.createElement('nav');tabs.className='fd-tabs';tabs.setAttribute('aria-label','モデリング機能');
    actions=document.createElement('div');actions.className='fd-actions';
    stage=document.createElement('div');stage.className='fd-stage';
    message=document.createElement('div');message.className='fd-message';message.setAttribute('role','status');
    body.append(tabs,actions,stage,message);shell.append(head,body);root.appendChild(shell);
    document.body.appendChild(root);render();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',create,{once:true});
  else create();
  const start=setInterval(()=>{
    if(!source||!canRun())return;
    clearInterval(start);ready=true;send('state');
  },500);
  setInterval(()=>{
    if(ready&&!pending&&canRun()&&root?.dataset.collapsed!=='true')send('state');
  },5500);
})();
