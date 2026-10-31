# Phase 5 — 一键安装、全局记忆库、新网站、新控制台

用户要求（2026-10-30）：一条命令在本地装好，任何模型、任何 harness（Claude Code、Codex 等）都能用；记忆库默认放全局 `~/.elysian`；拆依赖；宣传站和本地控制台都按 Isometric Picture Book 风格重做（pnpm、Vite、three.js、平滑滚动），场景讲 Elysian 自己；网站源码在 `site/`，部署到 `elysian.elydora.com`，删除 `model.elydora.com`。同日改名：Elysium → Elysian（往世乐土不变），仓库、包、命令、变量、目录、README、网址全改。

每条：实现 → herdr 右侧 codex 评审（`codex --yolo -m gpt-6-astra -c model_reasoning_effort=xhigh -c service_tier=fast`，最多 3 轮）→ PASS 后 commit + push → 打勾。

## A. 安装

- [x] **p5-0** 改名 Elysian：仓库 `ELY-Open-Source/Elysian`，Go 模块 `github.com/ELY-Open-Source/Elysian/elysian-mcp`，包与命令 `elysian`，变量 `ELYSIAN_*`，库 `elysian.sqlite`；旧的 `ELYSIUM_*` 变量、`.elysium` 库与 `elysium.sqlite` 和 `ELY_EYE_*` 一样报错退出，不静默忽略。冻结报告里的历史 arm 名不改。
  - 评审第 1 轮 FAIL，D1–D3：D1 Go 向上找库时跳过旧目录与旧库名，加 `refuseOldStores`，每一层都查；D2 Python 旧目录守卫看的是新目录是否存在，安装器先建 `.elysian/bin` 就绕过了，改看新数据库；D3 冻结的 `live.json` 仍用 `elysium` arm 名，画图读不了，`live_chart.label` 读作 elysian 并加测试。第 2 轮 PASS（`8ce0127`）。

- [x] **p5-1** 拆依赖：`pip install ./backend` 只装核心（存、取、检索、API、CLI、MCP 需要的后端）；torch、transformers、sentence-transformers、peft、bitsandbytes、accelerate、datasets、qwen-vl-utils 进 `elysian[models]`。一个干净 venv 只装核心，`elysian remember / search / serve` 能跑，`torch` 不在环境里；一个测试钉住核心模块导入时不加载 torch。`scripts/install.sh` 与 `.ps1` 跟着改。
  - 核心依赖 17 个，干净 venv 785 MB（pyarrow、pymupdf、opencv、onnxruntime 占大头），没有 torch；`networkx`、`platformdirs` 无人引用，删除；`rank-bm25` 只有 bench 用，进 dev。`backend/tests/test_core_install.py` 在新解释器里跑 remember、search 与建 API，再读 `sys.modules`；注入一行 `import transformers` 时它失败。评审第 1 轮 PASS（`afc51c0`）。
- [x] **p5-2** 全局库：后端和 Go MCP 用同一条规则找库：`ELYSIAN_HOME`，没有就是 `~/.elysian`。当前目录有旧的 `.elysian` 库而 `ELYSIAN_HOME` 没指向它时，报错并给出命令，不静默开一个空库。
  - 评审第 1 轮 FAIL，D1–D5：D1 安装器总把默认 home 当显式 `--elysian-home` 传给 Go，绕过项目库守卫，改为只传用户给的；D2 Go 项目根仍取 home 的父目录，项目级注册写进 `~/.mcp.json`，改为当前目录；D3 `.env` 里的 ELYSIAN_HOME 与空值让 Python、Go 选不同库，Python 设 `env_ignore_empty`，拒绝 `.env` 里的 home；D4 Go 不跟符号链接，改用 `EvalSymlinks`；D5 相对 home 让源码安装失败，安装器转绝对路径。第 2 轮 FAIL，D1 PowerShell 吞掉 setup 退出码，D3 pydantic 不分大小写而 Go 只读大写，改为拒绝任何非大写的 `ELYSIAN_` 名字。第 3 轮 PASS（`5ebeb73`）。顺带：`api.py` 的模块级 `app = create_app()` 无人使用且在导入时读真实 home，删除；两个测试原本读了开发者仓库里的 `.elysian`，改为依赖 tmp 设置。
