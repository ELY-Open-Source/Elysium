# Phase 5 — 一键安装、全局记忆库、新网站、新控制台

用户要求（2026-10-30）：一条命令在本地装好，任何模型、任何 harness（Claude Code、Codex 等）都能用；记忆库默认放全局 `~/.elysium`；拆依赖；宣传站和本地控制台都按 Isometric Picture Book 风格重做（pnpm、Vite、three.js、平滑滚动），场景讲 Elysium 自己；网站源码在 `site/`，部署到 `elysium.elydora.com`，删除 `model.elydora.com`。

每条：实现 → herdr 右侧 codex 评审（`codex --yolo -m gpt-6-astra -c model_reasoning_effort=xhigh -c service_tier=fast`，最多 3 轮）→ PASS 后 commit + push → 打勾。

## A. 安装

- [ ] **p5-1** 拆依赖：`pip install ./backend` 只装核心（存、取、检索、API、CLI、MCP 需要的后端）；torch、transformers、sentence-transformers、peft、bitsandbytes、accelerate、datasets、qwen-vl-utils 进 `elysium[models]`。一个干净 venv 只装核心，`elysium remember / search / serve` 能跑，`torch` 不在环境里；一个测试钉住核心模块导入时不加载 torch。`scripts/install.sh` 与 `.ps1` 跟着改。
- [ ] **p5-2** 全局库：后端和 Go MCP 用同一条规则找库：`ELYSIUM_HOME`，没有就是 `~/.elysium`。当前目录有旧的 `.elysium` 库而 `ELYSIUM_HOME` 没指向它时，报错并给出命令，不静默开一个空库。
- [ ] **p5-3** MCP 自启后端：MCP 发现 API 不通时启动 `elysium serve`（同一个 `ELYSIUM_HOME`），等它健康后再转发；日志写到 `~/.elysium/logs/api.log`；起不来就报错并指向日志。
- [ ] **p5-4** 一条命令安装：仓库根目录 `install.sh`（`curl -fsSL … | bash`）和 `install.ps1`（`irm … | iex`）：没有 uv 就装 uv，用 uv 装 Python 与 `elysium`，建 `~/.elysium`，下载并校验 MCP 二进制，注册到本机已装的客户端。
- [ ] **p5-5** 客户端：除 Codex、Claude Code 外，注册 Cursor、Gemini CLI、OpenCode、VS Code；格式按各家文档，不靠猜。其余客户端，安装结束时打印一段通用 stdio 配置。
- [ ] **p5-6** 干净机器验收：没有 Python 的 Linux 容器里跑那一条命令，再用 stdio JSON-RPC 驱动 MCP 写一条记忆、读回来；CI 在 Linux、macOS、Windows 上跑同样的步骤。
- [ ] **p5-7** 发布：打 `mcp-v0.2.0`，安装脚本取它；README、`elysium-mcp/README.md`、AGENTS.md 同步。

## B. 宣传站（`site/` → `elysium.elydora.com`）

- [ ] **p5-8** 骨架与等距引擎：pnpm + Vite + three.js + Lenis；正交相机锁在等距角，三色平涂、无描边无阴影，按地面足迹排序，背影小人，地面衬线字逐字落下。
- [ ] **p5-9** 场景：滚动驱动的连续一块地面，讲 Elysium 的规则——各人的记忆各归各人（holder 作用域）、"我不知道，但我妻子知道"（转介）、和 Mem0 比成本（地面上的条形）、一条命令安装、接任何 agent。数字只用 README 与 `bench/reports/` 里测过的。
- [ ] **p5-10** 部署与验收：Worker 静态资源部署到 `elysium.elydora.com`；Playwright 桌面与手机截图、`prefers-reduced-motion`、性能预算。
- [ ] **p5-11** 删除旧站：解绑 `model.elydora.com`，删除 Worker `ely-eye-web`。

## C. 本地控制台（`frontend/`）

- [ ] **p5-12** 重写控制台：同一套 API、同样的功能，同一种等距画册风格，改用 pnpm；`frontend/scripts/verify-ui.mjs` 按新界面重写，覆盖原来的每个流程；`scripts/ui_smoke.sh` 通过。

## D. 收尾

- [ ] **p5-13** AGENTS.md、README 与技术栈同步；输出验收逐条核对表。
