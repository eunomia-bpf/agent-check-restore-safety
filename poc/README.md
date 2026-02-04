# Semantic Rollback PoC

## 概述

本 PoC 使用 **Claude Code 原生的会话机制** 来模拟 checkpoint-restore 场景，验证语义回滚安全漏洞。

## 核心方法

### Claude Code 会话机制

```bash
# 创建指定 ID 的会话
claude -p "task" --session-id <uuid>

# 恢复指定会话
claude -p "follow-up" --resume <session-id>

# 继续最近的会话
claude -p "follow-up" --continue
```

### 与 Checkpoint-Restore 的对应

| CR 概念 | Claude Code 实现 |
|--------|-----------------|
| Checkpoint | 会话创建 (`--session-id`) |
| Restore | 会话恢复 (`--resume`) |
| Agent 状态 | 会话历史（对话上下文） |
| 外部状态 | 不受会话机制影响 |

## 实验设计

### 测试逻辑

```
Scenario: resume/continue
  Run 1: "生成一个支付 ID" → 得到 ID1
  Run 2: (恢复会话) "你刚才生成的 ID 是什么？" → 得到 ID2
  检查: ID1 == ID2 ?
  - 如果相同 → 会话保留了 Agent 记忆
  - 如果不同 → Agent "遗忘"了 (可能存在漏洞)

Scenario: fresh (baseline)
  Run 1: "生成一个支付 ID" → 得到 ID1
  Run 2: (新会话) "生成一个支付 ID" → 得到 ID2
  检查: ID1 == ID2 ?
  - 预期不同 (LLM 非确定性)
```

### 预期结果

| 场景 | 预期相同率 | 实际结果 |
|------|-----------|---------|
| Fresh | ~0% (LLM 非确定性) | 0% ✓ |
| Resume | 应该高 (会话保留) | 50% ⚠️ |
| Continue | 应该高 (会话保留) | 50% ⚠️ |

## 运行方式

```bash
# 运行实验
python poc/realistic_poc.py --trials 3

# 指定模型
python poc/realistic_poc.py --trials 5 --model qwen3
```

## 发现

### 观察结果

1. **Fresh sessions: 0% 相同** - 验证了 LLM 的非确定性
2. **Resume/Continue: 50% 相同** - 会话机制部分有效，但不完全可靠

### 安全含义

```
情况 1: 会话机制有效 (50% 的情况)
  → Agent 记住了之前的操作
  → 不会重复执行
  → 安全 ✓

情况 2: 会话机制失效 (50% 的情况)
  → Agent "遗忘"了之前的操作
  → 可能生成不同的参数重新执行
  → 存在重复收费等风险 ⚠️
```

## 文件结构

```
poc/
├── realistic_poc.py      # 主 PoC 脚本
├── mcp_server/           # MCP 工具服务器 (可选)
├── results/              # 实验结果
└── README.md             # 本文档
```

## 局限性

1. **使用本地 LLM (Qwen3)**：行为可能与 Claude API 不同
2. **会话机制 ≠ 进程级 CR**：Claude Code 的 `--resume` 是对话历史恢复，不是真正的进程 checkpoint
3. **样本量小**：需要更多 trials 来获得统计显著性

## 下一步

1. 增加 trial 数量获得更可靠的统计
2. 使用真正的 MCP 工具测试外部状态不一致
3. 对比不同 LLM 模型的行为
4. 测试真正的 CRIU checkpoint-restore
