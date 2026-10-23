(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('dataset').textContent);
  const core = window.JevEvalCore;
  const $ = id => document.getElementById(id);
  const names = {keep:'符合要求',reject:'不符合要求',review:'信息不足'};
  const modelNames = {keep:'通过',reject:'拒绝',review:'不确定'};
  const objects = {place:'场所整体',building:'建筑或建筑组成部分',facility:'空间设施',landscape:'雕塑、装置、花坛等景观',decoration:'门头、招牌、墙绘等固定装饰',person:'人物',wild_animal:'场所自然环境中的野生动物',park_animal:'园区饲养或管理的动物',scene_animal:'公共场景偶遇的动物',pet:'个人饲养或随行宠物',animal:'场所关联未确认的动物',food:'食物或饮品',unrelated_item:'随身物品或无场景组成关系的商品',name:'名字、地名等语言名称',exhibit:'独立文物或展品',unclear:'对象不明确'};
  const relations = {target_itself:'描述关键词二本身',scene_component:'描述该场所的组成对象或场景动物',element_component:'描述具体元素的造型、图案等组成部分',unrelated:'没有允许的场所／元素组成关系',unclear:'关系不明确'};
  const reasons = {jev_screening_candidate:'作为文本初筛候选保留，仍需人工核对',low_or_missing_confidence:'置信度偏低或未保存',negative_evaluation:'评价证据含否定表达',pet_not_allowed:'明确描述个人饲养或随行宠物',semantic_reject:'模型明确拒绝',evidence_not_verified:'原文证据未通过验证',evidence_contradicted:'证据复核不支持该关系'};
  const storageKey = 'jev-human-eval:' + data.datasetId;
  let annotations = {}, current = 0, revealed = false, storageAvailable = true;
  let view = 'model';
  function warn(message) { $('warning').textContent = message; $('warning').hidden = false; }
  function notice(message) { $('notice').textContent = message; $('notice').hidden = false; }
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) annotations = core.validateBackup(JSON.parse(saved), data);
  } catch (error) {
    storageAvailable = false;
    warn('未能恢复浏览器标注：' + error.message + ' 请导入备份；当前标注仍可导出保存。');
  }
  function backupObject() {
    return {schemaVersion:1,datasetId:data.datasetId,exportedAt:new Date().toISOString(),
      manifest:data.manifest,annotations,metrics:{model:core.statistics(data.items,annotations,'model'),pipeline:core.statistics(data.items,annotations,'pipeline')}};
  }
  function persist() {
    try {
      localStorage.setItem(storageKey,JSON.stringify({datasetId:data.datasetId,annotations}));
      storageAvailable = true;
      $('save-status').textContent = '已自动保存在此浏览器';
    } catch (error) {
      storageAvailable = false;
      $('save-status').textContent = '浏览器保存失败，请导出 JSON 备份';
      warn('浏览器存储不可用。不要直接关闭页面，请先导出标注备份。');
    }
  }
  function download(text,filename,type) {
    const url = URL.createObjectURL(new Blob([text],{type}));
    const link = document.createElement('a'); link.href=url; link.download=filename;
    document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),30000);
  }
  const annotated = item => core.labels.includes(annotations[item.id]?.label);
  const wrong = item => annotated(item) && annotations[item.id].label !== core.prediction(item,view);
  function allowed(item) {
    switch ($('filter').value) {
      case 'todo': return !annotated(item);
      case 'done': return annotated(item);
      case 'wrong': return revealed && wrong(item);
      default: return true;
    }
  }
  function move(index) {
    if (index < 0 || index >= data.items.length) return;
    current = index; render();
  }
  function advanceTodo() {
    for (let step=1;step<=data.items.length;step++) {
      const next=(current+step)%data.items.length;
      if (!annotated(data.items[next])) { move(next); return; }
    }
    notice('100 条已全部标注，可以查看对比并导出备份。');
  }
  function label(choice) {
    const item = data.items[current];
    annotations[item.id]={label:choice,note:annotations[item.id]?.note || '',updatedAt:new Date().toISOString()};
    persist(); render(); if ($('auto-next').checked) advanceTodo();
  }
  function addText(parent,tag,text,className) {
    const el=document.createElement(tag); el.textContent=text; if(className) el.className=className;
    parent.append(el); return el;
  }
  function prose(parent,text,keywords) {
    parent.replaceChildren();
    const words=keywords.filter(Boolean).sort((a,b)=>b.length-a.length);
    if(!words.length){parent.textContent=text;return;}
    const pattern=new RegExp(words.map(word=>word.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|'),'gi');
    let offset=0;
    for(const match of text.matchAll(pattern)){
      parent.append(document.createTextNode(text.slice(offset,match.index)));
      const index=keywords.findIndex(word=>word.toLocaleLowerCase()===match[0].toLocaleLowerCase());
      const marked=addText(parent,'mark',match[0],index===1?'keyword-two':'keyword-one');
      marked.title='关键词'+(index+1);offset=match.index+match[0].length;
    }
    parent.append(document.createTextNode(text.slice(offset)));
  }
  function renderGrid() {
    $('sample-grid').replaceChildren();
    data.items.forEach((item,index)=>{
      if (!allowed(item)) return;
      const button=addText($('sample-grid'),'button',String(index+1));
      button.className=(annotations[item.id]?.label || '') + (index===current?' selected':'');
      button.title='第 '+(index+1)+' 条 · '+(names[annotations[item.id]?.label] || '未标注');
      button.setAttribute('aria-label',button.title); button.onclick=()=>move(index);
    });
    if(!$('sample-grid').childElementCount) addText($('sample-grid'),'p','暂无匹配样本','muted');
  }
  function metric(parent,name,ratio,numerator,denominator) {
    const box=addText(parent,'div','','metric');
    addText(box,'div',name,'name'); addText(box,'div',ratio==null?'—':(ratio*100).toFixed(1)+'%','value');
    addText(box,'div',`${numerator} / ${denominator}`,'denom');
  }
  function renderResults() {
    $('results').hidden=!revealed; if(!revealed)return;
    const s=core.statistics(data.items,annotations,view);
    $('evaluation-count').textContent=`已标注 ${s.total} / 100`;
    $('metrics').replaceChildren();
    metric($('metrics'),'三分类一致率',s.accuracy,s.correct,s.total);
    metric($('metrics'),'明确判定准确率',s.definiteAccuracy,s.definiteCorrect,s.definite);
    metric($('metrics'),'通过精确率',s.precision,s.tp,s.tp+s.fp);
    metric($('metrics'),'通过召回率',s.recall,s.tp,s.tp+s.fn);
    metric($('metrics'),'明确判定覆盖率',s.coverage,s.definite,s.humanDefinite);
    $('matrix').replaceChildren();
    const table=document.createElement('table'), head=table.createTHead(), hr=head.insertRow();
    addText(hr,'th','人工 ↓ / '+(view==='model'?'Jev':'程序')+' →');
    core.labels.forEach(k=>addText(hr,'th',modelNames[k]));
    const body=table.createTBody();
    core.labels.forEach(actual=>{
      const row=body.insertRow(); addText(row,'th',names[actual]);
      core.labels.forEach(pred=>addText(row,'td',String(s.matrix[actual][pred]),actual===pred?'diagonal':''));
    });
    $('matrix').append(table);
    $('abstentions').textContent=`人工信息不足：${s.humanUncertain} 条；${view==='model'?'Jev':'程序'}不确定：${s.modelUncertain} 条。二分类参与计算：${s.definite} 条；不确定项不混入二分类分母。`;
    $('complete-note').textContent=s.total<100?'当前仅为部分标注结果，完成全部 100 条后再作正式对比。':'100 条已完成。这是本次抽样的结果，不是全部数据或当前新版的总体精度。请导出 JSON 备份和 CSV。';
  }
  function renderModel(item) {
    const show=!$('hide-model').checked; $('model-result').hidden=!show; if(!show)return;
    $('comparison-line').replaceChildren();
    addText($('comparison-line'),'strong','Jev 原始判断：'+modelNames[item.modelChoice],'model-choice '+item.modelChoice);
    addText($('comparison-line'),'span','程序文本初筛：'+modelNames[item.pipelineChoice]);
    addText($('comparison-line'),'span','人工：'+(names[annotations[item.id]?.label] || '未标注'));
    if(annotated(item))addText($('comparison-line'),'strong',annotations[item.id].label===item.modelChoice?'一致':'不一致');
    $('model-details').replaceChildren();
    const fields=[['模型评价对象',objects[item.originalObject] || item.originalObject],['评价原文证据',item.evidence],['场所关联证据',item.targetEvidence],['保存的场所关系',relations[item.targetRelation] || item.targetRelation],['程序处理后对象',objects[item.objectType] || item.objectType],['处理后置信度',item.confidence ?? '未保存'],['程序处理原因',reasons[item.reason] || item.reason || '未保存额外处理原因'],['规则版本',item.ruleVersion]];
    fields.forEach(([name,value])=>{addText($('model-details'),'dt',name);prose(addText($('model-details'),'dd',''),String(value || '未保存'),item.keywords);});
  }
  function render() {
    const item=data.items[current], entry=annotations[item.id], done=data.items.filter(annotated).length;
    $('progress').textContent=`已标注 ${done} / 100`;
    $('progress-bar').value=done; $('remaining').textContent=`剩余 ${100-done}`;
    $('compare').disabled=done===0;
    $('compare').textContent=revealed?'收起统计对比':'查看统计对比';
    $('mode').textContent=$('hide-model').checked?'盲标 · 模型判断已隐藏':'模型判断与依据已显示';
    $('sample-position').textContent=`样本 ${String(current+1).padStart(3,'0')} / 100`;
    $('original').href=item.url; $('original').hidden=!item.url;
    $('keywords').replaceChildren();
    item.keywords.forEach((value,index)=>{const tag=addText($('keywords'),'div','','keyword '+(index===1?'keyword-two':'keyword-one'));addText(tag,'span','关键词'+(index+1));addText(tag,'strong',value);});
    $('title').textContent=item.title || '未采集独立标题';
    $('post-meta').textContent=`帖子 ${item.noteId} · ${item.nickname || '未记录账号名'} · ${item.published || '未记录发布时间'} · 全文状态：${item.fullTextStatus}`;
    prose($('body'),item.content || '未保存正文，请依据已保存评论判断；证据不足请选“信息不足”。',item.keywords);
    $('extra-fields').replaceChildren();
    (item.extraText || []).forEach(field=>{const details=document.createElement('details');addText(details,'summary',field.label);prose(addText(details,'div','','prose'),field.text,item.keywords);$('extra-fields').append(details);});
    $('comments-title').textContent=`已保存一级评论（${item.comments.length} 条）`;
    $('comments').replaceChildren(); $('comment-details').open=false;
    if(!item.comments.length) addText($('comments'),'p','本条记录没有保存评论；不要把没有保存评论当作原帖没有评论。','muted');
    item.comments.forEach(comment=>{const box=addText($('comments'),'div','','comment');addText(box,'span',comment.author || '评论人未注明','author');prose(addText(box,'div',''),comment.content,item.keywords);});
    document.querySelectorAll('[data-label]').forEach(button=>button.setAttribute('aria-pressed',String(entry?.label===button.dataset.label)));
    $('human-note').value=entry?.note || ''; $('human-note').disabled=!entry;
    $('save-status').textContent=entry?(storageAvailable?'已自动保存在此浏览器':'浏览器保存失败，请导出 JSON 备份'):'未标注 · 快捷键 1 / 2 / 3';
    $('nav-count').textContent=`${current+1} / 100`; $('prev').disabled=current===0; $('next').disabled=current===99;
    renderGrid(); renderModel(item); renderResults();
  }
  $('subtitle').textContent=`100 条真实历史记录 · ${data.manifest.ruleVersion} · 对照模型判断与原文依据进行人工标注`;
  $('methodology').textContent=`来源：本机真实 Jev 检查点；同一规则 ${data.manifest.ruleVersion}。从 ${data.manifest.eligiblePosts} 条符合条件的独立帖子中按固定种子 ${data.manifest.seed} 简单随机抽取 100 条，未按模型类别配额抽样。仅包含已保存 Jev 原始选择的记录；排除了无 Jev 判断、账号/无图硬排除及重复处理。抽样信息不足以衡量这些预筛之外的全量数据。未重跑模型。`;
  document.querySelectorAll('[data-label]').forEach(button=>button.onclick=()=>label(button.dataset.label));
  $('human-note').addEventListener('input',()=>{const entry=annotations[data.items[current].id];if(entry){entry.note=$('human-note').value;entry.updatedAt=new Date().toISOString();persist();}});
  $('clear-label').onclick=()=>{delete annotations[data.items[current].id];persist();render();};
  $('prev').onclick=()=>move(current-1); $('next').onclick=()=>move(current+1); $('next-todo').onclick=advanceTodo;
  $('filter').onchange=renderGrid;
  $('compare').onclick=()=>{revealed=!revealed; if(!revealed && $('filter').value==='wrong')$('filter').value='all';render();};
  $('hide-model').onchange=render;
  $('result-view').onchange=()=>{view=$('result-view').value;renderGrid();renderResults();};
  $('backup').onclick=()=>download(JSON.stringify(backupObject(),null,2),'jev-100-人工标注备份.json','application/json;charset=utf-8');
  $('csv').onclick=()=>{
    const header=['样本编号','帖子ID','关键词1','关键词2','人工标签','人工说明','Jev原始判断','程序文本初筛','与Jev是否一致','规则版本','原帖链接','正文'];
    const rows=data.items.map((item,index)=>[index+1,item.noteId,...item.keywords,names[annotations[item.id]?.label] || '未标注',annotations[item.id]?.note || '',modelNames[item.modelChoice],modelNames[item.pipelineChoice],annotated(item)?(annotations[item.id].label===item.modelChoice?'一致':'不一致'):'未标注',item.ruleVersion,item.url,item.content]);
    download('\ufeff'+[header,...rows].map(row=>row.map(core.csvCell).join(',')).join('\r\n'),'jev-100-人工对比.csv','text/csv;charset=utf-8');
  };
  $('import').onclick=()=>$('import-file').click();
  $('import-file').onchange=async()=>{
    const file=$('import-file').files[0];if(!file)return;
    try {const incoming=core.validateBackup(JSON.parse(await file.text()),data);annotations={...annotations,...incoming};persist();render();notice(`已合并导入 ${Object.keys(incoming).length} 条标注。`);}
    catch(error){warn(error.message || '导入失败，已有标注未变。');}
    finally{$('import-file').value='';}
  };
  document.addEventListener('keydown',event=>{
    if(event.ctrlKey||event.metaKey||event.altKey||['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return;
    if(['1','2','3'].includes(event.key)){event.preventDefault();label(core.labels[Number(event.key)-1]);}
    if(event.key==='ArrowLeft'){event.preventDefault();move(current-1);}
    if(event.key==='ArrowRight'){event.preventDefault();move(current+1);}
  });
  current=Math.max(0,data.items.findIndex(item=>!annotated(item))); render();
})();