- [x] **p5-3** MCP 自启后端：MCP 发现 API 不通时启动 `elysian serve`（同一个 `ELYSIAN_HOME`），等它健康后再转发；日志写到 `~/.elysian/logs/api.log`；起不来就报错并指向日志。
  - 写入要 token，一键安装的人不会设：`elysian init` 一次性写 `~/.elysian/auth_token`（O_EXCL、0600、从不打印），后端与 Go 在 `ELYSIAN_AUTH_TOKEN` 为空时读它，空文件两边都报错。`scripts/mcp_autostart_smoke.sh`：新 home、API 未起，MCP 客户端写入再读回，API 在客户端退出后仍在。评审第 1 轮 FAIL，D1 只看 200 不核对 `data_home`，写进别的库；D2 并发自启时输家立即退出。第 2 轮 FAIL，D3 相对 home 被报成相对路径，同库误判异库，Settings 改为保存绝对 home。第 3 轮 FAIL，D1 用客户端目录解释旧 API 的相对路径，改为拒绝；D4 `~` 在守卫之后才展开且 Go 不展开，改为两端在守卫前同规则展开。3 轮用完，修复 `c9ad4b0` 由 p5-4 的评审复现通过。
- [x] **p5-4** 一条命令安装：仓库根目录 `install.sh`（`curl -fsSL … | bash`）和 `install.ps1`（`irm … | iex`）：没有 uv 就装 uv，用 uv 装 Python 与 `elysian`，建 `~/.elysian`，下载并校验 MCP 二进制，注册到本机已装的客户端。
  - 根目录 `install.sh` / `install.ps1` 是唯一安装器（删 `elysian-mcp/install.*`）：uv（官方脚本装到 `~/.local/bin`）、按 release tag 的 GitHub 归档装后端（不需要 Git，`--excludes opencv-python` 避开要 X 库的 GUI 版 OpenCV）、`elysian init`、校验后的 MCP 二进制、旁边放 `elysian`（Windows 复制 exe）、`elysian-mcp setup`。重装先停本 home 的 API（真实路径匹配；Linux 读 `/proc`，macOS 用 `pgrep`）。评审第 1 轮 FAIL D1–D4（注册未用解析后的 home、要 Git、sed 解析 JSON、ASCII 写 .cmd）；第 2 轮 FAIL D5（Windows 覆盖不了在跑的 elysian.exe）；第 3 轮 FAIL（停止排在 uv 重装之后）。3 轮用完，修复 `a6c757a` 与之后的真实路径匹配由 p5-5 的评审复核 PASS。
- [x] **p5-5** 客户端：除 Codex、Claude Code 外，注册 Cursor、Gemini CLI、OpenCode、VS Code；格式按各家文档，不靠猜。其余客户端，安装结束时打印一段通用 stdio 配置。
  - Cursor（编辑 `~/.cursor/mcp.json`，保留其它键，非 JSON 就停）、Gemini CLI、OpenCode、VS Code（WSL 下跳过）；结果附 `any_other_client` 的 `mcpServers` 条目。真实 gemini-cli 与 opencode-ai 各跑两遍：写入并替换。评审第 1 轮 FAIL 只报 p5-4 的真实路径问题；第 2 轮 PASS。
- [x] **p5-6** 干净机器验收：没有 Python 的 Linux 容器里跑那一条命令，再用 stdio JSON-RPC 驱动 MCP 写一条记忆、读回来；CI 在 Linux、macOS、Windows 上跑同样的步骤。
  - `scripts/install_acceptance.sh --source`：debian:bookworm-slim（无 Python 无 Git）一条命令装好，客户端经 `scripts/mcp_roundtrip.py` 写入并读回。CI `install.yml`：ubuntu、macos、windows 与裸容器四个 job 全绿（run 41154989666）。验收逼出三个真问题并在根上修掉：精简 Debian 没有 `pgrep`（改读 `/proc`）；rapidocr 拉进的 GUI 版 OpenCV 缺 libxcb（安装时排除，用 headless）；uv 的 macOS Python 不能加载扩展（只有 VectorIndex 加载 sqlite-vec，`test_without_extensions.py`）。评审第 1 轮 PASS。
