# multi-agent-harness

基于 [`openai-agents`](https://github.com/openai/openai-agents-python) 的 **supervisor + worker** 多智能体 harness 原型。

一个 supervisor 持有控制权，把子任务委派给三个 worker（researcher / coder / reviewer），
worker 作为「工具」被调用，而不是接管对话。所有文件读写被限制在一个工作区目录内，
每次运行都会留下可回放的轨迹和本地 trace。

## 它是怎么工作的

```
用户目标
   │
   ▼
supervisor ──委派──> researcher   （只读：摸清现状、定验收标准）
   │        ──委派──> coder        （读写：在工作区产出文件）
   │        ──委派──> reviewer     （只读：对照标准挑毛病）
   │
   ▼
汇总结论 + runs/ 运行产物
```

三个关键设计：

1. **用 `as_tool()` 而不是 handoff。** worker 是一次「可调用的能力」，supervisor 始终保留控制权，
   这样才能多轮委派、交叉验证。handoff 适合分流（triage），不适合主管制。
2. **worker 上下文隔离。** worker 看不到用户原始需求和别人的对话，只拿到 supervisor 写的那段委派内容。
   好处是 context window 干净；代价是 supervisor 必须把委派写得自包含。
3. **能力边界 = 工具列表。** researcher 和 reviewer 拿不到 `write_file`，这不是靠提示词约束，
   而是它们的工具列表里根本没有这个函数。

## 目录结构

```
src/harness/
  config.py     环境变量 → HarnessConfig
  provider.py   模型/端点构造（OpenAI 官方 或 任意 OpenAI 兼容端点）
  workspace.py  路径沙箱：所有文件访问都限制在 workspace 内
  tools.py      工具层（list_files / read_file / write_file / run_command）
  agents.py     supervisor 与三个 worker 的定义、提示词
  progress.py   运行时的实时进度事件（RunHooks）
  tracing.py    本地 span 收集器（数据不出本机）
  runner.py     组装 + 运行 + 落盘产物
  runs_index.py runs/ 的数据层（纯数据，可单测）
  usage.py      token 消耗统计（写入方和读取方共用，避免循环依赖）
  sessions.py   会话：对话历史持久化 + 会话名校验
  server.py     本地只读服务（标准库，无 Web 框架）
  web/          运行浏览器的单页前端
  cli.py        命令行入口
  testing.py    ScriptedModel，离线测试编排用
tests/          118 个测试，全部离线可跑
examples/       offline_demo.py
```

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Copy-Item .env.example .env    # 然后填 HARNESS_API_KEY

# 先看装配对不对，不调用模型
.\.venv\Scripts\python.exe -m harness --dry-run

# 真正跑一个任务
.\.venv\Scripts\python.exe -m harness "在工作区写一个 hello.py 并附上 README"
```

常用参数：`--workspace` `--model` `--base-url` `--max-turns` `--allow-shell` `--tracing` `-v`。
加 `--quiet` 可以关掉实时进度，只在结束时打印报告。

多轮追问用 `--session`，看历史用 `--list-sessions`：

```powershell
.\.venv\Scripts\python.exe -m harness --session refactor "把 utils.py 里的重复逻辑合并"
.\.venv\Scripts\python.exe -m harness --session refactor "刚才改的那两个函数，补一下测试"
.\.venv\Scripts\python.exe -m harness --list-sessions
```

### 不用 API key 先看效果

```powershell
.\.venv\Scripts\python.exe examples\offline_demo.py
```

它用脚本模型跑完整的「调研 → 实现 → 汇总」流程，会把一个真实的 `hello.py` 写进
`examples/_demo_output/workspace/`，并打印委派轨迹和内部 span 时间线。

### 接不同的模型

只要设置 `HARNESS_BASE_URL` 就会自动切到 Chat Completions，适配任何 OpenAI 兼容端点：

```ini
# DeepSeek
HARNESS_BASE_URL=https://api.deepseek.com/v1
HARNESS_MODEL=deepseek-chat
HARNESS_API_KEY=sk-...

# 本地 Ollama（不需要 key）
HARNESS_BASE_URL=http://localhost:11434/v1
HARNESS_MODEL=qwen3:8b
```

不设置 `HARNESS_BASE_URL` 就走 OpenAI 官方的 Responses API。

## 扩展点

**加一个能力** —— 在 `tools.py` 里加一个 `@function_tool` 函数，然后决定给哪些 worker。

**加一个角色** —— 在 `agents.py` 的 `build_workers` 里加一个 `Agent`，
并在 `WORKER_TOOL_DESCRIPTIONS` 里写清什么时候该委派给它。supervisor 会自动多出这个工具。

**换成别的编排拓扑** —— 想试 handoff 就把 `build_supervisor` 里的 `as_tool` 换成
`handoffs=[...]`；想试流水线就把 worker 串起来，不走 supervisor。

## 实时进度

跑起来能看到过程，不用等结束：

```
> supervisor
  . coder({"input": "在工作区新建文件 fizzbuzz.py。…"})
  > coder
    . write_file({"path": "fizzbuzz.py", …})
    . write_file -> 已写入 fizzbuzz.py（182 字符）
    . run_command({"command": "python fizzbuzz.py > out.txt & type out.txt"})
    . run_command -> exit_code=0 stdout: 1 2 Fizz 4 Buzz … FizzBuzz 15
    . run_command({"command": "del out.txt"})
  < coder: 产出：新增 fizzbuzz.py…验证输出 15 行，全部符合预期。
< supervisor: 已完成。
```

缩进就是嵌套层级：`>` 是 agent 开始，`<` 是 agent 结束，`.` 是它调用的工具。

实现上有两个选择，值得说明：

1. **用 `RunHooks` 而不是 `run_streamed`。** 对 supervisor/worker 这种结构，
   「谁委派给谁、worker 在调什么工具」比逐字吐 token 有用得多；而且 `RunHooks`
   在现有的非流式路径上就能工作，模型实现不需要支持流式。
2. **必须把 hooks 显式传给 `as_tool()`。** 嵌套运行不继承父级的 `RunHooks`，
   漏掉这一层，进度里就只剩「委派」和「回传」两条，看不到 worker 内部在干什么。

进度写 stderr、报告写 stdout，所以 `harness "任务" > result.txt` 只会重定向报告。

## 运行浏览器

```powershell
.\.venv\Scripts\python.exe -m harness --serve        # 默认 http://127.0.0.1:8765
.\.venv\Scripts\python.exe -m harness --serve --port 9000
```

左边是历史运行列表（时间 / 调用次数 / tokens / 耗时），点开看详情：
结论、`委派轨迹`、`内部 span`，以及完整的消耗拆分。

**调提示词时最有用的是「设为对比基线」**：把某一次钉成基线，再点别的运行，
每个指标后面会直接显示涨跌百分比。比如把优化前的 hello.py 那次设为基线，
就能看到优化后调用次数 `-80%`、tokens `-94%`。

设计上的取舍：

- **只用标准库**，没引 Web 框架。这是个本地查看器，不值得为它加依赖。
- **默认绑定 `127.0.0.1`**。`runs/` 里含完整的 prompt 和产出，不该暴露到网络上。
- **数据层（`runs_index.py`）和 HTTP 层分开**，所以读取逻辑可以单独测试；
  同时对 `run_id` 做了格式校验 + 路径穿越防护，坏记录的目录会被跳过而不是拖垮整个列表。
- 这个页面以后会长成实时控制台，所以从一开始就做成了服务而不是生成静态 HTML。
- **列表读的是小文件。** 完整 `run.json` 里 spans 占了九成以上（单份 164 KB），
  而列表只需要几百字节的标量字段。所以落盘时会顺手写一份 `summary.json`（181 字节），
  列表接口优先读它，读不到才退回解析完整记录。
  实测 500 次运行：**1907ms → 164ms**。

顶部会把带会话的运行按会话分组，点一下只看该会话的几次运行。
等待批准的运行会高亮出来，并带一条「待批准」的筛选 —— 打开页面就能看到
有没有东西卡在那里等你。

## 会话

带 `--session <名字>` 的运行会共享同一段对话历史，**跨进程存活**：

```powershell
> harness --session memory-test "记住口令：蓝鲸。不要写文件，直接确认。"
确认，口令已记住：蓝鲸。

> harness --session memory-test "我刚才让你记的口令是什么？"
蓝鲸。
```

两次是独立的进程调用，第二句能答对，说明历史真的落盘了。

实现上刻意做得很薄：

- **对话历史**（模型真正看到的东西）交给 SDK 自带的 `SQLiteSession`，
  存储落在 `runs/sessions.db`。这种地方不该自己造轮子。
- **会话的展示信息不额外存**：`run.json` 里记一个 `session_id`，
  标题、运行次数、累计 tokens 全部从 `runs/` 分组推出来。
  只有一个真实数据源，不存在"索引和实际数据对不上"的问题。
- 会话名会被用作数据库键，也会出现在网页 URL 里，所以限制成
  `字母/数字/._-`、最长 64 字符，避免注入和路径问题。

一个需要注意的边界：**会话历史属于 supervisor，worker 仍然是无状态的。**
worker 拿不到 supervisor 的对话，所以 supervisor 必须把相关背景写进委派内容里
——这正是它提示词里「委派必须自包含」那条规则。

## 审批门

开了 shell 之后，**每条命令执行前都要你点头**：

```powershell
> harness --allow-shell "新建 greet.py 并运行确认输出"
> supervisor
  . coder({"input": "..."})
  > coder
    . write_file({"path": "greet.py", ...})
    . write_file -> 已写入 greet.py（15 字符）

⏸ 已暂停：有工具调用在等待你批准

  [run_command] {"command": "python greet.py"}

批准：harness --approve 20261001-154213
拒绝：harness --reject 20261001-154213
```

```powershell
harness --pending              # 看还有哪些在等
harness --approve <run_id>     # 放行并继续
harness --reject  <run_id>     # 拒绝并继续（模型会如实报告验证没做成）
```

**批准之前命令不会执行**，这是有测试兜底的核心断言。

直接动机是一次真实事故：agent 自己跑了 `pip install pytest`，把包装进了系统 Python。
它有 shell 权限，但没人授权它装东西。

几个设计决定：

- **默认就要审批**（`HARNESS_APPROVE_SHELL=1`）。开 shell 只代表「允许执行」，
  不代表「随便执行」。
- **暂停时落盘完整运行状态**（`runs/<id>/state.json`），所以可以关掉终端、
  第二天再批准。状态由 SDK 的 `RunState` 序列化，续跑走 `RunState.from_string`。
- **续跑会自动恢复原运行的工具配置。** 这条是踩出来的：原运行带了 `--allow-shell`，
  批准时忘了带，coder 的工具列表里就没有 `run_command`，运行会**永远卡在同一个
  暂停点**且看不出原因。现在配置随记录一起存（`graph_config`），续跑自动套用，
  不一致就直接报错。
- **`status` 从 `state.json` 是否存在推导**，不存进文件。存下来的话，续跑清掉
  状态标记后，那句 "paused" 就会一直留在记录里说谎。
- **网页上可以直接批准。** 待批准的运行会高亮、有单独筛选、顶部汇总报数，
  详情里就是「批准并继续 / 拒绝」两个按钮，点完自动刷新。

### 网页上的写操作

批准按钮是本地服务里**唯一的写操作**，而且它会真的跑模型、可能执行命令，
所以多做了几层：

- **要求自定义请求头 `X-Harness-Action: 1`。** 跨域请求带自定义头会先发预检，
  而服务不响应预检 —— 恶意网页发起的 POST 会被浏览器挡掉。实测无头返回 403。
- **只接受 POST。** GET 打这个路径是 404。
- **不是待批准状态就返回 409**，不会把重复批准当成成功。
- **一次只跑一个写操作**（进程内加锁）。`Harness` 的追踪开关是进程级全局状态，
  并发跑两个会互相覆盖。

已知限制：POST 是同步的，页面会一直等到这次运行结束（可能几十秒）。
想做成"点了就返回、后台跑完再刷新"的话，需要引入任务队列。

## 踩过的坑

这几条都是实际调试出来的，不是推测：

1. **worker 必须显式传 `model=`。** `as_tool()` 的嵌套运行用的是 worker 自己的模型。
   不传就会退回 SDK 默认的 OpenAI provider，于是父级用着 DeepSeek、子级偷偷去连 OpenAI。
2. **自定义 `Model` 必须自己开 `generation_span`。** SDK 内置的 OpenAI 模型都包了这一层，
   自己实现时漏掉，追踪里就完全看不到模型调用。`harness/testing.py` 是最小参考。
3. **supervisor 看不到 worker 的内部步骤。** `new_items` 里只有一次委派调用和一条回传结论。
   想看内部过程必须走 trace —— 这也是 `tracing.py` 存在的原因。
4. **委派内容必须自包含。** worker 拿不到原始需求和历史，写不清楚它就只能瞎猜。
5. **追踪开关是进程级全局状态。** 同一个进程里只应存在一个 `Harness` 实例。
6. **`run_command` 默认关闭**，且拒绝列表只是防手滑，不是安全沙箱。
   真要跑不可信代码请丢进容器。
7. **`RunResult.raw_responses` 不包含嵌套 worker 的调用。** 统计模型调用次数要看
   `generation` span，`RunOutcome.model_calls` 就是这么算的。
8. **`as_tool()` 的嵌套运行不继承父级 `RunHooks`。** 想让进度显示 worker 内部，
   必须把同一个 hooks 实例传给每个 worker tool。
9. **`run_command` 里裸 `python` 会走 PATH 解析到系统解释器。** 实测时 agent 以为
   在验证代码，其实跑在另一个 Python 里，还把依赖装进了系统环境。现在会把
   harness 自己的解释器目录放到 PATH 最前面，并且工具描述里写明了当前是什么 shell。
10. **`SQLiteSession` 持有连接，不关会留下 `-wal` / `-shm`。** CLI 跑完进程退出无所谓，
    但长驻进程（比如以后的网页控制台）会泄漏句柄，所以 `Harness` 提供了 `close()`，
    也能当上下文管理器用。
11. **续跑必须用和原运行相同的工具配置。** 少了 `--allow-shell`，待执行的
    `run_command` 在新建的 agent 图里根本不存在，运行会无声地卡在同一个暂停点。
12. **中断可能发生在嵌套的 worker 里。** `result.interruptions` 会把 worker 内部的
    待批准调用冒泡上来，续跑时父级会重放委派、由嵌套状态接着跑 —— 所以
    `write_file` 不会重复执行。这点是验证过的，别凭直觉去「优化」它。
13. **推导出来的状态和存下来的快照会打架。** `status` 是从 `state.json` 实时推导的，
    但 `pending` 一度是落盘快照，结果出现「已完成却还挂着 1 个待批准」。
    同一个东西要么都推导、要么都存，不能一半一半。

## 成本控制

harness 的消耗不取决于任务本身，而取决于**编排有多克制**。
同一个「在工作区新建 hello.py 并打印一行」的任务，实测对比：

| | 优化前 | 优化后 |
|---|---|---|
| 模型调用 | 25 次 | **5 次** |
| 输入 tokens | 69,215 | **4,850** |
| 输出 tokens | 23,244 | **397** |
| 其中思维链 | 10,959 | **0** |
| 合计 tokens | 92,459 | **5,247** |
| 耗时 | 108.4s | **4.4s** |

差了 17.6 倍。原因不是模型，而是三个编排问题：

1. **过度编排。** supervisor 为一个建文件任务启动了 researcher + reviewer，
   还做了三轮「改注释 → 复查 → 再改注释」的返工。
   → 提示词里写明按任务量级编排：单一明确产出只委派 coder 一次。
2. **thinking 模式全程开着。** DeepSeek 默认 `effort=high`，每次工具调用都先产出思维链，
   光思维链就占了一万多 token。
   → `HARNESS_THINKING=disabled`。
3. **worker 输出太长。** 回传的报告带表格、贴完整文件内容，而这些内容每一轮都会被
   重新喂回 supervisor，成本是滚雪球的。
   → 提示词限制 worker 回复 8–10 行、禁止贴全文和表格。

每次运行结束都会打印真实消耗，也写进 `runs/<时间戳>/run.json` 的 `usage` 字段，
可以直接用来对比不同提示词版本的效果。

想进一步省：

- `HARNESS_MODEL` 保持 `deepseek-flash`（比 `deepseek-v4-pro` 便宜约 4 倍）
- 关掉 `HARNESS_ALLOW_SHELL`（默认就是关的）
- 调小 `HARNESS_MAX_TURNS` / `HARNESS_WORKER_MAX_TURNS`

## 测试

```powershell
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe -m pytest -q
```

10 个测试全部离线运行，不联网、不花钱，覆盖路径沙箱、工具权限边界、
委派链路、真实文件写入、产物落盘和 span 采集。

## 目前的局限

- 进度是「事件级」而不是「token 级」：能看到 agent 和工具调用，看不到逐字输出。
- 会话能记住上下文，但一次**被中断的运行**还不能接着跑（SDK 的 `RunState` 还没接）。
- 没有并发，worker 是串行逐个调用的。
- 运行浏览器是**只读**的：能看历史、能对比，但还不能从页面发起任务、叫停或干预。
  这些要先补后端能力（会话持久化 → 可中断 → 审批门），不是前端的事。
- 只有 token 统计，没有按人民币折算成本。
- 工作区沙箱只管文件读写，管不住进程：开了 `--allow-shell` 后 agent 仍能在
  本机执行任意命令（有超时和拒绝列表，但那是防手滑，不是隔离）。
