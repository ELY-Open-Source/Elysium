# CHECKLIST_P4.md — 阶段 4：recall@10 ≥ 0.92，并把 9B 跑起来

接续 `CHECKLIST.md`（阶段 0–3 与终验）。规则相同：从上到下一条一条做，禁止跳项；每条完成后用 `/herdr` 在右侧 split panel 起 `codex --yolo -m gpt-6.1-sol -c model_reasoning_effort=xhigh -c service_tier=fast` review，同一条最多 3 轮，PASS 才打勾。

状态记号：`[ ]` 待办 `[~]` 进行中 `[x]` 已过审

**口径（本阶段新增）**：冻结题集每题带 `split`（可答且带金标的 2,928 题里 dev 991 / test 1,937）。诊断与任何取值只在 dev 上做；验收数字报 test 与全库两行，各带 holder 内 chance。验收线由用户定为 **0.92**（原 0.90）。

**起点**（`bench/reports/VIDEO_AUDIO.md`，含语音，words-only，top_k 24）：全库 0.857。dev 上的漏召回（`top_k=240` 看金标在哪）：

| 模态 | 前 10 | 在窗口 11–240 | 不在窗口 |
| --- | --- | --- | --- |
| code | 0.960 | 0.007 | 0.033 |
| conversation | 0.965 | 0.035 | 0.000 |
| pdf | 0.917 | 0.064 | 0.019 |
| image | 0.760 | 0.107 | 0.133 |
| ui_screenshot | 0.658 | 0.090 | 0.252 |
| video | 0.643 | 0.054 | 0.304 |

不在窗口的题问的是画面：无字图标（「scan qr code」）、视频里有几个人、图里蓝色那组数据。这是看图的问题，要 VLM 把画面写成字。在窗口里排在 11 名开外的是排序问题。

- [x] **p4-1** 9B 运行时：`Qwen/Qwen3.5-9B` 快照落盘（`bench/models/Qwen3.5-9B`，记 commit 与各分片 sha256），vLLM 环境（`.venv-linux-vllm`，`scripts/setup-linux-runtimes.sh` 的那条），OpenAI 兼容服务能答文字与图片各一题；记显存占用与首字时间。
  - 快照：`hf download Qwen/Qwen3.5-9B --local-dir bench/models/Qwen3.5-9B`，revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`，19,329,398,400 字节；四个分片的 sha256 与 HF LFS oid 逐个相同（`db6f444b…` `31c7d7e2…` `7ec36ba3…` `b62b0c4c…`）。
  - 环境：`.venv-linux-vllm`（uv，Python 3.12）里 vLLM 0.32.0、torch 2.13.0+cu130，`torch.cuda.is_available()` True；GPU RTX 4090 23,028 MiB，驱动 617.14。
  - 起服务：`ELYSIUM_MODEL_DIR=bench/models/Qwen3.5-9B bash scripts/launch-vllm-live.sh`，75 s 就绪，显存 20,865 MiB。三处实测才定下的参数：bf16 权重吃满显存、KV 只剩 0.07 GiB，起不来（那次的日志被下一次启动覆盖，没有留档；数字取自当时终端输出），所以 `--quantization fp8`（KV 6.46 GiB = 172,894 token，`--max-model-len 16384` 时并发 10.55×）；FlashInfer 采样器首个请求要 nvcc 现编、本机没有 CUDA toolkit，所以 `VLLM_USE_FLASHINFER_SAMPLER=0`；Qwen3.5 默认先想后答，产品读 `content` 会把思考过程当回答，所以 `--reasoning-parser qwen3` 把它分到 vLLM 0.32.0 回包里的 `reasoning` 字段，`content` 只留答案。原脚本写的 262,144 上下文在这张卡上放不下（KV 只装得下 172,894 token），`.sh` / `.ps1` / `profiles.py` 的 `vllm-live` 三处一起改成实测能起的这一组。`config.live_context_tokens` 仍是 262,144，它只进 KV 指纹与状态展示，本条不动。
  - 应答（产品路径 `QwenRuntime.generate_prompt`，`ELYSIUM_RUNTIME_BACKEND=sglang`，`ELYSIUM_SGLANG_BASE_URL=http://127.0.0.1:8001/v1`）：文字题答「The capital of France is Paris.」；ScreenSpot 截图 `pc_155db9b3…png` 输入 2,492 token，描述出 Preferences 窗口、Python Scientific 选中、「Show plots in tool window」勾选。
  - 评审（codex）：第 3 轮 PASS（`602cda0`）。第 1 轮 FAIL，D1–D3：D1 产品路径的图片请求开着思考，512 token 全花在思考上，`finish_reason` 为 `length`、`content` 为 null，产品却把 `text=None` 当成功返回。修法：两条走服务的生成路径并成一个 `QwenRuntime._chat`，请求带 `chat_template_kwargs: {enable_thinking: false}`（答案依据是编译好的上下文，直接要答案），拿不到答案就抛 `RuntimeUnavailableError` 并点名 `finish_reason` 与预算；`backend/tests/test_runtime_http.py` 2 条，去掉修复 2 条都红。修后同一张截图实测 2,494 → 111 token、2.32 s 出答案。D2 dev/test 题数原写 1,000 / 1,928，可计分的 2,928 题实为 991 / 1,937，已改。第 2 轮 D4：我先把错数归因于「按未标不可答计数」，不成立——那次按模态的计数输出本来就是 dev 427+265+111+75+57+56 = 991、test 810+501+209+165+93+159 = 1,937，两种筛法（带金标 / 未标不可答）筛出同一批题；1,000 / 1,928 是我写计划时没把这两列加起来、凭印象写的整数。D3 思考字段名原写 `reasoning_content`，实为 `reasoning`，已改。
  - 首字时间（流式，关思考）：文字 0.432 s，同题第二次 0.046 s；图片 0.565 s，第二次 0.076 s——第二次快是 vLLM 前缀缓存，不是卡带；开思考的文字题首个答案 token 在 3.464 s（之前 208 段思考）。这些数随负载动，是单次实测，引用时当量级看。
