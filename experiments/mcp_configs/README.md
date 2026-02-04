# MCP Server Configurations

根据实验场景选择对应的 MCP 服务器配置。

## 配置文件

| 文件 | 场景 | 用途 |
|------|------|------|
| `mcp_bank.json` | V1-TM1 | 转账双花攻击 |
| `mcp_cloud.json` | V1-TM2 | 云资源重复创建 |
| `mcp_approval.json` | V2-TM2 | 审批绕过 + 支付欺诈 |
| `mcp_all.json` | 全部 | 所有场景（开发测试用）|

## 使用方法

```bash
# 复制对应配置到项目根目录
cp experiments/mcp_configs/mcp_bank.json .mcp.json

# 或者运行实验时指定
cd experiments
python -m experiments.exp1_action_replay --trials 5
```

## 场景与服务器对应

### 实验 1: Action Replay (V1)

| 场景 | 服务器 | 工具 |
|------|--------|------|
| V1-TM1 转账双花 | bank_server | check_balance, transfer |
| V1-TM2 云资源重复 | cloud_server | check_quota, create_server |

### 实验 2: Authority Resurrection (V2)

| 场景 | 服务器 | 工具 |
|------|--------|------|
| V2-TM2 审批绕过 | approval_server | request_approval, delete_customer_data |
| V2-TM2 支付欺诈 | approval_server | request_approval, execute_payment |
