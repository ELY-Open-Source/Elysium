# CHECKLIST.md — 执行进度真相

真相来源：`Gaps.md` 的 P0→P1→P2。从上到下一条一条做，禁止跳项。
每完成一条：跑「验收」列的命令，把结果贴进 `证据:` 行，再打勾。
主 agent 独自完成。禁止 subagent、worktree、新分支、并行。
每条完成后用 `/herdr` 在右侧 split panel 起 pi review（`strata/qwen3.8-flash-next-abliterated-iq3_s` Sol High），最多 5 轮。

状态记号：`[ ]` 待办 `[~]` 进行中 `[x]` 已过审 `[D]` DEFERRED（代码就绪、未真跑，不计入 pass）

---

## 阶段 0 — 先立量尺

- [x] **b-1** 下载真实语料并冻结
  - [x] b-1.1 `yubo2333/MMLongBench-Doc`：真实长文档 PDF + 人写问题 + `evidence_page_ids` + unanswerable 标记
  - [x] b-1.2 `xiaowu0162/longmemeval-cleaned`（清单原写 `xiaowu0162/longmemeval`，该 id 不存在→401）：会话记忆 QA，含 `knowledge-update` / `temporal-reasoning` / `multi-session` 类别与 `answer_session_ids`（字段实名，非 `evidence_session_ids`）
  - [x] b-1.3 `openbmb/VisRAG-Ret-Test-{SlideVQA,InfoVQA,ChartQA,MP-DocVQA,ArxivQA,PlotQA}`：query→页面图像 qrels
  - [x] b-1.4 `OS-Copilot/ScreenSpot-v2`：真实 UI 截图 + 指令 + bbox（实测 bbox 布局为 `[x,y,w,h]`：1271/1272 在界内 vs xyxy 61/1272）
  - [x] b-1.5 `lmms-eval/Video-MME`：真实视频 + QA；清单原写「只取 short 档」，实取分片归档里全部 129 个视频（short 105 / medium 76 / long 34 题），因为 mp4 只覆盖 900 个视频中的 129 个，再砍 short 会饿死 n
  - [~] b-1.6 3 个真实 git 仓库（pyparsing / regex / tokio）已下载冻结，但 b-3 的 code 集改用 `code-search-net/code_search_net`（2.2 万条 docstring→函数，天然 ground truth，n 大两个数量级）；仓库级设置挪到 b-5
  - 验收：`bench/corpus/manifest.jsonl` 28 条，每条含 `url`、`retrieved_at`、`sha256`、`annotation_source`、`license`、`files[]`；`python -m bench.manifest_check` 退出 0（实测 0）；manifest sha256 = `8fc1ed861c891d778853d41107630869f9eb267a669c5d1038e389de80114347`
- [x] **b-2** 构建多模态查询标注集（answerable n=2928）
  - [x] b-2.1 统一 schema：`{query_id, query{modality,text}, gold[{source_id,region}], scope{holder,scenario,as_of}, answerable, answer, origin}`；用 `source_id` 而非 `gold_atom_ids`，因为 atom 是新系统的产物、source 才是第三方语料的稳定身份；region 按模态受限（page/bbox/turn/path+symbol/`{}`）
  - [x] b-2.2 gold 映射：全部来自第三方标注（qrels / evidence_page_ids / answer_session_ids+has_answer / bbox / func_path+func_name），零模型判断
  - [x] b-2.3 配比（answerable）：文档 766≥90、图像 240≥60、截图 320≥40、视频 215≥30、代码 1237≥30、记忆 150≥90；unanswerable 2380/5308 = 44.8%≥15%
  - [x] b-2.4 陷阱类别齐：知识更新 25 / 时间推理 25 / 多会话 25（LongMemEval 原生类别）+ 无答案 2380（4 种构造：cross-holder、held-out、native unanswerable、distractor）
  - 验收：`python -m bench.validate_sets`（清单原名 dataset_check/manifest_check，实作合并为一个）报 `OK: 50789 sources, 2928 answerable queries, 2380 unanswerable` 退出 0；它同时校验 gold 存在性、gold holder==query holder、`observed_at <= as_of` 时间可达性、以及每个 set 文件的 SHA256 是否仍等于冻结的 manifest（重跑两次 SHA 相同由此保证）