- [x] **p4-2** 看图写字：`describe.py` 走已起的服务（不在产品进程里加载 9B），图片、截图、视频帧的描述成为 atom 文字；在冻结库副本上补描述，dev 量各模态，test 与全库出报告。
  - 产品：`VisionDescriber` 走 OpenAI 兼容接口（`ELYSIUM_VLM_BASE_URL`），关思考，温度 0，每图最多 192 token（p4-3b 起改为 512）；有字的图也描述，印刷字在前、描述在后，`caption` 记 `vlm`，模型信任 0.6。超过 1024×1024 的图整张等比缩小再发（一串约 2000×2000 的图曾让服务卡死），连接、发送、读取任一步 300 s 没有进展就报错（`STALL_SECONDS`；卡死时服务一个字节都不出）。`elysium describe-pictures` 给已有库补描述，可断点续跑。
  - 描述分两段跑，同一 commit `3993644`、同一服务：`bench.describe_check` 描述到 41,920 / 47,775 时被 Claude Code 的内存回收杀掉（不是命令出错）；剩下 5,855 张用 `ELYSIUM_HOME=bench/runs/describe/after elysium describe-pictures --workers 32` 续完，30 分 17 秒（约 3.2 张/s）。再跑 `python -m bench.describe_check --described-home bench/runs/describe/after --scratch bench/runs/describe2` 计分，所以报告里写的是「reused」。47,775 张全部带描述。
  - 结果（`bench/reports/DESCRIBE.md`，words-only，top_k 24）：dev 0.865 → 0.884，test 0.853 → 0.873，全库 0.857 → 0.877；chance 分别为 0.5222 / 0.5036 / 0.5099。全库分模态：video 0.651 → 0.819，ui_screenshot 0.659 → 0.713，image 0.781 → 0.827，pdf 0.876 → 0.886，conversation 0.907 → 0.914；code 0.941 → 0.928，跌了，原因没查，留到 p4-3 在 dev 上看。离 0.92 还差 0.043。
  - `describe.json` 进 `bench/audit.py` 的冻结报告表。
  - 评审（codex）第 1 轮 FAIL，D1–D3。D1 补描述先写文字、后同步向量；同步失败后续跑，图已记 `vlm` 被跳过，向量却留在旧文字上（`pending=1`）。修法：开了 dense 时，补描述收尾跑 `VectorIndex.sync()`，按 stamp 把旧向量重编。D2 补描述没走摄入的 `trust.stamp`，描述里带「ignore previous instructions」的图不进隔离。修法：每张描述后的 atom 按原 origin 过 `trust.stamp`。D3 300 s 是 httpx 的分步超时，不是总截止，原文写错；卡死的症状是一个字节都不出，分步超时正好抓它，所以改名 `STALL_SECONDS` 并改写说法，不加总截止。三处对计分无影响：计分库 dense 关闭；47,775 条描述里带注入短语的 0 条。`test_describe.py` 新增 2 条，去掉对应修复各红 1 条。第 2 轮 PASS（`9f3ca95`）。
