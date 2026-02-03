# 使用本地 LLM 运行 Claude Code

## 前提条件

1. llama.cpp 已编译并安装
2. 模型已下载

## 启动 llama-server

```bash
cd /home/yunwei37/workspace/gpu/llama.cpp

build/bin/llama-server \
    -hf unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:Q4_K_M \
    -c 65536 \
    --port 8080 \
    --jinja   # 重要：支持工具调用
```

**注意**：`--jinja` 标志是必须的，否则工具调用不会工作。

## 配置环境变量

添加到 `~/.bashrc` 或 `~/.zshrc`：

```bash
export ANTHROPIC_BASE_URL="http://localhost:8080"
export ANTHROPIC_AUTH_TOKEN="llama"  # 任意非空值
export ANTHROPIC_API_KEY=""          # 必须为空！
```

然后执行：

```bash
source ~/.bashrc  # 或 source ~/.zshrc
```

## 运行 Claude Code

```bash
# 使用模型别名
claude --model qwen3

# 或使用完整模型名
claude --model unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:Q4_K_M
```

## 一键启动脚本

```bash
# 启动服务器
./scripts/start_llm_server.sh

# 运行 Claude Code
ANTHROPIC_BASE_URL="http://localhost:8080" \
ANTHROPIC_AUTH_TOKEN="llama" \
ANTHROPIC_API_KEY="" \
claude --model qwen3
```

## 故障排除

### 工具调用不工作
- 确保 llama-server 启动时添加了 `--jinja` 标志

### 连接被拒绝
- 检查服务器是否在运行：`curl http://localhost:8080/health`
- 检查端口是否正确

### 模型不支持工具调用
- 不是所有模型都支持工具调用
- 推荐使用编码能力强的模型：Qwen3-Coder, Devstral, GLM-4

## 支持的模型推荐

| 模型 | 大小 | 最低内存 | 备注 |
|------|------|----------|------|
| devstral-small-2 | 24B | 32GB | 编码质量好 |
| qwen3-coder:30b | 30B | 32GB | 编码能力强 |
| GLM4.7-flash:q8_0 | 30B | 32GB | 性价比高 |
| Qwen3-Next-80B-A3B | 80B | 64GB+ | 当前使用 |

## 参考

- [Run Claude Code on Local/Cloud Models](https://medium.com/@luongnv89/run-claude-code-on-local-cloud-models-in-5-minutes-ollama-openrouter-llama-cpp-6dfeaee03cda)
- [llama.cpp GitHub](https://github.com/ggml-org/llama.cpp)