- [x] **b-3** 检索 benchmark：五路消融 + 延迟规模
  - [x] b-3.1 指标实现：recall@k、MRR、nDCG@10，纯 Python，无模型（`bench/metrics.py` + `bench/tests/test_metrics.py` 11 条：Wilson 90/100→0.8257、10/10→0.7225、0/10→0.0 手算对齐；nDCG@10 `1.5/1.6309297535714574`；chance 公式经测试修正为 `min(1.0, k/N)`）
  - [x] b-3.2 消融五路已跑满 5,308 条（`bench/systems.py`：`bm25_only / dense_only / graph_only / no_rerank / fusion_rerank`，融合权重照抄产品 `0.55/0.35/0.10`，`graph_only` 如实返回常量序因为产品从不填 `atom.relations`）。recall@10：bm25 0.519、dense 0.424、graph 0.001、fusion 0.565、fusion+rerank 0.453 —— **加 reranker 反而掉 0.112**，graph 等于 chance，融合比任何单信号高 0.046
  - [x] b-3.3 延迟规模曲线（`bench/run.py scale_curve`，p50/p95）；档位按语料实际取 `500 / 2_000 / 10_000 / 50_000` 个 source（清单原写 1k/10k/100k atom，语料冻结为 50,789 source，100k 档不存在）。首轮只有 50,000 一档出数：探针按 gold 是否在子集里筛，小前缀几乎不含 gold 就整档跳过 —— 已改为延迟不需要 gold（`scale_probes` + 测试），四档齐全
  - [x] b-3.4 **BASELINE 报告**：在改动前的代码上跑，冻结提交（`bench/reports/BASELINE.md` + `baseline.json`，冻结于 2916363，机器负载 1.0–1.7；P0 之后的同机同语料数字另存 `bench/reports/CURRENT.md`，同一套 `bench/run.py` 生成，标 commit + store schema 版本，`--name CURRENT` 不覆盖基线）
    - 偏差记录：BASELINE.md 里「产品路径 top-10 与快路径重合 0.0%」是 harness 的身份 bug，不是检索缺陷——gold 用 `mmlongbench:PH_2016.06.08_Economy-Final.pdf`，库里是 `PH_2016_06_08_Economy_Final_10e57152f44d1a2b`（storage.py 内容哈希），两边从不相等。修在 `bench/systems.py:_corpus_ids`（复用 `bench/ingest_baseline.py:89 source_map()`），CURRENT.md 里是修好的数。冻结文件保留原文，因为它是那一天的观测。
  - 验收：`python -m bench.run --config bench/configs/ablation.json` 出表（`--config` 已接，配置优先于默认、命令行仍可覆盖）；每格带 n 与 Wilson 95% 下界；`bench/reports/baseline_*.json` 入库
- [x] **b-4** 外部基线
  - [x] b-4.1 仓库内 Mem0/Zep 风格同构对照：扁平 store + holder 作用域 + 无失效（`bench/counterpart.py`：`split_items` 400 字切句、`(holder, sha256(text))` 去重＝Mem0、`supersede` 按 (holder, subject) 时间序关闭旧条目＝Zep；`visible(holder, as_of)` 只对 temporal store 生效）+ `bench/tests/test_counterpart.py` 11 条
  - [x] b-4.2 同语料同硬件跑，出对照数字：`bench/reports/baseline_external.json` + `BASELINE_EXTERNAL.md`（165,973 atom → 403,859 条 memory item，Zep 式 `supersede` 关闭 27,072 条；5,308 query 全量）
    - `mem0_flat [holder scope]` recall@10 **0.866**（Wilson 下界 0.855，MRR 0.629，p50 0.084 s）
    - `mem0_flat [whole corpus]` recall@10 **0.412**（p50 0.090 s）
    - `zep_temporal [holder scope]` 0.866；`zep_temporal [whole corpus]` 0.429
    - 读法：同一个 ranker、同一批 item，只把候选集从全库换成「这个 holder 的记忆」，recall@10 从 0.412 涨到 0.866（+0.454）——**收益来自 holder 边界，不是更好的排序**；Zep 式失效只在跨 holder 时有小幅正效应（conversation +0.091），在 holder 作用域内反而让 conversation 从 0.993 掉到 0.978、并把 5.8% 的不可答题变成拒答
    - 交叉校验：counterpart 的 whole-corpus 纯稠密 0.412 ≈ 产品 `dense_only` 0.424，两套 harness 互相印证
  - [x] b-4.3 附录：真 Mem0 跑法与参考值，标明其 `add()` 依赖 LLM 的不可比因素（`bench/reports/EXTERNAL_APPENDIX.md`：Mem0 论文 LOCOMO 判分表 full-context 72.90 / Mem0^g 68.44 / Mem0 66.88 / Zep 65.99 / best RAG 60.97，附 token 预算与 p50/p95 延迟；四条不可比理由，其中关键一条是论文只报 search/answer 延迟、不报 `add()` 成本，Zep 的图是异步构建的）
  - 验收：`bench/reports/baseline_external_*.json`；对照基线与 ely-eye 同标注集同指标
