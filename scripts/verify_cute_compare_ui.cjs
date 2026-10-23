const fs=require('fs'),vm=require('vm'),assert=require('assert');
const base=process.argv[2],report=JSON.parse(fs.readFileSync(base+'/results.json','utf8'));
const callbacks={},nodes=new Map(),store=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{textContent:id==='report-data'?JSON.stringify(report):'',innerHTML:'',hidden:false,addEventListener(kind,cb){callbacks[id+':'+kind]=cb},querySelector(){return node(id+':child')},click(){this.clicked=true}});return nodes.get(id)}
let clickedAnchor=null,createdBlob=null;
const legacyImage=report.posts.at(-1).images.at(-1).id;
store.set('cute-model-compare-v1-20261013',JSON.stringify({posts:{},images:{[legacyImage]:{outcome:'排除',note:'此前人工标记，保持不变'}}}));
const oldStorage=store.get('cute-model-compare-v1-20261013');
const expectedStorage=report.selection_manifest?.annotation_storage_key||'cute-model-compare-v1-20261013';
if(expectedStorage!=='cute-model-compare-v1-20261013'){
 const newNote='本批已经重新人工修改，应优先保留';
 const own=JSON.stringify({posts:{},images:{[legacyImage]:{outcome:'不排除',note:newNote}}});
 const isolated=vm.createContext({document:{getElementById:node,querySelector:node,querySelectorAll:()=>[]},localStorage:{getItem:k=>k===expectedStorage?own:store.get(k)||null,setItem(){throw new Error('No writes expected during load')}},console});
 vm.runInContext(fs.readFileSync(base+'/ui-check.js','utf8'),isolated);
 assert.equal(vm.runInContext('exportPayload()',isolated).annotations.images[legacyImage].note,newNote);
}
const context=vm.createContext({document:{getElementById:node,querySelector:node,querySelectorAll:()=>[],createElement(){return clickedAnchor={click(){this.clicked=true}}}},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},Blob:class{constructor(parts){createdBlob=parts.join('')}},URL:{createObjectURL:()=> 'blob:test',revokeObjectURL:()=>{}},setTimeout:cb=>cb(),console});
vm.runInContext(fs.readFileSync(base+'/ui-check.js','utf8'),context);
assert.equal(vm.runInContext('exportPayload()',context).annotations.images[legacyImage].note,'此前人工标记，保持不变');
assert(vm.runInContext("highlight('<可爱>&可爱')",context)==='&lt;<mark class="kw">可爱</mark>&gt;&amp;<mark class="kw">可爱</mark>');
assert.equal(vm.runInContext("categoryName({name:'狗狗草',kind:'植物景物'})",context),'狗狗草');
assert.equal(vm.runInContext("categoryName({name:'软萌猫咪',kind:'动物造型实体'})",context),'猫');
const synthetic={status:'recognized',validated:{status:'不确定',semantic_status:'明确',reason:'模型提取猫',targets:[{id:'t1',name:'猫',kind:'真实动物',ownership:'未见宠物证据',place_relation:'明确相关',evidence:'改写的引用',citation:{status:'unverified'},usable_for_matching:false}]}};
context.citationTest=synthetic;
const citationPanel=vm.runInContext("textPanel('q36',citationTest)",context);
assert(citationPanel.includes('模型主体判断'));assert(citationPanel.includes('猫'));assert(citationPanel.includes('引用待核对，暂不用于图片放行'));
synthetic.validated.targets[0].citation={status:'repaired',original:'原片段...后片段',spans:[{start:0,end:3,text:'原片段'},{start:5,end:8,text:'后片段'}]};
assert(vm.runInContext("textPanel('q36',citationTest)",context).includes('引用已修复并核实'));
assert.equal(vm.runInContext('STORE',context),expectedStorage);
if(report.selection_manifest?.jev_passed_only){
  assert(report.posts.every(p=>p.jev_pass?.choice==='keep'));
  assert(vm.runInContext('jevPanel(report.posts[0])',context).includes('Jev 已通过'));
  assert.equal(report.sample_count,100);
}
context.layerImage={status:'recognized',outcome:'待核对',decision_reason:'宠物身份不确定',image_outcome:'不排除',image_decision_reason:'图片包含猫',match:'包含',parsed:{label:'二者都不是',image_type:'实景照片',target_matches:[]}};
const layerPanel=vm.runInContext("imagePanel('q36',layerImage,'test',[])",context);
assert(layerPanel.includes('图片结论：<span class="badge ok">不排除</span>'));
synthetic.post_assessment={post_outcome:'待核对',post_decision_reason:'是否属于宠物尚不确定'};
assert(vm.runInContext("textPanel('q36',citationTest)",context).includes('帖子审核：'));
context.layerImage.image_outcome='排除';
context.layerImage.outcome='不排除';
context.layerSample={models:{q35:context.layerImage,q38:{...context.layerImage,image_outcome:'不排除'},q36:context.layerImage}};
vm.runInContext("filterMode='disagree'",context);
assert.equal(vm.runInContext('visible(layerSample)',context),true);
const image=report.posts[0].images[0],model=image.models.q35;
const value=['不排除','排除'].includes(model.outcome)?model.outcome:'排除';
callbacks['posts:input']({target:{dataset:{scope:'images',id:image.id,field:'outcome'},value}});
const saved=JSON.parse(store.get(expectedStorage));assert.equal(saved.images[image.id].outcome,value);
if(expectedStorage!=='cute-model-compare-v1-20261013')assert.equal(store.get('cute-model-compare-v1-20261013'),oldStorage,'Old report annotations must never be overwritten');
vm.runInContext("filterMode='unmarked'",context);assert.equal(vm.runInContext('visible(report.posts[0].images[0])',context),false);
const exported=vm.runInContext('exportPayload()',context);assert.equal(exported.annotations.images[image.id].outcome,value);
callbacks['export:click']();assert.equal(JSON.parse(createdBlob).annotations.images[image.id].outcome,value);assert(clickedAnchor.clicked);assert(clickedAnchor.download.endsWith('.json'));
assert.equal(vm.runInContext("Object.keys(sanitize({images:{'not-in-this-batch':{outcome:'不排除'}}}).images).length",context),0);
(async()=>{
const second=report.posts[1].images[0];
const imported={version:report.version,annotations:{posts:{},images:{[second.id]:{outcome:'不排除',match:'包含',subject:'二者都不是',type:'实景照片',note:'已人工核对'}}}};
await callbacks['import-file:change']({target:{files:[{size:500,text:async()=>JSON.stringify(imported)}],value:'selected'}});
const after=vm.runInContext('exportPayload()',context);
assert.equal(after.annotations.images[second.id].outcome,'不排除');assert.equal(after.annotations.images[image.id].outcome,value);
await callbacks['import-file:change']({target:{files:[{size:500,text:async()=>JSON.stringify({version:'other-report'})}],value:'selected'}});
assert(node('save-state').textContent.includes('导入失败'));
vm.runInContext("localStorage.setItem=()=>{throw new Error('blocked')};save()",context);assert(node('save-state').textContent.includes('请导出'));
console.log(JSON.stringify({keyword_highlight:true,category_normalization_respects_kind:true,decision_layers_displayed_separately:true,image_disagreement_filter:true,existing_annotations_restored:true,manual_edit:true,persistence:true,annotation_export:true,annotation_import_preserves_existing:true,wrong_import_rejected:true,unmarked_filter:true,storage_failure_notice:true,import_scope_validation:true,mode:'Node DOM simulation; no live browser claim'}));
})().catch(error=>{console.error(error);process.exitCode=1});
