Now I have comprehensive data. Let me compile the complete research report.

---

# Comprehensive Research Report: Checkpoint-Restore / Replay / Duplicate Side Effects in LLM Agent Frameworks

This report documents real-world evidence of duplicate execution, replay side effects, and checkpoint-restore problems found across GitHub issues, community forums, blogs, and documentation across 13+ agent frameworks.

---

## Framework 1: LangGraph (langchain-ai/langgraph)

LangGraph has the deepest and most documented cluster of issues in this category.

### Issue #6208 — \"Do not re-execute a node that interrupted unless all of its interrupts have been resumed\"
- **URL:** https://github.com/langchain-ai/langgraph/issues/6208
- **Date:** September 26, 2025
- **Status:** Open (Enhancement label)
- **Type:** (a) Duplicate tool execution; (b) Checkpoint-restore side effects
- **Description:** A maintainer opened this issue noting that nodes with multiple interrupts re-execute after only one resume. Core quote: *\"a node with two interrupts will rerun after only one resume. We can't solve this without knowing how many resumes are pending per task, which would require tracking interrupt ids.\"* The node re-executes from the top, causing every tool that already fired before the interrupt to fire again.

### Blog post — \"LangGraph's HITL Has a Double Execution Problem\"
- **URL:** https://blog.raed.dev/posts/langgraph-hitl
- **Date:** 2025 (references issue #6208)
- **Type:** (a) + (b) — Primary real-world documentation of the problem
- **Description:** A practitioner documented a concrete scenario: a node calls `create_ticket` (auto-execute) followed by `send_email` (approval-required). On resume after approval, `create_ticket` fires a second time. Two identical tickets are created; the duplication is invisible at the application layer because the final message history shows correct state. Direct quote: *\"two tickets were created for the same issue when a user was reviewing an email draft and clicked Approve.\"*

### Issue #6624 — \"ToolNode doesn't collect all interrupts from parallel tool execution\"
- **URL:** https://github.com/langchain-ai/langgraph/issues/6624
- **Date:** December 24, 2025
- **Status:** Closed (Completed)
- **Type:** (b) + (c)
- **Description:** When multiple tools call `interrupt()` in parallel via `asyncio.gather`, only one interrupt is captured in the checkpoint. Resume values are misrouted — *\"Circle got Square's value.\"* The root cause is that the first `GraphInterrupt` cancels other concurrent coroutines. Checkpoint state cannot faithfully restore parallel tool execution.

### Issue #6626 — \"`interrupt()` calls in parallel tools generate identical IDs, making multi-interrupt resume impossible\"
- **URL:** https://github.com/langchain-ai/langgraph/issues/6626
- **Date:** December 2025
- **Status:** Open
- **Type:** (b) + (c)
- **Description:** When multiple tools call `interrupt()` in the same ToolNode, they all receive identical IDs because the ID hash uses only the checkpoint namespace. Resume values cannot be matched to specific tools, making multi-interrupt workflows unresumable.

### Issue #4796 — \"Subgraph (using interrupt) restarts instead of resuming from internal breakpoint\"
- **URL:** https://github.com/langchain-ai/langgraph/issues/4796
- **Date:** May 22, 2025
- **Status:** Closed (duplicate)
- **Type:** (a) + (b)
- **Description:** A subgraph configured with `interrupt_before` restarts from its entry point instead of resuming from the checkpointed next node. The first node executes twice (`counter_node_in_subgraph: 2`) while the human-input node never runs (`counter_human_node: 0`). Breaks human-in-the-loop workflows entirely.

### Issue #4397 — \"Multiple Tool Results for Single Tool Call with LangGraph Human Approval Flow\"
- **URL:** https://github.com/langchain-ai/langgraph/issues/4397
- **Date:** April 24, 2025
- **Status:** Open (Bug, Pending)
- **Type:** (a) + (b)
- **Description:** After a sensitive tool executes and returns a result, the system re-enters the same agent and executes the same tool twice more, creating three results for one tool call. Error: *\"Too many tool_result blocks found: 3, expected 1.\"*

### Issue #6577 — \"Unexpected behavior of functional API under interrupt\"
- **URL:** https://github.com/langchain-ai/langgraph/issues/6577
- **Date:** December 11, 2025
- **Status:** Closed (Completed)
- **Type:** (b)
- **Description:** When using the functional API with interrupts, side effects on mutable objects are lost across resume cycles because the entire entrypoint re-executes from the beginning. The fix requires returning updated state rather than relying on in-place mutations.

### LangChain Academy Issue #40 — \"Replay from checkpoint will run subsequent steps, not just replay it\"
- **URL:** https://github.com/langchain-ai/langchain-academy/issues/40
- **Date:** October 9, 2024
- **Status:** Open
- **Type:** (c)
- **Description:** The video instructor claimed replaying from a checkpoint would be fast because no re-execution happens. In practice, all subsequent steps re-execute — LLM calls, API requests, and interrupts fire again. Performance expectations and documentation are misaligned with actual behavior.

### Official Documentation Warning (Time Travel)
- **URL:** https://docs.langchain.com/oss/python/langgraph/use-time-travel
- **Key Quote:** *\"Replay re-executes nodes—it doesn't just read from cache. LLM calls, API requests, and interrupts fire again and may return different results.\"*
- **Type:** (b) + (c)

### LangChain Issue #33787 — \"Agent re-attempts original tool call after HumanInTheLoopMiddleware edit decision\"
- **URL:** https://github.com/langchain-ai/langchain/issues/33787
- **Date:** November 2, 2025
- **Status:** Open
- **Type:** (a) + (c)
- **Description:** After a human edits a tool call via middleware, the edited call executes correctly (email sent to `alice@test.com`). The agent then re-evaluates state, concludes the original request is unfulfilled, and generates a new call targeting the original (unedited) address. Root cause: direct mutation of `AIMessage.tool_calls` is not persisted by LangGraph's state management.

### Discussion #3000 — \"Duplicate tool calls, finally hits recursion limit\"
- **URL:** https://github.com/langchain-ai/langgraph/discussions/3000
- **Type:** (a) — Duplicate tool calls in production

---

## Framework 2: CrewAI (crewAIInc/crewAI)

### Issue #1978 — \"[BUG] crew is running twice every time it is called\"
- **URL:** https://github.com/crewAIInc/crewAI/issues/1978
- **Date:** January 27, 2025
- **Status:** Closed (Not Planned)
- **Type:** (a) Duplicate tool execution
- **Description:** The `kickoff()` function runs twice, causing all tasks to execute twice. Specifically: a communications crew with email-sending tools sends emails twice per invocation. Direct quote: *\"the kickoff function for the crew is being called twice which result in the crew performing the task twice.\"* The issue was auto-closed after 30 days with no resolution.

### Issue #2881 — \"Tool Called Multiple Times in CrewAI v0.121.0\"
- **URL:** https://github.com/crewAIInc/crewAI/issues/2881
- **Date:** May 22, 2025
- **Status:** Closed (Not Planned)
- **Type:** (a)
- **Description:** Regression in v0.121.0 where tools are invoked repeatedly despite successful first execution. Causes `RecursionError: maximum recursion depth exceeded`. A contributor traced the issue to an interaction with the Rich library's console output.

### Issue #2209 — \"[BUG] agent calling tool twice for same input\"
- **URL:** https://github.com/crewAIInc/crewAI/issues/2209
- **Date:** February 24, 2025
- **Status:** Closed (Completed)
- **Type:** (a)
- **Description:** A custom `QuestionsAskingTool` that sends questions through WebSocket was invoked twice with identical input, causing duplicate WebSocket messages. A fix was merged in PR #2210 addressing `_check_tool_repeated_usage`.

### Issue #1776 — \"[BUG] Replay feature not working as expected\"
- **URL:** https://github.com/crewAIInc/crewAI/issues/1776
- **Date:** December 17, 2024
- **Status:** Closed (Not Planned)
- **Type:** (c) Replay causing unintended actions
- **Description:** Running `crewai replay -t <task_id>` re-executes all tasks including resource-intensive ones, rather than using cached results. Documentation gives no warning about side effects of replaying tasks with external API calls.

### Community post — \"crewAI is executing the task multiple times in a loop\"
- **URL:** https://community.crewai.com/t/crewai-is-executing-the-task-multiple-times-in-a-loop/743
- **Date:** October 12, 2024
- **Type:** (a) — Unresolved loop execution

### Issue #416 — \"Agents work twice in every run\"
- **URL:** https://github.com/crewAIInc/crewAI/issues/416
- **Type:** (a) — Early documented instance of dual execution

---

## Framework 3: Google ADK (google/adk-python)

### Official Documentation — Session Rewind side-effect warning
- **URL:** https://google.github.io/adk-docs/sessions/session/rewind/
- **Type:** (b) Checkpoint-restore side effects — **Most explicit official warning found in any framework**
- **Key Quote:** *\"The rewind feature does not manage external dependencies. If a tool in your agent interacts with external systems, it is your responsibility to handle the restoration of those systems to their prior state.\"*
- Additional warning: *\"State updates, artifact updates, and event persistence are not performed in a single atomic transaction. Therefore, you should avoid rewinding active sessions or concurrently manipulating session artifacts during a rewind to prevent inconsistencies.\"*
- **Description:** The ADK v1.17 Session Rewind feature restores session-level state but explicitly cannot roll back external API calls, emails sent, or database writes. After rewind, tools could be invoked again against external systems unless the developer manually implements idempotency.

### Issue #3940 — \"Tool Call has been called multiple times by ADK\"
- **URL:** https://github.com/google/adk-python/issues/3940
- **Date:** December 17, 2025
- **Status:** Open (Bug)
- **Type:** (a) + (d)
- **Description:** A custom MongoDB semantic search tool (`generate_test`) is called in an infinite loop because it takes >10 seconds and the LLM retriggers without waiting. Root cause: *\"base_llm_flow.py has no tool call tracking.\"* The `LongRunningFunctionTool` adds instructions but does not enforce single execution.

### Issue #3395 — \"[Live] Multiple responses after agent transfer and repeat response on session resumption\"
- **URL:** https://github.com/google/adk-python/issues/3395
- **Date:** November 5, 2025
- **Status:** Closed (Completed)
- **Type:** (b) + (c)
- **Description:** Upon reconnecting using `SessionResumption` after an agent transfer, the session history is only restored to the transfer point, causing the agent to respond again to the query that triggered the transfer. The N+1 response pattern during transfers also causes audio conflicts and redundant transcriptions.

### Issue #3207 — \"Duplicated/wrong events when using A2A agent in streaming mode\"
- **URL:** https://github.com/google/adk-python/issues/3207
- **Type:** (a) — Duplicate events in A2A streaming

### Discussion #3187 — \"Tool and LLM retry mechanisms and checkpoints\"
- **URL:** https://github.com/google/adk-python/discussions/3187
- **Date:** October 15, 2025
- **Type:** (d) — Feature request for checkpoint-based recovery
- **Description:** A user requests checkpoint-based recovery and retry for tool calls that fail due to hallucinated tool names or schema mismatches, noting there is *\"no reliable way to reroute to an earlier step (or even retry the failed event)\"*.

---

## Framework 4: Microsoft AutoGen (microsoft/autogen)

### Discussion #6595 — \"Autogen: Why is my first node in GraphFlow called twice?\"
- **URL:** https://github.com/microsoft/autogen/discussions/6595
- **Date:** May 26–27, 2025
- **Status:** Resolved in v0.5.8
- **Type:** (a)
- **Description:** The entry node `start_agent` in a GraphFlow executes twice, producing two messages with contradictory statuses (\"ok\" and \"error\"), activating both conditional branches simultaneously. Both downstream agents execute when only one should.

### Discussion #5806 — \"Checkpoint team while it is running\"
- **URL:** https://github.com/microsoft/autogen/discussions/5806
- **Date:** March 4, 2025
- **Type:** (b) + (d)
- **Description:** Feature request for emitting `CheckpointEvent` during team execution. A maintainer noted that resuming from checkpoints is *\"an exercise for the developer\"*, requiring agents be written as idempotent actors. The framework provides no built-in checkpointing for teams.

### Issue #6882 — \"TeamTool fails to execute twice for one Agent\"
- **URL:** https://github.com/microsoft/autogen/issues/6882
- **Type:** (a) — TeamTool breaks on second invocation

---

## Framework 5: Microsoft Semantic Kernel (microsoft/semantic-kernel)

### Issue #13435 — \"New Feature: Deterministic execution, replay, and audit gaps for long-running Semantic Kernel agent workflows\"
- **URL:** https://github.com/microsoft/semantic-kernel/issues/13435
- **Date:** January 2, 2026
- **Status:** Open
- **Type:** (b) + (d) — Feature request exposing absence of protection
- **Description:** When multi-step agent processes fail mid-execution, there is *\"no reliable way to determine which steps completed [or] which external side effects occurred.\"* The framework has no execution checkpoints, no side-effect classification, no memory versioning, and no deterministic replay capability. Key gaps: teams must construct custom infrastructure to avoid duplicating already-executed side effects on resume.

---

## Framework 6: OpenAI Agents SDK (openai/openai-agents-python)

### Issue #1789 — \"Duplicate item found with id fc_xxxx when using conversation_id with function calling\"
- **URL:** https://github.com/openai/openai-agents-python/issues/1789
- **Type:** (a) — Duplicate function call items corrupt conversation state

### Issue #1814 — \"Agent responses are repeated multiple times\"
- **URL:** https://github.com/openai/openai-agents-python/issues/1814
- **Type:** (a) — Response duplication

### Issue #2171 — \"Bug: Next agent receives duplicate history when nest_handoff_history is enabled\"
- **URL:** https://github.com/openai/openai-agents-python/issues/2171
- **Type:** (a) — Duplicate tool calls and outputs in handoff history

---

## Framework 7: Claude Code (anthropics/claude-code)

### Issue #13897 — \"Agent calls tools twice after permission approval, causing redundant executions\"
- **URL:** https://github.com/anthropics/claude-code/issues/13897
- **Date:** December 13, 2025
- **Status:** Closed (Not Planned)
- **Type:** (a) — Duplicate tool execution on permission approval
- **Description:** After a user approves a permission-denied tool call, Claude Code runs the original approved call AND generates a new redundant invocation. The `mcp__sdkman__install_sdkman` tool installed SDKMAN successfully, then immediately ran again, reporting \"already installed.\" Key quote: *\"Claude Code incorrectly makes a second tool call after a user approves a permission-denied tool execution. This causes the tool to execute twice and produces confusing results.\"*

### Issue #10871 — \"[BUG] Plugin-registered hooks are executed twice with different PIDs\"
- **URL:** https://github.com/anthropics/claude-code/issues/10871
- **Date:** November 2, 2025
- **Status:** Open
- **Type:** (a) — All hook types (SessionStart, Notification, PreCompact) fire twice as separate processes

### Issue #24115 — \"Plugin hooks fire twice: marketplace source + cache both loaded\"
- **URL:** https://github.com/anthropics/claude-code/issues/24115
- **Type:** (a) — Every hook event fires twice due to double loading

### Issue #9433 — \"[BUG] API Error: 400 due to tool use concurrency issues. Run /rewind to recover the conversation\"
- **URL:** https://github.com/anthropics/claude-code/issues/9433
- **Date:** October 12, 2025
- **Status:** Closed (duplicate of #8763)
- **Type:** (b) — State corruption from parallel tool invocations; `/rewind` proposed as recovery but often fails
- **Description:** Parallel tool invocations corrupt conversation state: `tool_use` blocks are sent to the API without corresponding `tool_result` blocks. The `/rewind` recovery command frequently fails to actually restore state, leaving conversations unrecoverable.

### Issue #27387 — \"Rewind UX: code+conversation rewind should not be default and needs confirmation\"
- **URL:** https://github.com/anthropics/claude-code/issues/27387
- **Date:** February 21, 2026
- **Status:** Open
- **Type:** (b) — Destructive checkpoint restore without warning
- **Description:** The default rewind option silently reverts both conversation history AND file changes. Key quote: *\"Having 'rewind everything' as the default is roughly equivalent to putting `rm -rf` as the first option in a context menu.\"*

---

## Framework 8: OpenClaw (openclaw/openclaw)

### Security Advisory — \"Nextcloud Talk webhook replay could trigger duplicate inbound processing\"
- **URL:** https://github.com/openclaw/openclaw/security/advisories/GHSA-r9q5-c7qc-p26w
- **Date:** February 26, 2026
- **Severity:** Moderate (CWE-294: Authentication Bypass by Capture-replay)
- **Type:** (c) Replay causing unintended actions — **Security vulnerability**
- **Description:** The webhook verification used `HMAC(secret, random + body)` without persistent replay protection. A captured valid signed request could be replayed, triggering duplicate inbound processing. Patched in v2026.2.25 with persistent deduplication and pre-execution origin validation.

### Issue #29106 — \"Gateway delivery-recovery replays already-delivered messages after restart\"
- **URL:** https://github.com/openclaw/openclaw/issues/29106
- **Date:** February 27, 2026
- **Status:** Open (Fixed)
- **Type:** (b) + (c)
- **Description:** If the gateway is restarted between delivery completion and queue-file removal, the queue entry persists and messages are replayed on restart — including messages up to weeks old. Root cause: no atomic acknowledgment. The fix applied a two-phase commit using atomic rename.

### Issue #9167 — \"[Bug]: boot-md hook fires multiple times during gateway startup (causes duplicate messages)\"
- **URL:** https://github.com/openclaw/openclaw/issues/9167
- **Date:** February 4, 2026
- **Status:** Closed (Not Planned)
- **Type:** (a) + (b)
- **Description:** A hook named `runBootOnce` fires 8–9 times within 30 seconds during startup. Each execution sends the agent's BOOT.md instructions to channels, resulting in message spam. Quote: *\"Each time, the agent receives the same boot prompt and dutifully executes BOOT.md, sending duplicate messages.\"*

### Issues #34039 / #34041 — \"[Queued messages] causes duplicate delivery\"
- **URL:** https://github.com/openclaw/openclaw/issues/34039
- **Date:** March 4, 2026
- **Status:** Closed (duplicate of #25192; fixed in PR #33168)
- **Type:** (a) + (b)
- **Description:** Messages queued while an agent is busy are delivered twice after the agent becomes idle. Root cause: the queue dedupe check only applies to items currently in-queue; once drained, items can be re-enqueued.

### Issue #18870 — \"[Bug]: Agent sends duplicate/repetitive messages to Telegram during long tool-call sequences\"
- **URL:** https://github.com/openclaw/openclaw/issues/18870
- **Date:** February 17, 2026
- **Status:** Closed (Fixed in PR #18956)
- **Type:** (a)

---

## Framework 9: Cursor IDE (forum.cursor.com)

### Forum post — \"'Restore Checkpoint' permanently destroys change history\"
- **URL:** https://forum.cursor.com/t/restore-checkpoint-permanently-destroys-change-history/129652
- **Date:** August 14, 2025
- **Status:** Closed for investigation
- **Type:** (b) — Destructive checkpoint restore; agent proceeds without restoring files

### Forum post — \"Editing agent terminal commands still runs the original command\"
- **URL:** https://forum.cursor.com/t/editing-agent-terminal-commands-still-runs-the-original-command/145507
- **Date:** December 8, 2025
- **Type:** (c) — User edits are ignored; original command executes regardless

### Forum post — \"In 2.0 undo checkpoint is not agent-independent\"
- **URL:** https://forum.cursor.com/t/in-2-0-undo-checkpoint-is-not-agent-independent/139630
- **Date:** October 30, 2025
- **Status:** Acknowledged by staff as *\"critical regression\"*
- **Type:** (b) — Undoing one agent's checkpoint reverts changes across all active agents

### Forum post — \"Command being sent to Agent twice\"
- **URL:** https://forum.cursor.com/t/command-being-sent-to-agent-twice/145842
- **Type:** (a) — Same command queued and executed twice

---

## Framework 10: Pydantic AI (pydantic/pydantic-ai)

### Issue #1391 — \"Duplicated results when streaming with tool calls\"
- **URL:** https://github.com/pydantic/pydantic-ai/issues/1391
- **Date:** April 6, 2025
- **Status:** Closed (Fixed in PR #3777)
- **Type:** (a)
- **Description:** Tool call messages are yielded twice during streaming, causing duplicate entries in message history and OpenAI API errors: *\"Duplicate item found with id... Remove duplicate items from your input and try again.\"*

### Issue #642 — \"Interrupt before making a tool call (human in the loop)\"
- **URL:** https://github.com/pydantic/pydantic-ai/issues/642
- **Type:** (d) — Feature request for safe human-in-the-loop checkpoint/resume to prevent unsafe tool side effects

---

## Framework 11: OpenHands / All-Hands-AI

### Issue #9595 — \"[Bug]: Messages are sent twice and agent is invoked twice\"
- **URL:** https://github.com/All-Hands-AI/OpenHands/issues/9595
- **Date:** July 7, 2025
- **Status:** Closed (Completed, August 5, 2025)
- **Type:** (a) — Duplicate agent invocation with real side effects
- **Description:** Clicking \"Push to Branch\" launched two agents running in parallel on the same container. Both agents attempted the same work, generating duplicate git commits. Key quote: *\"one agent did the actual work and the second agent got confused due to the work already being done but still found something to do and committed it.\"*

---

## Framework 12: Vercel AI SDK (vercel/ai)

### Issue #7261 — \"Double answers / Repeated tool-calls issue\"
- **URL:** https://github.com/vercel/ai/issues/7261
- **Date:** July 13, 2025
- **Status:** Closed (Completed)
- **Type:** (a) — Database writes triggered redundantly
- **Description:** The `generateChatTitle` tool is invoked repeatedly with identical inputs. Database updates trigger redundantly. Root cause: misalignment between UI message IDs and model message IDs causes duplicate message creation.

---

## Framework 13: LiveKit Agents (livekit/agents)

### Issue #4219 — \"preemptive_generation=True causes duplicate LLM requests and doubled token costs\"
- **URL:** https://github.com/livekit/agents/issues/4219
- **Date:** December 10, 2025
- **Status:** Open
- **Type:** (a) + (d)
- **Description:** Two complete LLM requests execute per user turn when context changes during preemptive generation phase. Both requests complete with `cancelled=False`. If tool calls are invoked in either request, they could execute multiple times.

### Issue #3414 — \"I think the current implementation of preemptive generation is wrong\"
- **URL:** https://github.com/livekit/agents/issues/3414
- **Date:** September 12, 2025
- **Status:** Closed (Not Planned)
- **Type:** (a)
- **Description:** Business logic callbacks (`on_user_turn_completed`, `tts_node`) can trigger multiple times due to duplicate transcription results. Quote: *\"tool calls and parameters might change during preemptive generation itself, and the final results that we expect might not be the same as what get executed.\"*

---

## Framework 14: Microsoft VS Code Copilot (microsoft/vscode)

### Issue #262313 — \"Copilot Chat checkpoint restore intermittently fails - data loss risk\"
- **URL:** https://github.com/microsoft/vscode/issues/262313
- **Date:** August 19, 2025
- **Status:** Open
- **Type:** (b) — Silent checkpoint restore failure with data loss
- **Description:** Checkpoint restore silently fails with no error message in agent mode. One user was *\"saved only by file history + git staged changes.\"* Restores can also revert changes in files unrelated to the checkpoint, causing unnoticed data loss.

---

## Framework 15: n8n (agentic workflow)

### Community post — \"Stopping duplicate Stripe charges in n8n (webhook retries)\"
- **URL:** https://community.n8n.io/t/stopping-duplicate-stripe-charges-in-n8n-webhook-retries-simple-idempotency-pattern/272743
- **Type:** (a) + (d) — Real financial side effects from retry-induced duplicate execution
- **Description:** Stripe webhook retries cause n8n workflows to execute charges multiple times. *\"Customer gets charged twice.\"* The at-least-once delivery of webhooks combined with n8n treating each retry as a new trigger creates duplicate financial transactions.

### Community post — \"HTTP Request node executing twice\"
- **URL:** https://community.n8n.io/t/http-request-node-executing-twice-need-help-with-duplicate-execution/141038
- **Type:** (a)

---

## Hacker News Community Reports

### \"Show HN: SafeAgent – exactly-once execution guard for AI agent side effects\"
- **URL:** https://news.ycombinator.com/item?id=47294291
- **Date:** ~March 2026
- **Type:** (a) + (d) — Community tool solving the problem across frameworks
- **Description:** A Python library addressing duplicate execution of irreversible actions (emails, tickets, payments) across OpenAI tool calls, LangChain tools, and CrewAI actions. Quote: *\"retries can come from multiple layers (agent loops, orchestration frameworks, API retries, etc.).\"*

### \"Show HN: agent-ledger – prevent agents from executing duplicate tool calls\"
- **URL:** https://news.ycombinator.com/item?id=46933954
- **Date:** February 8, 2026
- **Type:** (a) + (d) — Community tool solving the problem
- **Description:** Hashes `(workflow_id, tool, args)` into idempotency keys stored in a ledger. Designed specifically for: *\"emails sent twice, tickets created multiple times\"* after crashes, webhook retries, or LLM timeouts.

### \"Ask HN: How do you handle duplicate side effects when jobs, workflows retry?\"
- **URL:** https://news.ycombinator.com/item?id=47175746
- **Date:** ~March 2026
- **Type:** (d) — Community acknowledgment of widespread problem

---

## Cross-Framework and Security Research

### DZone — \"Idempotency in AI Tools: Most Expensive Thing Teams Forget\"
- **URL:** https://dzone.com/articles/idempotency-in-ai-tools-most-expensive-mistake
- **Type:** (d) — Industry acknowledgment across multiple frameworks

### Jack Vanlightly — \"Remediation: What happens after AI goes wrong?\"
- **URL:** https://jack-vanlightly.com/blog/2025/7/28/remediation-what-happens-after-ai-goes-wrong
- **Type:** (b) — Analysis of irreversible side effects: *\"Once a file is permanently deleted from a local disk with no backup, it's gone.\"* Recommends journaling, immutable versioned data, and append-only logs as external safeguards.

### Inferable.ai — \"Building Reliable Tool Calling in AI Agents with Message Queues\"
- **URL:** https://www.inferable.ai/blog/posts/distributed-tool-calling-message-queues
- **Type:** (d) — Production-focused analysis. Code comment explicitly warns: *\"could raise duplicate POs!\"* (purchase orders) without idempotency protection.

### Microsoft Agent Framework Discussion #2305 — \"Workflow Checkpoints Limitations\"
- **URL:** https://github.com/microsoft/agent-framework/discussions/2305
- **Date:** November 18, 2025
- **Type:** (b) — Checkpoint state is in-memory only; in multi-pod deployments a resumed agent on a different pod loses checkpoint state.

---

## Summary Table

| Framework | Issues Found | Types | Most Critical |
|---|---|---|---|
| LangGraph | 8+ GitHub issues + blog + docs | (a)(b)(c)(d) | #6208: HITL double execution, nodes re-run on resume |
| CrewAI | 5 GitHub issues + community | (a)(c)(d) | #1978: crew runs twice, emails sent twice |
| Google ADK | 4 GitHub issues + official docs | (a)(b)(c)(d) | Official docs warn: rewind cannot undo external side effects |
| AutoGen | 2 discussions + 1 issue | (a)(b)(d) | #6595: GraphFlow first node called twice |
| Semantic Kernel | 1 issue | (b)(d) | #13435: No checkpoint/replay primitives exist |
| OpenAI Agents SDK | 3 issues | (a)(d) | #1789: duplicate function call items |
| Claude Code | 5 issues | (a)(b)(c) | #13897: tool called twice after permission approval |
| OpenClaw | 5 issues + 1 CVE | (a)(b)(c) | CVE: webhook replay security vulnerability |
| Cursor IDE | 4 forum posts | (b)(c) | Checkpoint not agent-independent; edits ignored |
| Pydantic AI | 2 issues | (a)(d) | #1391: duplicate streaming messages |
| OpenHands | 1 issue | (a) | #9595: two agents launched, duplicate git commits |
| Vercel AI SDK | 1 issue | (a) | #7261: duplicate DB writes from tool re-execution |
| LiveKit Agents | 2 issues | (a)(d) | #4219: preemptive generation fires tools twice |
| VS Code Copilot | 1 issue | (b) | #262313: silent checkpoint restore failure |
| n8n | 3 community posts | (a)(d) | Stripe charged twice from webhook retry |

**Classification key:** (a) duplicate tool execution, (b) checkpoint/restore side effects, (c) replay causing unintended actions, (d) idempotency concerns

Sources:
- [LangGraph Issue #6208](https://github.com/langchain-ai/langgraph/issues/6208)
- [LangGraph's HITL Has a Double Execution Problem](https://blog.raed.dev/posts/langgraph-hitl)
- [LangGraph Issue #6624](https://github.com/langchain-ai/langgraph/issues/6624)
- [LangGraph Issue #6626](https://github.com/langchain-ai/langgraph/issues/6626)
- [LangGraph Issue #4796](https://github.com/langchain-ai/langgraph/issues/4796)
- [LangGraph Issue #4397](https://github.com/langchain-ai/langgraph/issues/4397)
- [LangGraph Issue #6577](https://github.com/langchain-ai/langgraph/issues/6577)
- [LangChain Academy Issue #40](https://github.com/langchain-ai/langchain-academy/issues/40)
- [LangChain Time Travel Docs](https://docs.langchain.com/oss/python/langgraph/use-time-travel)
- [LangChain Issue #33787](https://github.com/langchain-ai/langchain/issues/33787)
- [CrewAI Issue #1978](https://github.com/crewAIInc/crewAI/issues/1978)
- [CrewAI Issue #2881](https://github.com/crewAIInc/crewAI/issues/2881)
- [CrewAI Issue #2209](https://github.com/crewAIInc/crewAI/issues/2209)
- [CrewAI Issue #1776](https://github.com/crewAIInc/crewAI/issues/1776)
- [Google ADK Rewind Docs](https://google.github.io/adk-docs/sessions/session/rewind/)
- [Google ADK Issue #3940](https://github.com/google/adk-python/issues/3940)
- [Google ADK Issue #3395](https://github.com/google/adk-python/issues/3395)
- [Google ADK Discussion #3187](https://github.com/google/adk-python/discussions/3187)
- [AutoGen Discussion #6595](https://github.com/microsoft/autogen/discussions/6595)
- [AutoGen Discussion #5806](https://github.com/microsoft/autogen/discussions/5806)
- [Semantic Kernel Issue #13435](https://github.com/microsoft/semantic-kernel/issues/13435)
- [OpenAI Agents Issue #1789](https://github.com/openai/openai-agents-python/issues/1789)
- [Claude Code Issue #13897](https://github.com/anthropics/claude-code/issues/13897)
- [Claude Code Issue #10871](https://github.com/anthropics/claude-code/issues/10871)
- [Claude Code Issue #9433](https://github.com/anthropics/claude-code/issues/9433)
- [Claude Code Issue #27387](https://github.com/anthropics/claude-code/issues/27387)
- [OpenClaw Security Advisory](https://github.com/openclaw/openclaw/security/advisories/GHSA-r9q5-c7qc-p26w)
- [OpenClaw Issue #29106](https://github.com/openclaw/openclaw/issues/29106)
- [OpenClaw Issue #9167](https://github.com/openclaw/openclaw/issues/9167)
- [OpenClaw Issue #34039](https://github.com/openclaw/openclaw/issues/34039)
- [Cursor Forum: Restore Checkpoint destroys history](https://forum.cursor.com/t/restore-checkpoint-permanently-destroys-change-history/129652)
- [Cursor Forum: Editing terminal commands runs original](https://forum.cursor.com/t/editing-agent-terminal-commands-still-runs-the-original-command/145507)
- [Cursor Forum: Undo checkpoint not agent-independent](https://forum.cursor.com/t/in-2-0-undo-checkpoint-is-not-agent-independent/139630)
- [Pydantic AI Issue #1391](https://github.com/pydantic/pydantic-ai/issues/1391)
- [OpenHands Issue #9595](https://github.com/All-Hands-AI/OpenHands/issues/9595)
- [Vercel AI Issue #7261](https://github.com/vercel/ai/issues/7261)
- [LiveKit Agents Issue #4219](https://github.com/livekit/agents/issues/4219)
- [VS Code Issue #262313](https://github.com/microsoft/vscode/issues/262313)
- [n8n Duplicate Stripe Charges](https://community.n8n.io/t/stopping-duplicate-stripe-charges-in-n8n-webhook-retries-simple-idempotency-pattern/272743)
- [Show HN: SafeAgent](https://news.ycombinator.com/item?id=47294291)
- [Show HN: agent-ledger](https://news.ycombinator.com/item?id=46933954)
- [Ask HN: Duplicate side effects in retries](https://news.ycombinator.com/item?id=47175746)
- [Jack Vanlightly: Remediation after AI goes wrong](https://jack-vanlightly.com/blog/2025/7/28/remediation-what-happens-after-ai-goes-wrong)
- [Inferable.ai: Distributed tool calling](https://www.inferable.ai/blog/posts/distributed-tool-calling-message-queues)
- [Microsoft Agent Framework Discussion #2305](https://github.com/microsoft/agent-framework/discussions/2305)
- [Top 9 AI Agent Frameworks - Shakudo](https://www.shakudo.io/blog/top-9-ai-agent-frameworks)
