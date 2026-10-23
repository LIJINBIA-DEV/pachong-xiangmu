const test = require('node:test');
const assert = require('node:assert/strict');
const { statistics, validateBackup, csvCell } = require('./core.js');
const items = [
  {id:'tp',modelChoice:'keep',pipelineChoice:'keep'},
  {id:'fp',modelChoice:'keep',pipelineChoice:'keep'},
  {id:'fn',modelChoice:'reject',pipelineChoice:'reject'},
  {id:'tn',modelChoice:'reject',pipelineChoice:'reject'},
  {id:'abstain',modelChoice:'review',pipelineChoice:'keep'},
  {id:'human-uncertain',modelChoice:'review',pipelineChoice:'keep'},
  {id:'unlabelled',modelChoice:'keep',pipelineChoice:'keep'},
];
const annotations = {tp:{label:'keep'},fp:{label:'reject'},fn:{label:'keep'},tn:{label:'reject'},abstain:{label:'keep'},'human-uncertain':{label:'review'}};
test('accuracy and precision use actual manual labels, exclude unlabelled and distinguish abstentions',()=>{
  const s=statistics(items,annotations);
  assert.equal(s.total,6);assert.equal(s.correct,3);assert.equal(s.accuracy,.5);
  assert.equal(s.definite,4);assert.equal(s.definiteAccuracy,.5);
  assert.equal(s.precision,.5);assert.equal(s.recall,.5);assert.equal(s.coverage,.8);
  assert.equal(s.modelUncertain,2);assert.equal(s.humanUncertain,1);
  assert.equal(s.matrix.keep.review,1);
});
test('program initial screening is evaluated separately from Jev review decisions',()=>{
  const s=statistics(items,annotations,'pipeline');
  assert.equal(s.total,6);assert.equal(s.correct,3);assert.equal(s.coverage,1);
  assert.equal(s.matrix.keep.keep,2);assert.equal(s.matrix.review.keep,1);
});
test('empty and zero-positive denominators never manufacture a percentage',()=>{
  const empty=statistics(items,{});
  assert.equal(empty.accuracy,null);assert.equal(empty.precision,null);assert.equal(empty.recall,null);
  const one=statistics([{id:'tn',modelChoice:'reject'}],{tn:{label:'reject'}});
  assert.equal(one.accuracy,1);assert.equal(one.precision,null);assert.equal(one.recall,null);
});
test('backup restoration checks dataset identity and every label before applying it',()=>{
  const dataset={datasetId:'sample',items};
  assert.deepEqual(validateBackup({datasetId:'sample',annotations:{tp:{label:'keep',note:'理由'}}},dataset),{tp:{label:'keep',note:'理由',updatedAt:''}});
  assert.throws(()=>validateBackup({datasetId:'other',annotations},dataset));
  assert.throws(()=>validateBackup({datasetId:'sample',annotations:{unknown:{label:'keep'}}},dataset));
  assert.throws(()=>validateBackup({datasetId:'sample',annotations:{tp:{label:'pass'}}},dataset));
});
test('CSV retains literal text rather than introducing spreadsheet formulas',()=>{
  assert.equal(csvCell('=1+1'), '"\'=1+1"');
  assert.equal(csvCell('a"b\nc'), '"a""b\nc"');
});
