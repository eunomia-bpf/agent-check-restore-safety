# CSF Paper Editing Contract

本文件是后续编辑的唯一标准。不得重新引入旧版术语与故事线；不得新增模型、术语、定理、贡献、实验或 claim。

## 1. Central Thesis

**首选**

> An execution edit is safe exactly when the protected execution record supports ways to continue that respect past authorizations and keep every still-required result safely completable throughout execution; exact checking and atomic installation make that condition enforceable at runtime.

**备选 1**

> Restoring workspace state is insufficient for security: a runtime must derive each execution edit from the protected execution record, allow execution only while every required result remains completable, and install that decision atomically.

**备选 2**

> The security of Checkpoint, Fork, Restore, and Merge depends on preserving the connection between recorded authorizations and future required outcomes across both checking and runtime installation.

### Plain-English Thesis (for editing only)

> Changing a running Agent workflow is safe only when the runtime uses its protected record to respect earlier approvals, keep every required result achievable, and enforce that decision without a race.

## 2. 唯一故事线

1. **现实安全问题：** Checkpoint、Fork、Restore 和 Merge 会改变未来执行，却不会撤销已经授权或发出的外部动作，因此不可信 Agent 可能重复获得授权或丢弃可信方仍要求的结果。
2. **已有方法为什么不够：** recovery、transaction 和 synthesis 分别处理回滚、提交或给定模型，但不会从一次具体执行的受保护记录中共同推导该 edit 必须保留什么。

> 为什么 checkpoint、transaction 和 workflow synthesis 都不能解决这个问题？

这一问题必须在论文第一页得到明确回答，并成为后续 execution record 出现的直接动机。

3. **Execution record：** runtime 因而需要自己保护的事实来源，记录 workflow/outcomes、call-to-action identity、authorization/progress 和活动规则版本。
4. **Execution edit：** Agent 只能请求已注册的变换；runtime 根据记录推导目标 workflow、仍需结果以及新授权或授权复用，而不接受 Agent 自述的替代历史。
5. **Exact checker：** checker 删除违反 policy 或会让 compatible required outcome 无法完成的执行，并返回 `Invalid`、带证明的 `Reject` 或最大的安全继续集合。
6. **Runtime installation：** 接受结果仍可能过期，因此 runtime 在生效前重新检查记录，并原子关闭旧规则、安装新规则和 token。
7. **Preservation：** 原子切换使并发 call 明确落在更新之前或之后，并让同一安全条件在后续 calls、edits、stops 和 restarts 中继续成立。
8. **Validation：** 手写证明覆盖一般理论，Lean 覆盖有限线性核心与生命周期保持，Python 覆盖有界 checker 实例和时间；三者共同支持但不扩大上述保证。

## 3. 三项 Contribution

1. **缺失的安全状态与判定目标。** 以前只看 workspace、trace 或 authorization log 不能判断 edit 是否仍尊重过去授权和未来义务；本文以受保护 execution record 建立安全条件，并说明精确判定需要哪四类事实；reviewer 获得明确的安全输入、信任边界和必要性依据。
2. **精确的 edit 准入判定。** 以前只检查终点或逐 outcome 检查可能接受会在执行中途卡死必要结果的 edit；本文通过最大不动点返回最大安全继续集合或不存在安全实现的证明；reviewer 获得同时说明 safety 与 permissiveness 的判定结果。
3. **可持续执行的判定。** 以前离线 checker 结果可能被并发 call 变成 stale，且一次性安全结论不足以覆盖重复 edit 和 restart；本文用重新检查、原子规则安装和 invariant preservation 连接 checker 与 runtime；reviewer 获得一个条件化、可执行且证据范围清楚的端到端保证。

**Editing rule:**

Contribution 只能说明：

- 以前不能做什么；
- 本文解决什么；
- reviewer 得到什么。

Contribution 不允许引用 theorem 名称，不允许写 “We prove...”、“Theorem X...” 等证明导向表达。

## 4. Scope 与证据边界

**本文证明：**

- 对有限、可信注册的 workflow，Checkpoint 及六种 Fork/Restore/Merge edit 的目标可由 execution record 确定地推导。
- checker 接受当且仅当存在满足正文安全条件的 runtime implementation；空 fixed point 给出拒绝证明。
- workflow/required outcomes、action identity、authorization/progress 和 concurrent rule version 四类记录对精确判定均不可省。
- 在完整中介、可信注册、认证记录和持久可线性化事务等假设下，安全性在有限 calls、edits、stops 和 restarts 中保持，runtime 与理想原子机在声明的 API 观测下对应。

**本文没有证明：**

- 不从自然语言、任意 workspace diff 或 Merge 自动推断 workflow intent、action identity、outcome authority 或 edit semantics。
- 不证明现实 runtime hooks 实现 complete mediation，也不证明 remote service/sink 如实报告 completion。
- 不提供与当前 exact checker 完整对齐的生产 runtime prototype、真实 lifecycle traces、端到端性能或部署可行性结论。
- 旧 authority-continuity adapter 不作为当前模型的 runtime 实现证据。

**各证据真正覆盖：**

