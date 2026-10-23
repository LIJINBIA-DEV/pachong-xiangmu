(function (root) {
  'use strict';
  const labels = ['keep', 'reject', 'review'];
  function prediction(item, view) { return view === 'pipeline' ? item.pipelineChoice : item.modelChoice; }
  function statistics(items, annotations, view = 'model') {
    const matrix = Object.fromEntries(labels.map(actual => [actual, Object.fromEntries(labels.map(pred => [pred, 0]))]));
    let total = 0, correct = 0, humanDefinite = 0, definite = 0, definiteCorrect = 0;
    for (const item of items) {
      const actual = annotations[item.id]?.label, pred = prediction(item, view);
      if (!labels.includes(actual) || !labels.includes(pred)) continue;
      matrix[actual][pred]++; total++; if (actual === pred) correct++;
      if (actual !== 'review') {
        humanDefinite++;
        if (pred !== 'review') { definite++; if (actual === pred) definiteCorrect++; }
      }
    }
    const tp = matrix.keep.keep, fp = matrix.reject.keep, fn = matrix.keep.reject;
    const ratio = (n, d) => d ? n / d : null;
    return { matrix, total, correct, accuracy: ratio(correct, total), humanDefinite, definite,
      definiteCorrect, definiteAccuracy: ratio(definiteCorrect, definite), tp, fp, fn,
      precision: ratio(tp, tp + fp), recall: ratio(tp, tp + fn),
      coverage: ratio(definite, humanDefinite), humanUncertain: matrix.review.keep + matrix.review.reject + matrix.review.review,
      modelUncertain: matrix.keep.review + matrix.reject.review + matrix.review.review };
  }
  function validateBackup(value, dataset) {
    if (value?.datasetId !== dataset.datasetId) throw new Error('不是这 100 条样本的标注文件，未导入。');
    if (!value.annotations || typeof value.annotations !== 'object' || Array.isArray(value.annotations)) throw new Error('标注结构无效，未导入。');
    const validIds = new Set(dataset.items.map(item => item.id)), result = {};
    for (const [id, entry] of Object.entries(value.annotations)) {
      if (!validIds.has(id) || !entry || !labels.includes(entry.label)) throw new Error('包含未知样本或无效标签，未导入。');
      if (entry.note != null && typeof entry.note !== 'string') throw new Error('人工说明必须是文本，未导入。');
      result[id] = { label: entry.label, note: entry.note || '', updatedAt: typeof entry.updatedAt === 'string' ? entry.updatedAt : '' };
    }
    return result;
  }
  function csvCell(value) {
    let text = value == null ? '' : String(value);
    if (/^[\s]*[=+@-]/.test(text) || /^[\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  }
  const api = { labels, prediction, statistics, validateBackup, csvCell };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.JevEvalCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
