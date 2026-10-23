"""Replay saved evidence through local guards, without claiming new model accuracy."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook

from semantic_filter import Decision, MIN_KEEP_CONFIDENCE
from semantic_quality import duplicate_kind, evidence_records, keep_problem, scene_animal_ambiguity
from semantic_rules import RULE_VERSION


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(path, workbook, output_dir):
    before = {str(p.resolve()): sha256(p) for p in (path, workbook)}
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[(str(row["note"]["note_id"]), row["note"]["source_keyword"])] = row
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        sheet_rows = {sheet.title: sum(1 for row in sheet.values if any(x is not None for x in row)) - 1 for sheet in book}
    finally:
        book.close()
    details, earlier = [], []
    for (nid, query), row in latest.items():
        note = row["note"]
        fields = [(name, str(note.get(name) or "")) for name in ("title", "desc", "content")]
        fields += [(f"comment:{c.get('comment_id') or i}", str(c.get("content") or "")) for i, c in enumerate(row.get("comments") or [], 1)]
        records = evidence_records(fields)
        item = {"note_id": nid, "query": query, "old_status": row["status"], "flags": []}
        if row["status"] == "matched":
            quote = row.get("evidence_text") or ""
            for prefix in ("笔记上下文（以下标题、正文、一级评论属于同一条微博）：", "content: "):
                quote = quote.removeprefix(prefix)
            found = [r for r in records if quote.strip() and quote.strip() in r.text]
            parts = query.split(maxsplit=1)
            if len(parts) != 2:
                item["flags"].append("unknown_keyword_pair")
            else:
                # Legacy records have no target ID. This location is a diagnostic
                # candidate only; it is NOT treated as verified relational evidence.
                location = next((r for r in records if parts[1] in r.text), None)
                selected = found[0] if len(found) == 1 else None
                decision = Decision("keep", row.get("confidence"), object_type=row.get("object_type"), target_relation=row.get("target_relation"), evidence_id=selected.key if selected else None, target_evidence_id=location.key if location else None)
                problem = keep_problem(tuple(parts), decision, records, MIN_KEEP_CONFIDENCE)
                if problem:
                    item["flags"].append(problem)
                # Isolate the evidence defect from the provisional confidence gate.
                decision.confidence = 1.0
                structural = keep_problem(tuple(parts), decision, records, MIN_KEEP_CONFIDENCE)
                if structural and structural not in item["flags"]:
                    item["flags"].append(structural)
                item["located_evidence_sources"] = [r.source for r in found]
                if selected and selected.source.startswith("comment:") and row.get("source") == "note":
                    item["flags"].append("legacy_source_mismatch")
            duplicate = duplicate_kind(note, row.get("source"), row.get("evidence_text"), [x for x in earlier if x.note["source_keyword"] == query])
            if duplicate:
                kind, original = duplicate
                item["flags"].append(kind)
                item["duplicate_of"] = original
            else:
                earlier.append(SimpleNamespace(note=note, source=row.get("source"), evidence_text=row.get("evidence_text")))
            item["requires_new_model_verification"] = True
        elif row["status"] == "excluded" and row.get("object_type") == "animal" and scene_animal_ambiguity("\n".join(text for _, text in fields)):
            item["flags"].append("animal_or_installation_reassessment")
        details.append(item)
    after = {str(p.resolve()): sha256(p) for p in (path, workbook)}
    if before != after:
        raise RuntimeError("Source data changed during regression; cannot certify input preservation")
    report = {
        "mode": "offline_guard_replay_no_model_calls", "rule_version": RULE_VERSION,
        "confidence_threshold": MIN_KEEP_CONFIDENCE, "source_hashes": before,
        "sources_unchanged": before == after, "workbook_data_rows": sheet_rows,
        "old_status_counts": dict(Counter(row["status"] for row in latest.values())),
        "flag_counts": dict(Counter(flag for row in details for flag in row["flags"])),
        "details": details,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "guard_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 微博语义质量回归：2026-09-29 批次", "",
        "这是旧结论与原始证据的离线规则回放，没有调用新版 Jev；不代表新模型已纠正全部错误，也不能据此计算准确率或召回率。", "",
        f"规则：{RULE_VERSION}。检查点最新记录 {len(latest)} 条；原 Excel 工作表数据行：{sheet_rows}。",
        f"旧状态：{report['old_status_counts']}。原 Excel 和检查点的 SHA-256 在回放前后相同。", "",
        "## 发现的风险", "",
        "同一条记录可能触发多个风险，因此下列计数不能相加当作帖子数。旧版没有双证据验证记录，所有旧 matched 都需要新版模型重审；未触发本地规则不表示合格。", "",
        "|风险|条数|", "|---|---:|",
    ]
    names = {
        "evaluation_without_keyword": "旧评价证据不含评价关键词",
        "exact_text": "完全重复正文",
        "animal_or_installation_reassessment": "动物/造型景观冲突，需重审",
        "low_or_missing_confidence": "低于门槛或缺少置信度",
        "near_text": "近重复正文，需复核",
        "name_only_evidence": "证据评价的是名字",
        "target_relation_conflict": "对象与目标场所的关系冲突",
        "legacy_source_mismatch": "旧标记为正文，实际证据在评论中",
    }
    lines += [f"|{names.get(flag, flag)} ({flag})|{count}|" for flag, count in report["flag_counts"].items()]
    lines += ["", "## 可追溯样本", "", "|帖子 ID|旧状态|风险|重复原帖 ID|", "|---|---|---|---|"]
    lines += [f"|{row['note_id']}|{row['old_status']}|{', '.join(row['flags'])}|{row.get('duplicate_of', '')}|" for row in details if row["flags"]]
    lines += ["", "## 验收范围", "",
        "- 真实问题样本与正常样本存于 tests/fixtures/weibo_quality_20260929.json，共 20 条；规则测试覆盖误收拦截、动物造型漏收复核、证据原文及评论 ID、转载重复、长文完整覆盖、断点恢复和目标计数。",
        "- MockTransport 测试验证服务返回后的处理逻辑，不作为模型真实语义判断效果证明。",
        "- 0.8 是可配置的保守门槛，尚未用人工标注集校准，不能理解成 80% 的准确率。",
        "- 近重复只转人工复核；同一公园或同一雕塑的独立体验不因主题相同而删除。",
        "- 当前终端无 Jev 密钥，未执行真实服务重筛。请用 run_semantic_filter 的 --output-dir 将新结果写到独立目录，并对照样本人工验收。",
        "- 本次范围不包含账号性质、图片主体或图片下载质量。", "",
        "完整逐条结果与输入哈希见 guard_replay.json。", ""]
    destination = output_dir / "回归验收.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/weibo/semantic_checkpoint_0b1a23c8281f.jsonl"))
    parser.add_argument("--workbook", type=Path, default=Path("data/weibo/weibo_search_20260929_131142.xlsx"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/weibo/quality_regression_20260929"))
    args = parser.parse_args()
    destination, report = replay(args.checkpoint, args.workbook, args.output_dir)
    print(json.dumps({"report": str(destination), "old_status_counts": report["old_status_counts"], "flag_counts": report["flag_counts"], "sources_unchanged": report["sources_unchanged"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
