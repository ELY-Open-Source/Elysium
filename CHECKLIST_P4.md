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

- [~] **p4-1** 9B 运行时：`Qwen/Qwen3.5-9B` 快照落盘（`bench/models/Qwen3.5-9B`，记 commit 与各分片 sha256），vLLM 环境（`.venv-linux-vllm`，`scripts/setup-linux-runtimes.sh` 的那条），OpenAI 兼容服务能答文字与图片各一题；记显存占用与首字时间。
  - 快照：`hf download Qwen/Qwen3.5-9B --local-dir bench/models/Qwen3.5-9B`，revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`，19,329,398,400 字节；四个分片的 sha256 与 HF LFS oid 逐个相同（`db6f444b…` `31c7d7e2…` `7ec36ba3…` `b62b0c4c…`）。
  - 环境：`.venv-linux-vllm`（uv，Python 3.12）里 vLLM 0.32.0、torch 2.13.0+cu130，`torch.cuda.is_available()` True；GPU RTX 4090 23,028 MiB，驱动 617.14。
  - 起服务：`ELYSIUM_MODEL_DIR=bench/models/Qwen3.5-9B bash scripts/launch-vllm-live.sh`，75 s 就绪，显存 20,865 MiB。三处实测才定下的参数：bf16 权重吃满显存、KV 只剩 0.07 GiB，起不来（那次的日志被下一次启动覆盖，没有留档；数字取自当时终端输出），所以 `--quantization fp8`（KV 6.46 GiB = 172,894 token，`--max-model-len 16384` 时并发 10.55×）；FlashInfer 采样器首个请求要 nvcc 现编、本机没有 CUDA toolkit，所以 `VLLM_USE_FLASHINFER_SAMPLER=0`；Qwen3.5 默认先想后答，产品读 `content` 会把思考过程当回答，所以 `--reasoning-parser qwen3` 把它分到 vLLM 0.32.0 回包里的 `reasoning` 字段，`content` 只留答案。原脚本写的 262,144 上下文在这张卡上放不下（KV 只装得下 172,894 token），`.sh` / `.ps1` / `profiles.py` 的 `vllm-live` 三处一起改成实测能起的这一组。`config.live_context_tokens` 仍是 262,144，它只进 KV 指纹与状态展示，本条不动。
  - 应答（产品路径 `QwenRuntime.generate_prompt`，`ELYSIUM_RUNTIME_BACKEND=sglang`，`ELYSIUM_SGLANG_BASE_URL=http://127.0.0.1:8001/v1`）：文字题答「The capital of France is Paris.」；ScreenSpot 截图 `pc_155db9b3…png` 输入 2,492 token，描述出 Preferences 窗口、Python Scientific 选中、「Show plots in tool window」勾选。
  - 评审第 1 轮 FAIL，D1–D3：D1 产品路径的图片请求开着思考，512 token 全花在思考上，`finish_reason` 为 `length`、`content` 为 null，产品却把 `text=None` 当成功返回。修法：两条走服务的生成路径并成一个 `QwenRuntime._chat`，请求带 `chat_template_kwargs: {enable_thinking: false}`（答案依据是编译好的上下文，直接要答案），拿不到答案就抛 `RuntimeUnavailableError` 并点名 `finish_reason` 与预算；`backend/tests/test_runtime_http.py` 2 条，去掉修复 2 条都红。修后同一张截图实测 2,494 → 111 token、2.32 s 出答案。D2 dev/test 题数原写 1,000 / 1,928，可计分的 2,928 题实为 991 / 1,937，已改。第 2 轮 D4：我先把错数归因于「按未标不可答计数」，不成立——那次按模态的计数输出本来就是 dev 427+265+111+75+57+56 = 991、test 810+501+209+165+93+159 = 1,937，两种筛法（带金标 / 未标不可答）筛出同一批题；1,000 / 1,928 是我写计划时没把这两列加起来、凭印象写的整数。D3 思考字段名原写 `reasoning_content`，实为 `reasoning`，已改。
  - 首字时间（流式，关思考）：文字 0.432 s，同题第二次 0.046 s；图片 0.565 s，第二次 0.076 s——第二次快是 vLLM 前缀缓存，不是卡带；开思考的文字题首个答案 token 在 3.464 s（之前 208 段思考）。这些数随负载动，是单次实测，引用时当量级看。
- [ ] **p4-2** 看图写字：`describe.py` 走已起的服务（不在产品进程里加载 9B），图片、截图、视频帧的描述成为 atom 文字；在冻结库副本上补描述，dev 量各模态，test 与全库出报告。
- [ ] **p4-3** 排序：只针对「在窗口 11–240」那一类，dev 上量重排（9B 判相关或现有 dense 腿），不涨就不上并写明。
- [ ] **p4-4** 生成侧实测：`elysium runtime-generation-proof` 与钥匙测试场景 7 的首字时间（同题两次，第二次走缓存），把 PARTLY MEASURED 变成实数。
- [ ] **p4-5** 验收重算：test 与全库 recall@10 对 0.92，并排 chance 与外部对手；README / Gaps / CHECKLIST 同步。