- [x] **p4-3** 排序：只针对「在窗口 11–240」那一类，dev 上量重排（9B 判相关或现有 dense 腿），不涨就不上并写明。
  - 描述后 dev 再看漏召回（`top_k=240`）：在窗口 11–240 的约 3.7%（37 / 991），不在窗口的约 6.4%（63 / 991）；就算重排全对，dev 最多到 0.92 上下。
  - 9B 判相关（`f5c47d9` 的 `bench/rank_check.py --judge-url`，前 40 个 atom 逐个问 yes / no，按 P(yes) 重排）：第一版只取 top_logprobs 里最后一个「yes」写法，`yes` 与 ` yes` 互相覆盖，量出 dev 0.901 → 0.606，评审 D1 抓到。改成同一答案的各写法相加后重跑（`bench/reports/RANK.md`，`e046136`）：dev 0.901 → 0.916，MRR 0.711 → 0.795；code 0.979 → 0.984，conversation 0.909 → 0.965，image 0.827 → 0.880，pdf 0.891 → 0.894，ui_screenshot 0.712 → 0.730，video 0.821 → 0.875。涨了，按本条规则上。
  - 产品形态（`elysium/rerank.py`，`5c43124`）：设 `ELYSIUM_RERANK_BASE_URL` 才开，默认关；只重排返回的那一页（24 个 atom），页里还是同一批记忆，翻页不漏不重（`test_rerank.py` 6 条，去掉接线红 2 条）；判官失败则搜索失败，不静默退回。dev 上比窗口：前 40 个 0.916（`e046136` 的报告），只排这一页 0.913——差 0.003，换来翻页不变，取页。
  - 结果（`bench/reports/RANK.md`，`96b3bb9`）：重排后 dev 0.901 → 0.913，test 0.888 → 0.907，全库 0.893 → 0.909；MRR 全库 0.717 → 0.801。test 分模态：code 0.954 → 0.974，conversation 0.906 → 0.936，image 0.827 → 0.861，ui_screenshot 0.737 → 0.789，pdf 0.884 与 video 0.818 不动——页中位只有 9 个来源，不到 10 个时重排动不了 recall@10。代价：每次搜索多 24 次 9B 调用，p50 从 0.13–0.15 s 到 0.80–0.81 s，p95 从 1.34–1.42 s 到 1.65–1.80 s（`rank.json` 三档，单次跑，随负载变）。离 0.92 还差 0.011–0.013。
  - dense 腿（MiniLM，`dense_scale` 的 153,857 条向量带进描述库副本、只重编变了字的 atom，436 s；临时脚本，未入库）：dev words-only 0.884，+dense 0.881（top_k 24）/ 0.883（top_k 30），image 0.827 → 0.753。不上。
  - 找到的真病因（dev 逐条看 code 题）：常用词按全库计数、检索却在提问者的 holder 里跑。描述把 `axis` `series` `value` `text` 推过全库 5% 线，被丢掉；一个只有 4 个函数的 holder 问「will get the axis mode for the current series」，只剩 `will` `current`，在 holder 里一条都不中，`no_match`。修法（`store_search.search_atoms` 的 `fill`）：稀有词在范围内凑不满一页（`fill=limit`，即调用方要的条数），就用全部词再查一次；每页都从第一行读，翻页不会换表达式。dev 上比过定值：5% 0.884、10% 0.890、20% 0.896、50% 0.895、100% 0.897（p50 0.56 s）；补查 0.901（p50 0.14 s），阈值取页大小，不另设常数。代价在尾部：补查对常用词全表扫，p95 从 0.15–0.18 s（`describe.json` 三档）升到 1.37–1.46 s（`rank.json` 三档）；评审另量 40 题 2.54–2.77 s，随负载变。`test_scoped_terms.py` 2 条，去掉修复各红。
  - 结果（`bench/reports/RANK.md`）：dev 0.884 → 0.901，test 0.873 → 0.888，全库 0.877 → 0.893；chance 0.5222 / 0.5036 / 0.5099。全库 code 0.928 → 0.963，ui_screenshot 0.713 → 0.728；conversation 0.914 → 0.907（dev 不变；test 0.917 → 0.906，只有 `lme:195a1a1b` 从中变成不中，少 1 题）。离 0.92 还差 0.027。
  - 顺带修的崩溃：写测试时 `remember()` 在「plot axis series of the graph」之后再记「… 0」抛 `KeyError`（`trust.quantity_conflict` 读了旧记忆里不存在的主语数值）。改成两边都有才比；`test_memory_conflicts.py` 加 1 条。
  - 评审（codex）第 1 轮 FAIL，D1–D3：D1 判官同一答案的各写法互相覆盖（`f5c47d9` 改为相加，重跑后判官由 0.606 变为涨）；D2「少 2 题」应为 1；D3「中位 149」未注明是 60 张探针。第 2 轮 PASS（`1d066b6`）。
