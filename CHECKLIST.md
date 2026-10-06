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
- [ ] **b-3** 检索 benchmark：五路消融 + 延迟规模
  - [ ] b-3.1 指标实现：recall@k、MRR、nDCG@10，纯 Python，无模型
  - [ ] b-3.2 消融五路：BM25-only / dense-only / graph-only / no-rerank / fusion+rerank
  - [ ] b-3.3 延迟规模曲线：1k / 10k / 100k atom，p50 与 p95
  - [ ] b-3.4 **BASELINE 报告**：在改动前的代码上跑，冻结提交
  - 验收：`python -m bench.run --config bench/configs/ablation.json` 出表；每格带 n 与 Wilson 95% 下界；`bench/reports/baseline_*.json` 入库
- [ ] **b-4** 外部基线
  - [ ] b-4.1 仓库内 Mem0/Zep 风格同构对照：扁平 store + user/agent/run 作用域 + 无失效
  - [ ] b-4.2 同语料同硬件跑，出对照数字
  - [ ] b-4.3 附录：真 Mem0 跑法与参考值，标明其 `add()` 依赖 LLM 的不可比因素
  - 验收：`bench/reports/baseline_external_*.json`；对照基线与 ely-eye 同标注集同指标
- [ ] **b-5** 反自证审计
  - [ ] b-5.1 单次尝试：禁 best-of-N 重摇
  - [ ] b-5.2 禁达标即停：跑满 n 才算分
  - [ ] b-5.3 每个分数旁必有 chance 基线行
  - [ ] b-5.4 producer ≠ verifier：判分器与被评对象不共享题目生成
  - 验收：`python -m bench.audit` 对故意注入的 best-of-N 用例报错退出

---

## 阶段 1 — P0：让它成为记忆

- [ ] **p0-1** 记忆模型加四维度
  - [ ] p0-1.1 `holder_id` + `origin`（self / observed / artifact / third_party）+ 写入方不可伪造
  - [ ] p0-1.2 双时间轴：`event_time` / `event_time_end` / `event_time_precision` / `event_time_source` + `valid_from` / `valid_to` + `supersedes`
  - [ ] p0-1.3 `scenario` + `visibility`（holder / visible_to / purpose / retention_until）
  - [ ] p0-1.4 `PRAGMA user_version` 迁移框架 + 旧库可重放
  - [ ] p0-1.5 视图 `v_atoms_current` 与 `v_atoms_as_of(:ts)`
  - 验收：`pytest tests/test_memory_schema.py tests/test_migrations.py` 绿；时间旅行返回历史版本
- [ ] **p0-2** 写入路径
  - [ ] p0-2.1 `remember` / `forget` / `supersede` 三写，Python 单一写者
  - [ ] p0-2.2 MCP 工具面 + HTTP `POST /api/memory{,/forget,/supersede}` + CLI 三面同源
  - [ ] p0-2.3 服务端盖 provenance：`ingested_at`、`holder_id`、`origin` 由服务端写，客户端不可传
  - [ ] p0-2.4 `forget` 级联：派生 atom、卡带成员、向量、元信念
  - 验收：`pytest tests/test_write_path.py tests/test_forget_cascade.py` 绿；端到端「记住→重启→召回」
- [ ] **p0-3** 检索改 SQL-only
  - [ ] p0-3.1 用 `db.search_fts()` 取代 `list_atoms()`，`LIMIT top_k*10`
  - [ ] p0-3.2 分词修复：CJK 分词 + camelCase/标识符切分 + 前缀
  - [ ] p0-3.3 空命中返回显式 `no_match`，不返回裸空数组
  - [ ] p0-3.4 过滤器：`since/until/source/scenario/holder/modality/trust` + 游标分页
  - [ ] p0-3.5 RRF 取代 `0.55/0.35/0.10` 加权混合
  - [ ] p0-3.6 MCP 与 HTTP 收敛到同一排序实现
  - 验收：`MATCH "钥匙"` 命中「我们的钥匙放在玄关抽屉里」；`search atoms` 命中 `func SearchAtoms`；100k atom p50 <100ms；`pytest tests/test_retrieval_parity.py` 绿
- [ ] **p0-4** 卡带变成可挂载作用域
  - [ ] p0-4.1 `mount` / `unmount` / `switch` / `append` 四动词
  - [ ] p0-4.2 检索按已挂载卡带过滤（作用域，不再是全局）
  - [ ] p0-4.3 `kv_fingerprint`：model / tokenizer / chat template / adapter hash / rope / 量化 / 引擎版本
  - [ ] p0-4.4 fingerprint 不匹配则拒绝挂载，错误信息点名差异字段
  - 验收：`pytest tests/test_cartridge_scope.py tests/test_kv_fingerprint.py` 绿
- [ ] **p0-5** holder registry + who_knows
  - [ ] p0-5.1 `holders` 表 + registry CRUD
  - [ ] p0-5.2 `who_knows` 工具：返回 holder 与置信度，非空结果
  - [ ] p0-5.3 转介：visited-set + 深度上限 + 终止态 `NO_HOLDER_KNOWS`
  - [ ] p0-5.4 默认 answer-only 转介，不外泄原文
  - 验收：`pytest tests/test_transactive.py` 绿；钥匙测试场景通过
- [ ] **p0-6** 证明套件去自证
  - [ ] p0-6.1 删 arena 答案入墨（`evals.py:1408-1409` 连接线、`evals.py:1417-1426` 白圈）
  - [ ] p0-6.2 删 best-of-N 重摇与达标即停
  - [ ] p0-6.3 删自造矛盾场景（出题者≠判分者）
  - [ ] p0-6.4 删缓存/证据图自触发式检查
  - [ ] p0-6.5 模型相关检查标 `DEFERRED`，不进 pass
  - 验收：`python -m ely_eye.proofs --report` 逐条 PASS/DEFERRED/REMOVED + 理由

---

## 阶段 2 — P1：让它成为产品

- [ ] **p1-1** 图像进 dense
  - [ ] p1-1.1 选 embedding ≤500MB，双语 + 图像；记录模型 SHA 与体积
  - [ ] p1-1.2 图像 atom 入索引；query 侧支持图像
  - [ ] p1-1.3 视觉 token 计数改 32×32 口径（1280×720 ≈ 900）
  - [ ] p1-1.4 VLM 描述：代码路径就绪，标 `DEFERRED`
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
