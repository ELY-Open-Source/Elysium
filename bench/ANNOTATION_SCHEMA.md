# 标注集 Schema（b-2）

评测的真相来源。所有 `bench/sets/*.jsonl` 必须满足本文件；`bench/validate_sets.py` 拒绝任何违规。

## 1. 一条标注的字段

```json
{
  "query_id": "mmlongbench:PH_2016.06.08_Economy-Final.pdf:0",
  "modality": "pdf | image | ui_screenshot | video | code | conversation",
  "question": "原文问题，逐字保留",
  "answer": "标准答案原文；不可回答时为 null",
  "answer_format": "str | int | float | list | none",
  "gold": [{ "source_id": "mmlongbench:PH_2016.06.08_Economy-Final.pdf", "region": { "page": 5 } }],
  "scope": { "holder": "owner", "session": null, "scenario": "document-qa" },
  "as_of": "2024-01-01T00:00:00+00:00",
  "unanswerable": false,
  "origin": { "dataset": "yubo2333/MMLongBench-Doc", "revision": "2ff6aa...", "item": "row:0", "license": "see dataset card" },
  "split": "dev | test"
}
```

## 2. 硬约束

1. **gold 必须来自第三方人工标注**，不得由被测系统或本仓库生成。每个来源在 `bench/corpus_sources.py` 里登记 `annotation_source`。
2. **gold 表达为「源 + 区域」，不是 atom id**。atom id 依赖切分策略，而切分策略正是 P0 要改的东西；runner 在运行时把区域解析成当时重叠的 atom id 集合。这样换切分不用重标。
3. `unanswerable=true` 的条目 `gold` 必须为空数组，且计入误召回率。目标占比 ≥15%。
4. `as_of` 是查询发生的时间点；记忆条目的 `observed_at` 晚于 `as_of` 时不得作为 gold 命中（时间正确性指标）。
5. `scope.holder` 决定可见性；跨 holder 泄漏即判错（transactive 指标）。
6. `split` 冻结：`test` 只在最终验收用，调参期间不得读取。
7. `origin.revision` 必须能在 `bench/corpus/manifest.jsonl` 中找到对应文件，否则该条目标本失效。

## 3. 区域表达

| modality | region |
|---|---|
| pdf | `{"page": int}` 或 `{"page": int, "block": int}` |
| image | `{}`（整图） |
| ui_screenshot | `{"bbox": [x0,y0,x1,y1]}` |
| video | `{"t_start": float, "t_end": float}` |
| code | `{"path": str, "symbol": str}` 或 `{"path": str, "line": int}` |
| conversation | `{"turn": int}` |

## 4. 指标映射

| 指标 | 定义 | 门槛 |
|---|---|---|
| recall@10 | gold atom 集合进入前 10 的比例（按 gold 覆盖） | ≥0.90 |
| MRR | 首个 gold 命中排名倒数均值 | 报告 |
| nDCG@10 | 二值相关 | 报告 |
| 误召回率 | unanswerable 条目里返回了 gold 之外强证据的比例 | ≤0.10 |
| 时间正确性 | 含 `as_of` 的条目里，命中项未泄漏未来证据的比例 | ≥0.95 |
| holder 正确性 | 跨 holder 查询未泄漏他人记忆的比例 | ≥0.95 |
| 编译延迟 | 从提问到 cartridge 就绪的墙钟 p50/p95 | 报告 |

分母一律是「该模态的标注条目数」，不得用命中数。

## 5. 反自欺条款

- 禁止用被测系统自己抽取的文本当 gold（例如「OCR 出来的就是答案」）。
- 禁止把 gold 文件整文件当 gold atom：gold 必须落到区域，否则整文件切分也能满分。
- 任何指标变化必须同时报告 n 与分母。
- 报告必须引用 `bench/corpus/manifest.jsonl` 的 sha256 与 `bench/sets/*.jsonl` 的 sha256。
