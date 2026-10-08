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
- [x] **p1-2** 音频摄入
  - [x] p1-2.1 `Modality` 加 audio；未知扩展名不再静默跳过
  - [x] p1-2.2 ASR 接入，转写 atom 带词级时间戳
  - 验收：`pytest backend/tests/test_asr.py` 绿（13 个测试）；ASR **实跑**，不是 DEFERRED
  - 实测证据（`bench/reports/ASR.md`，`.venv/bin/python -m bench.asr_check` 生成）：3 段 Video-MME 真视频
    **258.18 秒**音频（容器时长 88.93 / 109.18 / 60.07），对着第三方字幕 WER **0.242**——分母是
    **533 个参考词**（听到 563 个词），三行各自的参考词数是 201 / 296 / 36。CPU int8 4 线程跑完这 258 秒
    音频：两份已提交报告分别 3.26 秒与 3.12 秒（逐行 63.9–112.2× 与 68.4–111.2× 实时——转写秒数随
    机器负载浮动，WER 与词数不随负载动）。走产品路径摄入后从库里读回：**80 个 audio atom**、
    **563 个词级时间戳**、0 个时序倒错、0 个早于自己所属片段（总共 133 个 atom）。模型
    `Systran/faster-whisper-tiny`（78.2MB，model.bin sha256 dcb76c6586fc06cb…），远低于 500MB 上限。
  - 可复现性是量出来的：解码参数钉死 `beam_size=1, temperature=(0.0,), condition_on_previous_text=False,
    vad_filter=False, cpu_threads=4`（`temperature` 给单元素 tuple 才是真的没有回退阶梯——
    faster-whisper 1.2.1 **没有** `temperature_increment_on_fallback` 这个参数，第一版我传了它，
    直接 `TypeError`）。同一台机器连跑两遍：WER 0.242 → 0.242，转写文本逐字节相同。
  - 字幕不是逐字稿，所以这个 WER **不是任何方向的界**：字幕漏词也会掩盖模型漏词。
    报告把分母写在表里，不写「上界」这种断言。
  - review 第二轮 FAIL 的 4 条全是数字与措辞，也都改了：docstring 里的 1.7 秒是钉参数前那次运行的残留
    （现在不写数字，只指向报告；并且不再把容器时长叫「语音时长」，因为 `vad_filter=False`）；
    CHECKLIST 里的 3.55 秒 / 61.6× 与「31 段语音」同样是旧运行残留（钉死后是 38/39/3 段，加起来
    正好是库里的 80 个 atom）；报告那句「库里有 80 个 atom、0 个时序倒错」原本把只在模型输出上
    算过的不变量说成库侧的，现在 harness 对库里存的 words 重算（`out_of_order_in_store` /
    `before_their_segment_in_store`）。速度只报区间，因为转写秒数跟机器负载走。
  - 偏差与根因：
    - 验收路径 `tests/test_audio_ingest.py` 不存在，实际是 `backend/tests/test_asr.py`。
    - `Modality` 只加 `audio`，没加 `transcript`：一份转写就是带时间戳的 audio atom，
      两个成员是同一件事的两个名字。
    - faster-whisper 自带的音频加载器在 PyAV 19 上是坏的（`av.open(..., metadata_errors=)` →
      `TypeError`），而它声明 `av` 时没写版本界。所以 `asr.decode_audio()` 自己用 PyAV 解码成
      float32/16kHz 单声道再喂给 `model.transcribe()`，不降级 pin 一个没有 cp314 wheel 的旧 av。
    - PyAV 19 的异常面是量出来的不是猜的：`av.Error` 不存在（第一版会死在 except 里），
      真实基类是 `av.error.FFmpegError`；只 catch 它，我自己的 `ValueError` 消息才不会被吞。
    - 未知扩展名：显式给路径 → 抛 `UnsupportedFile`（“no reader for .xyz”）；目录扫描 →
      记进 `IngestResponse.skipped` 带原因，继续摄入能读的。以前是返回空 batch，无声无息。
    - 同一个静默毛病还有一处被 review 抓出来：`_ingest_text` 对超过 `max_text_file_bytes`（10 MiB）
      的文件也是直接返回空 batch。本仓库自己的语料里就有 277MB 的 `longmemeval_s_cleaned.json`。
      现在抛 `FileTooLarge`（带字节数和上限），扫描照样记进 `skipped`。
    - 视频现在除了帧 atom 还会产出 speech atom（同一个 mp4：18 帧 + 38 段语音，即 38 个 audio atom）。
    - 顺手把 p2-4 提前做了：`ingestion.py` 748 行超了 500 规则，拆成
      `ingestion_common.py`(102) / `ingestion_media.py`(ABC mixin, 278) / `ingestion_repository.py`(321) /
      `ingestion.py`(177)；`cli.py` 544 行也超了，按已有的 `cli_transactive.register` 模式拆出
      `cli_senses.py`(79) 和 `cli_common.py`(json_dump)，`cli.py` 现在 479 行。
    - review 第一轮 FAIL 的 11 条全部落地：钉死解码参数并跑两遍证明确定性；用容器真实时长
      而不是「最后一段的结束时间」；表里露出参考词分母、删掉「上界」断言；speech atom 数改成
      从库里读回（80，不是 bench 自己数的 66）；报告在代码提交之后重新生成，stamp 指向含代码的
      commit；`cli_senses` 里重复的 `json_dump` 删掉改用 `cli_common`；Go 的 `search_atoms` 描述补上
      `audio`（MCP 调用方原本发现不了这个过滤值）；`test_a_file_with_no_audio_track_says_so` 原本
      测的是 markdown，现在用 PyAV 写真·无音轨 mp4 命中 `asr.py` 那条分支，另加空 wav 命中
      「音轨是空的」；删掉 `_seconds` 这个空壳 wrapper。
    - 顺手改了个默认值（review 也点了）：`config.py` 的 `embedding_model_id` 从
      `Qwen/Qwen3-VL-Embedding-8B`（16GB，违反本轮 ≤500MB 的界）换成
      `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`——冻结的 bench 数字用的就是它。
    - 门禁里挖出的真根因：`bench/tests/*` 用 `from bench.x import` 而仓库根没有 conftest，
      所以裸 `pytest` 会 `ModuleNotFoundError: No module named 'bench'`（只有 `python -m pytest` 能跑）。
      `pyproject.toml` 加 `[tool.pytest.ini_options] pythonpath=["."] testpaths=[…]`，两种起法都绿。
    - 拆完顺手修掉搬过来的旧类型债：`MediaIngest._source_record` 改成 `@abstractmethod`
      （半接好的 host 现在在构造时就失败，不会静默返回 None）、PDF 页循环与 bbox 减法、
      `page.get_text` 的 union 收窄；`pyproject.toml` 里失效的 `fitz.*` mypy override 换成 `faster_whisper.*`。
    - 全仓 mypy：干净树上冷缓存实测 parent `03ca357` **26** 个错 → 本任务 **24**（净修 2 个，
      没新增；之前写的 29 是在半成品工作树上量的，不算）；改动文件 pyright **0 错**、
      ruff 干净、**212** 个测试绿（裸 `pytest` 与 `python -m pytest` 都是 212）。
  - 独立 review（`herdr` 里的 `pi`，模型 `strata/qwen3.8-flash-next-abliterated-iq3_s:high`）：
      第一轮 FAIL 11 条 → 第二轮 FAIL 4 条 → **第三轮 PASS**。reviewer 不是读我的话，而是自己
      重跑 `bench.asr_check`（新进程）、重跑门禁、逐项核对 stamp 链与 18 条 CHECKLIST 断言，
      并确认旧数字（1.7 秒 / 3.55 / 61.6 / 31 段 / 210.5 / 51×）零残留。三轮都是同一个 reviewer，
      没有换人放水。
