# CHECKLIST_P4.md — 阶段 4：recall@10 ≥ 0.92，并把 9B 跑起来

接续 `CHECKLIST.md`（阶段 0–3 与终验）。规则相同：从上到下一条一条做，禁止跳项；每条完成后用 `/herdr` 在右侧 split panel 起 `codex --yolo -m gpt-6.1-sol -c model_reasoning_effort=xhigh -c service_tier=fast` review，同一条最多 3 轮，PASS 才打勾。

状态记号：`[ ]` 待办 `[~]` 进行中 `[x]` 已过审

**口径（本阶段新增）**：冻结题集每题带 `split`（dev 1,000 / test 1,928）。诊断与任何取值只在 dev 上做；验收数字报 test 与全库两行，各带 holder 内 chance。验收线由用户定为 **0.92**（原 0.90）。

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

- [ ] **p4-1** 9B 运行时：`Qwen/Qwen3.5-9B` 快照落盘（`bench/models/Qwen3.5-9B`，记 commit 与各分片 sha256），vLLM 环境（`.venv-linux-vllm`，`scripts/setup-linux-runtimes.sh` 的那条），OpenAI 兼容服务能答文字与图片各一题；记显存占用与首字时间。
- [ ] **p4-2** 看图写字：`describe.py` 走已起的服务（不在产品进程里加载 9B），图片、截图、视频帧的描述成为 atom 文字；在冻结库副本上补描述，dev 量各模态，test 与全库出报告。
- [ ] **p4-3** 排序：只针对「在窗口 11–240」那一类，dev 上量重排（9B 判相关或现有 dense 腿），不涨就不上并写明。
- [ ] **p4-4** 生成侧实测：`elysium runtime-generation-proof` 与钥匙测试场景 7 的首字时间（同题两次，第二次走缓存），把 PARTLY MEASURED 变成实数。
- [ ] **p4-5** 验收重算：test 与全库 recall@10 对 0.92，并排 chance 与外部对手；README / Gaps / CHECKLIST 同步。