- [~] **p4-3b** 描述写长（p4-3 dev 上查出来的，2026-10-29 加）：192 token 的预算把描述截在半句（按句末标点估：图 82%、截图 86%、视频帧 37%），屏幕下半截的按钮没写进去。dev 截图 111 题、只重写 730 张截图：512 token 0.712 → 0.748；改成「至多 150 词」的短提示反而 0.685——对 BM25，字多比句子完整更要紧。把文档图与截图（约 21,400 张）按 512 token 重写，视频帧不动（按 atom_id 顺序各抽 60 张、按 512 token 重写的探针里，视频帧 60 张全写完、中位 149 token；文档图 44 / 60、截图 35 / 60）；dev 量，test 与全库出报告。
- [ ] **p4-4** 生成侧实测：`elysium runtime-generation-proof` 与钥匙测试场景 7 的首字时间（同题两次，第二次走缓存），把 PARTLY MEASURED 变成实数。
- [ ] **p4-5** 验收重算：test 与全库 recall@10 对 0.92，并排 chance 与外部对手；README / Gaps / CHECKLIST 同步。
- [ ] **p4-6** 与真 Mem0、真 Zep 对跑并出图（用户要求，2026-10-29）：同一批冻结语料与题目，三家各跑几档配置（Elysium 的 top_k 与腿；Mem0 / Zep 的检索条数与它们的 LLM 写入），纵轴 recall@10（附 holder 内 chance），横轴每题成本（对数刻度：查询耗时与写入时的 LLM token，本地 9B 承担两家的 LLM 调用），画成「每个系统一条线、点是配置档」的图，提交图与生成它的脚本。Mem0 / Zep 的 `add()` 要 LLM 抽取，量级与耗时如实写进报告；跑不全的部分照实标出，不外推。