- [x] **b-5** 反自证审计（`bench/audit.py` + `bench/tests/test_audit.py` 9 条）
  - [x] b-5.1 单次尝试：禁 best-of-N 重摇 —— AST 规则：`while` 循环的测试或 `break` 守卫里出现分数词（pass_rate/target/recall/accuracy/score/hit_rate）即违规；函数名含 `best_of/reroll/until_pass` 即违规。已抓到产品现行违规 `backend/src/ely_eye/evals.py:2351`（Visual HashHop 达标即停）
  - [x] b-5.2 禁达标即停：跑满 n 才算分 —— 报告的 `meta.queries/answerable` 必须等于冻结集 `5308/2928`，否则必须记录 `limit_per_modality`
  - [x] b-5.3 每个分数旁必有 chance 基线行 —— 报告缺 `chance.recall_at_10` 或缺任一格的 `hit_at_10_wilson_lower` 即报错
  - [x] b-5.4 producer ≠ verifier —— `bench/metrics.py` 不得 import `ely_eye/transformers/sentence_transformers/torch/bench.systems/bench.counterpart`；每条 gold 的 `origin.dataset` 必须在 `bench/corpus/manifest.jsonl` 里且 `revision` 等于冻结 revision（实测 6 个 set 全通过）
  - 验收：`python -m bench.audit --self-test` 退出 0（注入的 best-of-N 与缺 chance 两例都被拒）；`python -m bench.audit --product` 现存 3 条违规退出 1（1 条产品重摇 + 2 份报告未落盘）
  - 遗留：b-1.6 挪过来的「仓库级代码检索设置」（pyparsing/regex/tokio 三仓库）尚未做成查询集，记在 P2

---

## 阶段 1 — P0：让它成为记忆

- [x] **p0-1** 记忆模型加四维度
  - [x] p0-1.1 `holder_id` + `origin`（self / observed / artifact / third_party）——字段与 DB CHECK 已上；「写入方不可伪造」是服务端盖章，归 p0-2.3
  - [x] p0-1.2 双时间轴：`event_time` / `event_time_end` / `event_time_precision` / `event_time_source` + `valid_from` / `valid_to` + `supersedes`（旧 `time` 列重命名为 `ingested_at`，只有一个名字）
  - [x] p0-1.3 `scenario` + `visibility`（scope=holder / visible_to / everyone + holders + purpose）+ `retention_until`（提升为真列，因为 current 视图要过滤它）
  - [x] p0-1.4 `PRAGMA user_version` 迁移框架 + 旧库可重放（`migrations.py`：v1 库原地 ALTER + RENAME COLUMN 升到 v2，行不丢；版本高于本构建则 SystemExit）
  - [x] p0-1.5 视图 `v_atoms_current` + 时间旅行查询——偏差记录：SQLite 视图不能带参数，所以 as-of 是 `db.atoms_as_of(moment, holder=None)`，谓词与视图一致但去掉 retention（retention 是保存策略，不是当时是否为真）
  - 验收：`pytest backend/tests/test_memory_schema.py` 绿（8 条，含 v1→v2 升级不丢行、时间旅行返回历史版本）；实际路径是 `backend/tests/`，不是 `tests/`
- [x] **p0-2** 写入路径
  - [x] p0-2.1 `remember` / `forget` / `supersede` 三写，Python 单一写者（`memory.py:MemoryService`；同一 holder 同一句子是更新，两个 holder 各留一条）
  - [x] p0-2.2 MCP 工具面 + HTTP `POST /api/memory{,/supersede,/forget}` + CLI 三面同源——偏差记录：Go 侧不碰 SQLite 写，三个工具经 HTTP 转给 Python 写者（`ELY_EYE_API`，默认 `http://127.0.0.1:8765`），写规则只有一份；顺带把 Go 读路径跟上 v2（`atoms.time`→`ingested_at`，读改走 `v_atoms_current`，fetch/search 现在带 holder/origin/scenario/event_time）
  - [x] p0-2.3 服务端盖 provenance：`ingested_at`、`holder_id`、`origin` 由服务端写，客户端不可传（`RememberRequest` 里根本没有这三个字段；HTTP 测试里 POST `holder_id=attacker&origin=third_party` 仍落成 `wife`/`self`）
  - [x] p0-2.4 `forget` 级联：删 atom 与 FTS 行、删证据边、清 cache_events（留一条 invalidated 轨迹）、删 dense 向量索引——偏差记录：卡带成员是**报告**而非重写，已引用 DNA 的导出卡带不该被偷偷改掉
  - 验收：`pytest backend/tests/test_memory_write.py backend/tests/test_memory_api.py backend/tests/test_memory_cli.py` 绿（21 条）；端到端跨进程 `bash scripts/mcp_write_smoke.sh` → `PASS: remember, supersede, search and forget work through MCP`（Go MCP + Python API 两个进程读写同一 SQLite，supersede 后旧记忆不再可检，forget 后 fetch 报 not found）；偏差：checklist 写的 `tests/test_write_path.py` / `tests/test_forget_cascade.py` 路径不存在，实际在 `backend/tests/`
  - 顺带修的根因：`import fitz` 把 deprecation 警告打到 **stdout**，污染所有 CLI 命令的 JSON 输出（改 `import pymupdf as fitz`）；`cli status` 原本 echo 一个 Python dict repr，改 `json_dump`
