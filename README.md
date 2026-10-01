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
  cli.py        命令行入口
  testing.py    ScriptedModel，离线测试编排用
tests/          10 个测试，全部离线可跑
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
- 没有会话持久化和断点续跑，每次 `run()` 都是一次性的。
- 没有并发，worker 是串行逐个调用的。
- 没有把 `runs/` 的产物做成回放界面。
- 只有 token 统计，没有按人民币折算成本。
- 工作区沙箱只管文件读写，管不住进程：开了 `--allow-shell` 后 agent 仍能在
  本机执行任意命令（有超时和拒绝列表，但那是防手滑，不是隔离）。
