# 实验日志 1: PoC 分析与改进讨论

**日期**: 2026-02-02
**参与者**: 研究者 + Claude

---

## 1. 当前 PoC 实现总结

### 1.1 实现了什么

`poc/simple_test.py` 实现了一个简化的 Action Duplication 测试：

```
流程:
1. Agent 收到任务: "Process payment $49.99 for order #001"
2. [CHECKPOINT] 用 Python deepcopy 保存 agent 状态
3. LLM 生成 tool call → idempotency_key_1 = "abc123"
4. Payment Service (内存) 执行 → charge 创建成功
5. [RESTORE] 用 Python deepcopy 恢复状态
6. LLM 再次生成 tool call → idempotency_key_2 = "xyz789"
7. Payment Service 执行 → 新 charge 创建 (重复!)
```

### 1.2 实验结果

运行 `python poc/simple_test.py --trials 5` 的结果：

| 指标 | 结果 |
|------|------|
| Key instability rate | 100% (5/5) |
| Duplicate rate | 100% (5/5) |

看起来漏洞被"确认"了？

---

## 2. 问题分析：当前 PoC 真的能说明安全问题吗？

### 2.1 核心问题

**当前 PoC 本质上只证明了：**

```
"LLM 是非确定性的"
      +
"idempotency key 由 LLM 生成"
      =
"两次调用产生不同的 key"
```

**这不需要 checkpoint-restore 也能发生！**

### 2.2 反例：不用 checkpoint 也能重现

```python
# 不需要任何 checkpoint，同样的问题
task = "Process payment for order #001"

key1 = llm.generate_tool_call(task)["idempotency_key"]  # "abc123"
key2 = llm.generate_tool_call(task)["idempotency_key"]  # "xyz789"

# key1 != key2，这只是 LLM 非确定性，不是 checkpoint 的问题
```

### 2.3 当前 PoC 的技术局限性

| 方面 | 当前实现 | 真实场景 |
|------|----------|----------|
| **Checkpoint 机制** | Python `deepcopy` | CRIU / Podman / VM Snapshot |
| **Agent 运行环境** | 单进程 Python | Container / VM |
| **Tool Service** | 内存中的 Python 类 | 独立的 HTTP 服务 + 数据库 |
| **状态持久化** | 无 | 数据库 / 文件系统 |
| **故障注入点** | 只有 P1 (发送前) | P1/P2/P3 |
| **并发/Fork** | 无 | 多实例并发 |

---

## 3. 与实验设计文档的对比

参考文档: `docs/experiment-design.md`

### 3.1 文档设计 vs 当前实现

| 方面 | 文档设计 | 当前 PoC | 状态 |
|------|----------|----------|------|
| **三类漏洞** | Action Duplication, Authority Resurrection, Fork Amplification | 只测了 Action Duplication | ⚠️ 缺 2/3 |
| **Checkpoint** | CRIU / Podman | Python `deepcopy` | ❌ 简化 |
| **Tool Service** | 独立 FastAPI + SQLite | 内存类 | ❌ 简化 |
| **注入点** | P1 / P2 / P3 | 只有 P1 | ❌ 缺失 |
| **RQ2 (Auth Resurrection)** | 详细设计 | 未实现 | ❌ 缺失 |
| **RQ3 (Fork Amplification)** | 详细设计 | 未实现 | ❌ 缺失 |
| **Baselines** | No-CR, Det-Replay | 无 | ❌ 缺失 |

### 3.2 文档中的关键设计（当前缺失）

**架构隔离原则 (文档第 72 行):**
```
关键设计原则:
1. 隔离 checkpoint 边界: Agent container 被 checkpoint，Tool Services 不被 checkpoint
```

**RQ2 - Authority Resurrection (文档第 391-450 行):**
```python
def run_auth_trial(validation_mode, trial_id):
    token = auth_service.issue_token(single_use=True)
    agent.receive_token(token)
    checkpoint_id = checkpoint_agent(agent)  # Token 在 Agent 内存中

    result1 = agent.use_token(token)         # 使用 token
    assert auth_service.is_consumed(token)   # 外部标记为已消耗

    restored_agent = restore_agent(checkpoint_id)  # 恢复到 checkpoint
    result2 = restored_agent.use_token(token)      # 尝试再次使用

    # 如果 result2.valid == True，说明已消耗的 token 被复活了！
```

**RQ3 - Fork Amplification (文档第 452-505 行):**
```python
def run_fork_trial(fork_count, quota, trial_id):
    checkpoint_id = checkpoint_agent(agent)

    # 从同一个 checkpoint Fork N 个实例
    forked_agents = [restore_agent(checkpoint_id) for _ in range(fork_count)]

    # 并发执行 - 每个实例都认为自己有完整的 quota
    with ThreadPoolExecutor(max_workers=fork_count) as executor:
        results = executor.map(lambda a: a.create_vm(), forked_agents)

    # 检查：创建的 VM 数量是否超出 quota？
    total_vms = provisioning_service.count_created_vms()
    # 如果 total_vms > quota，漏洞确认！
```

---

## 4. 真正的安全问题是什么？

### 4.1 Checkpoint-Restore 引入的独特问题