- [ ] **p0-3** 检索改 SQL-only
  - [x] p0-3.1 `retrieval.py` 不再 `list_atoms()`：一条 SQL 里 `LIMIT ? OFFSET ?`，候选窗口 `CANDIDATE_WINDOW = 10`（`db.search_atoms()` 返回 `FtsPage{rows, has_more}`）
  - [x] p0-3.2 分词修复：`text_index.py` 一处归一化，索引侧与查询侧共用（NFKC + camelCase 切分 + CJK 逐字 + 前缀 `"token"*` + CJK 串按短语匹配）——偏差记录：schema 升到 v3，`_rebuild_fts()` 重建旧 `atom_fts`；旧行存的是原文，「钥匙」在旧索引里永远匹配不上
  - [x] p0-3.3 空命中是 `SearchResult{status:"no_match"}`，HTTP 与 CLI 同形，不再是裸空数组
  - [x] p0-3.4 七个过滤器（holder/scenario/source/modality/since/until/min_trust）+ base64 游标；`since > until` 报 "search since must not be after until"，游标坏了报 "search cursor is unreadable"
  - [x] p0-3.5 RRF（`RRF_K = 60`）取代 `0.55/0.35/0.10`；顺手删掉无人调用的 `tokenize()` / `lexical_score()` / `_graph_score()`（graph 项恒为 0，因为证据边从不参与排序）
  - [x] p0-3.6 Go 的 `search_atoms` / `compile_context` 改走 `POST /api/search`，删掉 Go 侧第二套分词器（`store.SearchAtoms` / `ftsQuery` / `tokenPattern`）——两面不可能再漂开，因为只剩一个排序实现
  - [x] p0-3.7 100k atom 下 p50 <100ms：`python -m bench.scale_check` → `bench/reports/SCALE.md`。实测 **165,973 atom（bar 的 1.66 倍）、300 探针、p50 57ms / p95 138ms**，机器 load 1.76 / 32 核 / 每查询 4 线程；基线 p50 20.16s ⇒ **快 354 倍**。带 holder 作用域再测一遍（n=173）：recall@10 0.870、MRR 0.740、p50 62ms / p95 117ms。
    - 根因不是 SQL 慢，是 OR 表达式里那些「每个文档都有」的虚词：`"parsing"* OR "error"* OR "in"* OR "the"* …` 命中 127,145 行、305ms，而中文二元组短语查询 32 命中只要 1.0ms。bm25 必须给每条命中打分，延迟就跟着命中数走。
    - 修法：用索引自己当 IDF 源，按文档频率丢掉虚词（`text_index.rare_terms`，`COMMON_TERM_FRACTION = 0.05`，无手写停用词表，换语料自动换答案）。0.05 是扫出来的：n=173 上 0.20→0.893/112.9ms、**0.05→0.899/58.6ms**、0.02→0.870/27.2ms、0.01→0.844/13.4ms、0.005→0.783/6.5ms —— 召回峰值就在 0.05。
    - 计数缓存 `term_df`（schema v6）：一个词只数一次，任何 atom 写入都清空它，所以缓存不会比它所描述的库更老。冷缓存 p50 73ms / 热 63ms，1,324 个词被缓存。
  - 验收：`pytest backend/tests/test_text_index.py backend/tests/test_search_api.py` 绿（18 条，真 FTS5 表 + TestClient）：「钥匙」命中「我们的钥匙放在玄关抽屉里」、`search atoms` 命中 `func SearchAtoms(ctx context.Context)`、`forg` 命中 forgotten、全角 `Ｓｅａｒｃｈ　Ａｔｏｍｓ` 命中、游标翻页无重复、supersede 后旧记忆不再应答；MCP 一致性由 `ely-eye-mcp/internal/mcpserver/search_tools_test.go`（3 条）+ `bash scripts/mcp_write_smoke.sh` PASS 证明；偏差：checklist 写的 `tests/test_retrieval_parity.py` 不存在，实际在 `backend/tests/` 与 Go 测试里