- [x] **p1-3** adapter 加载
  - [x] p1-3.1 按卡带/场景解析 6 个 adapter，不再只有 `runtime.py:317`
  - [x] p1-3.2 加载结果可观测：日志 + `GET /api/runtime/adapters`
  - 验收：状态端点列每个 adapter 的 loaded/deferred + 原因；桩权重测试证明加载分支执行
  - `backend/src/ely_eye/adapters.py` 是唯一的 adapter 解析处。`runtime.py` 原先在 7 处调 `resolve_runtime_adapter`，现在统一走 `_generation_adapter_fields()`；生成路径上的 `peft` 只在 `adapters.load_into_model` 里懒加载（训练路径 `training.py:443`、`training.py:767`、`proofs/training_trace.py:33` 仍直接 import peft，那是训练不是生成），`RuntimeAdapter` 与 `resolve_runtime_adapter` 已删除。
  - 「场景」= 挂载的卡带：`AdapterManifest` 和 `CartridgeManifest` 都没有 scenario 字段（读出来的事实），所以解析按 `cartridge_store.mounted_ids` 选，报告写明来自哪个卡带，没有新造字段。
  - 修掉的真 bug：`CartridgeService.attach_adapter`（`cartridge.py:230`）把 adapter 拷进 `<卡带>/adapters/{kind}/`，但解析从来不看卡带目录，挂上去的东西运行时根本不加载。现在挂载卡带里的副本优先于库里的同名 adapter。
  - 测试写出来才发现的第二个 bug：`ready.sort(key=_preference)` 丢了原来的 `reverse=True`，库里的 adapter 反而赢了挂载副本。
  - 状态只由事实支撑：loaded（模型还活着——`record_load` 存 `weakref`，且记录挂在具体 `QwenRuntime._attached` 上，不是进程全局）/ available（manifest 与 `adapter_model.safetensors` 都在；模型没了就说「attached earlier in this process … that model is gone」）/ deferred（base_model 不匹配或缺权重文件，原因里写两个模型名）/ missing（磁盘上没有该 kind）。落选者单独一行 `shadowed=True`，且**只在真有赢家时**才有这行，原因点名赢家。
  - 排序键是三个：挂载卡带 > manifest 带 `cartridge_id` > 权重 mtime。第一个版本漏了中间那个，reviewer 在 /tmp 里对比 parent `9f0f799` 与本提交选中的文件，量出两者不同（可复现做法：先写一个带 `cartridge_id` 的 adapter，再写一个不带但 mtime 更新的，看 `resolve` 选哪个）——`training.py:106` 写库内 adapter 时会带卡带标记，所以这不是风格问题。
  - 验收命令：`pytest backend/tests/test_adapters.py -q` → 16 passed。`test_stub_weights_prove_the_load_branch_runs` 用桩权重断言 `attached == [(ANY, 路径)]`、`model.evalled is True`、LoadRecord 存在、端点该行 `state == "loaded"`；`test_generation_reports_the_adapter_it_attached` 走完 transformers 生成路径，断言答案里的 adapter 路径 / kind / id / sha256 与 `output_tokens`；`test_unload_stops_claiming_a_model_that_is_gone` 断言 unload 后回到 available 并说明模型已消失，同时断言另一个实例不会继承这个声明；`test_a_loaded_row_names_the_adapter_that_is_actually_attached` 与 `test_one_unload_does_not_declare_another_live_model_gone` 钉住第二轮那两条（行里的身份列必须跟加载记录一致；一个模型 unload 不能说成另一个活模型消失了）。两条都做了变异检验：把行身份改回按解析结果取 → 前者 FAILED；让 `live_attachments()` 忽略存活 → 后两个 FAILED。`test_three_live_models_are_named_as_models_not_one_model` 钉住第三轮那条单复数 bug。
  - 证明与生成解析一致：`proofs/checks_runtime.py` 的 `_generation_adapter()` 用 `discover` + `resolve`（含挂载卡带），不再用只看库的解析，否则同一份证明里 `resolved_adapter` 与 `adapter` 两块会指向不同副本还静默。
  - 新文件 `backend/src/ely_eye/runtime_schemas.py`（30 行）：`schemas.py` 已 498 行，离 500 行红线 2 行，报告类型不放进去。
  - 门禁：`pytest -q` 228 passed；ruff 干净；mypy 冷缓存查 3 个改动源文件 → 2 errors，与 `git stash` 后同一命令在 HEAD 树上的实测完全同两条（`qwen_vl_utils` 无 stubs、`model_class` 重赋值），净新增 0；pyright 同文件 → 2 errors，HEAD 也是 2 条，都是 `process_vision_info` 的双返回（`vision_process.py:532-534` 由 `return_video_kwargs` 决定返回 2 或 3 元组，产品用默认值取 2 个，运行时正确）。
  - 独立 review（同一个 `p1review` 里的 pi，模型 `strata/qwen3.8-flash-next-abliterated-iq3_s:high`）第一轮 **FAIL 6 条**，全部核实并改掉：
    1. `plan()` 用 `chosen_paths` 判落选，把「被拒绝的候选」也当成落选者，于是没有任何 adapter 胜出时却说「another adapter of this kind wins」，还把真正的 deferred 原因盖掉了（reviewer 挂载 cart-home 复现，`hme_router`、`hme_vision_lora` 两行都在撒谎）。
    2. `_LOADED` 是进程全局，而原因写「attached to the live model」——`api.py` 每个请求新建一个 `QwenRuntime`，`_model is None` 也报 loaded。改成 weakref + 实例字段。
    3. CHECKLIST 那句「peft 只在 `adapters.load_into_model` 里」在全仓范围不真（training.py 两处、training_trace.py 一处），已限定为生成路径。
    4. `LoadRecord.loaded_at` 写了没人读 → 删。
    5. `_preference` 丢了 `manifest.cartridge_id is not None` 这个次级键，换掉了原来会加载哪个 adapter（见上）。
    6. 证明检查与生成解析不一致（见上）。
    reviewer 还指出 4 条生成路径与 `status()` 零覆盖，所以「没丢函数」当时只是读出来的——现在有了走完生成路径的测试。
  - 第二轮 **FAIL 1 条**（同一 reviewer，它自己建 worktree + `PYTHONPATH` 跑 harness，并记下 editable install 指向主树、不加 `PYTHONPATH` 的 worktree 测试会假绿）：`plan()` 里 loaded 行的 `reason` 按加载记录写，而 `path`/`adapter_id`/`base_model`/`origin`/`cartridge_id` 按当前解析结果写——实测：活模型挂 X，磁盘上又写了个更新的 Y，端点就返回 `adapter_id=adapter-Y` 却解释「attached from …/x-attached」。同一个根因的第二个症状：登记按 kind 存、后写覆盖，两个 runtime 时 unload 其中一个会把另一个还活着的模型说成「that model is gone」。修法：`LoadRecord` 直接携带 `AdapterSource`，行身份从记录取（`_choice()` 只有一个身份来源）；登记改成按 attachment 列表 + 各自 weakref，`loaded` 只看是否还有活模型持有，多于一个时原因里写明另一个。
  - 第三轮 **FAIL 2 条**（都是措辞与重复字段，reviewer 用三个活 runtime 实测）：`adapters.py` 的 `plan()` 在三个以上模型同时持有时写「another live model still holds adapter-a and adapter-b」，单数主语把多个 adapter 塞给了一个模型；`LoadRecord.sha256` 仍是 `source.manifest.sha256` 的存储副本，正是这次刚清掉的「第二个真相来源」。修法：主语按数量分单复数，`sha256` 改成 property。两条都有变异检验：去掉复数分支 → 两个测试 FAILED；换回存储副本 → 生成路径测试 FAILED。reviewer 另记三条它判定不算缺陷的，这里补记：`base_model` 在「磁盘上没有该 kind」的行上从「运行时的模型 id」改成 `null`（更诚实：那一行根本没有 adapter）；同一 adapter id 可能同时出现在 loaded 行与 shadowed 行（它自已被挂着，但挂载里另有副本胜出，两行都真）；被加载的 adapter 从磁盘删掉且无解析结果时不再说「that model is gone」（`missing` 行身份为 null，没有假断言）。
  - 第四轮 **PASS**（同一个 reviewer，39 条命令、15分44秒，不读我的话只跑东西）：它自己写探针复现了三个场景（挂 X 后写更新的 Y → 行说 adapter-x；两个 runtime 一个 unload → 仍 loaded/adapter-y 且不说 gone；两个都 unload → available + gone），自己跑变异测试（行身份改回解析结果 → 3 个测试 FAILED；`live_attachments()` 忽略存活 → 2 个 FAILED；去掉复数主语 → 2 个 FAILED），并逐项核了仓库规则（无文件 >500 行、新增 `#` 注释 0 行、4 个单行 docstring、无新造 scenario 字段、无新依赖、无 v1/v2、无死代码）。它另记一条有界陈旧：`live_attachments()` 只在下次 `record_load` 时清理，所以刚被回收的模型在下一次加载前仍可能显示 loaded（docstring 写了）。它还提了一条「挂载是按连接的」——**这条我实测推翻**：`mounts` 是表，同一个 home 上换一个 `Database` 对象读 `mounted_ids` 仍返回 `['cart-a']`；那个测试断言 `mounted == []` 只是因为那个测试本身没挂任何东西。
  - CLI 面：`ely-eye adapters` 打印同一份报告。
