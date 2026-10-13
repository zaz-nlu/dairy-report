# 日报越狱计划（daily-prison）— 自动日报桌面小软件

## Context
单位强制每天写日报，漏交罚 ¥200（已被罚过一次）。目标：做一个双击即用的 Windows 小软件，自动从 **git / Claude Code / Codex** 采集当天工作，AI 整理成日报，每天 18:00 自动提交到「德尔塔日报管理系统」（`http://221.238.56.226:8866/dailyweb`）。可直接发给同事/朋友使用，换项目零配置。UI 以「监狱 · 失去自由」为主题，**黑色幽默漫画风**，顶部常驻到 18:00 的倒计时。

已确认的决定：
- 数据源自动全读：git、SVN、Claude Code、Codex（没装的自动跳过）；只有「实际改了仓库文件」的对话和提交进日报
- 日报系统验证码不校验（任意值），密码明文，软件自动登录；用户在软件里填自己的用户名密码
- 桌面软件：pywebview 原生窗口（Edge WebView2）载入本地 Vue 页面，前端经 js_api 直接调 Python，无 HTTP 服务、无需另启后端；托盘常驻；**安装包分发**（`日报越狱-安装.exe`）
- 前端 Vue 3（全局构建版，本地文件，无 npm 构建）
- 周六日自动休息；法定节假日/调休在设置里手动勾选
- 代码目录 `D:\daily-prison`（独立 git 仓库），数据目录 `D:\工作\YYYY-MM-DD\`

已核实的本机数据格式：
- Claude Code：`~/.claude/projects/*/*.jsonl`，每行含 `type`、`timestamp`(UTC)、`cwd`、`gitBranch`、`message`。**目录名对中文路径有损，项目路径必须取行内 `cwd`**；用户消息里混有 `<local-command-caveat>`、`<system-reminder>` 等包装，需过滤。
- Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，首行 `session_meta.payload.cwd`，用户消息为 `response_item` + `payload.type=message, role=user`；同样有 AGENTS.md / environment 包装需过滤。

---

## 一、架构

```
日报越狱-安装.exe（Inno Setup）→ 安装出 日报越狱\ 目录（PyInstaller --onedir）
├─ app.py          入口：pywebview 窗口 + pystray 托盘 + 调度线程
├─ bridge.py       暴露给前端的 js_api（window.pywebview.api.xxx），无 HTTP 服务
├─ config.py       设置读写：%APPDATA%\daily-prison\config.json；密码进 Windows 凭据管理器(keyring)
├─ collect.py      三个采集函数 collect_git / collect_claude / collect_codex → 统一条目
├─ interrogate.py  AI 整理（"审讯"）：自动选 `claude -p` 或 `codex exec`
├─ delta_client.py 日报系统客户端：登录、项目/任务列表、查询当日、提交
├─ ui/             index.html + app.js + style.css + strings.js + vendor/vue.global.prod.js + fonts/ + img/
└─ tests/          test_collect.py、test_interrogate.py、test_schedule.py（assert 级别，python tests/xxx.py 直接跑）
```
依赖只有：`pywebview`、`pystray`、`Pillow`(pystray 需要)、`keyring`、`pyinstaller`(打包)，HTTP 用标准库 urllib；安装包用 Inno Setup（一个 `installer.iss`）。调度用标准库线程循环（每 30 秒看一次钟），不引 APScheduler；不用 Flask（pywebview 的 js_api 直接桥接）；不用 Element Plus（漫画风要全自绘，组件少）。

## 二、业务逻辑

### 1. 采集（"搜身"）— 每 4 小时 + 手动
- 每次都**重采当天全量**（幂等），写 `D:\工作\YYYY-MM-DD\raw.json`；另追加一份 `git status` 快照到 `snapshots[]`（保留未提交工作的证据，之后 git log 查不到）。
- 统一条目：`{source, time(本地时区), project(仓库根目录名), cwd, text, files[]}`
- **Claude Code**：取当天 `type=user` 的人类输入（过滤包装/工具结果/isMeta），附带同会话 assistant 的 Edit/Write 工具调用里的文件路径。
- **Codex**：按日期目录读当天会话，取 role=user 的 input_text，过滤包装，项目取 session_meta.cwd。
- **git**：仓库清单 = 对话 `cwd` 反查 `git rev-parse --show-toplevel` ∪ 设置里手动添加的目录；每个仓库跑 `git log --since=当天00:00 --author=<该仓库 user.email> --all --no-merges --name-only` + `git status --porcelain`。
- 截断：单条 text 截 300 字，单日总量超限按时间均匀抽样（控制 AI token）。

### 2. 审讯（AI 整理）— 17:30 自动 + 手动「重新审讯」
- 输入：raw.json + 日报系统里当前用户可选的「项目→任务」列表 + 设置里的默认工时（8.0）。
- 输出严格 JSON：`items[{workInfo, projectId, workTime, completionDegree, confidence}]`，校验失败重试 1 次。任务类型/汇报人/优先级用设置里的默认值填，不让 AI 猜。
- 提示词硬规则：只依据证据不编造；同一件事在对话和 git 里出现合并为一条；中文、编号短句，贴近现有日报风格（"1.修复了知识库…bug 2.…"）；工时之和 = 默认工时；`confidence<0.6` 或匹配不到项目 → 用默认项目，UI 盖「存疑」章（18:00 照样提交，通知里标出来让用户去网页改）。
- 不做设置，自动选：PATH 里有 `claude` 用 `claude -p`，否则有 `codex` 用 `codex exec`，都没有 → 设置页提示。都沿用本机已配好的后端（你用 Claude，同事用单位本地 DeepSeek），零配置。子进程超时 180s，`CREATE_NO_WINDOW` 防黑框。
  - **审讯本身不能留会话记录**，否则第二天会被当成"工作"采回来：claude 加 `--no-session-persistence`；codex 加 `--ephemeral`。
  - claude：不加 `--bare`（只认 API Key，OAuth 会失效）；不限制 `--setting-sources`（同事的 DeepSeek 地址在用户级 settings 里）。hook 噪音靠严格 JSON 校验 + 重试 1 次兜住。
  - codex：`codex exec --ephemeral --skip-git-repo-check -s read-only --output-schema <schema.json> -o <out.json> -`，prompt 走 stdin，结果读 `-o` 文件。
  - 只装 Trae 的同事：之后加「OpenAI 兼容接口直连单位 DeepSeek」，需要单位服务器地址。

### 3. 画押（提交）— 18:00
- 流程：登录(验证码 111) → 查当日是否已有非 0 工时记录（有则跳过，防重复）→ 按草稿逐项目提交 → 记录结果到 `D:\工作\YYYY-MM-DD\result.json`。
- 只有一种模式：17:30 审讯出草稿（「认罪书」页可随时改），**18:00 不等确认直接提交**；提交后托盘通知 + 弹出窗口显示「已交了什么」，附「打开日报系统」按钮，有问题用户自己去网页改。
- 跳过条件：周末、设置里勾的节假日、当天标记请假、当天采集为空（为空不自动编造，弹通知让用户手填）。
- 失败：18:05、18:15 各重试一次，仍失败托盘气泡 + 窗口红色警报。
- 日报系统规则（用户确认）：18:00 以后提交即可，所以 18:00 到点提交是正确时间点，不必提前。
- 电脑 18:00 在睡眠/关机：程序下次醒来若当天未提交且未过 23:59，立即补交。
- 自启：安装时勾选，由 Inno Setup 在启动文件夹建快捷方式；设置里的开关只是增删同一个快捷方式。

### 日报系统接口（已从前端 JS 反查，renren-fast 框架）
基址 `http://221.238.56.226:8866/daproject`，JSON 收发，响应 `{code:0,...}` 为成功；鉴权 = 请求头 `token: <登录返回的 token>`。
| 用途 | 接口 | 参数 |
|---|---|---|
| 登录 | `POST /sys/login` | `{username, password, uuid:任意, captcha:任意}` 明文 → `token` |
| 我的项目 | `GET /projtask/selfProject` | → `data[{projectId, projectName}]` |
| 任务类型 | `GET /projtasktype/selfProjectType` | → `data[{projectTypeId, projectTypeName}]` |
| 汇报人 | `GET /sys/user/reportUser` | → `data[]` |
| 查本人日报 | `GET /dailymain/list` | `page, limit, isself, start, end`（防重复） |
| 提交①主表 | `POST /dailymain/save` | `{dateTime:"yyyy-MM-dd", remark, isLeave:0}` → `data`=mainId, `groupId` |
| 提交②明细 | `POST /daily/saveorupdate` | `{mainId, list:[{mainId, groupId, isProjTaskId, isProjTaskTypeId, sendUserId, priority(1低2中3高4紧急), workInfo, completionDegree(0-100 步长5), workTime(0.5步长), haveQuestion, solution, isSolve(0解决1未解决), remark}]}` |

明细必填：项目、任务类型、汇报人、优先级、工作内容、完成度、工时。前端下拉值是 `"groupId-id"` 字符串，提交前取 `-` 后半段转数字。待登录后用读接口核实返回结构；提交在用户在场时试一次。

### 4. 实现要点（防坑）
- **单实例**：启动时抢一个本地锁（绑定 127.0.0.1 固定端口），抢不到就唤起已有窗口后退出——双开会导致重复提交。
- **两步提交的半成功**：①主表成功、②明细失败时，重试必须复用该日已有 mainId（先查 `/dailymain/list`），不能再建一个主表。防重复判断 = 当日主表存在 **且** 明细工时 > 0。
- **数值在代码里规整，不靠 AI**：工时按 0.5 取整后把差额补到最大项，保证总和 = 默认工时；完成度取整到 5 的倍数并夹在 0–100。
- **Codex 跨午夜**：同时读昨天和今天的日期目录，再按行内时间戳过滤当天。
- **每次提交前重新登录**，不缓存 token。
- **数据目录可配置**，默认 `D:\工作`；同事电脑没有 D 盘时退回 `%USERPROFILE%\daily-prison`。
- **前后端契约**：`bridge.py` 的 js_api 方法清单（名称/入参/返回 JSON）写在文件头注释里，P4 附一个极简调试页；P5 的漫画 UI 只依赖这份契约，不碰后端。

## 三、UI 设计：黑色幽默漫画风

### 视觉语言
| 元素 | 规格 |
|---|---|
| 主色 | 囚服黑 `#1a1a1a`、泛黄纸 `#f4ecd8`、警报红 `#d7263d`、囚服橙 `#ff7a00`、警示黄 `#ffd23f` |
| 线条 | 3px 纯黑描边，硬投影 `4px 4px 0 #000`，卡片轻微旋转 ±1° |
| 纹理 | 网点(halftone)背景、囚服黑白横条装饰带、身高刻度尺侧栏 |
| 字体 | 标题/对话框：站酷快乐体（OFL）；数字倒计时：Black Ops One 模版字（OFL）；正文：微软雅黑。字体文件打包进 exe |
| 图形 | 手铐、铁栏、牢门、粉笔正字、红色印章，全部 SVG 内联，不用外网资源 |
| 窗口 | 默认 1000×680，可缩放，最小 860×600 |

### 顶部倒计时（全局常驻）
挂在铁链上的木牌：「距离放风还有 **HH:MM:SS**」，下方「刑期进度」锁链条 = (当前−09:00)/(18:00−09:00)。状态机：

| 状态 | 表现 |
|---|---|
| 工作日未交，>2h | 黑字，囚犯漫画头像无聊脸 |
| <2h | 橙色，头像冒汗 |
| <30min | 红色闪烁 + 对话气泡「再不交，罚款 ¥200！」 |
| 已提交 | 牢门打开动画，「✓ 今日已画押 · 刑满释放」，倒计时改为「明日 09:00 再次收监」 |
| 18:00 后未交 | 「越狱失败 · ¥200 罚单生效中」红章 + 「立即补交」按钮 |
| 周末/节假日 | 「今日放风 · 自由活动」，太阳 + 断掉的锁链 |

托盘图标是手铐，tooltip「服刑中 · 剩 02:13:05」。

### 页面（导航做成牢房门牌）
1. **牢房**（首页）：倒计时 + 今日劳改记录时间线（git=铁锹图标，Claude/Codex=对讲机图标）+ 上次搜身时间 + 「立即搜身」按钮 + 墙上粉笔正字（连续按时交天数）+「已为你省下 ¥200 × N」账本。
2. **认罪书**（日报预览编辑）：AI 生成条目可编辑，项目/任务下拉、工时、进度；「重新审讯」「签字画押」；存疑条目盖红章。
3. **档案室**（历史）：按日期列出，状态印章「已画押 / 越狱失败 / 放风」，点开看当日 raw 与提交内容。
4. **典狱长办公室**（设置）：首次运行即「入狱登记」向导——账号、数据源勾选、git 额外目录、数据目录、提交时间/采集间隔、默认项目/任务类型/汇报人/优先级/工时、节假日、开机自启。

### 文案映射（集中在 `ui/strings.js`）
提交=签字画押、采集=搜身、AI 整理=审讯、设置=典狱长办公室、首次登录=入狱登记、退出=保外就医、17:30 通知=「典狱长：还有 30 分钟查房」、成功通知=「画押成功，今日刑满释放」。

---

## 四、制作顺序（每阶段先用真实数据跑通再进下一阶段）
| 阶段 | 内容 | 完成标志 |
|---|---|---|
| P0 准备 | `git init D:\daily-prison`（接口已反查，无需抓 cURL） | 资料齐 |
| P1 搜身 | `collect.py` + `tests/test_collect.py`；命令行 `python collect.py 2026-10-13` | raw.json 里能看到今天 dify 仓库的提交和本次对话 |
| P2 审讯 | `interrogate.py`（claude / codex 两路）；`python interrogate.py 2026-10-13` | 生成的草稿和你手写日报内容大体一致 |
| P3 画押 | `delta_client.py`：先只做登录+读接口；提交接口在你在场时用一个日期试提交一次并人工核对/修改 | 系统里看到正确的一条日报 |
| P4 骨架 | `app.py`/`bridge.py`/`config.py`：窗口、托盘、调度循环、设置持久化，极简页面 | 关窗进托盘，到点自动采集/提交 |
| P5 漫画 UI | 四个页面 + 倒计时状态机 + 字体/SVG 素材 | 各状态可手动切换预览 |
| P6 打包 | PyInstaller `--onedir --windowed --add-data ui` + Inno Setup 出安装包（桌面图标、开始菜单、卸载、开机自启勾选） | 在没装 Python 的电脑上安装后双击可用 |
| P7 试运行 | 跑一周，每天看提交通知，按实际偏差调提示词 | 一周无漏交、无错交 |

## 五、验证
- P1/P2：两个 `tests/*.py` 用小样本 jsonl 断言过滤和合并逻辑；对今天真实数据人工比对。
- P3：读接口打印项目/任务列表与日报网页一致；试提交后在网页「本人」列表核对日期、工时、详情。
- P4：把提交时间临时改到 2 分钟后，观察自动审讯→提交→通知全流程；睡眠唤醒补交用改系统时间或临时阈值模拟。
- P6：干净 Windows 机器/同事电脑运行 exe，走完入狱登记→搜身→审讯→画押。