- [x] **p0-4** 卡带变成可挂载作用域
  - [x] p0-4.1 `mount` / `unmount` / `switch` / `append` 四动词（`cartridge.py:CartridgeService`；schema v2→v3 新增 `cartridge_atoms` 成员表与 `cartridge_mounts` 挂载表，重开时自动重建——挂载是机器状态，不是数据事实）
  - [x] p0-4.2 检索按已挂载卡带过滤（`retrieval.py:search` 默认作作域 = 当前挂载集，显式 `cartridge_ids` 覆盖挂载；什么都没挂时仍是全库，空库行为与以前一致）——偏差：`forget` 同时从所有卡带成员表里掉出，否则“忘了”还能从卡带里搜到
  - [x] p0-4.3 `kv_fingerprint`（`kv_fingerprint.py`）：model / tokenizer / chat template hash、adapter hash、RoPE 块（factor / original_max_position_embeddings / mrope_interleaved / mrope_section / partial_rotary_factor）、context 长度、引擎版本、指纹格式版本；读不到的项写进 `unverifiable_fields`，不留空
  - [x] p0-4.4 fingerprint 不匹配则拒绝挂载，错误信息逐字段点名差异（`home_x was built for a different runtime; refusing to mount: rope: factor: cartridge 4.0 vs local 2.0; …`）
  - 验收：`pytest backend/tests/test_cartridge_scope.py backend/tests/test_kv_fingerprint.py` 绿（26 条：16 作用域 + 10 指纹）；端到端 `bash scripts/mcp_write_smoke.sh` → `PASS: remember, supersede, search, forget and cartridge mounting work through MCP`（挂载后 work 的记忆搜不到、上传后新写的记忆要 append 才能检索、unmount 后全库恢复、改 RoPE factor 后 `mount_cartridge` 报错含 `rope`）；偏差：checklist 写的 `tests/` 不存在，实际在 `backend/tests/`
  - 偏差记录：四动词同时有 HTTP（`/api/mounts`、`/api/cartridges/{id}/{mount,switch,unmount,append}`）、CLI（`ely-eye mount/mounts/unmount/append`）和 5 个 MCP 工具；`append` 重写 `atoms.parquet` + `sparse_index.bm25.zst` 并重算 DNA，文件先写、后写库，失败不会留半个卡带；**量化没进指纹**——量化是引擎启动参数（`profiles.py` 的 `--cache-type-k q4_0` 等），不在模型快照里，指纹只比快照真说得出的东西，否则就是拿不存在的字段做门禁
  - 跑出来的两个真缺陷：`atoms.parquet` 根本导不出记忆（pyarrow 拒绝无子字段的 struct，`metadata={}` 炸掉整表 → 六个 JSON 列改存 JSON 文本，读取端 `load_cartridge_atoms` 解码）；`materialize()` 先写成员表后写 cartridges 行，外键拒绝所有卡带
  - `api.py` 超 500 行，卡带/挂载路由拆到 `api_cartridges.py`；那个模块不能用 `from __future__ import annotations`——FastAPI 会拿模块 globals 去解 `Depends(settings_dep)`，而它只是 `register()` 的参数，结果每条路由都要 `settings` 查询参数
- [x] **p0-5** holder registry + who_knows
  - [x] p0-5.1 `holders` 表 + registry CRUD
    - 验收：`pytest backend/tests/test_transactive.py -k "registry or kind or blank or holding" -q` 通过；schema v5 在旧库上补表。
    - 事实：`migrations.py` SCHEMA_VERSION 4→5，`holders` 进 `_BASE_TABLES`（holder_id 主键、kind CHECK、knows_about_json、contact_json、created/updated）。CRUD 在 `holder_store.py`（`db.py` 已 498 行，逼近 500 上限，故另立模块）。删除保护：`holder 'x' still holds N memories; forget them before deleting the holder` → HTTP 409。
    - 偏差：方法名 `list` 在类内遮蔽内置 `list`，mypy 判 `list[Holder]` 注解非法（`Function ... is not valid as a type`）→ 改名 `list_holders()`，不是加 cast 糊过去。
  - [x] p0-5.2 `who_knows` 工具：返回 holder 与置信度，非空结果
    - 验收：`pytest backend/tests/test_transactive.py -k "directory or declared" -q`；`bash scripts/mcp_write_smoke.sh` 里 who_knows("护照") 首位是 wife 且带 contact.channel=signal。
    - 事实：目录**不按可见性过滤**（"她知道"就是答案），回答才按可见性过滤。置信度是序数的：`0.60*相对得分 + 0.25*min(1, matched/3) + 0.15*声明过这个话题`，相对 = top_score / 候选集最高 top_score（避免 BM25 魔法常数：同一 query 在 3 文档库上量级 1e-7）。每条命中附 matched / top_score / latest_time 与 basis 说明。
    - 根因修复：FTS5 的 `bm25()` 不能聚合（`MAX(-bm25())` + GROUP BY 报 `unable to use function bm25 in the requested context`），子查询/窗口形式也被拒 → 用 FTS5 自带的 `rank` 列（`-MAX(rank)`，实测与 `MAX(-bm25())` 相等，9.1786e-07）。
    - 根因修复：`fts_query("钥匙在哪里")` 生成与问句等长的短语 → 0 命中（实测 钥匙 ✓ / 钥匙在哪里 ✗）。`text_index.py` 新增 `_cjk_phrase`：整段短语 OR 每个相邻二元组短语，相邻性保留（p0-3 的反精确测试仍成立），等长不再是条件。拉丁路径未动 ⇒ 冻结的 BASELINE 数字不受影响。
  - [x] p0-5.3 转介：visited-set + 深度上限 + 终止态 `NO_HOLDER_KNOWS`
    - 验收：`pytest backend/tests/test_transactive.py -k "walks or hop or nobody" -q`。
    - 事实：`ask()` 先查 asker 可见范围（hop 0），再按 who_knows 命中依次跳转，`asked` 列表即 visited-set，不重复问同一 holder；`max_hops` 限 1..10，越界 `ValueError("ask needs max_hops between 1 and 10, got N")`；终止态 `answered` / `referred` / `no_holder_knows`（无人知道是结果，不是错误：`basis=["no holder has a memory that answers this"]`）。
    - 根因修复：`if len(asked) >= max_hops: break` 把 asker 自己算作一跳 ⇒ `max_hops=1` 谁也没问就返回 no_holder_knows → 改 `len(asked) - 1 >= max_hops`，docstring 写明「max_hops 数的是 asker 之外被问的人」。
  - [x] p0-5.4 默认 answer-only 转介，不外泄原文
    - 验收：`bash scripts/mcp_write_smoke.sh` → `PASS: remember, supersede, search, forget, cartridge mounting and the transactive referral work through MCP`（两个进程、一个 SQLite：husband 通过 MCP `ask` 得到 `status=referred`、`answered_by=wife`、`answer` 为空且整份 JSON 里搜不到妻子的原文）。
    - 事实：`include_text` 只对可读所有者（asker 本人或无主的 library 条目）显示原文；`referred` 只带 contact 渠道。
    - 根因修复：`_answered()` 里 `readable = owner in (as_holder, LIBRARY)` 是 SQL 可见性子句之外的第二份、更严的规则，与 `visible_to=[husband]` 冲突（共享记忆被错误隐藏）→ 删掉这份重复判断，SQL 的 `as_holder` 可见性子句是唯一权威。
    - 偏差：Go 侧 `limit`/`max_hops` 零值曾当真实数字发出，被 API 以 `greater_than` 拒 → 未设置的可选字段一律省略，由服务端定默认值。
  - 验收：`pytest tests/test_transactive.py` 绿；钥匙测试场景通过