- [x] **p1-4** 工程地基
  - [x] p1-4.1 pytest 从零到有（后端）
    - 验收写的路径是 `tests/`，实际在 `backend/tests/`（19 个文件：18 个 `test_*.py` + `conftest.py`）；`pytest -q` 全仓 **253 passed**（`922d012` 上是 239，maintenance 那 14 个测试把它推到 253）
  - [x] p1-4.2 go test 从零到有（MCP）
    - 5 个 `*_test.go`（`internal/apiclient/client_test.go` 4 个、`internal/mcpserver/write_tools_test.go` 6 个等），`go build ./... && go vet ./... && go test ./... && gofmt -l .` 全干净
  - [x] p1-4.3 CI 在 Linux runner 上跑真测试
    - `.github/workflows/ci.yml` 四个 job：backend（python 3.12 = `requires-python` 的下限，`pip install -e "./backend[dev]"` → `python -m pytest -q` → `ruff check backend/src bench`）、mcp（go 1.25 build/vet/test + gofmt）、interface（node 22 `npm ci && npm run build`）、image（`docker build` + 起容器 curl `/api/status` 与 `/`）
    - 首跑 run **37736363930**：image / interface / mcp 绿，backend 红在 `No module named pytest` —— **pytest 不是任何地方的依赖，所以「跑测试」这件事在一个新克隆上根本不可执行**。修法是把测试工具写进依赖声明：`backend/pyproject.toml` 新增 `[project.optional-dependencies] dev = ["pytest>=9.1.0", "ruff==0.16.10"]`，CI 与新人装的是同一套，ruff 也不再靠 CI 里一个裸版本号漂移
    - 为了让 CI 真能当门禁，先清了仓库既有的 lint 债：`ruff check backend/src bench` 在 HEAD 上是 **17 errors**，现在 All checks passed（14 条机械 `--fix`，加 `profiles.py` 三个探针收窄异常面：`linux_package_versions` 是 `(OSError, subprocess.SubprocessError, ValueError)`——`json.loads` 需要 `ValueError`；`runtime_launcher_probe` 与 `gpu_available` 是 `(OSError, subprocess.SubprocessError)`；并显式挡住 `json.loads` 返回 dict 的假设）
    - 第二跑 run **37738221392** 仍红：`bench/tests/test_joint.py` 四条挂在 `SystemExit: bench/models/paraphrase-multilingual-MiniLM-L12-v2: model not downloaded`。那四条断言的是「联合跑与单臂跑排序一致」「三个需要 BM25 的臂只算一次稀疏信号」——这是**harness 的等价性**，不是 embedding 的好坏，所以不该要求先下 470MB。修法是在两条路径共用的接缝注入确定性的 384 维替身模型与替身 reranker（`_TinyDense` / `_TinyReranker` / `_stub_models`），报告里的测量仍由真模型承担
    - 本地按 CI 的条件验过：把 `paraphrase-multilingual-MiniLM-L12-v2` 和 `bge-reranker-base` 两个目录移出仓库，全套 **253 passed**；移回来后门禁数字不变
    - 绿：**run 37741248855 @ 4b367cb** 与 **run 37744547992 @ 20c0416** 都是 `conclusion=success`，四个 job（backend / mcp / interface / image）全绿；之后每个 push 都跑同一套
  - [x] p1-4.4 `Dockerfile` 不再 COPY 缺失的 `PRD.md`
    - 干净克隆实测：`git clone` 之后 `ls PRD.md` → `No such file or directory`（PRD 一直没进 git），旧镜像在 `COPY README.md PRD.md ./` 那一步就建不出来
    - 改两阶段：`node:22-bookworm-slim AS ui` 跑 `npm ci && npm run build`（Ubuntu 24.04 自带的 node 18 建不了 Vite 8，`frontend/package.json` 是 `vite ^8.0.0`），运行阶段 `pip install ./backend`（不再 `-e`）+ `COPY --from=ui /ui/dist /srv/ely-eye/ui`，node/npm 从运行阶段去掉
    - 建了却没人服务也是假的：`config.py` 加 `ui_dir`（env `ELY_EYE_UI_DIR`），`api.py` 用 `StaticFiles(html=True)` 同源挂 `/`；目录被设了但不存在 → `SystemExit` 点名 `npm run build`，不静默降级。前端本来就打相对 `/api/...`，所以同源不需要改客户端
    - 实测：干净克隆 `docker build -t ely-eye:ci .` → `Successfully built 09803cd49add`（22.4GB，torch CUDA wheel）；`docker run -p 18765:8765` → `GET /api/status` 200（`available:false` + `SGLang endpoint is not reachable`，无模型服务器时应有）、`GET /` 200 text/html 带 `/assets/index-C4NuxpJV.js`（200，208733 字节）与 css 200
    - 另加 `.dockerignore`（commit `36f40c4`）：没有它从这台开发机建镜像要送 **81G** 构建上下文（`du -sh .`：`bench/runs` 60.2GB、`bench/corpus` 20.7GB、`.venv` 2.5GB），而 Dockerfile 一个字都不读
  - [x] p1-4.5 去掉 `RTX 4090` / `Ubuntu` 硬编码，改可配置
    - 根因是量出来的：这台机器 `printenv` 里 `WSL_DISTRO_NAME=Ubuntu` 已设，也就是在 WSL 内部地 shell 本来就是 Linux，`wsl.exe` 那一跳只有从 Windows 宿主才需要。旧代码无条件 `wsl.exe -d Ubuntu`，于是原生 Linux 上六个 profile 全被报成 missing，哪怕卡就在机器上
    - `profiles.py` 重写宿主判定：`uses_wsl()`（`WSL_DISTRO_NAME` 有值即假）、`host_shell()`、`host_path()`、`gpu_available()`（替掉 `wsl_gpu_available()`）、`host_python_command()`、`launch_script()`（按宿主选 `.ps1` / `.sh`）；`Settings.wsl_distro` 可配；`schemas.py:442` 字段名 `wsl_gpu` → `gpu_available`（Linux 上叫 wsl 是撒谎）
    - 设备名致命这条也拆了：`proofs/training_trace.py` 新增 `cuda_bf16_training(environment)`，判据是 `cuda_available and bf16_supported`（`training.training_environment()` 本来就记了这两个事实），不再 `"RTX 4090" in device_name`；`training.py:1271` 报错里那句 PRD 卡名删掉
    - 验收就是桩：PATH 上放一个打印 `NVIDIA GeForce RTX 5090` 的假 `nvidia-smi` → `gpu_available` 为真（顺带证明 `bash -lc` 会带 PATH）；exit 127 的桩 → 假；`cuda_bf16_training` 对 5090、4080 都为真，对 `bf16_supported=False` 的机器为假（测试自己伪造那个 flag；这台机器的卡真是 RTX 4090，而 4090 是 Ada 8.9、本身支持 BF16，所以拿卡名当判据正是这次要拆的东西）；`require_cuda_bf16` 的报错里不含 4090。`backend/tests/test_host_profiles.py` 8 个测试，含「每个 profile 在本机都有对应脚本」
  - [x] p1-4.6 补 `.sh` 脚本，与 `.ps1` 对等
    - 14 个 `.sh`：六个 launch（sglang live/extreme、vllm live/extreme、ktransformers、llamacpp，flag 与 `.ps1` 逐条对齐）+ install / install-cuda-torch / setup-linux-runtimes / serve-backend / serve-frontend / verify / download-models / run-prd-finetune；全部 `chmod +x` 且 `bash -n` 干净
    - 六个跨 WSL 的 `.ps1` 改成 `$distro = if ($env:ELY_EYE_WSL_DISTRO) { $env:ELY_EYE_WSL_DISTRO } else { "Ubuntu" }` 再 `wsl.exe -d $distro`
    - 诚实记录两处没证到的：这台机器没有 PowerShell 解析器，那六个 `.ps1` 的改动是机械替换、未经语法校验；`scripts/run-all-prd-finetunes.ps1`（100 行）还没有 `.sh` 对应
  - [x] p1-4.7 `LICENSE`
    - 选 **AGPL-3.0-only**，依据是查来的不是猜的：`pymupdf` 安装元数据写 `Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License`，而 `gh repo view --json visibility` → **PUBLIC**，分发真的发生，所以 AGPL 的 network 条款真的会咬人。PyMuPDF 是 PDF 页/区块 atom 的承重墙，只要它还在，写 MIT 就是不诚实
    - `LICENSE` 与 gnu.org 原文逐字节相同（sha256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`）；`backend/pyproject.toml` 加 `license = "AGPL-3.0-only"`，`pip wheel` 实测元数据出 `License-Expression: AGPL-3.0-only`；`frontend/package.json` 同值；README 新增 License 段写明版权人与「买 Artifex 商业授权才谈得上宽松许可」
    - 这是业务决定不是工程决定：owner 若要 MIT，得先处置 PyMuPDF（买授权或换 reader），我在 README 与这里都标出来
  - [x] p1-4.8 `backup` / `restore` / `doctor`
    - `backend/src/ely_eye/maintenance.py` + `cli_maintenance.py`（走仓库已有的 `register(app, settings)` 模式，因为 `cli.py` 已 490 行，再塞三个命令就破 500 规则）。backup 用 SQLite 自己的在线备份 API（服务在跑也能备，不是 `shutil.copy` 拷一个正在写的 WAL 库），清单记 schema 版本 / 行数 / sha256 / 体积 / 版本，行数是从**副本**读回来的
    - restore 的顺序是校验在先：sha256 对不上清单 → 拒绝；`PRAGMA integrity_check` 不是 ok → 拒绝；缺必需表 → 拒绝；schema 比本构建新 → 拒绝；被替换的库连同 `-wal`/`-shm` 留成 `.before-restore`；然后 `Database(settings).init()`，所以旧备份是「进来时被迁移」而不是要求人再跑一次
    - doctor 分两级：problems 让库停摆（integrity、打不开、挂载的卡带文件没了、ui_dir 设了但没建），warnings 只说明降级（快照缺失、视觉索引落后、dense 索引落后）
    - 真数据实测（`bench/runs/baseline`，948,822,016 字节 = 904.8 MiB / 165,973 atoms / 50,278 sources / schema 7，库文件 mtime `2026-10-08 02:33:36`）：`backup` 清单里的 sha256 `c815c6049c5bb562…` 用 `sha256sum` 独立核对一致；`restore` 到新 home 后读回 165,973 atoms / 50,278 sources / schema 7 全等；`doctor` ok=true、0 problems，并给出真降级警告：**「the store holds 21362 picture atoms but no CLIP snapshot is set (ELY_EYE_CLIP_MODEL_DIR), so they are findable only by the text already on them」**
    - 那个 sha256 是**那份快照**的指纹，不是目录的：同一状态下连备两次哈希逐字节相同（所以它是确定的），但库在提交之后又被写过，现在再备会得到 `498b0cd92c1be78d…`。秒数不写死：我这次 backup 4.0 秒 / restore 2.8 秒，reviewer 复跑 2.24 秒 / 5.65 秒，同一台机器负载不同就差这么多，只有行数和哈希是可复现的
    - doctor 第一版是假健康：它只对「路径设了但目录不在」报警，对「库里有 21,362 个图片 atom 却压根没配 CLIP」报 ok=true。现在按库里的 modality 计数判，`test_doctor_names_the_senses_a_store_holds_but_cannot_use` 钉住这条
    - 测试写出来才发现的两条：`Database.__init__` 每次构造都跑迁移，所以 doctor 永远看不到旧 schema，我原先那句 remediation「run `ely-eye status` to migrate」是编的 → 改成 catch `SystemExit` 报「the store cannot be opened by this build: …」；另一条是 fixture 假设错（`_store()` 往已有库里加，被替换的库确实有 3 个 atom），改测试不改产品
  - 验收：CI 绿；干净 clone 上 `docker build` 成功（已实测 `09803cd49add` + 容器 curl 通）；桩 `nvidia-smi` 打印 RTX 5090 证明设备名不再致命（已实测）
  - 独立 review（同一个 `p1review` 里的 pi，模型 `strata/qwen3.8-flash-next-abliterated-iq3_s:high`，三轮，不读我的话只跑东西）：第一轮 **FAIL 9 条**（全是 CHECKLIST 里的数字与断言不重现：测试文件数、套件规模、构建上下文体积、`profiles.py` 异常元组、`training.py` 行号、`cli.py` 行数、把 4090 说成不支持 BF16、备份摘要不可复现、秒数写死）→ 第二轮 **FAIL 1 条**（`_TinyDense` 那两行 docstring 是 p1-4 唯一新增的多行注释，跟 p1-6.4 的「≤1 行」相冲）→ **第三轮 PASS**。reviewer 自己跑 `gh run view`、`pytest`、`ruff`、`mypy`（冷缓存逐文件比对 `908157f` 与 HEAD → 两边都是 24 错/6 文件，逐条同消息）、`pyright`、go 全套、`bash -n` 15 个 `.sh`、`pip wheel`、`sha256sum LICENSE` 与 gnu.org 逐字节比对、拉起 22.4GB 容器 curl 三个 URL，并在真 worktree 里做变异测试（去掉 reranker 桩 → 2 failed；去掉 dense 桩 → 正好复现 CI 那 4 条；只翻 `bench/systems.py:414` 的排序键 → 正好 `fusion_rerank` 那条挂）。它还量了全仓多行 docstring 数 `114 → 114`，确认 p1-4 现在新增 0 条。三轮同一个人，没换人放水。
  - 门禁：`pytest -q` **253 passed**；`ruff check backend/src bench` All checks passed（HEAD 是 17 errors）；mypy 冷缓存查改动文件与 HEAD 同错、净新增 0；`pyright` 查 maintenance 三个文件 → **0 errors, 0 warnings**；go build/vet/test + gofmt 干净；`bash -n` 15 个 `.sh` 干净；`pip wheel ./backend` 能建且元数据带 license 表达式
- [x] **p1-5** 产品面
  - [x] p1-5.1 搜索端点接上前端
    - 验收写的是 `GET /api/search`，实际是 p0-3 就有的 `POST /api/search`：查询体带 holder / scenario / modality / image，GET 塞不下这些。前端 `search()` 调它
  - [x] p1-5.2 前端：搜索、浏览、forget、挂载卡带、时间显示、图像渲染
    - `App.tsx` 517 行拆成 131 行的壳 + `components/{MemoryPanel,CartridgePanel,SensesPanel,AdapterPanel,ProofPanel,IngestPanel,CompilerPanel,ui}.tsx` + `lib/format.ts`，每个面板自己取数，前端没有一个文件超 500 行
    - 为此新增的后端能力在 `backend/src/ely_eye/browse.py`：`GET /api/atoms`（游标翻页 + modality / holder / source 过滤，读 `v_atoms_current`）与 `GET /api/atoms/{atom_id}/image`（`FileResponse`；没图 → 404 点名那颗 atom）
    - 时间显示：`formatAgo`（just now / 5m / 2h / 3d / 1y）与 `formatStamp`（写死 UTC，`2026-10-08 09:03Z`）；每行是 `holder · origin · scenario · 时间 · trust`
    - 图像渲染：`<img class="thumb" src=/api/atoms/{id}/image>`，E2E 断言 `naturalWidth > 0`——真解码出像素，不是有个标签就算
  - [x] p1-5.3 `types.ts` 补回记忆维度
    - 验收写的 `time` 在 p0-1 已改名 `ingested_at`，另有 `event_time / valid_from / valid_to`。补的是 `source_id, ingested_at, holder_id, origin, scenario, event_time, event_time_precision, valid_from, valid_to, trust`。`relations` 没补：至今没人写 atom 的 relations（p0 记过这条），前端拿它没东西可渲染
    - 另加 `AtomPage, SearchFilters, SenseStatus, CartridgeManifest, MountState, AdapterChoice, AdapterLoadReport, Runtime*Profile*, ForgetReport`；`MemoryMap` 类型随端点一起删
  - [x] p1-5.4 未用端点：接上或删除
    - 删 8 个：`/api/benchmarks/{registry,sources,samples,predictions}`、`/api/research/modules`、`/api/index/dense`、`/api/visual-contradiction-proof`、`/api/memory-map`（前端是 memory-map 唯一的消费者，状态卡本来就带 layer 与卡带数）。底层函数一个没删——`cli.py` 与 `proofs/checks_visual.py` 在用；删的是没人调的 HTTP 壳
    - 加 2 个：`/api/atoms`、`/api/atoms/{atom_id}/image`；`/api/status` 现在带 `senses`。HTTP 面从 36 条到 **30** 条
    - 反漂移门禁：`backend/tests/test_product_api.py::test_the_http_surface_is_exactly_what_someone_uses` 把 30 条路由钉成集合，多一条少一条都红
  - [x] p1-5.5 E2E 五项
    - `scripts/ui_smoke.sh`：`mktemp -d` 起一个干净 home（`ELY_EYE_DEFAULT_HOLDER=wife`、`ELY_EYE_UI_DIR=frontend/dist`），API 自己用 `StaticFiles(html=True)` 同源挂 UI，浏览器只对一个 origin 说话，收尾删 home
    - 五项都在真浏览器里做：① 搜 `spare glasses` + scenario `home` → 那行必须同时写 `wife` 和 `home`（「谁在什么场景下知道」就是这个意思）② 按 modality 过滤 → 无字图片渲染出真像素；翻页用行的 `data-atom` 身份证明，不用行数——搜索列表和浏览列表共用 `.atom-row`，「行数变了」可以只是上面那条搜索命中在闪。断言：第一页正好 `PAGE_SIZE=12` 行（与 `MemoryPanel.tsx:10` 同值）、下一页与第一页**零重叠**、末页行数 = `total − 12`（API 报的 total）、Prev 回到原来那串 id ③ Forget → 提示 `forgotten: N atoms`，再搜同一句返回「Nothing in the store answers」④ Mount → 状态真的变了 ⑤ Adapter Matrix 每个 kind 一行，状态落在 `loaded|available|deferred|missing` 内且**必须带原因**
    - 实测：拒绝挂载的原文是 `cannot verify <cartridge_id> on this machine: model_hash, tokenizer_hash, chat_template_hash, rope are unknown; set ELY_EYE_MODEL_DIR to the model snapshot`（`cartridge.py:169-173`，p0-4 那条「没有 model_dir 就拒绝挂载」的偏差在 UI 里看得见；smoke 打印前 200 字符，所以整句都在）；`adapters: 6 kinds: missing ×6`，每条原因是「no adapter of kind X is on disk」；KPI 显示 `Runtime ready`、`Qwen/Qwen3.5-9B`、`NVIDIA GeForce RTX 4090 20901/23028 MiB`、`Cartridges 1`
    - 失败留证据：截图 `ui-failure.png` + Memory 面板文本 + 那一刻 `/api/atoms?modality=…` 返回的 JSON
    - 网络噪声分开判：`404 /api/proof-suite/latest`（没跑过证明的库就该 404，面板写 pending）和被拒的挂载 400 算预期，其余 ≥400 一律红；JS 未捕获异常一律红
  - 三条是 E2E 逼出来的真缺陷，都不是样式问题：
    - `AdapterPanel` 的指标条渲染 `load.gpu_available` 与 `load.probe_status`，而 `AdapterLoadReport`（`runtime_schemas.py:27`）只有 `model_id / mounted / adapters`——没 GPU 的机器上它会永远显示「no gpu visible」，而这台机器有 4090。删掉那两个 span 和 `types.ts` 里编出来的五个字段，只渲染服务端真给的
    - 我第一版 E2E 硬写 `modality=image`，结果 0 行：`ingestion_media.py:277` 按**文件名**判 kind（`ui_markers = ("screenshot","screen","figma","ui","wireframe","mockup")`），我那个文件叫 `ui-smoke-wordless.png` → 存成 `ui_screenshot`。改成从 `/api/atoms` 读回那颗 atom 的 modality 再选，库说是啥就是啥。顺带记一条本轮没动的产品缺陷：`"ui"` 是子串匹配，`guide.png`、`quickstart.png` 都会被叫成 UI 截图；不改是因为冻结的 bench 数字是在现规则下量的
    - playwright 1.60 在 Ubuntu 26.04 上没有 chromium 构建（`Playwright does not support chromium on ubuntu26.04-x64`），`npm i -D playwright@1.64.0` 才有；而且它的 npm 包不自动下浏览器，要 `npx playwright install chromium`
  - 顺手挖掉的产品根因：`/api/status` 与 `doctor` 各算一遍「这台机器能感知什么」，两份真相。抽成 `backend/src/ely_eye/senses.py::sense_facts()`，两边只渲染它。图片计数从 modality 改成「有没有 `image_ref`」：按 modality 数会漏掉 pdf_region 的截图裁块，也看不见字节已被删走的 atom。现在 `picture_bytes_missing` 会让 doctor 说「N picture atoms with no bytes behind them; re-ingest the source they came from」，而 CLIP 那条警告只数还能编码的
  - 验收：`bash scripts/ui_smoke.sh` → `PASS: the console searches, pages, forgets, mounts and reports adapter states`；`pytest -q` **263 passed**；`ruff check` 8 个改动文件 All checks passed；mypy 冷缓存查这 8 个文件 `Success: no issues found`，全仓仍是 **24 错 / 6 文件**（与 p1-4 记的基线相同，净新增 0）；`pyright` 这 8 个文件 **0 errors, 0 warnings**；go build/vet/test + gofmt 干净；`npm run build` + `eslint .` 干净；`scripts/mcp_write_smoke.sh` 仍 PASS
  - 独立 review（herdr 里的 pi，模型 `strata/qwen3.8-flash-next-abliterated-iq3_s:high`）。第 1 轮 FAIL 两条，都在我那条提交里：`schemas.py` 被我从 498 顶到 534 行，破了「单文件 ≤500 行」；同一提交净增 3 条多行 docstring（114→117）。修在 `6df713d`：自报家族（`CacheLayerStatus`/`MemoryStatus`/`RuntimeStatus`/三个 state 别名/`SenseStatus`/`SystemStatus`）搬进 `backend/src/ely_eye/status_schemas.py`（它只需要 `schemas.py` 的 `TrainingAdapterKind`，反向不依赖），schemas.py 回到 469；三条 docstring 各压成一行，全仓多行 docstring 回到 114，与父提交同数。
  - 第 2 轮 FAIL 三条：① **翻页其实没被测到**——E2E 等的是「行数变化」，而搜索列表与浏览列表共用 `.atom-row`，那一刻的 13 行里有一条是搜索命中；把 `nextPage()` 里的 `setCursor`+`loadBrowse` 删掉、或把翻页改成追加而不是替换，E2E 都还 PASS。改成 `data-testid="browse-list"` + 每行 `data-atom`，断言第一页正好 12 行、下一页零重叠、末页 = `total−12`、Prev 复原；两个变异现在各自红：`Next page did not swap the page: the pager is not paging` 与 `the next page repeated 12 of 12 atoms from the first page` ② CHECKLIST 写 `App.tsx`「130 行的壳」，`wc -l` 是 131 ③ CHECKLIST 引的拒绝挂载原文被 smoke 的 `.slice(0,120)` 砍掉了后半句 `; set ELY_EYE_MODEL_DIR to the model snapshot`，改成 slice 200 并照原文记。
  - 同一轮实测为真：263 passed；ruff 干净；全仓 mypy 24 错/6 文件（净新增 0）；go build/vet/test+gofmt 干净；`npm run build`+`eslint .` 干净；`ui_smoke.sh` PASS（4.0s）；`mcp_write_smoke.sh` PASS（3.2s）；30 条路由与 `HTTP_SURFACE` 一致；senses 单一真相（`api.py:52/:105` 与 `maintenance.py:238` 都只渲染 `sense_facts()`）；26 个 `types.ts` 接口对着 pydantic 模型逐个 diff 零编造字段；8 条被删路由无人引用，它们背后的函数都还从 CLI/proof 可达。pyright 在那 8 个文件：reviewer 的工作树 **0 errors**，我这棵树多两条 `runtime.py:283` 的 tuple 告警——它只在 `qwen_vl_utils` 那个无类型导入被解析时出现，HEAD 的副本同样有，不是本轮引入；两边都不是新增。
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