| 问题 | 描述 | 当前 PoC 是否测试 |
|------|------|------------------|
| **状态不一致** | Agent 内部状态被回滚，但外部状态（数据库、API）不回滚 | ❌ |
| **Authority Resurrection** | 已撤销/消耗的 token 在 restore 后重新出现在 Agent 内存中 | ❌ |
| **Fork Amplification** | 从同一 checkpoint 恢复多个实例，每个都认为有完整权限 | ❌ |
| **P2 In-flight Crash** | 请求已发送但响应未收到时 crash，外部已执行但 Agent 不知道 | ❌ |

### 4.2 为什么当前 PoC 不够？

当前 PoC 测试的 "idempotency key 变化" 实际上是：
- **LLM 非确定性问题**，不是 checkpoint-restore 问题
- 没有 checkpoint 也会发生
- 没有证明是 checkpoint 引入的新风险

真正的安全问题应该是：
- **有 checkpoint 才会发生**
- **没有 checkpoint 不会发生**
- 需要 baseline 对比来证明

---

## 5. 改进建议

### 5.1 最小改动方案

**优先级 1: 实现 RQ2 (Authority Resurrection)**

```python
def test_authority_resurrection():
    # 1. 给 Agent 一个 single-use token
    token = auth_service.issue_token(single_use=True)
    agent.credentials["token"] = token

    # 2. Checkpoint
    saved_state = checkpoint(agent)

    # 3. Agent 使用 token
    result = agent.use_token(token)
    assert result.success == True

    # 4. 外部服务标记 token 为 consumed
    assert auth_service.is_consumed(token) == True

    # 5. Restore
    agent = restore(saved_state)  # Agent 内存中仍有 token

    # 6. 尝试再次使用
    result = agent.use_token(token)

    # 7. 检查：如果成功，说明 token 被复活了
    if result.success:
        print("VULNERABILITY: Authority Resurrection confirmed!")
```

这个测试能明确说明：
- Token 在 checkpoint 时是有效的
- Token 被使用后，外部已标记为 consumed
- Restore 后 Agent 不知道 token 已消耗
- **问题来自 checkpoint-restore 的状态不一致**

**优先级 2: 添加 No-CR Baseline**

```python
def test_no_checkpoint_baseline():
    # 不做 checkpoint，直接执行两次
    key1 = agent.generate_tool_call(task)
    payment_service.execute(key1)

    # 不恢复，直接再次生成
    key2 = agent.generate_tool_call(task)
    result = payment_service.execute(key2)

    # 在正常流程中，Agent 应该知道任务已完成，不会重复执行
    # 如果这里也产生重复，说明问题不是 checkpoint 引入的
```

**优先级 3: 实现 P2 注入点**

```python
def test_p2_inflight_crash():
    tool_call = agent.generate_tool_call(task)

    # 发送请求
    http_client.send_async(tool_call)

    # [CHECKPOINT HERE] - 请求已发出，但还没收到响应
    saved_state = checkpoint(agent)

    # 请求完成
    response = http_client.wait_response()

    # [CRASH & RESTORE]
    agent = restore(saved_state)

    # Agent 不知道请求已完成，会重新执行
    # 这次可能生成不同的 key，绕过 idempotency
```

### 5.2 完整实现路线图

| 阶段 | 任务 | 复杂度 | 优先级 |
|------|------|--------|--------|
| 1 | 实现 RQ2 (Authority Resurrection) | 低 | ⭐⭐⭐ |
| 2 | 添加 No-CR Baseline | 低 | ⭐⭐⭐ |
| 3 | 实现 P2 注入点 | 中 | ⭐⭐ |
| 4 | Tool Service 独立进程化 | 中 | ⭐⭐ |
| 5 | 实现 RQ3 (Fork Amplification) | 中 | ⭐⭐ |
| 6 | 使用真实 CRIU/Podman | 高 | ⭐ |

---

## 6. 结论

### 6.1 当前状态

- ✅ 实验设计文档 (`experiment-design.md`) 设计合理，覆盖了真正的安全问题
- ⚠️ 当前 PoC (`simple_test.py`) 只实现了简化版本，不能有效说明安全问题
- ❌ 缺少 RQ2, RQ3 的实现
- ❌ 缺少 baseline 对比

### 6.2 核心问题

当前 PoC 只能证明 "LLM 是非确定性的"，这不是新发现，也不需要 checkpoint-restore。

要证明 checkpoint-restore 引入了安全问题，需要：
1. 测试 Authority Resurrection（token 复活）
2. 测试 Fork Amplification（quota 突破）
3. 有 No-CR baseline 作为对照

### 6.3 下一步

1. 实现 RQ2 (Authority Resurrection) PoC
2. 添加 No-CR baseline
3. 更新文档记录实验进展

---

## 附录: 文件结构

```
poc/
├── simple_test.py                        # 当前 PoC (RQ1 简化版)
├── run_poc_with_claude_code_local_llm.py # Claude Code 运行器
└── results/
    ├── experiment_*.json                 # 实验结果
    └── claude_code_runs/                 # Claude Code 运行记录
        └── run_*/
            ├── run_result.json
            ├── tool_calls.json
            ├── conversation.json
            └── session_full.jsonl

docs/
├── experiment-design.md                  # 完整实验设计
├── claude-code-local-llm.md              # Claude Code 本地 LLM 配置
└── exp_log1.md                           # 本文档
```