- [x] **p0-6** 证明套件去自证
  - [x] p0-6.1 删 arena 答案入墨（`evals.py:1408-1409` 连接线、`evals.py:1417-1426` 白圈）
    - 偏差：入墨是唯一的可读信号——`render_visual_hash` 只画噪声、不画字，答案槽被青色线+白圈标出后，模型不需要检索也能答。所以删墨的同时把 id 印上瓦片（`proofs/arena.py:render_visual_hash` 白底黑字、每行 8 字符、字号 `tile_size//8`），否则删墨 = 删题。
  - [x] p0-6.2 删 best-of-N 重摇与达标即停
    - `collect_model_visual_proofs(evaluator, hops, token_equivalent, attempts)` 固定跑 `HASHHOP_ATTEMPTS = 8` 题；旧代码 `while len(proofs) < max_samples` 里一达标就 break（`evals.py:2365`），等于弱模型反复重摇到及格。
  - [x] p0-6.3 删自造矛盾场景（出题者≠判分者）
    - 偏差：自造场景没有删掉（删了就没得测），而是从代码搬进**数据**：`proofs/contradiction_scenarios.json`（12 场景，sha256 `5f93aba09cbfc32f…`），`corpus_path(settings.data_dir)` 优先读运维者放的第三方集，`ely-eye contradiction-corpus` 写默认集。检查项**永久 DEFERRED**，直到磁盘上不是自带的那份；reason 里写明「生产者用自家例题判分不算证据」。
  - [x] p0-6.4 删缓存/证据图自触发式检查
    - 缓存：旧检查只要 `any(layer.entries > 0)` 就算过（`evals.py:1252-1265`）。现在拿 store 里真实的一条 atom 拼一个带 nonce 的问题，编译两次，读 `cache_events` 的 miss→hit 计数；空 store 直接 failed（空上下文会让两次编译「一致」得毫无意义）。顺带修掉真实双计数：`read_semantic_cache` 与 `compiler.compile` 各记一次事件，现在读是纯读、编译恰好记一次（缓存命中带 hits 才记 hit，空缓存记 miss 并附 reason）。
    - 仓库覆盖：旧检查 `indexed_file_count > 0` + 有调用图 + 有 git 历史就算过，不碰 store。现在必须 `sources > 0 && atoms > 0`，否则 failed 并说明「仓库上下文建了但没进 store」。
    - 研究模块：旧检查断言八个模块各返回非空列表，而那些向量是 SHA256 派生的假向量——**不可能失败**。改为 `status="removed"`，artifact 记下为什么撤下、重新加回的条件。
  - [x] p0-6.5 模型相关检查标 `DEFERRED`，不进 pass
    - `ProofCheck.status` 加 `deferred`/`removed` + `reason` + `rerun`；`_deferred_without_model()` 在 `model_dir` 缺失时产出 deferred 并点名缺什么。聚合改成 `failed > deferred > passed`：只要还有没跑成的主张，整个套件就不说「通过」。每条 failed/deferred 都带 why 与可执行的 rerun 命令（`proofs/table.py` 渲染）。
  - [x] p0-6.6 顺手还清的文件尺寸债
    - `evals.py` 2427 行 → `proofs/` 包 15 个模块，最大 445 行（`checks_cartridge.py`），全部 ≤500 行；`suite.py` 218 行只剩「跑哪些检查、怎么定论」。`proofs/__main__.py` 删掉（它的 `latest_report()` 与 `PRDProofSuite.latest()` 是两份 glob 不同的重复实现），渲染移到 `proofs/table.py`，`latest-proof-suite` 成为唯一入口并在 failed 时 `exit 1`。
  - 顺带修掉两个被证明测试逼出来的真 bug：
    1. `text_index.fts_query` 把拉丁词用空格连起来 = FTS5 隐式 AND，长问题永远查不到短答案（实测「Which Ely-Eye PRD requirements prove long context memory, HashHop, and adapters?」→ 0 命中）。改成 OR + bm25 rank 排序。
    2. `profiles.windows_path_to_wsl()` 对本来就是 POSIX 的路径也拼 `/mnt/` + 空 drive，产出 `/mnt//home/...`，六个 runtime profile 的探针全部 `probe_exit_code: 1`。
  - 验收：`python -m pytest backend/tests/test_proofs.py -q` → 12 passed；`ELY_EYE_HOME=/tmp/p06home ely-eye proof-suite --cartridge-id p06_20cf30f7804d && ely-eye latest-proof-suite` → 15 行判决（5 failed / 3 passed / 6 deferred / 1 removed），每条带 why 与 rerun。
  - 验收：`python -m ely_eye.proofs --report` 逐条 PASS/DEFERRED/REMOVED + 理由

