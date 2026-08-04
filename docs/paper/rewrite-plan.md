# CSF 叙事重构与最小修改计划

## 0. 审查范围、硬约束与当前基线

本计划基于当前 `docs/paper/main.tex`、`docs/paper/sections/*.tex`、附录、Lean/可执行制品说明、现有 `main.pdf` 和 `main.log`。它不是对旧版本故事线的复述。用户意见中提到的 `authority continuity`、`residual set`、`rectangularity`、`promotion-order confluence` 和两个 algebraic boundary 已不再是当前稿件的主对象；现稿已经改成：

> 从受保护的 execution record 推导一次 execution edit 的目标，计算仍能安全完成所有必要 outcome 的最大执行集合，再把该集合原子地安装为运行时规则。

因此，后续修改不应把旧版本的两条 boundary 重新塞回当前论文。仍然适用的是用户指出的更深层问题：问题和安全边界出现太晚、抽象对象太多、例子没有贯穿、定理与工程决策之间缺桥、验证证据没有形成清楚的链条、相关工作定位过宽、缺少真实接口映射，以及大量绝对化和压缩名词链。

硬约束如下：

1. **所有 theorem 的数学内容固定。** 可以移动、增加动机、增加直觉、增加工程含义、调整 proof roadmap，但不得改变 theorem statement 的逻辑内容。
2. **最小必要修改。** 优先移动和拆分现有内容，其次补少量缺失的 scope、例子和解释；不为了“优雅”引入新抽象。
3. **面向不熟悉本文模型的 CSF reviewer。** 读者不应先记住一套术语，才能知道论文解决什么问题。
4. **正文必须不依赖附录才能理解。** [CSF 2027 CFP](https://www.ieee-security.org/TC/CSF2027/cfp.html) 允许正文最多 12 页，AI 声明、参考文献和明确标注的附录不计页数；同时明确说明审稿人没有义务阅读附录。
5. **当前分页基线。** `main.pdf` 共 23 页：正文为第 1--12 页，Supplementary Proof Appendix 从第 13 页开始，第 23 页出现 AI Use Acknowledgment 和参考文献。因此当前形式上满足 12 页正文限制，不应把“23 页”误报为超页。
6. **当前编译基线。** 日志中未见 undefined reference、multiply-defined label 或 overfull box；有 22 个 underfull `\hbox` 警告。后续每轮修改应保持无 undefined/overfull，并逐步消除高 badness 的 underfull，而不是用压缩正文来掩盖结构问题。
7. **现有制品状态不能混写。** 当前论文使用新的 exact-history checker；`adapter/README.md` 仍描述旧的 authority-continuity adapter，不能直接作为现稿 runtime prototype 证据。`artifact/README.md` 也同时包含旧模型和新的 `exact_history_realization.py`，正文必须只声明与当前模型对应的部分。

---

## 1. 当前故事线（一页）

### 1.1 作者当前试图讲的故事

Agent runtime 允许在执行中 Checkpoint、Fork、Restore 和 Merge。不同于普通 crash recovery，这些操作会改写接下来可能执行的 workflow，却不会撤销已经授权、发出或完成的外部动作。学校采购例子说明了危险：Agent 在一次性审批后向供应商 \(R\) 发起付款，又 Restore 到审批前的 checkpoint 并探索供应商 \(L\)。如果 runtime 只看恢复出的 workspace，它可能重复审批，或把与 \(R\) 已授权付款不兼容的 \(L\) 路径继续下去。

论文据此主张，安全检查不能只看恢复后的 bytes，也不能相信 Agent 提交的 replacement workflow。可信 controller 必须读取一份不可由 Agent 修改的 execution record。该记录至少保留四类事实：原 workflow 及其 required outcomes、哪些 workflow calls 指向同一个外部 action、已有 authorization 和 call progress、以及 edit 与并发 call 相交时哪一版规则有效。这个记录既约束过去发生了什么，也约束未来哪些 outcome 仍必须可完成。

对一个注册过的 edit，controller 先从 execution record 推导目标 workflow，并把源 outcome 分成三类：已满足、由原 authority 明确允许删除、仍然必须保留。然后它判断目标 workflow 中每个 call 是创建新的 authorization record，还是复用已有 record。对目标 workflow 的所有完整执行，它删去违反 policy 的执行，并反复删去那些会产生“某个仍兼容的 outcome 再也无法安全完成”前缀的执行。最大不动点非空时，剩余集合是允许的最大安全行为；为空时，checker 返回按删除轮次组织的 rejection proof。

接受并不自动等于安全落地。Controller 把安全前缀编译成有限自动机，在一个 policy domain 内原子关闭旧规则、激活新规则、替换每个当前 workflow call 的 rule entry 和 authorization token。任何并发 protected call 要么完整发生在规则切换之前，使旧候选过期；要么发生在切换之后，此时旧 token 失效。append-only authorization record、checkpoint record、request queue 和原子事务共同支持 retry、stop 和 restart。

最后，五个主 theorem 分别声称：注册模型忠实于源 workflow；checker 接受当且仅当存在安全 runtime implementation；四类 execution-record 信息均不可省；任意有限次 edit/call/restart 保持 invariant；实际 runtime 与理想原子机在 Agent 可见行为上弱互模拟。Lean 机械化 finite linear-contract core、六种 edit derivation、安装和有限 trace preservation；Python 对有限实例、反例和 checker 时间做可执行检查；general pomset lift、具体信息下界 record pairs 和 ideal/runtime weak bisimulation 主要由手写证明承担。

### 1.2 Reviewer 当前实际读到的故事

上述故事在逻辑上可以连成一条线，但正文没有让读者始终看到这条线：

- 摘要和引言在读者尚未理解“安全实现是什么”时，就连续承诺 “exact procedure”“every safe way”“every possible implementation”“complete executions”“six forms”“extensions”“atomic enforcement”。
- 采购例子在第 II 节后基本消失。进入模型后，读者面对 pomset、contract algebra、十元组 \(H\)、workflow grammar、多个 registry/map/digest/version，而没有继续看到“审批、两家供应商、付款、发货”分别对应什么。
- 真正的安全条件被分散为 required-outcome preservation、policy safety、prefix completion 和 compatible-outcome completion；直到 `Safe execution set` 定义才合在一起，但这时读者已经跨过大量基础对象。
- 第 IV 节的 checker、第五节的 runtime enforcement、五个主 theorem 和验证章节各自有内部逻辑，却缺少一张“问题 → 决定 → 机制 → theorem → evidence”的总表。
- “为什么是 security”主要靠读者自行推断。论文应直接说：不可信 Agent 可以利用 stale/copy/merge state 获得本不应再允许的 protected action，或让 runtime 丢掉由可信 authority 要求的 outcome；这同时涉及 authorization integrity 和 complete mediation，不只是资源记账或普通 workflow correctness。
- 现稿没有与新 exact checker 对齐的 concrete runtime prototype。旧 Codex adapter 实现的是另一套 authority-continuity 模型。若正文暗示已有端到端 runtime implementation，reviewer 会认为证据错位。

### 1.3 建议采用的单一故事

全文只讲一个问题，并把它拆成三个 runtime 决策：

> **Restore/Fork/Merge 会改变未来 workflow，但不会撤销过去的授权和外部动作。一个不可信 Agent 请求这种 edit 时，runtime 应根据哪些受保护事实判断它是否仍有安全实现，并如何在并发 call 与 restart 下让该判断持续有效？**

三个决策按因果顺序展开：

1. **目标是什么：** 从受保护的 execution record，而不是 Agent 文本，推导 edit 后的 workflow、action identity 和仍需保留的 outcomes。推导失败就是 `Invalid`。
2. **是否存在安全实现：** 以一个核心安全条件检查所有前缀；如果任何允许前缀会让一个仍可能的 required outcome 无法完成，就删除造成该前缀的完整执行。最终为空就是 `Reject`，非空就是 `Accept`。
3. **如何持续执行：** 把接受集合编译成每次 tool call 前检查的自动机，并通过原子规则切换、append-only authorization history 和 restart transaction 保持相同条件。

贯穿全文的采购例子对应如下：

| 论文对象 | 采购例子 |
|---|---|
| workflow call | “请求一次审批”“向 \(L\) 付款”“向 \(R\) 付款”“允许发货”的具体调用位置 |
| protected action | 外部世界中被授权的审批、付款或发货动作；Restore 出来的新 call 可以仍指向同一个 action |
| outcome | 最终从 \(L\) 采购或最终从 \(R\) 采购 |
| required outcome | edit 前仍被学校 workflow 要求保留的完成选择 |
| policy | 一次审批、至多一家付款、付款先于对应发货 |
| execution record | 当前/保存的 workflow、call-to-action 对应、authorization/progress、活动规则版本 |
| `Invalid` | Agent 请求的 edit 不匹配已注册 edit rule，或删除 outcome 没有 authority 签名 |
| `Reject` | edit 结构合法，但不存在能同时保留所有必要 outcome 的安全运行时规则 |
| `Accept` | 存在非空安全执行集合，并可安装为运行时自动机 |

这条故事同时吸收了旧意见中仍然有效的部分：普通 checkpoint 缺少 durable history；Fork/Restore/Merge 改变未来相关性；runtime 需要做明确决策；lifecycle semantics 只解释这些检查在哪里执行。旧稿的两个 algebraic boundary 不再是现稿主线，不应重新出现。

---

## 2. 每章一句话目标

| 当前部分 | 一句话目标 |
|---|---|
| Abstract | 用普通语言说明 execution edit 的安全问题、受保护的输入、核心安全条件、checker 的三种结果、原子落地方式和验证边界。 |
| I. Introduction | 让 reviewer 在第一页回答“攻击/失败是什么、为什么现有 checkpoint 或 transaction 不够、本文精确解决哪一层、三项贡献分别是什么”。 |
| Overview figure (`lifecycle-figure.tex`) | 用一张图展示 checkpoint → fork → protected call → restore/merge → atomic rule swap，并把 workflow、authorization history 和 active rules 三种状态区分开。 |
| II. Execution-Edit Safety | 用采购例子定义问题、scope、trust boundary 和三个 runtime 决策，在任何一般数学对象之前建立直觉。 |
| III. Model and Security Objective | 只定义表达核心安全条件不可缺少的对象，并把每个对象立即映射回采购例子。 |
| IV. Exact Checking of Execution Edits | 说明 controller 如何从记录推导目标、区分新授权与复用、计算最大安全执行集合，并返回 `Invalid`/`Reject`/`Accepted`。 |
| V. Runtime Enforcement | 说明接受结果如何变成逐 call 规则，以及原子切换、并发、retry 和 restart 为什么不会使先前判定失效。 |
| VI. Formal Guarantees | 按 reviewer 会问的工程问题介绍固定 theorem，并为每个 theorem 给出一句现实含义和证据位置。 |
| VII. Mechanization and Executable Validation | 建立“定义一致性 → Lean invariant/theorem → Python counterexample/checker → 未验证内容”的证据链。 |
| VIII. Related Work | 逐类说明现有 recovery、transaction、capability、control/synthesis、provenance/merge 和 Agent runtime 机制能解决什么，以及缺少哪一个具体输入或保证。 |
| 新增 Discussion / Scope | 明确理论适用所依赖的 adapter/TCB 事实、当前没有 prototype/performance/real-trace evidence 的部分，以及这些限制如何约束 claim。 |
| IX. Conclusion | 只重述安全问题、核心条件和最主要保证，不引入“完整 foundation”式新外延。 |
| Supplementary Proof Appendix | 保存 theorem 的完整证明和低层 formal machinery，但不承担理解正文所必需的首次定义。 |

---

## 3. 每章存在的问题

### Abstract

1. 摘要连续引入 `execution edits`、`authorized or released`、`complete executions`、`prefix`、`registered workflow`、`trusted controller`、`safe implementation`、`six execution edit forms`、`extensions`、`atomic enforcement`，没有给非作者读者足够的直觉。
2. “We give an exact procedure”“every safe way”“every possible implementation”“complete executions”“main theorem covers ...”构成密集的绝对化承诺。数学上的 iff 可以保留，但摘要应先说明安全条件和工程含义，再概括 exactness。
3. 没有明确说 threat：Agent 不可信，可能提交隐藏过去 action/outcome 的 replacement workflow；安全目标是防止未授权 protected action 和 silent outcome loss。
4. 没有明确非目标：不从自然语言推断 workflow、action identity 或 merge semantics；不证明 hooks complete mediation、remote sink truthfulness、真实 runtime crash atomicity。
5. “Lean proofs and executable tests validate the theory and checker”把不同覆盖层级合成一句。Lean 没有覆盖 general pomset lift、具体 record-pair lower bound 的全部实例化和 ideal/runtime weak bisimulation；Python 也没有实现完整 edit-schema/refinement/runtime protocol。
6. “The main theorem”与正文实际五个 theorem 不一致。

### I. Introduction

1. 采购例子是当前最有价值的叙事资产，但第 27 行马上跳到“四类事实”，没有先画出攻击者、可信 controller、protected action 和 durable state 的边界。
2. 第 36--43 行的 gap claim 过宽：“neither line of work derives ... everything”容易被 capability、dynamic update、supervisory control、transaction 和 provenance reviewer 反驳。
3. 第 45 行 “Our key idea is ...”仍是 AI 模板句；更重要的是，它只说 preserve past actions/outcomes，没有把四项正式安全条件说成一条可检验规则。
4. 第 49 行 `registered edit`、第 51 行 `registered workflow`、第 58 行 authorization reuse、以及第 64 行 atomicity 同时出现，scope 和接口尚未定义。
5. “三个 technical problems”与后续五个 theorem、三项 contributions 的映射不清。
6. 没有直接回答：
   - 为什么这是 security 而不是 resource accounting/workflow validation；
   - 与保守做法“Restore 后把每个 call 当成新 call，全部重新审批”的差别；
   - 与“复制 authorization token”的不安全做法的差别；
   - 对 Codex/Claude runtime 的具体设计要求是什么。
7. Contributions 中 “runtime implementation”会让 reviewer 期待 concrete implementation；当前正文只有形式 runtime model 和 checker artifact，没有与当前模型对齐的真实 runtime prototype。
8. 没有 upfront system status：formal model、Lean development、bounded Python checker，而非已部署安全边界。

### Overview figure

1. 图把 current workflow、authorization order 和 rules in force 放在三条水平线上，这是正确方向，但符号 \(b_0,x_a,\eta_F,\Alias(x_a',d_a)\) 在 caption 中没有解释。
2. 图没有直接标出不可信 Agent、trusted controller、protected tool/sink 和 TCB 边界。
3. 图同时展示 Fork、select Merge、Restore、join Merge 和 rule swap，初次阅读负担过高。
4. 没有把三个 controller 结果 `Invalid`/`Reject`/`Accept+install` 展示出来。
5. `lifecycle-figure.tex` 在 `introduction.tex` 之前 input，源结构上不属于任何章节；即使排版可工作，也增加维护和 cross-reference 的不透明性。

### II. Execution-Edit Safety

1. 第 5--61 行的采购例子顺畅，但第 35--53 行已开始定义 workflow call、\(q_{\rm act}\)、\(\Delta\)、labels；问题/scope 与 mini-model 混在一起。
2. `reserve budget` 在现稿数学模型中不是核心对象，容易把读者带回旧 authority-accounting 故事。应说明这里的 reservation 只是 workflow step，或删去不承载当前 theorem 的预算措辞。
3. `ForkChoice`、registered rule、\(M_o\)、`\Fresh/\Alias` 在读者还不知道 edit grammar 时出现。
4. 第二个 \(X\otimes(Y\oplus Z)\) 反例是固定点必要性的关键证据，但突然离开采购例子。应先给采购版反例，再给三符号最小化形式。
5. `Calls During the Atomic Rule Update` 已经进入 enforcement，应移到 lifecycle integration；问题章节只需用一张 race timeline 说明为什么最终 recheck 必要。
6. 第 164 行四项规则是全文最接近“核心安全公式”的自然语言版本，却放在本章末尾，且之后又被多套定义拆开。
7. Scope boundary 缺失：模型要求 workflow/action/edit rule 已可信注册，不解决从自然语言、任意 workspace diff 或 artifact merge 推断这些事实。

### III. Model and Security Objective

1. 662 行的 `model.tex` 实际包含两个 section，模型和 exact checker 的边界在文件层面也不清楚。
2. 章节从 policy domain、execution record 和 finite-state 假设开始，随后直接进入一般 pomset/contract algebra；没有遵循“单次审批、两个分支、一个单位 action identity → 一般模型”的读者顺序。
3. `policy domain`、`execution record`、`workflow call`、`workflow contract`、pomset、outcome、action、branch、group、source region、scope、canonical request、rule entry、authorization token 等术语超过一篇 12 页论文合理的核心概念预算。
4. 第 71--85 行先给三个一般 constructor 的公式，再解释 choice/parallel/sequence；缺少对采购例子的逐项实例化。
5. 第 86 行使用 \(\rho\)，直到第 199--205 行才定义，是明确的 defined-after-used 问题。
6. 十元组 \(H=(\omega,G,T,K,\Sigma_\zeta,\rho,\beta,\chi,\mathsf{ver},\eta)\) 一次引入过多状态；读者无法判断哪些字段决定 edit 语义，哪些只支持 runtime serialization。
7. 第 230--273 行 well-formedness 包含大量重要假设，却没有按“semantic inputs / trust / runtime atomicity”分层。
8. Threat model 到第 298 行才出现，晚于几乎所有核心对象。它应在形式模型前出现。
9. 第 317--342 行才暴露最难的现实输入：canonicalization、registration、source/action mapping、idempotent/queryable remote service。这些是保证成立的前提，不应埋在模型后半段。
10. 第 345--365 行仅用 prose 给 security objective；正式定义直到后续 `Safe execution set` 才出现。
11. `RequiredBefore`、`Satisfied`、`AuthorizedRemoval` 的正式定义在附录，正文却把它们作为主 checker 的输入。CSF reviewer 不读附录也应能理解三分法。

### IV. Exact Checking of Execution Edits

1. 结构上分成 target derivation、new/reuse resolution、safe fixed point 和 outputs，但这些内容跨 `model.tex` 与 `semantics.tex`，章节边界对维护者和读者都不清楚。
2. 第 382 行先宣布六个 `Edit_6` constructor；读者还不知道为什么正好是六个、每个对应哪种产品语义、哪些 runtime verbs 不在 scope。
3. preservation map \(\mu,\pi,\mathcal P_u,\mathsf{pr},\mathsf{Covers}\) 在短距离内成批出现，且没有用采购例子演示一个 map。
4. Table I 是重要的工程接口表，但 “checked preservation” 一栏仍只给 `Copy/Keep` 符号，没有一句普通语言解释每行防止什么错误。
5. source outcome 三分法依赖附录定义；`RestoreReplace` 和 `MergeSelect` 的 authorized removal 语义应在表前用普通话说明。
6. fixed-point operator 是 checker 的核心，却在读者已经经过大量 edit-derivation machinery 后才出现。应先给算法直觉和具体删除轮次，再给公式。
7. “largest safe”既承担安全性也承担 permissiveness。正文没有明确说工程意义：它避免了保守 checker 无谓拒绝安全 call order。
8. generalized nonblocking proposition 的定位说明在 proposition 之后；应在 statement 前说清它回答 related-work reviewer 的哪一个问题。
9. 主文第 342--344 行给复杂度公式，却没有在正文定义 \(D,n,\Lambda,\mathcal G_{\rm cov},V_B\)，定义在附录。当前公式对正文读者不可独立理解。

### V. Runtime Enforcement

1. 本章比旧版单独 algorithm 章更接近正确角色，但仍像另一套 formal objects：\(W,B,q_z,\mathsf{Can},\mathsf{AgentSec},\mathsf{Ready},Y\)。
2. automaton construction 没有先用采购 trace 展示一个状态和一条允许/拒绝转移。
3. “smallest deterministic marked partial automaton”是 theorem 的额外性质，但没有说明系统为什么需要 minimality；若 theorem 内容固定，应在前文说明这是 representation result，而不是安全主线。
4. `AgentSec` 五个条件压在一个长句中，正文没有一张状态/责任表。
5. `Ready` 的定义也是一个长名词链式句子，应该先用 race timeline 说明 call-first 与 update-first 两种情况。
6. Trust Boundary 小节只回指 Model，没有再次列出真正 load-bearing 的 TCB assumptions。
7. retry、Dispatch、completion、restart 的完整规则全部在附录。正文至少需要一张生命周期图说明哪些事件改变安全前缀、哪些只改变外部完成状态。

### VI. Formal Guarantees

1. 开头写 “The theorem”，但本章实际有五个 theorem。
2. 在 theorem 前连续引入 `safe runtime implementation`、四分量 \(P/I/E/C\)、`PreservesRequired`、可见事件集合、weak bisimulation；这再次形成一套新词汇。
3. 关键 assumptions 在第 90 行、Faithful Registration theorem 之后才出现。Reviewer 会先误读第一个 theorem 的适用范围。
4. **Faithful Registration** 没有先解释现实问题：形式 checker 如何知道模型没有漏掉 protected call、改变 action identity 或丢掉 outcome。
5. **Exact Safety Checking** 是主 theorem，但 statement 把 `Invalid`、`Reject`、nonempty fixed point、safe implementation、`Ready` 和 successor invariant 压成一段，缺少 statement 前的三分支图。
6. **Necessary Record Information** 有清楚的问题意识，但 \(P/I/E/C\) 名称不可记，具体 counterexample 全在附录，正文没有采购版直觉。
7. **Repeated-Use Safety** 只有一句，没有说明它为什么不是由单次 exactness 自动得到，以及它对 repeated Restore/Merge 有何意义。
8. **Runtime Correctness** 直接使用 divergence-insensitive weak bisimulation，没有先解释 reviewer 应从中得到的可观察保证。
9. theorem 与证据没有逐项标注：哪些 clause Lean mechanize，哪些是 handwritten lift，哪些只有 bounded executable check。

### VII. Mechanization and Executable Validation

1. 29 行内堆入六个 Lean theorem 名和三组 timing，没有按验证问题组织。
2. “Six Lean modules pass `--trust=0`”与当前日志的 kernel replay 成功可以对应，但仓库 `lean/README.md` 仍保留“full fresh replay resource-incomplete”的旧说明，证据 provenance 需要先统一。
3. Lean 覆盖 finite linear-contract core、registered model、six-edit derivation、atomic install 和 finite trace preservation；general pomset lift、具体 record-pair lower bound 和 ideal/runtime weak bisimulation仍由手写 appendix 完成。当前正文没有把边界逐项列出。
4. Python 的 19 个测试覆盖 indexed resolution、fixed point、反例和六个 structural fixtures；`artifact/README.md` 明确说明早期六形状接口不实现 immutable edit-schema refinement、authorized retirement 或单一 domain epoch。正文“exercise the executable checker”过于宽泛。
5. 0.11--53.47 ms 是 synthetic bounded checker microbenchmark，不是 runtime overhead、end-to-end latency 或可实施性证明。
6. 没有与新 exact checker 对齐的真实 Codex/Claude adapter、真实 lifecycle traces、complete mediation audit 或 case study。
7. 没有明确列出未验证项：
   - natural-language/workspace-to-workflow inference；
   - action identity、canonical request 和 merge/edit-rule binding 的真实性；
   - product-wide complete mediation；
   - external service truthfulness；
   - concrete crash-atomic storage implementation；
   - general runtime prototype 与性能；
   - real traces；
   - general pomset lift、record-pair theorem 和 weak bisimulation 的 Lean mechanization边界。

### VIII. Related Work

1. 只有两个 paragraph，无法支撑引言中“现有两类工作都不推导 complete safety condition”的强 gap claim。
2. Recovery/workflow update/synthesis 被合并成一组，差异过大；capability/linear permission、transaction/outbox/saga、provenance/lineage、speculative/nested transaction 基本缺席。
3. “Our controller derives ... directly from the execution record”仍是自我总结，不是具体对比。
4. 应给一个统一 separating example：一次审批、两条互斥供应商路径、Restore 后的 same-action reuse、随后 Merge/并发 call。逐类说已有机制能处理哪一部分、缺哪一个输入或保证；不要声称所有 prior work 都没有本文对象。
5. 当前参考文献包含若干 2026 预印本，最终稿需要逐条核实可获得性、匿名化、自引第三人称和 claims 的准确支持。

### Discussion / Scope（当前缺失）

1. 论文没有独立 Discussion，也没有在前半篇集中声明 non-goals。
2. 最关键现实事实来自模型外：registered workflow 是否忠实、call-to-action mapping 是否正确、edit rule/merge semantics 是否可信、所有 protected call 是否被中介、远端完成记录是否可信。
3. 缺少这一节会让 reviewer 把论文误读成完整 Agent runtime security solution；应明确它是“在 adapter 能提供可信 lifecycle facts 和 complete mediation 的前提下，对 execution edit 做精确 authorization/workflow admission”。
4. 现有旧 adapter 可以作为未来工作或对照资产，但在未适配新模型前不能计入当前 validation。

### IX. Conclusion

1. “formal foundation for Agent runtimes”外延过大，应限定为 registered finite workflows、受保护 calls 和所述 TCB assumptions 下的 execution-edit checking。
2. 结论只说 exact criterion，没有重述核心安全条件的直觉。
3. 没有重申证据边界，容易放大 validation 章节的歧义。

### Supplementary Proof Appendix

1. 附录标注清楚，分页符合 CSF，但承担了正文 load-bearing 定义：`RequiredBefore/Satisfied/AuthorizedRemoval`、registration refinement、完整 `AgentSec`、runtime LTS、ideal machine。
2. CSF reviewer 可不读附录，因此正文至少要给这些对象的普通语言定义和最小公式，附录只保留完整构造与证明。
3. 附录出现 `boundary-finite typed Agent workflow`、`domain-separated injective authenticated digests`、`finite-trie derivative signatures`、`least-generated LTS` 等高密度名词链。
4. Appendix theorem 多数是 proof scaffold；无需逐个在正文宣传，但应在 proof roadmap 中说明它们如何支持五个主 theorem。

---

## 4. 建议调整后的结构

### 4.1 建议目录与 12 页预算

| 建议部分 | 目标页数 | 主要来源/动作 |
|---|---:|---|
| Abstract | 0.25 | 重写，不加新 claim |
| I. Introduction | 1.25 | 保留采购例子和三项贡献，提前 security/scope |
| II. Problem, Scope, and Running Example | 1.25 | 重组当前 lifecycle 前半、threat model、总图 |
| III. Minimal Model and Security Condition | 1.50 | 从 Model 中只保留必要对象和核心定义 |
| IV. Exact Checker | 2.00 | 合并 edit derivation、new/reuse、fixed point、outputs |
| V. Lifecycle Integration and Enforcement | 1.50 | 合并 atomic update、call race、retry/restart procedure |
| VI. Formal Guarantees | 1.25 | theorem 内容不变，增加动机/工程含义/证据标签 |
| VII. Evidence and Validation | 1.00 | 三层证据链与 non-claims 表 |
| VIII. Related Work | 1.00 | 4--5 个主题组和统一 separating example |
| IX. Discussion | 0.50 | assumptions、deployment obligations、case-study status |
| X. Conclusion | 0.25 | 限定范围的 thesis |
| 缓冲 | 0.25 | figure 浮动与排版 |

### 4.2 各部分内部顺序

#### Abstract

只保留六个角色：

1. 问题：execution edit 改未来，但不撤销过去的 protected action。
2. 安全风险：不可信 Agent 可借 Restore/Merge 重复授权或丢弃仍要求的 outcome。
3. 输入和 scope：可信 record 提供 workflow、action identity、authorization/progress、active rule version；本文不推断这些事实。
4. 核心条件：每个允许前缀遵守 policy，并给每个仍可能的 required outcome 保留安全完成路径。
5. 结果：checker 给 `Invalid`/`Reject`/最大安全 continuation，接受结果原子安装。
6. 证据：Lean 覆盖哪些 core，手写证明覆盖哪些 lift，Python 测什么；无 runtime prototype/real-trace claim。

#### I. Introduction

按以下 paragraph role：

1. Agent runtimes 正常使用 execution edits。
2. 采购 deployment example 和攻击结果。
3. Root cause：workspace checkpoint 缺 durable execution record；这是一项 authorization-integrity 问题。
4. Existing mechanisms 各自覆盖局部，但没有同时完成“从可信 record 推导目标 + outcome-sensitive admission + atomic install”；避免全称否定。
5. Insight：过去 action 不回滚，仍需 outcome 不可静默消失。
6. 三个 runtime questions：derive、decide、install。
7. Solution preview：三种 checker 结果和 fixed-point 直觉。
8. Scope/non-goals 一小段。
9. 三项 contributions：problem/model；exact checker + lifecycle enforcement；validation。若无 concrete prototype，不写 “runtime implementation”。

#### II. Problem, Scope, and Running Example

1. 一张端到端图：checkpoint → choice fork → one protected call → restore/merge request → `Invalid/Reject/Accept` → atomic install。
2. 现实组件责任表：Agent、platform/adapter、trusted controller、policy authority、protected tool/remote service。
3. 采购例子的四类 record state。
4. 为什么 conservative fresh-only checking 过度拒绝，为什么 token copying 不安全，same-action reuse 如何居中。
5. Security objective 的普通语言四条。
6. 提前写非目标和 trust assumptions；形式细节留下一节。

#### III. Minimal Model and Security Condition

严格按依赖顺序：

1. 一个 workflow call 与一个 protected action；Restore 可以产生新 call 但仍指向旧 action。
2. 两个 outcome 和每个 outcome 的 call order。
3. execution record 的四个**语义分组**，先不要给十元组。
4. append-only authorization log 与 new/reuse。
5. 一条核心安全定义：required outcome preservation + policy-safe prefixes + some completion + every compatible outcome remains completable。
6. 只有读者理解标量/两分支例子后，才引入 pomset、vector of outcomes 和一般 contract constructors。
7. 十元组和完整 well-formedness 移到本节末或附录；正文用表解释每个字段属于哪一语义分组。

#### IV. Exact Checker

按 procedure，而不是按作者最终形式化依赖倒序：

1. `Derive`: 验证 registered edit，得到 target 和 outcome 三分法；失败为 `Invalid`。
2. `Resolve`: 对采购例子展示 restored approval 是 `Alias`，另一供应商付款是 `Fresh`。
3. 生成 policy-safe complete executions。
4. 用采购版坏前缀展示为什么 outcome-by-outcome check 失败。
5. 展示两轮删除，再给 \(\widehat\Phi\) 与 greatest fixed point。
6. 空集合为 `Reject` 并返回 deletion proof；非空为 `Accepted`。
7. 六种 edit form 表作为 `Derive` 的 procedure 表；每行增加一句现实含义，不再另起一套 algorithm 术语。

#### V. Lifecycle Integration and Enforcement

1. 把 safe prefixes 编译成 automaton，用采购 trace 演示一个 state。
2. procedure: prepare inactive rules → final recheck → one atomic policy-domain swap → expose success。
3. 两条 race timeline：call-first stales candidate；install-first invalidates old token。
4. retry/reuse、Dispatch/completion、stop/restart 分成“改变 checked prefix”和“不改变 checked prefix”两类。
5. 用 `AgentSec` 五行表连接 state field、检查点和负责维护的组件。

#### VI. Formal Guarantees

固定 theorem statement 不改，只调整每个 theorem 的外围结构：

1. reviewer question；
2. 一句 theorem intuition；
3. 原 theorem statement；
4. 一句 runtime consequence；
5. evidence tag：`Lean core` / `handwritten lift` / `bounded executable check`。

#### VII. Evidence and Validation

用一张主表代替 theorem-name/数字堆叠：

| Claim | Handwritten proof | Lean | Python | 未覆盖 |
|---|---|---|---|---|
| checker iff safe implementation | general pomset lift | finite linear core | bounded instances/counterexample | production workload scaling |
| registered six edits preserve required outcomes | full source/target map | six constructors | structural fixtures only | arbitrary natural-language/workspace edit inference |
| four record parts necessary | five concrete record pairs | generic factor separation/部分 lower bound | fixtures if available | real telemetry sufficiency |
| repeated runtime preservation | full LTS cases | finite traces + install serialization | selected races | concrete transaction implementation |
| ideal/runtime API equivalence | handwritten weak bisimulation | 未完整 mechanize | 无 | product integration |

随后单独列：

- 测试环境、caps、重复次数和 timing 的含义；
- 不是 runtime latency；
- 无 current-model adapter、complete mediation、real trace、semantic binding 或 dishonest sink evaluation。

#### VIII. Related Work

建议五组：

1. checkpoint/rollback/reversible sessions；
2. transactions、outbox/saga、speculative/nested execution；
3. capabilities、linear/fractional permissions 和 one-time authorization；
4. supervisory control、nonblocking、dynamic synthesis/update；
5. workflow provenance/lineage/merge 与 Agent-specific recovery。

每组都用采购例子问同一问题：它是否同时知道 edit 前 required outcomes、same-action reuse、Restore/Merge 语义和 atomic install cut？结论写成具体差异，不写“所有现有工作都没有我们的对象”。

#### IX. Discussion

1. 当前贡献是 conditional security guarantee，不是完整 Agent safety solution。
2. adapter 必须提供可信 workflow、action identity、edit rule/merge meaning 和 complete mediation。
3. 远端 service、canonicalization、crash-atomic store 的 deployment obligations。
4. 真实 case study 的最低可接受版本：把 Codex/Claude 的 branch、checkpoint、call、action、restore 和 merge 映射到当前模型；若无法控制 dispatch，只能作为接口 mapping，不能作为 security evaluation。
5. 当前旧 adapter 与新 checker 不一致，必须明确标为 future integration，或另做一个最小新 adapter 后再进入 evaluation。

---

## 5. 所有 AI 味表达

这里的“所有”指当前英文正文中需要审查的 reader-facing 模式；theorem 内为了表达 iff、唯一性、最大性而必须出现的 `exact/exactly/every` 不应机械删除。修改原则是：**形式 statement 保留精确词；摘要、贡献、过渡、related work 和 conclusion 只在已经说明量化域时使用精确词。**

### 5.1 绝对化承诺和自我认证

| 位置 | 当前表达/模式 | 问题 | 处理 |
|---|---|---|---|
| `main.tex:55--67` | “exact procedure”, “every safe way”, “every possible implementation”, “complete executions”, “independently checkable”, “exactly their prefixes”, “main theorem covers ...” | 摘要在定义安全实现和量化范围前连续做全称承诺 | 先写安全条件与有限注册模型，再用一句 iff 总结 |
| `introduction.tex:36` | “do not derive its complete safety condition” | 对 prior work 的全称 gap claim | 改成具体缺失组合，并由 related-work separating example 支撑 |
| `introduction.tex:45` | “Our key idea is ...” | AI 式模板开场，且未落到可检验条件 | 直接陈述不变量 |
| `introduction.tex:67--75` | “exact checker ... every safe way ... every possible implementation ... independently checkable” | 与摘要重复、过度自信 | 保留一次，限定 finite registered model |
| `introduction.tex:95--104` | “every exact checker needs”, “returns every safe way”, “exact local check”, “exactly when” | contribution 像 theorem 摘要而非贡献解释 | 改成问题/机制/证明三项 |
| `model.tex:334--340` | “exact correspondence”, “exact finite check and proof” | registration 尚未建立直觉就自我认证 | 先说明漏注册的攻击，再保留 theorem 中的 iff |
| `model.tex:371--373` | “exact edited workflow”, “precisely those complete executions” | 算法尚未解释 | 改成 procedure 动词并把精确性留给 theorem |
| `model.tex:461` | 一句包含 “exactly when every ... every ... every ...” | 八个 premise 压成一条长句 | 拆成 typed target / preservation / authority 三组 |
| `model.tex:487` | “exact disjoint partition” | `exact` 冗余，等式本身已表达 | 直接说 partition |
| `model.tex:594--596` | “consists exactly of ... exactly the copied ...” | 机械化口吻过强 | 用步骤 1/2 解释 |
| `semantics.tex:138` | “removes exactly the complete executions ...” | 在证明前先下结论 | 改为“removes candidates that currently violate ...”; exactness 留给 lemma |
| `semantics.tex:233` | “formal reason the exact checker rejects” | 元叙事 | 直接说 fixed point is empty, so no safe set exists |
| `semantics.tex:276` | “computes every safe continuation ... atomically” | 把三层贡献塞进一句 | 拆为 derive/check/install |
| `semantics.tex:334--344` | “ordered reasons for removing every execution”, “exact returned data”, undefined complexity symbols | 密度高且正文不可独立理解 | 用 output table；复杂度变量在正文定义或移附录 |
| `algorithm.tex:13` | “ideal machine ... admits exactly its resolved prefixes” | 还未说明比较目的 | 先说 reviewer 可从 equivalence 得到什么 |
| `algorithm.tex:43--49` | “Exact finite enforcement”, “exactly”, “smallest” | theorem 合法，但 motivation 缺失 | theorem 不改；前置 representation question |
| `algorithm.tex:78` | 五个条件中两次 “exactly” | 长句且难扫读 | 改五行表，数学内容不变 |
| `results.tex:5--10` | “The theorem connects ... central clause ... other clauses establish ...” | AI 式总括，而且实际有五个 theorem | 改成三个 reviewer questions |
| `results.tex:104` | “same mutually exclusive and exhaustive answer” | statement 固定可保留；外围应先解释三种结果 | 增加 `Invalid/Reject/Accept` 图 |
| `results.tex:119` | “The full record is sufficient.” | “full”无直觉，四部分刚命名 | 改外围说明，theorem 内容保持 |
| `results.tex:133` | “exact solver only after ...” | related-work claim 混入 result | theorem 后移到 Related Work，或加 cited comparison |
| `results.tex:167` | “complete case proofs” | AI/证明包口吻 | 说清哪些 cases 在 appendix |
| `validation.tex:7--18` | 六句 “proves ... exact/sound and complete/every finite ...” | theorem-name dump | 改 claim-evidence table |
| `validation.tex:22--28` | “All 19 ... complete measurement protocol and executable coverage” | 测试通过不等于覆盖完整；“complete”歧义 | 写清 caps、implemented subset、non-claims |
| `related.tex:11--22` | “derives ... directly”, “computes every”, “exact criteria”, “all six”, “all four”, “arbitrary finite” | related work 变成贡献宣传 | 改成逐类具体差异 |
| `conclusion.tex:5--13` | “exact criterion”, “every registered ... every safe continuation”, “formal foundation” | 结论放大 scope | 限定 finite registered workflow + stated TCB |

### 5.2 压缩名词链

以下表达均应拆开，或在首次出现前先给普通句子：

- `finite linear-contract core` (`validation.tex:5`)
- `core executable checker ... ValidRealization` (`validation.tex:7`)
- `executable workflow editing ... six edit constructors` (`validation.tex:11`)
- `source-outcome preservation maps`、`information lower bound`、`ideal--runtime weak bisimulation` (`validation.tex:19`)
- `outcome-indexed runs` (`model.tex:336`)
- `surrounding-workflow identity map` (`model.tex:415,645`)
- `target-derived set` (`model.tex:476`)
- `well-typed workflow context` (`model.tex:594`)
- `prefix--required-outcome support pairs` (`semantics.tex:344`)
- `paired-language derivative construction` (`algorithm.tex:56`)
- `divergence-insensitive weak bisimulation` (`results.tex:71`)
- `order- and identity-preserving correspondence` (`results.tex:155`)
- `domain-separated injective authenticated digests` (`appendix-proofs.tex:298`)
- `finite-trie derivative signatures` (`appendix-proofs.tex:252`)
- `boundary-finite typed Agent workflow` (`appendix-proofs.tex:650`)
- `least-generated LTS` (`appendix-proofs.tex:928`)
- `current-rule-version automaton` (`appendix-proofs.tex:1411`)
- `state-preserving Invalid/Reject`（多处）
- `policy-domain rule versions`、`domain-wide rule-version protocol`（多处）

### 5.3 AI 式元叙事和过渡

- “This idea creates three technical problems.” (`introduction.tex:56`)：直接写三个 runtime questions。
- “Together, these executions give the paper's end-to-end safety rule.” (`lifecycle.tex:162`)：直接写“An edit is safe only if ...”。
- “This section gives ... used by the main theorem.” (`algorithm.tex:17`)：删元叙事，先讲 runtime need。
- “The next section states ...” (`algorithm.tex:131`)：用内容转接，而不是目录导航。
- “The full argument is in ...”“The appendix gives the complete case proofs.”：只在确实需要时保留一次。
- 连续使用 `Thus/Therefore/Consequently/Hence`：逐段检查是否真的表达推理；若只是换句话说，删除或合并。
- 频繁的 “write ...”, “put ...”, “fix ...”, “let ...” 使正文像 proof script；一般读者段落先解释用途，再进入记号。

### 5.4 低频复合词处理规则

保留为核心概念的候选最多 6--8 个：`execution edit`、`execution record`、`workflow call`、`protected action`、`required outcome`、`safe execution set`、`authorization record`、`policy domain`（若确实需要）。

其余低频 reader-facing compounds 优先改为普通语言，而不是新增定义，例如：

- `target-derived set` → “the required outcomes derived for the target”
- `source-outcome preservation map` → “a map showing which target outcome preserves each source outcome”
- `state-preserving Reject` → “Reject without changing runtime state”
- `outcome-specific nonblocking conditions` → 先解释每个仍可能 outcome 都必须能完成
- `boundary-finite typed Agent workflow` → 直接说 finite-state workflow with finitely many protected-call traces
- `record-request pair` → “a record together with the edit request”

LaTeX label 名（如 `app-spec-bridge`、`history-rules`）不属于读者术语，不需要为了统计结果修改。

---

## 6. 所有第一次出现却未解释的术语

以下清单聚焦会影响 reviewer 理解的术语、接口和记号；标准数学词若在同一句中定义则不列。处理优先级为：先删不必要的词，其次在首次出现前给一句普通解释，最后才给术语/符号。

| 术语/对象 | 首次问题位置 | 当前问题 | 建议首次解释 |
|---|---|---|---|
| workflow | Abstract / `main.tex:45` | 默认读者知道注册 workflow 的语义 | “a platform-registered set of protected calls and allowed completion outcomes” |
| authorized vs released | `main.tex:49` | 两个 lifecycle phase 未区分 | authorization 是 controller 允许；release 是请求离开本地 gate |
| action / same action | `main.tex:51`，Intro 之前 | action identity 是全文关键但摘要无直觉 | 两个 call 可指向同一外部操作，因此共享一条 authorization record |
| required outcome | `main.tex:51` | outcome 是终态、选择还是 obligation 不清 | workflow authority 要求 edit 后仍可完成的某个注册结果 |
| registered workflow | `main.tex:59` | 谁注册、注册什么不清 | platform/authority 在运行前认证 protected-call model |
| execution record | `main.tex:59`，正式定义到 `model.tex:17` | 摘要和引言先用后定义 | 在 Intro 第一次出现即给四类 state 的一句定义 |
| trusted controller | `main.tex:59` | 责任与 TCB 不清 | 读取受保护记录、推导 edit、检查并原子安装规则的组件 |
| complete execution / prefix | `main.tex:61` | supervisory-control 语言提前 | complete execution 是到一个 registered outcome 的 call sequence；prefix 是已经执行的前段 |
| safe implementation | `main.tex:63` | 到 `results.tex:18` 才定义 | 能逐 call 强制核心安全条件的 runtime automaton |
| six execution edit forms | `main.tex:67` | 摘要不列，读者不知道为何是六 | 摘要删掉数字，正文表中列 Choice/Parallel Fork、Replace/Live Restore、Select/Join Merge |
| extension | `main.tex:67` | 直到 appendix 才有完整语义 | 若非主线，摘要删除；正文说明是经 authority 验证的 registry/policy 增量 |
| atomic enforcement | `main.tex:67` | 是 rule swap、transaction 还是 call dispatch 不清 | 一个 policy-domain transaction 同时关闭旧规则、激活新规则和更新 tokens |
| registered edit / edit rule | `introduction.tex:49,65` | request 和 trusted rule 的区别晚到 Model | Agent 只命名 rule；可信 registry 决定允许的 source/target shape |
| authorization record | `introduction.tex:58` | 与 token/log/return 混淆 | append-only record 绑定 action、canonical request、creator 和 label |
| policy | `lifecycle.tex:50--59` 之前已使用 | 到 `model.tex:278` 才形式化 | 允许哪些“新 authorization label 序列”的前缀闭语言 |
| authorization label | `lifecycle.tex:52` | label 与 action 未区分 | policy 检查的抽象事件；action 是具体外部操作 |
| `ForkChoice`, `MergeSelect`, `RestoreLive` | `lifecycle.tex:65,130,157` | 在六种 form 表前出现 | 先用普通产品语义，再在表中给正式 constructor |
| workflow contract | `lifecycle.tex:104`，正式定义 `model.tex:46` | “single-call contract”先于定义 | 某组 outcomes 及每个 outcome 必须执行的 calls/order |
| \(\oplus,\otimes,\triangleright\) | `lifecycle.tex:107` / `model.tex:71` | 符号先于直觉 | choice / parallel / sequence；先画小图再给公式 |
| authorization token | `lifecycle.tex:136` | token 与 authorization record 区别未解释 | token 证明某 call 当前受某 rule version 管理；record 表示已授权 action |
| ordered record \(\chi\) | `lifecycle.tex:155` | 突然出现 | 即使 `Alias` 不改变 auth log，它仍记录 workflow progress |
| policy domain | `model.tex:11` | 定义了集合，但为什么需要不清 | 原子 rule swap 和一个 append-only authorization log 的最小隔离单位 |
| protected tool/call | `model.tex:5--9` | “protected”的 enforcement surface 不清 | 所有影响安全目标的 calls 必须经过 controller；这是 assumption |
| pomset | `model.tex:42` | 形式定义有，工程直觉缺 | 一个 outcome 的 calls 与必须先后关系；并发 calls 不排序 |
| terminal workflow call | `model.tex:64` | 未说明 API 形态/为何认证 | 显式区分“现在完成”与“还可继续”的注册终止事件 |
| \(\rho\) | `model.tex:86`，定义 `model.tex:199` | 明确先用后定义 | 把 line 86 移到 \(\rho\) 定义后，或提前给 registry table |
| branch/group/head/leaf/current | `model.tex:136--177` | 多个结构视角连续出现 | 用一张 workflow tree 图统一定义；避免 loose synonym |
| source region | `model.tex:201` | 全文无独立直觉定义 | call 被 carry/clone 时追踪其授权和 outcome authority 的原区域 |
| scope | `model.tex:201` | 未说明是 capability scope、policy domain 还是 branch scope | 明确字段含义，若仅实现细节则移附录 |
| canonical request | `model.tex:201,205` | 先作为字段，后给 canon 函数 | 等价 tool request 的可信规范表示，用于防止同 action 换参数 |
| digest | `model.tex:201` | 密码学假设在 appendix 才出现 | 说明它只认证 bytes，安全依赖 collision resistance/signature |
| rule entry \(j\) / binding \(\beta\) | `model.tex:209` | 与 token/version 一次出现 | 每个当前 call 唯一指向 active rule version 中的检查入口 |
| policy authority / outcome authority | `model.tex:244,305` | authority 的身份、签名内容晚出现 | 谁有权要求或删除 outcome；不等于 Agent |
| finite model \(\mathcal R\) / source workflow \(\mathcal W\) | `model.tex:321,325` | 突然增加双层模型 | 用 registration bridge 小节说明 source workflow 与 checker model |
| `CheckReg` | `model.tex:334` | 名称先于具体检查直觉 | 检查 protected-call traces、outcomes、actions 和 order 一一对应 |
| `BRuns` / \(\lambda\) / refinement relation | `model.tex:336--339` | 一段内引入三对象 | 先用一句“registration supplies a trace-preserving bijection” |
| idempotent or queryable remote service | `model.tex:342` | 关键 deployment assumption 埋后面 | 提前到 Scope/TCB，并列为 non-claim |
| preservation map \(\mu\) | `model.tex:394` | “parent map”无例子 | 用 Restore approval call 的 same-action copy 举例 |
| outcome map \(\pi\) | `model.tex:398` | 满射的工程意义不清 | 每个 target outcome 指回它保留的 source outcome |
| \(\mathsf{pr},\mathsf{Covers},\mathsf{StillRequired}\) | `model.tex:423--453` | 三个关系连续出现 | 先画 source-outcome → target-outcome 二部图 |
| carry / clone | `model.tex:502--528` | 形式操作与现实 Restore/Fork 未绑定 | carry 保留 ID/progress；clone 分配新 call/branch ID 但保留 action identity |
| root derivation | `semantics.tex:11` | root 是 startup 还是 workflow root 不清 | 初次安装规则前对注册模型执行的安全检查 |
| registered extension | `semantics.tex:15` | scope 过大且定义在附录 | 主文给一句，若不承载故事则只在 theorem scope 提及 |
| annotated/resolved word | `semantics.tex:29--52` | formal-language 术语密集 | 先说每个 call 被标为 `new` 或 `reuse` |
| compatible outcome | `semantics.tex:101--107` | 公式有，直觉晚 | 尚未被当前 prefix 排除的 outcome |
| post-fixed / greatest fixed point / \(\nu\) | `semantics.tex:145--165` | 未解释为何迭代方向正确 | 用 2→1→0 删除示例后再引术语 |
| generalized nonblocking | `semantics.tex:236` | 相邻领域术语无普通解释 | 从任何标记为“仍可能”的 state 都能到同 outcome 的 done state |
| marked partial automaton / marked language | `algorithm.tex:43--49` | control-theory 术语无直觉 | generated prefixes vs complete accepted executions |
| derivative construction | `algorithm.tex:56` | 算法术语无解释 | state 只需记当前 prefix 后剩余的 allowed suffixes |
| `AgentSec` | `algorithm.tex:78` | 给了五项但在一长句中 | 五行 invariant table |
| `Ready` / candidate \(Y\) | `algorithm.tex:92` | 名字和数据包内容不清 | “the prepared answer still matches the current record and inactive target version” |
| \(\mathsf{Sec}(S;c,r)\), \(P/I/E/C\) | `results.tex:27--40` | 字母不传达含义 | 用 descriptive names，符号仅留 theorem |
| ideal machine | `algorithm.tex:13`, 完整定义在 appendix | 正文先用后解释 | 一步原子安装、直接执行 safe-prefix language 的 reference semantics |
| divergence-insensitive weak bisimulation | `results.tex:71` | 未解释 reviewer takeaway | 两台机器有相同 Agent-visible answers/calls/results，忽略内部准备和 restart bookkeeping |
| `ValidRealization` | `validation.tex:7` | Lean identifier 不是 reader 概念 | 写成 declarative safe runtime implementation，并在括号给 Lean 名 |
| boundary-finite | `appendix-proofs.tex:650` | 自造词且只用一次 | 删除术语，直接写有限条件 |
| universal residual policy | `appendix-proofs.tex:738` | “residual”未在现稿主线使用 | 改为 policy allowing all remaining prefixes |
| bootstrap namespace | `appendix-proofs.tex:835` | proof-internal 名词 | 保留附录但先说明仅用于构造可重命名初始状态 |

---

## 7. 哪些 theorem 缺少动机

Theorem statement 固定。下面只要求在 statement 前增加现实问题，在 statement 后增加工程含义。

| 结果 | 当前动机情况 | 需要补的动机/工程问题 |
|---|---|---|
| Lemma “Completion remains unambiguous” | 只有形式条件，弱 | runtime 必须可靠判断 sequence barrier 是否已完成，否则 checkpoint/Fork 的 current leaf 不确定 |
| Lemma “Exact edit derivation and atomic rule update” | 把多个性质打包，动机分散 | 为什么 Agent 不能自己给 target；为什么同一个 derivation 同时要保 outcome/action identity 和准备新 tokens |
| Lemma “New/reuse classification” | Restore 例子提供部分动机 | statement 中 streaming/composition clause 是后续 rechecking 的关键，应提前说明 |
| Lemma “Largest safe execution set” | 有反例，但 permissiveness 意义弱 | 它回答“是否存在任何安全 monitor；若存在，如何不额外拒绝安全行为” |
| Proposition “Exact correspondence with generalized nonblocking” | 定位解释在 proposition 后 | 它回答“为什么不能直接把模型交给普通 nonblocking solver；controller 还必须先推导 outcome labels/conditions” |
| Lemma “Rechecking after a prefix” | 有一句技术动机 | 补 runtime 含义：允许 call 后无需从不同语义重新证明，下一状态正是原结果的 residual |
| Lemma “Exact finite enforcement” | automaton construction 有动机，minimality 无 | 说明安全集合如何成为逐 call enforceable rules；minimality 只是 representation consequence |
| Lemma “Edit--call serialization” | 当前动机较好 | 保留 call-first/install-first 图，使 statement 成为图的形式总结 |
| Theorem “Faithful Registration” | **主要缺口** | checker 只对模型正确；若 registration 漏 call、错 action 或丢 outcome，后续 exactness 无意义 |
| Theorem “Exact Safety Checking” | 作为主结果有定位，但 statement 太密 | 先画 `Invalid / Reject / Accept+install` 三分支；说明 theorem 回答“checker 是否既 sound 又不过度保守” |
| Theorem “Necessary Record Information” | 有问题意识，缺现实例子 | 四个省略各给采购版一句：错 topology、错 same-action、漏 progress/release、旧 rule version race |
| Theorem “Repeated-Use Safety” | **明显不足** | 单次安全不自动保证下一次 edit；必须证明每个 call/edit/restart 都把系统留在可再次检查的 state |
| Theorem “Runtime Correctness” | **明显不足** | reviewer 需要知道具体实现的 preload/recheck/restart 内部步骤不会改变 Agent 可见语义 |
| Appendix Lemma “The computed result is exact” | 动机基本充分 | 强调它连接独立 declarative definition 与 executable fixed point，避免循环定义 |
| Appendix Proposition “Output-sensitive checking” | **不足** | 它回答 checker cost 是否来自输入还是显式枚举输出；解释为何不是 polynomial-in-workflow claim |
| Appendix Lemma “Rejection proof is sound and complete” | 部分充分 | 说明拒绝证书用于独立审计，不能只信任 search procedure |
| Appendix Lemma “Registered extension preserves safety” | **不足** | 先解释为什么运行中需要扩 registry，以及 extension 不能借机删除旧 outcome |
| Appendix Lemma “Registration reflection” | 技术动机晚 | 它是 Faithful Registration 的 proof bridge，应在 definition 前说明 |
| Appendix Proposition “Four necessary record parts” | 有总动机 | 每个 record pair 前加一句现实错误，不要求读者先解符号 |
| Appendix Lemma “Atomic events are well defined” | **不足** | 说明 quotient-by-renaming 是为了让 private ID 拼写不影响安全答案 |
| Appendix Corollary “Finite-prefix closure” | statement 有意义，前置动机弱 | 说明这是 Repeated-Use Safety 的归纳桥 |
| Appendix Lemma “Other events preserve the checked prefix” | 动机较好 | 保留“哪些事件不推进 protected-call automaton”的分类 |
| Appendix Lemma “Restart preserves an atomic prefix” | 动机较好 | 用 authorization record/queue 和 rule version 两个 torn-state 反例引入 |
| Appendix Theorem “Agent-API weak bisimulation ...” | 前面已有完整 cases | 在正文主 theorem 前补同样的 observable takeaway，附录无需扩写 |

---

## 8. 哪些 assumptions 应提前

| Assumption | 当前位置 | 应提前到 | 为什么 |
|---|---|---|---|
| Agent 不可信并可控制 edit request、tool args、retry、stale token 和 scheduling | `model.tex:301--302` | Intro/Section II threat model | 决定“为什么是 security” |
| execution record、registry、policy、authorization log 不可由 Agent 篡改 | `model.tex:303--311` | Section II | 所有 theorem 的根前提 |
| 每个 relevant protected call 都被 TCB mediation | `model.tex:5`, `results.tex:90` | Abstract scope + Section II | 否则安全保证可被旁路 |
| workflow、edit rules、action identity、outcome authority 已可信注册 | `model.tex:317--342` | Intro scope + Section II | 模型不从自然语言/workspace 自动推断这些事实 |
| registration faithfully covers source protected-call traces | `results.tex:81--88` | Section II/III | exact checker 只对注册模型 exact |
| finite-state workflow / finite model / each check finite | `model.tex:15`, `results.tex:81` | Abstract scope + Section III 开头 | 限定 decidability、枚举和性能 claim |
| authorization policy 是 regular、prefix-closed | `model.tex:278` | Section III security condition 前 | 证明 safe complete trace 的每个 prefix 也 policy-safe |
| complete trace 不是另一个 complete trace 的真前缀，或有 authenticated terminal call | `model.tex:54--65` | Section III outcome 定义处 | runtime 才能区分完成与继续 |
| 一个 action 至多一条 append-only authorization record；Restore 不删除它 | `model.tex:280--293` | Section II 采购例子后 | 解释 same-action reuse 与 non-replay |
| canonicalization 正确且同一 action 的 canonical request 一致 | `model.tex:201--208,319` | Section II TCB | 防止复用 authorization 时偷换参数 |
| signed outcome authority 决定谁可删除 requirement | `model.tex:244--247,305` | Section II | 防止 Agent 通过 edit 静默弱化目标 |
| policy domains 的 actions/logs/policies 不相交，edit 不跨 domain | `model.tex:13,266--269` | Section II scope | 原子 swap 和 product composition 的边界 |
| 一个 domain 内 transaction linearizable 且 restart 后仍原子 | `model.tex:313--315`, `results.tex:90` | Section II | Edit--call serialization 和 restart theorem 的关键 |
| remote service idempotent 或 queryable，并给 authenticated completion records | `model.tex:342` | Section II / Discussion | 决定 retry/return 语义，当前系统未验证 |
| signatures/digests 不可伪造/碰撞 | `appendix-proofs.tex:342--344` | Section II cryptographic assumptions | digest equality 在 final recheck 中被当作 authenticated identity |
| registered templates 在一次 check 期间有限且不变 | `model.tex:317--322` | Section III | 否则 fixed-point input 变化 |
| constructor operands 的 workflow-call IDs 不相交、IDs 全局唯一 | `model.tex:67--90,238--260` | Section III contract algebra 前 | 使 leaf/context decomposition 和 clone/carry 有定义 |
| complete outcomes 和 call/action mapping 的语义真实性来自 adapter/authority | 目前仅隐含 | Intro non-goal + Discussion | 这是最难现实问题，不能留给 reviewer 推断 |
| natural-language intent、任意 workspace merge、product verb 语义推断不在 scope | 目前未明确 | Abstract/Intro/Section II | 防止误读为完整 Agent safety |
| runtime prototype、complete mediation、real traces、end-to-end performance 尚未建立 | validation 未列 | Intro system status + Validation non-claims | 让 claim 与 evidence 对齐 |

---

## 9. 哪些公式缺少解释

全文应把 `Safe execution set` 的四项条件提升为唯一核心安全公式。其他公式都回答它的一个子问题，并在出现后回扣采购例子。

| 公式/位置 | 缺失的解释 | 修改计划 |
|---|---|---|
| no-complete-trace-is-prefix condition (`model.tex:56--59`) | 为什么 workflow 需要它、现实接口如何表达 stop/continue | 先给“shipment 后结束 vs 继续审计”的小例子，再给 authenticated terminal call |
| contract algebra (`model.tex:71--85`) | 先一般公式后用途；\(\uplus,\triangleright\) 解释在后 | 先画采购 choice/parallel/sequence，再给公式；每行写 outcome 和 order 如何变 |
| execution record tuple \(H\) (`model.tex:126--129`) | 十个字段同时出现，没有语义分组 | 先给四组 table，再给 tuple；每个字段标注属于 derive/check/install 哪一阶段 |
| workflow grammar \(T\) (`model.tex:144--150`) | branch/group/join/sequence 的 runtime 对应不清 | 配 workflow tree 图，并用六个 edit forms 回指 |
| `HStep` (`model.tex:180--187`) | \(T/(x,a)\) 没有正式或例子级定义 | 用一次 restored approval `Alias` 演示 \(G,T,\chi,\Delta\) 哪些变、哪些不变 |
| checkpoint equality \(\mathcal C_b=\Gamma_b/\mathsf{raw}(\chi_b)\) (`model.tex:216--220`) | 为什么这就是 exact local check | 解释它防止 checkpoint 替换为较小 outcome set，但不回滚 \(\Delta\) |
| preservation equations for \(\mu,\pi\) (`model.tex:394--406`) | 数学上清楚，系统意义不清 | 给 source approval call → restored call 的 map；解释 global bijection 防止把 shared call 拆成两次授权 |
| disjoint cover (`model.tex:419--422`) | `ctx/copied/added` 三部分无图 | 用 target workflow 着色图显示每个 call 必须恰属一类 |
| `EditedRequired`, `Covers`, `StillRequired` (`model.tex:429--450`) | 三套定义平行出现，基本/派生关系不清 | 先画 source-to-target outcome map；只把 `StillRequired` 当基本需求集合，其余作 witness |
| required-outcome partition (`model.tex:478--495`) | 正式 source-set 定义在附录 | 把三分法最小定义移正文，并用选中供应商/已完成当前 branch 举例 |
| clone targets \(L_\sigma,R_\sigma\) (`model.tex:516--519`) | 为什么 clone call ID 但保留 action identity 不清 | 紧接 Fork/Restore table，以审批 action 举例 |
| prepared tokens \(\mathcal H_u^+\) (`model.tex:604--609`) | 与 active token 的区别不清 | 加一句 inactive/inaccessible，配 atomic install timeline |
| derived cut (`model.tex:615--624`) | 一个 judgment 打包 target、record、contract、versions，读者不知道 takeaway | 公式前分四步列 output；公式后只总结“same derivation feeds checker and installer” |
| `Resolve` (`semantics.tex:35--44`) | 基本解释有，但未用贯穿例子 | 先算 restored approval = reuse，new supplier payment = new |
| \(R_o,M_o\) (`semantics.tex:93--100`) | `complete`、`policy allowed`与 required outcome 的关系易混 | 对 \(L/R\) outcome 各列 raw execution 和 policy-filtered execution |
| `Compat` (`semantics.tex:103--107`) | 为什么它不能直接从 surviving executions 得到不直观 | 强调它由 target workflow 决定，防止 checker 先删 outcome 再声称不兼容 |
| `Safe execution set` (`semantics.tex:115--132`) | 这是核心定义，但被放在众多定义后；四条件没有图 | 提前并加 boxed roadmap：preserve / policy / some completion / every compatible outcome |
| fixed-point operator \(\widehat\Phi\) (`semantics.tex:147--167`) | 量词嵌套，\(\nu\) 未解释；删除链直觉在后 | 先给 2→1→0 counterexample 表，再逐个解释 \(y,z,o'\) |
| `SafeEdit` (`semantics.tex:172--181`) | 与 `Safe execution set`/fixed point 像另一个平行定义 | 明确它只是 decision wrapper：derive defined 且最大集合非空 |
| generalized nonblocking equivalence (`semantics.tex:245--252`) | marker 语义和 prior-work relevance 太晚 | statement 前解释 possible/done marks 和普通 nonblocking 为什么太弱 |
| rechecking equations (`semantics.tex:304--315`) | 工程意义只在结尾一句 | 先说“执行一个允许 prefix 后，重新检查结果等于旧结果去掉该 prefix” |
| complexity formula (`semantics.tex:342--344`) | \(D,n,\Lambda,\mathcal G_{\rm cov},V_B\) 在正文未定义 | 要么把变量定义和一句解释移正文，要么整条 bound 留附录，正文只说 output-sensitive |
| canonical automaton (`algorithm.tex:27--35`) | 没有实例 state | 用采购 prefix \(ra\) 演示 \(q_{ra}\) 启用哪笔付款 |
| duplicated `PreservesRequired` (`results.tex:46--54`) | 与前文定义重复，没有新作用 | theorem 前用文字回指，不重复公式，除非为 page-local readability 必需 |
| API observation map (`results.tex:64--72`) | weak bisimulation takeaway未先给 | 先列可见/隐藏事件表，再给 \(\mathsf{obs}_{api}\) |
| exact-view lower-bound formula (`results.tex:123--126`) | \(P/I/E/C\) 不可记、`Keep` 语义过抽象 | 先给四个 concrete record-pair mini-example |
| checked-record digest (`appendix-proofs.tex:323--330`) | 为什么每个字段必须进 digest 未就地解释 | 公式后按 stale-call/stale-release/stale-version 三类说明 |
| exact-view definition (`appendix-proofs.tex:529--537`) | 两层 record/request/renaming 量词难读 | 先用一句“same reduced input must never require opposite answers” |
| protected-call rule (`appendix-proofs.tex:1023--1035`) | premise 很多但没有责任归类 | 在公式前分 identity/request/version/automaton 四组 |
| atomic update premise (`appendix-proofs.tex:1064--1074`) | variables 来自多处 | 加小表：current state、prepared result、old/new version、recomputed digest |
| recovery equation (`appendix-proofs.tex:1286--1291`) | 只给数学 prefix，无 torn-write 直觉 | 先写两个不允许的半状态：record without queue；new active version without closing old |
| bisimulation projections \(\alpha_I,\alpha_S\) (`appendix-proofs.tex:1333--1340`) | 为什么恰好比较这些字段不清 | 先列 API-visible equivalence contract |

---

## 10. 修改优先级（P0/P1/P2）

### P0：不修会导致 reviewer 无法判断贡献或保证范围

1. **锁定新的 paper contract。** 明确现稿不是旧的 two-boundary paper；主问题是 registered execution edit 的 derive/check/install。禁止重新引入旧 residual/rectangularity 故事。
2. **重写 Abstract 和 Introduction。** 第一页必须出现具体攻击、为什么是 security、核心安全条件、三种 checker 结果、scope/non-goals 和三项贡献。
3. **把 threat model/TCB/assumptions 提前。** 特别是 trusted registration、complete mediation、action identity、authorized removal、linearizable transaction、remote completion assumptions。
4. **问题与例子先于一般模型。** Section II 先讲采购 trace、组件责任和安全规则；pomset/十元组不得抢在问题边界之前。
5. **确立一个核心安全公式。** 以 `Safe execution set` 四项条件为中心，所有 derived definitions 回扣它；避免多个“安全”定义并列。
6. **让正文脱离附录可理解。** 把 source outcome 三分法、registration bridge、`AgentSec` 五项直觉和 ideal/runtime comparison 的最小定义放正文。
7. **修正 claim-evidence alignment。**
   - 区分 Lean finite core、handwritten general lift、Python bounded checks；
   - 明列未 mechanize/未实现/未测量内容；
   - 不把 synthetic checker timing 写成 runtime feasibility；
   - 不把旧 authority-continuity adapter 当作当前 exact checker prototype。
8. **为五个主 theorem 建立工程问题。** statement 不改；增加 motivation、runtime consequence 和 evidence tag。
9. **重写 Related Work 的 gap。** 用统一采购 separating example 做具体比较，删除无法防守的“neither/all existing work”式断言。
10. **维持 CSF 合规。** 正文继续不超过 12 页；appendix 明确；正文不依赖 appendix；double-blind/self-citation/AI disclosure 按 CFP 复查。

### P1：显著影响理解和说服力

1. 重画总图，加入 untrusted Agent、TCB、protected tool、三种 verdict 和 atomic cut。
2. 让采购例子贯穿 Model、Resolve、fixed-point 删除、automaton 和 record lower bound。
3. 按 derive → resolve → prune → output 重排 exact checker，把 procedure 融入问题叙事。
4. 把 enforcement 写成 lifecycle integration：prepare/final-check/swap/call/restart。
5. 减少核心术语到 6--8 个；删低频复合名词，修复 \(\rho\) 等先用后定义问题。
6. 给所有列出的 theorem/lemma 补 why-before-what。
7. 给所有列出的公式补一行用途和采购实例。
8. 新增短 Discussion，说明 conditional guarantee 和 deployment obligations。
9. 增加一个**诚实的接口 case study**：
   - 若只做文档/API mapping，就称 mapping/case study，不称 evaluation；
   - 若要称 prototype，必须实现当前 exact checker 的 registration、derive、fixed point、atomic install 路径，并控制至少一个 protected dispatch seam。
10. 将 validation 改成 claim/evidence/non-claim 表，避免 Lean/Python/timing 三条平行罗列。

### P2：语言、附录和版面打磨

1. 系统清理第 5 节列出的绝对化和 AI 模板句；theorem 内必要精确词不动。
2. 清理低频 hyphenated compounds、过长名词链、连续 `Thus/Therefore/Consequently`。
3. 统一大小写和术语：Agent/agent、Checkpoint/Fork/Restore/Merge、protected call/action、authorization record/token、rule version/entry。
4. 统一 subsection title 为平行 noun phrases；避免 question-style 和 proof-internal title 泄漏到正文。
5. 附录增加短 roadmap，把 supporting lemmas 映射到五个主 theorem。
6. 对 reference claim 做 citation audit，尤其是 broad gap、2026 预印本、产品文档和自引匿名化。
7. 清除 22 个 underfull warning 中由长不可断数学/`\path` 名造成的高 badness 项；不通过缩字号或挤压正文解决。
8. 检查 figure/table caption 是否首次阅读自足，符号是否与正文一致。

### 建议实施顺序与每轮验收

#### Round A：科学叙事与 scope

- 写一页 story contract、三项 contributions、核心安全条件、assumption/non-claim 表。
- 不动 theorem statement。
- 验收：只读 Abstract + Intro + Section II，就能回答问题、攻击者、TCB、输入、输出、非目标。

#### Round B：结构移动

- 重排为 Problem/Scope → Minimal Model → Exact Checker → Lifecycle Integration。
- 先移动现有段落，只有缺口处补新句。
- 验收：每个 section 第一段说明“为什么本节现在需要”；采购例子持续出现。

#### Round C：术语和公式

- 依第 6、9 节逐项修复 first-use 和 formula explanation。
- 核心概念超过 8 个时，优先删除术语而不是增加 glossary。
- 验收：任何正式对象首次出现前都有普通语言用途；不存在 \(\rho\) 这类先用后定义。

#### Round D：theorem 与 evidence

- statement 原样保留，补 motivation/consequence/evidence tag。
- 重建 validation evidence matrix 和 explicit non-claims。
- 验收：五个主 theorem 各能映射到 reviewer question、Lean/handwritten/Python 覆盖。

#### Round E：Related Work、Discussion、case study status

- 按五类 prior work 写具体比较。
- 决定 case study 是 interface mapping 还是新 prototype；不能用旧 adapter 冒充当前实现。
- 验收：每个 novelty/gap claim 有 citation 和具体 separating fact。

#### Round F：最小 diff 与 CSF 复查

- 每轮只改一个叙事目的，逐文件检查 word-level diff；任何 theorem/math diff 都必须为零，除非仅移动且内容 byte-equivalent。
- 每轮重新编译并检查：
  - 正文最后一页仍为第 12 页或更早；
  - appendix 从清楚的新页开始；
  - AI acknowledgment、bibliography 不计正文；
  - 无 undefined/multiply-defined reference；
  - 无 overfull box；
  - underfull 数量不增加；
  - figure/table/section/appendix cross-reference 正确；
  - PDF 中不存在 `??`、TODO、FIXME、TBD；
  - 所有字体嵌入。
- 最终对 Abstract、Intro contributions、theorem statements、Validation table、Conclusion 做 claim consistency audit；数字、术语和覆盖范围必须逐项一致。

### 最终验收问题

在提交前，请让一位不了解项目的 security/formal-systems reviewer 只读正文，并要求其不看附录回答：

1. 一次 Restore 为什么会造成安全问题，而不只是 workflow bug？
2. execution record 的四类事实分别防止什么错误？
3. `Invalid`、`Reject` 和 `Accepted` 有什么区别？
4. 核心安全条件为什么必须量化每个 prefix 和每个 compatible outcome？
5. fixed point 为什么会删除一个起初 policy-safe 的完整执行？
6. 接受结果怎样在并发 protected call 下原子生效？
7. 五个主 theorem 各回答什么 runtime 问题？
8. Lean、手写证明和 Python 各验证什么，没验证什么？
9. 论文依赖 adapter 提供哪些可信事实？
10. 当前是否有与该模型对齐的真实 runtime prototype？

若其中任一问题不能用两三句普通语言回答，说明结构或术语仍未达到本计划目标。