- **手写证明：** general pomset lift、source-outcome preservation、具体 record-pair lower bound、rechecking/repeated use 和 ideal/runtime weak bisimulation。
- **Lean：** finite linear-contract core、registration、六种 edit derivation、atomic installation、call/update 两种顺序以及有限 trace 上的 `AgentSec` preservation；不等同于全文一般理论全部机械化。
- **Python：** 有界 fixed-point checker、接受/拒绝反例、rejection data 和所报告实例规模下的 checker 时间；不验证生产 runtime。
- **Runtime：** 正文给出形式化事务协议和 ideal/runtime 对应，而非已部署实现或性能评价。

### Evidence Mapping Rule

论文正文中的每一个核心 claim 都必须能明确对应唯一主要证据来源（Handwritten proof、Lean、Python 或 Runtime model）。正文不得让同一个 claim 同时依赖多个证据而不说明各自覆盖范围，避免 reviewer 误以为 Lean、Python 或 Runtime 覆盖了超出论文实际证明范围的内容。

## 5. Reviewer 最关心的五个问题

| Reviewer question | 正文责任位置 |
|---|---|
| Restore/Fork/Merge 为什么构成 security failure，而不只是 workflow bug？ | Abstract、Introduction、Section II |
| checker 为什么必须看到 execution record 的四类事实？ | Introduction、Section III、Necessary Record Information theorem |
| `Invalid`、`Reject`、`Accepted` 分别表示什么，为什么 fixed point 是 exact 的？ | Section IV、Exact Safety Checking theorem |
| 一个接受结果如何在并发 calls、重复 edits 和 restart 下持续安全？ | Section V、Repeated-Use Safety 与 Runtime Correctness theorems |
| 五个 theorem 分别由什么证据支持，哪些内容没有验证或实现？ | Section VI、Section VII、Supplementary Appendix |

## 6. Running Example

当前学校采购例子足够作为唯一 running example：一次审批、供应商 \(L/R\)、付款、发货、Restore 和 Merge 已能覆盖重复授权、互斥 outcome、顺序约束、authorization reuse 和规则更新竞态。不得新增第二个例子。

需要持续回指该例子的部分仅包括：Section III 的 call/action/outcome/record 映射；Section IV 的 new/reuse、iterative pruning 和三种 verdict；Section V 的 stale candidate 与 atomic cut；Section VI 的 theorem intuition；Section VII 的 bounded fixture 含义。

## 7. Core Vocabulary

**保留并要求 reviewer 长期记忆（5 个）：**

1. execution edit
2. execution record
3. workflow call
4. tool action
5. authorization record

**弱化为局部形式词汇：** workflow contract、safe execution set、exact checker、policy domain、atomic rule update、pomset、edit rule、new/reuse classification、safe runtime implementation、`AgentSec`。首次出现时解释用途，但不让其承担故事主线。

**避免 reader-facing 使用：** `HStep`、`HRes`、`addr`、`carry`、`clone`、`Copy`、`Keep`、`BRuns`、`Theta` 及 Lean 内部 theorem/module 名；`\Fresh/\Alias` 在叙事层写成 new authorization/reuse；旧版术语不得出现。

## 8. 每个 Section 的唯一职责

| Section | 必须回答的问题 | 不应承担的内容 |
|---|---|---|
| Abstract | 问题、核心条件、checker 结果、runtime preservation 与证据边界是什么？ | 未解释术语、证明清单或实现夸大 |
| I. Introduction | 攻击/失败、现有缺口、Central Thesis、scope 和三项 contribution 是什么？ | 低层符号、完整算法或 theorem 细节 |
| Overview figure | execution edit、record、checker、installation 和 protected calls 如何形成一条链？ | 证明内部对象或过多 edit 变体 |
| II. Execution-Edit Safety | 采购例子中什么状态可恢复、什么事实不可撤销、正确 verdict 依赖什么？ | 一般 pomset machinery 或完整 runtime protocol |
| III. Model and Security Objective | 表达唯一安全条件最少需要哪些对象和可信假设？ | checker procedure、proof inventory 或产品 claim |
| IV. Exact Checking | 如何 derive、resolve、prune 并返回三种 verdict？ | 并发安装细节或重复定义安全目标 |
| V. Runtime Enforcement | 接受集合如何变成规则，并在 atomic update、call race 和 restart 下保持？ | 重新设计 checker 或新增安全条件 |
| VI. Formal Guarantees | 五个固定 theorem 分别回答哪个 runtime 问题、依赖什么假设、意味着什么？ | 修改 theorem、堆砌 Lean 名称或新增 claim |
| VII. Validation | 手写证明、Lean、Python 和 runtime model 各支持什么、不支持什么？ | 把 checker timing 写成 runtime performance |
| VIII. Related Work | 相邻机制覆盖链条的哪一部分，缺少哪个具体输入或保证？ | 无法防守的“all prior work”结论或新贡献 |
| Conclusion | 用 Central Thesis 收束条件化保证与证据边界。 | 新术语、新范围或“完整 Agent security foundation”式外延 |
| Supplementary Appendix | 保存完整证明、低层符号和复现细节。 | 承担正文理解所必需的首次解释 |