---

## 阶段 2 — P1：让它成为产品

- [x] **p1-1** 图像进 dense
  - [x] p1-1.1 选 embedding ≤500MB，双语 + 图像；记录模型 SHA 与体积
    - `Xenova/chinese-clip-vit-base-patch16` fp16 ONNX，361MB，`onnx/model_fp16.onnx` sha256 `0fad978faa89b85fda53a83a4c202116a9eb87c8f9723fb4d85e4483efbce4b2`；CPU 可跑（仓库已有 onnxruntime）；文本塔 76ms、图像塔 29ms/张（batch 8）
    - 契约是量出来的不是猜的：输入 `input_ids`/`attention_mask`/`pixel_values (N,3,224,224)`，输出 `image_embeds`/`text_embeds (N,512)`；这是融合对比图，未用的塔必须喂占位行；分词器用 `BertTokenizer`（按 CLIP 分词器加载会得到超出 vocab 的 id，Gather 直接炸）
  - [x] p1-1.2 图像 atom 入索引；query 侧支持图像
    - `backend/src/ely_eye/visual_index.py`（独立文件，retrieval.py 停在 499 行没有膨胀）；`ely-eye index-visual`；`search --image`；API `SearchRequest.image`
    - 开关规则：`clip_model_dir` 指向含 `onnx/model_fp16.onnx` 的目录才算可用，不再多一个 bool
    - 14 个测试：句子找到图、图找到图、新图一到索引即失效、缺快照点名、map/vector 不一致点名、词够多时不付 encoder、forget 之后图片不再从内存回答
  - [x] p1-1.3 视觉 token 计数改 32×32 口径（1280×720 ≈ 900）
    - `visual_token_equivalent = ⌈w/32⌉·⌈h/32⌉`；migration v7 重算存量：21,325 个图像 atom 从 5,331 → 34,618 tokens；整库 29.9M → **84.2M**，于是「100M 胶囊」在这份 50,278 文件语料上刚好装得下、再大就装不下——这才是那句 claim 的真实含义
  - [x] p1-1.4 VLM 描述：代码路径就绪，标 `DEFERRED`
    - `describe.py`；ingestion 只在 OCR 没找到字时才调用（图上已有字是免费的）；无快照 → atom metadata `deferred: no vision-language model snapshot`；模型报错 → `failed: …` 且 ingest 不死（策略在调用方，不在 describer）；`status` 显示两个视觉开关；5 个测试
- p1-1 证据（我额外加的六臂基准，不是验收项）：`bench/visual_recall.py`，ScreenSpot-v2 的 554 个图标 crop + 408 张整屏，报告 `bench/reports/VISUAL.md`
  - 图标池：picture 0.208 vs words 0.175 vs chance 0.018 —— 图片空间比瞎猜高 11.5 倍，并且在 427 个 OCR 没字的 crop 上超过了词
  - 整屏池：words 0.384 > picture 0.215 —— 整屏的身份主要是文字，OCR 词在这里赢
  - 整屏 → 图标：0.108 —— CLIP 不会在截图里定位小图标，它是整图相似模型，不是 grounding 模型
  - 单屏内：MRR 0.908（recall@10 是 1.000 但 chance 也是 1.000，所以那一行只有 MRR 有意义）
  - 本轮没测双语：ScreenSpot-v2 的指令全是英文，报告里写明了
  - 验收：无文字图像被图像查询召回有 recall 数字；`pytest tests/test_visual_tokens.py` 绿
