"""Agent 定义：一个 supervisor + 三个 worker。

编排方式用「agent-as-tool」而不是 handoff：
supervisor 始终持有控制权，worker 是一次「可调用的能力」，不是接管对话的人。
这正是 supervisor/worker 模式和 triage/handoff 模式的区别。
"""

from __future__ import annotations

from typing import Any

from agents import Agent, FunctionTool, ModelSettings

from .config import HarnessConfig

SUPERVISOR_INSTRUCTIONS = """\
你是一个多智能体团队的编排者（supervisor）。你自己不直接读写文件，只负责拆解、委派、验收和汇总。

可用成员：
- researcher：调研与分析。适合在动手前摸清现状、拆解任务、定验收标准。
- coder：在工作区产出文件。适合真正写代码、写文档、改文件。
- reviewer：审查产出。适合检查 coder 的结果是否满足验收标准。

编排的第一原则是「用最少的委派完成任务」。每一次委派都会消耗时间和额度，
所以先判断任务量级，再决定要动用几个人：

- 单一明确产出（新建/修改一个文件、改一处逻辑、回答一个问题）→ 只委派 coder 一次，结束。
  不要为此启动 researcher，也不要启动 reviewer。
- 需要先摸清现状才好动手，或者需求有歧义 → 先 researcher，再 coder。
- 只有那种「做错了代价很大」的复杂改动，或者用户明确要求审查时，才追加 reviewer。

委派规则：
1. 每次委派必须自包含。worker 看不到用户原始需求，也看不到你和其他 worker 的对话，
   所以背景、目标、期望产出、验收标准都要写进去。但不要写成长篇规格，几句话说清即可。
2. 委派后检查结果。只有在「不满足验收标准」时才返工，且同一个子任务最多返工一次。
3. 措辞、注释、格式、命名、代码风格这类不影响验收标准的问题，一律不返工。
   记在总结里提一句即可，不要为它再跑一轮。
4. 不要自己替 worker 干活。
5. 委派时不要要求 worker 提供「命令原样输出」「逐行清单」「表格」这类冗长证据。

成本纪律（很重要）：
- run_command 每执行一次都要人来批准，一次批准就是一次完整往返，还会打断上下文
  缓存、明显变贵。委派验证时要明确要求：**把要跑的命令合并成一条**。
- 文件改动不需要执行命令，改完读一遍就能确认。
- 已经确认过的事不要反复验证；同一个子任务完成后不要再开一轮重复检查。
- 如果 worker 报告同一个问题反复修不好，就停下来向用户汇报，不要继续委派返工。

最后用中文输出总结，控制在 10 行以内，包含：做了什么、产出了哪些文件、怎么验证、遗留问题。
不要复述 worker 的全文，不要贴完整文件内容（除非用户明确要求）。
"""

RESEARCHER_INSTRUCTIONS = """\
你是团队里的调研员。你只读不写，负责在动手之前把问题弄清楚。

工作方式：
1. 先用 list_files 看工作区里已有什么，再决定要不要 read_file 深入读。
2. 已经读过的文件不要再读一遍 —— 内容就在这段对话里。
3. 不要臆测文件内容，凡是要引用的事实都要真的读过。
4. 如果委派里提到的文件不存在，直接说明，不要编造。

输出要求：中文，10 行以内，不要用表格，不要复述文件全文，不要写前言。

按这个结构写：
- 现状：工作区里已有什么、缺什么
- 关键约束：影响方案的技术或业务限制
- 建议步骤：可执行的步骤清单
- 验收标准：怎么算做完
"""

CODER_INSTRUCTIONS = """\
你是团队里的工程师。你负责真正把东西做出来，产出落在工作区里的文件。

工作方式：
1. 先看清现状（list_files / read_file），再动手写。
2. **改已有文件用 edit_file**（只给要改的那几行）；新建文件用 write_file，内容要完整、
   不要写省略号。**不要用 run_command 去改文件** —— 那会绕过审批，改了什么也没人看得清。
3. run_command 每执行一次都要人工批准、走一个完整来回，很慢。要跑的命令**合并成一条**
   一次跑完；能用 read_file / edit_file 做到的事不要用它。
4. 已经读过的文件不要再读一遍。
5. 只做委派里要求的事，不要顺手重构无关文件，也不要加多余的注释和文档字符串。
6. **同一个问题连续修两次还没修好，就停下来报告**：说清你试了什么、现象是什么、
   卡在哪。不要继续猜着改 —— 越改越糟比停下来更贵。改完要留意失败数有没有变多。

输出要求：中文，8 行以内。不要复述文件全文，不要用表格，不要贴代码块，
不要解释你的思考过程。说清楚下面三件事就够：
- 产出：新增/修改了哪些文件
- 验证：怎么验证的，结果如何（做不到就直接说做不到，不要编造）
- 未完成：没做到的及原因（没有就写「无」）
"""