- [x] **p5-7** 发布：打 `mcp-v0.2.0`，安装脚本取它；README、`elysian-mcp/README.md`、AGENTS.md 同步。
  - 发布 `mcp-v0.2.0`，后修为 `mcp-v0.2.1`：发布流程末尾的 accept job 在裸 Debian 上跑公开的一行命令，两次都 success。评审第 1 轮 FAIL（Windows 覆盖不了运行中的 elysian-mcp.exe，改为先改名）；第 2 轮 FAIL，D1 带方括号的路径被当通配符，D2 下载前就移走旧二进制，D3 MCP 的 HTTP 客户端把成功响应截到 4096 字节（发布包既有问题，修后发 v0.2.1）；第 3 轮 FAIL（含方括号的 TEMP 下 `New-TemporaryFile` 失效，改 `GetTempFileName`，`907d362`）。3 轮用完，该修复经评审在原生 PowerShell 5.1 复核 PASS。Windows 的发布模式未在本机真跑（会改用户真实的客户端配置），只跑了 CI 的源码模式与上述局部实测。

## B. 宣传站（`site/` → `elysian.elydora.com`）

- [x] **p5-8** 骨架与等距引擎：pnpm + Vite + three.js + Lenis；正交相机锁在等距角，三色平涂、无描边无阴影，按地面足迹排序，背影小人，地面衬线字逐字落下。
  - 宣传站由一个 agent 在独立 worktree 写成，合并 `619920c`。评审第 1 轮 FAIL，D1 pnpm 11 拒绝 esbuild、workerd 的构建脚本（加 `site/pnpm-workspace.yaml` 的 `allowBuilds`）；D2 保持帧早于末帧，相机在 t=70 瞬跳（只在更晚时追加，加载时检查关键帧递增）。第 2 轮 PASS。
- [x] **p5-9** 场景：滚动驱动的连续一块地面，讲 Elysian 的规则——各人的记忆各归各人（holder 作用域）、"我不知道，但我妻子知道"（转介）、和 Mem0 比成本（地面上的条形）、一条命令安装、接任何 agent。数字只用 README 与 `bench/reports/` 里测过的。
  - 七幕：开场题字、各归其主（+0.455）、她知道（转介）、七分之一的代价（成本图画在地面，chance 0.591，写明 Mem0 raw 与不带 judge 的差距在误差内）、十六万条记忆一个文件（0.072 秒）、同一个柜台（六个客户端与安装命令）、结尾。手机按字幕上方实测区域取景。评审第 1 轮 PASS。
- [x] **p5-10** 部署与验收：Worker 静态资源部署到 `elysian.elydora.com`；Playwright 桌面与手机截图、`prefers-reduced-motion`、性能预算。
  - 部署为 assets-only Worker `elysian-site`（wrangler 4.156，关遥测）到 `elysian.elydora.com`。`check.mjs --url https://elysian.elydora.com/` 桌面、手机、减少动效、无 WebGL 全过；首个桌面加载 252,116 字节（含 Cloudflare zone 注入的 beacon 10,478），预算 300 KB 由 check.mjs 在浏览器里测。评审第 1 轮 FAIL（手报 229,811 字节漏了注入的 beacon 与浏览器压缩）；第 2 轮 PASS。
- [x] **p5-11** 删除旧站：解绑 `model.elydora.com`，删除 Worker `ely-eye-web`。
  - Cloudflare API 解绑 `model.elydora.com`、删除 Worker `ely-eye-web`；`model.elydora.com` 不再解析，`elysian.elydora.com` 仍 200，仓库无残留链接。评审第 1 轮 PASS。

## C. 本地控制台（`frontend/`）

- [ ] **p5-12** 重写控制台：同一套 API、同样的功能，同一种等距画册风格，改用 pnpm；`frontend/scripts/verify-ui.mjs` 按新界面重写，覆盖原来的每个流程；`scripts/ui_smoke.sh` 通过。

## D. 收尾

- [ ] **p5-13** AGENTS.md、README 与技术栈同步；输出验收逐条核对表。