- [ ] **p1-2** 音频摄入
  - [ ] p1-2.1 `Modality` 加 audio/transcript；未知扩展名不再静默跳过
  - [ ] p1-2.2 ASR 接入，转写 atom 带词级时间戳
  - 验收：`pytest tests/test_audio_ingest.py` 绿；ASR 跑通或明确 `DEFERRED`
- [ ] **p1-3** adapter 加载
  - [ ] p1-3.1 按卡带/场景解析 6 个 adapter，不再只有 `runtime.py:317`
  - [ ] p1-3.2 加载结果可观测：日志 + `GET /api/runtime/adapters`
  - 验收：状态端点列每个 adapter 的 loaded/deferred + 原因；桩权重测试证明加载分支执行
- [ ] **p1-4** 工程地基
  - [ ] p1-4.1 pytest 从零到有（后端）
  - [ ] p1-4.2 go test 从零到有（MCP）
  - [ ] p1-4.3 CI 在 Linux runner 上跑真测试
  - [ ] p1-4.4 `Dockerfile` 不再 COPY 缺失的 `PRD.md`
  - [ ] p1-4.5 去掉 `RTX 4090` / `Ubuntu` 硬编码，改可配置
  - [ ] p1-4.6 补 `.sh` 脚本，与 `.ps1` 对等
  - [ ] p1-4.7 `LICENSE`
  - [ ] p1-4.8 `backup` / `restore` / `doctor`
  - 验收：CI 绿；干净 clone 上 `docker build` 成功；桩 `nvidia-smi` 证明设备名不再致命
- [ ] **p1-5** 产品面
  - [ ] p1-5.1 `GET /api/search`
  - [ ] p1-5.2 前端：搜索、浏览、forget、挂载卡带、时间显示、图像渲染
  - [ ] p1-5.3 `types.ts` 补回 `time` / `source_id` / `trust` / `relations`
  - [ ] p1-5.4 12 个未用端点：接上或删除
  - 验收：E2E 测试覆盖五项；`grep` 无未接端点残留
- [ ] **p1-6** 代码卫生
  - [ ] p1-6.1 `evals.py` 2413 行拆到 ≤500 行/文件
  - [ ] p1-6.2 删 dead code 与未调用函数
  - [ ] p1-6.3 删 v1/v2/v3 废弃端口
  - [ ] p1-6.4 注释压到 ≤1 行
  - 验收：`python -m bench.filesize_check` 报无文件 >500 行；vulture/grep 证据

---

## 阶段 3 — P2：规模化、安全、分层与共享

- [ ] **p2-1** 规模
  - [ ] p2-1.1 `sqlite-vec` `vec0` 增量索引
  - [ ] p2-1.2 MRL 截断 + int8/binary 粗排 + reranker 精排（reranker ≤2GB）
  - [ ] p2-1.3 100k 实测；1M 外推表 + 假设
  - 验收：100k dense 腿 p50 <100ms 实测；新 atom 立即可查有测试
- [ ] **p2-2** 安全与隐私
  - [ ] p2-2.1 FastAPI 鉴权 + Origin 校验
  - [ ] p2-2.2 写入信任分级与隔离：未佐证不得被引用
  - [ ] p2-2.3 注入消毒：外来文本里的指令进隔离区
  - [ ] p2-2.4 擦除级联（GDPR 风格 forget）
  - 验收：无 token 写请求被拒；投毒用例在隔离区；级联测试绿
- [ ] **p2-3** 短期/长期分层
  - [ ] p2-3.1 工作记忆层
  - [ ] p2-3.2 巩固台账 + watermark，可重放不重复计数
  - [ ] p2-3.3 `importance` / `recall_count` / `last_recalled_at` / `decay` / `archived_at`
  - [ ] p2-3.4 冲突记录持久化
  - 验收：LongMemEval 风格的知识更新与时间推理两类有分数；被 supersede 的旧事实不当作现行
- [ ] **p2-4** 共享记忆
  - [ ] p2-4.1 多用户/多 agent 作用域 + ACL
  - [ ] p2-4.2 默认可见性：answer-only 转介
  - [ ] p2-4.3 能力卡：让外部 agent 能路由进 ely-eye
  - 验收：两 holder 互不可见；越权被拒；一次真实跨 holder 会话证明能力卡可用
- [ ] **p2-5** 文档单一真相
  - [ ] p2-5.1 `AGENTS.md` 重写并停止 gitignore
  - [ ] p2-5.2 `README.md` 每条宣称指向可重跑命令
  - [ ] p2-5.3 `TRAINING_ARTIFACTS.md` 未跑分数删除
  - [ ] p2-5.4 `Gaps.md` 更新为已闭合状态
  - 验收：`grep` 无未跑模型分数残留；每条数字可重跑

---

## 终验

- [ ] **final-accept** Gaps.md §6「钥匙测试」7 条场景逐条跑通
  - 验收：核对表列场景、命令、实测数字、通过与否；未通过不标绿；benchmark 报告与基线、外部基线、chance 行并排