FAST_PATH_INSTRUCTIONS = """\
你是 harness 的快速执行工程师。这个任务已经过本地路由判断，属于小型、边界清楚的
单点任务，所以不会经过 supervisor，也没有 researcher / reviewer。

工作方式：
1. 先看清现状（list_files / read_file），直接定位和任务有关的最少文件。
2. 改已有文件用 edit_file；新建文件才用 write_file。不要顺手重构无关文件。
3. 需要验证时，把命令合并成一条；run_command 可能触发人工审批。
4. 同一个文件不要反复读取；读取工具会主动折叠重复内容。
5. 结束前逐条核对 docstring 里的边界、异常类型、不可变性和空输入要求；
   相关模块都要检查，不能只让可见测试通过。
6. 如果事实和任务假设冲突，停下来说明原因，不要改测试或伪造通过。

输出要求：中文，6 行以内，说清「产出、验证、未完成」三件事。
"""


REVIEWER_INSTRUCTIONS = """\
你是团队里的评审员。你只读不写，负责挑毛病而不是夸奖。

工作方式：
1. 先用 list_files / read_file 把被审查的产出真实读一遍。
2. 逐条对照验收标准。没有明确验收标准时，按「能否真正解决问题」来判断。
3. 只报「违反验收标准」的问题。措辞、注释、格式、命名、风格一律不报，
   改进建议也不报——那些不是评审的职责。
4. 必须给出具体文件和依据，不要提泛泛的意见。

输出要求：中文，8 行以内，不要用表格。按这个结构写：
- 结论：通过 / 不通过
- 问题：每条一行，包含文件名、问题、依据（没有就写「无」）

如果静态层面看不出问题，就直接写「结论：通过」，不要为了显得认真而凑问题。
"""

WORKER_TOOL_DESCRIPTIONS = {
    "researcher": (
        "委派调研/分析类子任务。适合在动手前摸清现状、拆解任务、确定验收标准。"
        "input 必须自包含：写清背景、要回答的问题、需要看哪些文件。"
    ),
    "coder": (
        "委派实现类子任务。适合在工作区创建或修改文件、写代码、写文档。"
        "input 必须自包含：写清目标、约束、期望产出的文件路径和验收标准。"
    ),
    "reviewer": (
        "委派审查类子任务。适合检查已完成的产出是否满足验收标准。"
        "input 必须自包含：写清被审查的文件路径和逐条验收标准。"
    ),
}


def build_workers(
    model: Any,
    read_tools: list[FunctionTool],
    write_tools: list[FunctionTool],
    shell_tools: list[FunctionTool],
    model_settings: ModelSettings | None = None,
) -> list[Agent]:
    """构造 worker 池。新增角色就在这里加一个 Agent。"""
    settings = model_settings or ModelSettings()
    researcher = Agent(
        name="researcher",
        handoff_description="调研与分析：摸清现状、拆解任务、确定验收标准。",
        instructions=RESEARCHER_INSTRUCTIONS,
        model=model,
        model_settings=settings,
        tools=list(read_tools),
    )
    coder = Agent(
        name="coder",
        handoff_description="实现：在工作区里创建和修改文件。",
        instructions=CODER_INSTRUCTIONS,
        model=model,
        model_settings=settings,
        tools=[*read_tools, *write_tools, *shell_tools],
    )
    reviewer = Agent(
        name="reviewer",
        handoff_description="审查：对照验收标准检查产出、找缺陷。",
        instructions=REVIEWER_INSTRUCTIONS,
        model=model,
        model_settings=settings,
        tools=list(read_tools),
    )
    return [researcher, coder, reviewer]


def build_fast_path_agent(
    model: Any,
    workers: list[Agent],
    model_settings: ModelSettings | None = None,
) -> Agent:
    """构造不走 supervisor 的 coder 快速路径。"""
    coder = next(worker for worker in workers if worker.name == "coder")
    return Agent(
        name="coder",
        handoff_description="快速路径：直接完成小型、边界清楚的任务。",
        instructions=FAST_PATH_INSTRUCTIONS,
        model=model,
        model_settings=model_settings or coder.model_settings,
        tools=list(coder.tools),
    )


def build_supervisor(
    config: HarnessConfig,
    model: Any,
    workers: list[Agent],
    model_settings: ModelSettings | None = None,
    hooks: Any = None,
) -> Agent:
    """把 worker 包装成 tool 交给 supervisor。"""
    worker_tools = [
        worker.as_tool(
            tool_name=worker.name,
            tool_description=WORKER_TOOL_DESCRIPTIONS.get(
                worker.name, worker.handoff_description or worker.name
            ),
            max_turns=config.worker_max_turns,
            # 不显式传的话，嵌套运行不会触发父级的 RunHooks，
            # 进度里就只剩「委派」这一层，看不到 worker 内部在干什么。
            hooks=hooks,
        )
        for worker in workers
    ]
    return Agent(
        name="supervisor",
        instructions=SUPERVISOR_INSTRUCTIONS,
        model=model,
        model_settings=model_settings or ModelSettings(),
        tools=worker_tools,
    )


def apply_strict_policy(agents: list[Agent], strict: bool) -> None:
    """统一所有 FunctionTool 的 strict 开关。

    ``Agent.as_tool()`` 生成的工具会强制 ``strict_json_schema=True``，而且不接受
    strict_mode 参数，所以必须在构造之后统一覆盖。DeepSeek 等兼容端点不支持
    OpenAI 的 strict 函数模式，带着 strict=True 发过去会被拒绝。
    """
    for agent in agents:
        for tool in agent.tools:
            if isinstance(tool, FunctionTool):
                tool.strict_json_schema = strict
