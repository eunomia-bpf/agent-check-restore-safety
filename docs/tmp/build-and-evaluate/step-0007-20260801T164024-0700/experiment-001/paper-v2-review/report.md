# CSF 2027 风格攻击性 story / claims review

日期：2026-08-01（America/Vancouver）  
评审对象：`docs/paper/main.tex` 及其全部 section；当前 `main.pdf` 为 11 页。  
评审方式：先通读论文，再核对 Lean 定义/定理、既有 formal/runtime/trace 独立报告，并用一手来源检查最接近工作。  
隐私边界：没有打开或搜索任何原始私有轨迹；只读了 aggregate、method report 和 independent recheck。  
快照声明：本报告评价的是写作时的工作区快照。并行 formal strengthening 仍在收尾；凡标为“未进 Audit”的结论，在正式提交前应以最终 audit log 为准。

## 结论先行

**当前模拟决定：Weak Reject（2/5），信心 4/5。**

这不是因为 idea 太小。相反，论文已经有一个简单、可记忆、具有原则性的核心：

> **History may be copied; controller-held authority occurrences may not.**

最有价值的贡献不是“发明 token”，也不是“给 retry 一个 ID”，而是：**定义哪个 controller occurrence 必须在线性地穿过 choice/parallel Fork、replacing/live Restore、两类 Merge、撤销和原子 promotion，并证明已有 durable operation 的 claim/token identity 在任意 checked history 中不漂移。** 这个核心是 CSF 风格的，也确实有 agent runtime 的现实动机。

今天仍偏拒稿，是因为论文的最强叙述比当前形式化集成和证据边界快了半步：weighted accounting 与真实 current/bound claim 的 coherence 没有被统一证明；新 theorem 尚未进入 frozen Audit/Main；论文描述的 operational gate 与 `TokenPositiveTrace` 的 constructor 还不是同一个东西；私有轨迹复审为 **REVISE**；而 related work 尚未正面化解“consumable credential + transactional outbox/idempotency 的 agent 化重命名”这一最强拒稿理由。

如果只做一次大改，我建议把整篇文章收束成下面这句话，而不是继续增加机制：

> **A copyable agent history needs a non-copyable, controller-defined occurrence semantics; checked lineage transport preserves that occurrence until one atomic transition converts it into a retry-stable durable binding.**

## 1. 这篇论文真正挑战了什么旧信念？

论文挑战的不是“rollback 会重复 external effects”——这是经典问题；也不是“capability 应该线性”——这同样已有深厚基础。它真正挑战的是一个更细的、适合 agent runtime 的默认假设：

> 只要 snapshot/workspace、numeric budgets、capability possession 和 idempotency key 分别处理正确，复制或重组执行历史就不会扩大一个尚未执行的授权 occurrence。

零需求反例很好地击穿了这个假设，但必须精准限定：它证明的是，**任何在所有被跟踪坐标中都把该动作映射为零的 aggregate budget abstraction，不能区分一个 origin 的一份和两份 current witness。** 它没有证明“所有 vector model 天生不可能表示 identity”；给每个 origin 增加一个 unit coordinate 就能表示，但那已经等价于重新引入 token-indexed discrete identity。

一个强 reviewer 会给出更简单的替代解释：

> 这只是一个 consumable credential，在本地数据库中通过 transactional outbox 原子消耗，然后用 idempotency key 重试；Fork/Restore/Merge 只是新的 API 名称。

论文必须证明这个解释不完整。最佳反驳不是强调 token，而是强调以下 theorem family：

1. `rho` 是不同 history operators 的真实 lineage transport，而不是任意状态复制；
2. transfer-local non-amplification 与 **computed target current-fiber linearity 构成 exact iff**，并覆盖 canonical、simulation Merge、direct Merge；
3. valid transfer 不能触及 durable `opClaim`，所以既有 operation 的 claim/token origin 单步不变；
4. 上述性质提升到 arbitrary checked histories，包括 Prepare、Restriction、Revoke 和 ticket phases；
5. Prepare 明确区分“新创建的 binding”和“必须原样保留的旧 binding”。

这些是论文的理论核心。`B+E+W=P`、三分类求和、stable retry ID 和 SQLite outbox 本身都不应作为主要 novelty headline。

## 2. Story、标题、摘要和引言

### 标题

`Branching Histories, Linear Authority` 很强：短、可记忆、直接呈现 tension。副标题 `Safe Promotion Plans for Forkable Agents` 也准确。除非作者决定把“promotion plan”降为次要术语，否则不建议改标题。

### 摘要

摘要的前 12 行非常有效：外部现实不可 restore、copyable plan representation、zero-cost duplicate、三层状态、Prepare 边界，读者能迅速理解问题。后半段的问题是一次塞入太多强断言：exact weighted accounting、全操作 preservation、local workspace lower bound、Lean 全机制化、SQLite、Codex callback、private lineage。结果是核心 theorem 被 artifact 清单稀释，同时带入数个 scope mismatch。

最小重写方向：

- 保留 counterexample、三层状态和一句原则；
- 用一句话突出“local non-amplification iff computed target current linearity”；
- 用一句话突出“existing durable operation origin is stable through arbitrary checked histories”；
- 把 weighted projection 降为同一 disposition partition 的 corollary；
- 把 observation theorem 准确写成“one fixed local plan-reuse observation”；
- runtime/trace 各留半句，并明确 private case only characterizes workload/telemetry。

### 引言

引言总体是论文最成熟的部分：零需求例子、三 rollback domains、“为什么不能全回滚”、Prepare/Dispatch split，以及 agent-specificity 都串得起来。尤其第 28--44 行把 workspace 问题提升成 controller/external reality 问题，是正确的故事。

但四条 contribution 仍把“简单但已有”的东西和“真正新且难”的东西放在同一层级。建议改成三条：

1. **Separation and model：** 三状态面 + zero-demand separating example；
2. **Theorem：** typed history transport、exact non-amplification characterization、stable durable origins 和 arbitrary-history preservation；
3. **Realizability：** reference-monitor algorithm + narrow runtime integration + trace-informed telemetry contract。

weighted projection 是第 2 条的 corollary；observation pair 是 caching design implication；private trace 不是独立贡献。

### 简单还是深？

原则是简单的，证明义务可以是深的。这正是优势。当前稿件的问题不是“不够复杂”，而是有时用很多 bookkeeping 让核心显得复杂。最深的地方应是：

- 各类 history transformation 的语义不同，但共享同一个 occurrence transport obligation；
- one-to-many lineage、live coexistence 和 semantic Merge 使“复制历史但不复制 authority”不再等于 choose-one commit；
- durable effect binding 必须在后续任意 history transformation 中保持 claim/token origin，而非仅保证当前 state linear。

## 3. Token 是否只是 nonce / outbox 的重命名？

| 论文构件 | 最接近的既有构件 | 单独看是否新 | 本文应主张的差异 |
|---|---|---:|---|
| origin token | nonce、linear/consumable credential、logical capability ID | 否 | 它标识 controller occurrence，并由 typed history lineage transport，而不是充当 bearer secret |
| remaining/prepared/withdrawn | credential available/consumed/revoked；outbox pending/sent/cancelled | 否 | disposition 同时连接 current plan witness 与 durable ticket/receipt binding |
| atomic Prepare | atomic ratification；transactional outbox | 否 | 它是 copyable plan occurrence 到 durable effect identity 的唯一 linearization point，且进入后续 history theorem |
| stable operation ID / Retry | idempotency key、durable execution ID | 否 | 论文只保证 logical identity，不声称 physical exactly-once；这一区分写得好 |
| `B+E+W=P` | 对三分 partition 的 weighted sum | 基本否 | 可作为“identity 和 resource 用同一 token metadata 投影”的工程一致性结果，但不能作为主 novelty |
| transfer-local non-amplification iff target linearity | lineage-aware admission criterion | **可能是** | 必须成为 headline，并明确覆盖哪些真实 operation / premises |
| existing operation origin 的 RTC stability | rollback/fork 后 authority continuity | **较强** | 应成为第二个 headline theorem，而非埋在结果中部 |
| pair-specific observation bound | indistinguishability argument | 中等、辅助 | 精确说明一个 footprint 缺少 owner topology；不能推广成所有 workspace guard 的下界 |

最危险的 related-work overlap 是 Bowers et al. 的 Consumable Credentials：其一手论文已经包含 single-copy/use credential、atomic all-or-none ratification、对 proof+nonce 的绑定，以及防止复制 credential/proof 重用的全局 bounded-use invariant。论文已经引用它，但目前只用一句“linearity 本身不新”带过，力度不够。必须直接解释：**那里 ratify 的对象和 proof context 是什么；这里被 transport 的 controller occurrence、history algebra、live parallel descendants 和 Merge 分别增加了什么 theorem obligation。**

## 4. Formal claim-to-theorem 审计

状态标记：

- **SUPPORTED**：当前 Lean 源码中有直接 theorem；
- **CONDITIONAL**：核心 theorem 存在，但 paper 省略 premise、组合桥或 operational 对应；
- **UNSUPPORTED AS WRITTEN**：当前 theorem 不支持这句强度；
- **AUDIT BLOCKED**：模块可独立编译，但尚未进入 frozen paper-facing audit root。

| Paper claim | 对应 Lean theorem / object | 状态 | 问题与最小修复 |
|---|---|---|---|
| `checkLinear=true -> Linear` 及 token trichotomy | `checkLinear_sound`; `LinearValid.token_trichotomy` | SUPPORTED | 把这两个 theorem 加入 paper-facing Audit |
| transfer-local check 可执行且正确 | `checkTransferTokenNonAmplifying_sound`, `_complete` | SUPPORTED / AUDIT BLOCKED | 当前 `Audit.lean` 未 import/打印 strengthening module |
| local non-amplification “characterizes” target current linearity | `canonical_nonAmplifying_iff_target_current_linear`; `simulationMerge_nonAmplifying_iff_target_current_linear`; `directMerge_nonAmplifying_iff_target_current_linear` | SUPPORTED / AUDIT BLOCKED | 这是最强新结果之一，应在 theorem statement 明说 exact iff 及三个 operation families，而不是只写 prose |
| source invariant + local atom 推出 target linearity | `afterTransfer_preserves_linearity_source`; `checkedCanonical_preserves_linearity_source`; 两类 Merge 对应 theorem | SUPPORTED / AUDIT BLOCKED | 很适合作为“不是 target postcondition 假证明”的核心回答 |
| Restriction/Revoke/Prepare source-derived preservation | `restriction_preserves_linearity_source`; `revoke_preserves_linearity_source`; `prepare_preserves_linearity_source`; `checkedPrepare_preserves_linearity_source` | SUPPORTED / AUDIT BLOCKED | 应在 Audit matrix 中逐项列出 |
| production checker 同时执行 local atom 和 complete target scan | 新 `check*TokenDefended` 定义；旧 `TokenPositiveStep` constructor 仍只携带 target `checkLinear` | **CONDITIONAL / RELATION MISMATCH** | target current-linearity 与 local atom 有 iff，所以旧 relation 语义上蕴含 local atom；但它没有记录“实际执行两道检查”。新增 `checked*Defended_token_step` bridge 和 defended relation，或把论文改成“local atom is derivable and can be checked explicitly; target scan is the modeled gate” |
| arbitrary checked history preserves `Safe` | `token_positive_trace_preserves_source_decomposed`，以及旧 preservation family | SUPPORTED / AUDIT BLOCKED | paper 的 `TokTrace` 必须明确就是哪一个 Lean relation；不要混用 defended operational checker 和 old semantic grammar |
| valid transfer 不能改已有 durable binding origin | `bound_durable_rho_none`; `bound_durable_origin_afterTransfer`; `afterTransfer_bindingFiber_eq` | SUPPORTED / AUDIT BLOCKED | 这是重要 novelty，建议正式编号为 lemma family |
| 任意 history 中已有 operation 保持 claim 和 token | `OperationTokenBound`; `tokenPositiveStep_preserves_existing_operation_token`; `token_positive_trace_preserves_existing_operation_token` | **CONDITIONAL** | theorem 需要 source `TokenSafe` 和初始 `OperationTokenBound`；论文 `results.tex:63--67` 漏写 `Safe(S)` premise |
| Prepare 新 binding 或保留旧 binding | `prepare_binding_new_or_preserved` | SUPPORTED / AUDIT BLOCKED | 该 theorem 很有解释力，值得进入正文 proof sketch |
| version monotone、initial token set fixed、projection to lifecycle | `token_positive_trace_version_mono`; `within_plan_epoch_initial_tokens_fixed`; `token_positive_trace_projects_actual` | SUPPORTED | “每个 authority mutation 都严格 advance”比已列 theorem 的 monotonicity 更强；若要保留严格措辞，应逐 constructor audit |
| epoch-qualified immutable token spec | `EpochToken`; `PlanEpochSpec`; `UnifiedProjection`; `unifiedProjection_initial_same_epoch` | **CONDITIONAL / AUDIT BLOCKED** | spec 是 theorem 的外部固定参数，不是 `TokenState` 中被 transition 携带的字段；动态 mint/rollover 明确未建模 |
| `B+E+W=P` 与 cardinality partition | `PlanEpochSpec.weighted_partition_exact`; `cardinality_partition`; `zero_weight_token_visible` | SUPPORTED / AUDIT BLOCKED | 等式对任意 total disposition 按 cases 求和即可成立，技术上正确但不深；不要把它包装成主要 conservation theorem |
| 每个 reachable state 同时有 identity + weighted projection | `tokenSafe_unifiedProjection`; `trace_preserves_unifiedProjection` | SUPPORTED / AUDIT BLOCKED | theorem 依赖 `TrustedPlanEpochStart`，应在 paper theorem 中显式出现 |
| `B` 等于真实 current claim load，`E` 等于真实 bound claim load | 只有 optional `CurrentWitnessCoherent` 和 `current_witness_matches_spec`，且只覆盖 **current** witness | **UNSUPPORTED AS WRITTEN** | 当前没有 bound-witness coherence；也没有证明 coherence 随 trace 保持。删除 `model.tex:101--102,118--119` 对 bound 的声称，或加入 `BoundWitnessCoherent`、统一 coherence、初始化与每步 preservation theorem |
| weighted token accounting 与旧 quantitative plan rows 是同一 invariant | `TokenWeightedAccounting` 文件头明确“不声称与旧 `FullPlanInvariant` coherence” | **UNSUPPORTED IF IMPLIED** | 论文应明确这是 token-spec projection，不是已证明等于 claim-indexed/stored plan rows；否则补 bridge theorem |
| token specification through RTC unchanged | `trace_preserves_unifiedProjection` 对同一外部 `spec` 重建 projection | CONDITIONAL | 改成“the same installed external spec remains applicable because initial identities are fixed”；不要暗示 state 内有被更新/验证的 spec store |
| zero-demand base checker accepts、token checker rejects、fiber card=2 | `ZeroDemandRegression.source_token_check_accepts`; `base_plan_check_accepts`; `zero_demand_parallelFork_rejected`; `duplicated_token_fiber_cardinality` | SUPPORTED | “minimal / any resource bound cannot repair”过强；只对 all-zero tracked coordinates 的 aggregate abstraction 成立 |
| pair-specific observation lower bound | `local_observation_indistinguishable`; `version_observation_lower_bound`，加 source/merged witness theorems | SUPPORTED | theorem 仅针对一个固定 `LocalAuthObs` 和一对状态；不能提升成“所有 local workspace guards” |
| semantic observation/cache policy | `semantic_observation_distinguishes_cross_slot`; `semantic_observation_ignores_irrelevant`; fixture suite | CONDITIONAL | 没有证明 paper 列出的 root/topology/epoch/token key 全局 sound 或 minimal |
| “audit root prints every paper-facing theorem” | 当前 `AuthorityContinuity/Audit.lean` 只 import `Trace` 和 `TopologyExamples`，未 import token/strengthening/weighted modules | **UNSUPPORTED / BLOCKER** | 在声称完成前更新 Audit/Main、运行全库 fresh checker、保存 axiom output；不能只凭三个新文件独立编译 |

### Formal 总评

strengthening work 已把旧独立评审指出的“target-only postcondition 冒充 source preservation”问题实质性修好了：现在有 source-derived proofs，并且 exact iff 说明 target scan 为什么能恢复 local atom。这是重要进展。

但当前 formal story 仍有三套相邻而未完全统一的对象：

1. 旧 `TokenPositiveStep/Trace`（constructor 要求 full target scan）；
2. 新 source/defended operational gates（显式 local atom，可再加 target scan）；
3. 新 epoch/weighted projection（外部 spec，未桥接旧 claim-indexed FullPlanInvariant）。

提交前要么把三者合并成一个清晰的 paper relation，要么在论文里非常诚实地分别命名，不要用一个 `TokTrace` 同时指代它们的并集。

## 5. Observation theorem 是否过度泛化？

正文 theorem statement 本身已经相当谨慎：one actual simulation-admitted cross-slot Merge、one fixed observation、every deterministic Boolean classifier、safe source versus plan-transport-invalid target。这部分是好的。

过度泛化发生在 theorem 前后：

- 摘要说“information unavailable to local workspace guards”，但 `LocalAuthObs` 不只是 workspace；它含 capacity、durable load、scheduled-claim metadata 和 plan version。
- 结果末尾说 cache key “must cover … authenticated roots”，但这一 witness 的 root lineage 恰好不变；真正被该 pair 证明必要的是 co-owner topology。authenticated roots 可以由 admission model 单独要求，但不是这条 lower bound 推出的必要性。
- 论文没有证明所列 semantic cache key 对所有 operation sound、complete 或 minimal。

建议把结论固定为：

> For this plan-reuse footprint, omitting scheduled-owner topology makes a valid source indistinguishable from one simulation-admitted Merge target on which the old plan is invalid.

然后单独写设计推论：production keys **may additionally need** authenticated roots, epochs, and token origins according to the transition dependencies。不要把设计建议伪装成 lower-bound theorem。

## 6. Runtime、轨迹、双盲和伦理边界

### Runtime

runtime 层当前最可信的结论是：**一个 SQLite reference monitor 的关键原子边界可以实现，并能插入真实 Codex App Server 的一个 client-owned tool callback 路径。** 现有证据包括 targeted 19/19、adapter 52/52，以及独立 adversarial recheck 12/12；两 writer Prepare race、crash before/after commit、retry/settlement 和独立 semantic replay 都是有价值的 controlled tests。

论文已经正确承认：

- 不是 native Codex plan/topology integration；
- native Fork activation 未与 Prepare 原子耦合；
- 不是 product-wide mandatory mediation；
- Python oracle 不是 Lean refinement proof；
- SQLite injection 不是 power-loss/linearizability proof；
- exactly-once physical effect 仍依赖 sink。

因此 `deployable reference-monitor algorithm` 稍强，建议改为 `implementation-oriented reference-monitor algorithm` 或 `deployable design with a narrow prototype path`。CSF 理论论文不需要为了显得“系统”而扩展成大规模性能实验；真正需要的是 proof-to-implementation contract 表，以及一个明确说明 trusted adapter obligations 的端到端 sequence diagram。

### 私有 paper-formation lineage：当前 verdict 为 REVISE

independent recheck 没有接触 raw trace，确认 pinned Codex source contract 的核心思路成立，但发现三个会影响 final count claim 的缺陷：

1. matching header、`task_started` 和 first marker 可在 timestamp 缺失/损坏时仍决定 counting boundary；
2. extractor 接受 `trigger_turn:false`，而 pinned spawn path 要求 initial communication 为 true；
3. 每个 live rollout 被 reopen 两次，未固定同一个 byte snapshot，存在 TOCTOU；独立 fixture 已构造第一遍验证一个 header、第二遍计入两个 header 的成功攻击。

因此当前 exact event/tool counts，连同其 rounded projection，应在修复并对 immutable snapshot 双重 rerun 前视为 **provisional**。论文不能以现在的肯定语气写“the case contains …”。最小路径是：修 extractor、fail closed、固定一份只读 snapshot/byte limit+digest、两次 rerun 记录同一 snapshot 的 sanitized digest log，再刷新 aggregate。

即使修好，private case 仍只能支持：

- one author-operated retrospective fixed-cutoff longitudinal case；
- workload shapes、copied-history normalization、observability gap；
- 不能支持 prevalence、安全率、算法正确性、exactly-once 或 rollback success。

正文目前基本遵守最后一条，这一点值得保留。

### 双盲

目前正文做了 rounded counts，但 anonymous artifact 仍需额外防链接：

- 不发布 raw trace、HMAC key、private summary、root/thread IDs、cutoff timestamp 或 author path；
- exact Codex/runtime/model 组合和 distinctive count vector 也可能 fingerprint；
- HMAC 只能称 `author-auditable commitment`，不能称 reviewer-verifiable evidence；
- 对 artifact history、absolute paths、usernames、timestamps、HMAC vectors 做完整 scrub。

### 伦理

“author-operated、没有 recruited/manipulated users、raw not released、no IRB claim”是合理起点，但 CSF ethics 预期还要求写清：

- incidental third-party/private content 的存在；
- data minimization；
- 谁可访问；
- retention/deletion policy；
- non-release policy；
- 为什么 aggregate 的研究收益超过 residual linkage/privacy risk。

`privacy_assertions` 当前不是完整 schema enforcement：它未验证 dictionary keys，且允许任意特定长度 hex value 出现在任意字段；修复后再称“only allowlisted aggregates”。

## 7. 结构与 CSF 12-page fit

当前 PDF 为 11 页；related work 在第 9 页，discussion/conclusion 和 references 从第 10 页交叠，references 延续到第 11 页。按 CFP 所述 12 页正文、AI acknowledgment/参考文献不计，形式上有空间，但不是无限空间。正文已经有两个表，却缺少最能帮助理解的图。

建议增加一张极小、但高价值的图：三条 state planes + token 的 `remaining -> prepared -> receipt` 轨迹，同时画出 history Fork 只复制 representation、controller 只保留一个 current occurrence。它会比更多 prose 更能防止 reviewer 把 token 看成普通 nonce。

为图和 related-work property matrix 腾空间，建议压缩：

- lifecycle walkthrough 中重复解释 Prepare/Retry 的段落；
- validation 中逐项罗列 fixtures 的细节，保留 evidence boundary 和 summary table；
- private case 的 extraction mechanics 移到 appendix/artifact，只在正文保留 selection unit、normalization principle、可用结论和 limitation；
- discussion 中与 intro 已重复的 “why not rollback everything / exactly-once” 各缩成一段。

不建议删 theorem statement、premises、trusted boundary 或 proof sketch。CSF reviewer 首先会审正确性和 foundations，不是测试数量。

当前没有正式 RQ 不是致命问题；理论论文无需硬套系统 RQ。但 validation 可以用三个 evidence obligations 组织：

1. formal safety and theorem audit；
2. realizability of the atomic monitor boundary；
3. whether real traces exhibit the workload shape and expose the required telemetry。

## 8. Closest-work / same-claim risk（一手来源）

| 工作 | 与本文最接近处 | 本文可防守差异 | 当前 related-work 缺口 |
|---|---|---|---|
| [Bowers et al., Consumable Credentials (NDSS 2007)](https://www.ndss-symposium.org/wp-content/uploads/2017/09/Consumable-Credentials-in-Linear-Logic-Based-Access-Control-Systems.pdf) | linear credential、atomic ratification、proof+nonce binding、bounded reuse | typed transport of controller occurrences across intentional Fork/Restore/Merge；RTC durable-origin theorem | 当前一句话严重低估重叠；必须逐 property 对比 |
| [ACRFence](https://arxiv.org/html/2603.20625) | Action Replay、Authority Resurrection、restore 后 single-use authority resurfacing、effect-log replay-or-fork | 不只 restore；覆盖 choice/parallel fork、live/replacing restore、两种 merge，并 mechanize non-amplification | 应直接比较 attack/threat object、covered operators、proof |
| [Commit-Time Authorization](https://arxiv.org/html/2607.10487) | freshness、causal priority、effect binding、commit eligibility；branch effects | 它验证 per-effect witness eligibility；本文限制一个 origin 在多个 current witnesses 中的 multiplicity | 当前差异有方向，但应明确“eligibility vs occurrence conservation” |
| [Atomix](https://arxiv.org/html/2602.14849) | epochs、staged/gated effects、idempotency keys、losing branches、transactional outbox | choose-one/speculative settlement 不等于 live parallel descendants 和 Merge 中保留一个共享 origin | “focus on progress”过于笼统，容易被认为 strawman |
| [Cordon](https://arxiv.org/html/2606.17573) | semantic transaction、lineage、staged effects、delegated authority、outbox/idempotency/recovery metadata | task transaction containment 不等于 multi-form history occurrence transport/non-amplification theorem | 应按 lineage、effect binding、fork/merge、proof 逐列比较 |
| [Rebound](https://arxiv.org/abs/2511.13641) | policy-authorized rollback、security continuity、reference monitor、atomic state/rollback、formal proof | 本文允许 intentional branch/merge 并保护 future authority occurrence | 当前遗漏；这是 reviewer 很可能找到的 rollback continuity closest work |
| [LCM](https://arxiv.org/abs/1701.00981) | rollback/fork detection、fork-linearizability | malicious fork divergence vs permitted typed branching with non-amplification | 现有定位基本正确 |
| [AWS durable idempotency guidance](https://docs.aws.amazon.com/durable-execution/patterns/best-practices/idempotency/) / [transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html) | stable operation key；atomic local state+event intent；later relay | 工业意义在于 history admission 和 authority occurrence semantics，而非重新发明 outbox | 算法 section 应明确把这些当 deployment substrate，强化工业可用性而非 novelty |

建议加一张 property matrix，列：conserved object、history operations、live multi-branch、Merge、commit boundary、external effect semantics、mechanized proof。现在按主题写的 related work 容易让 reviewer 认为作者只是在重述各论文的“focus”，没有比较 same claim。

## 9. Unsupported / ambiguous phrases 与最小修复

以下按当前行号列出最值得立即修的句子。

| 位置 | 当前表述/问题 | 最小修复 |
|---|---|---|
| `main.tex:60` | “Every … has an immutable origin token”易被理解为 origin map 不变；实际 tentative claim mapping 会 transport | 写“an immutable token identity/specification whose controller witness is transported” |
| `main.tex:65--67` | exact accounting + full history preservation 暗示已完成统一 audit | 在 Audit/Main 集成前降为“we formalize/prove in separate modules”；完成 audit 后恢复 |
| `main.tex:69` | “resource accounting is insufficient”过于普遍 | 限定为“aggregate tracked vectors that erase per-origin identity” |
| `main.tex:70--71` | “unavailable to local workspace guards”超出 `LocalAuthObs` | 写“unavailable to one fixed local plan-reuse observation” |
| `introduction.tex:48--49` | “every future protected operation”与 online planning 冲突 | 写“every protected operation approved in the installed plan epoch” |
| `introduction.tex:69--75` | weighted load 被描述为真实 current/bound load | 在 bound coherence theorem 前，只称“spec-weight projection of disposition” |
| `introduction.tex:76--79` | consumable credential overlap 处理过轻 | 直接写 atomic ratification/outbox 已有；novelty 是 multi-form history transport + RTC origin proof |
| `introduction.tex:85--87` | “minimal … proving resource conservation does not imply”无 abstraction qualifier | 加 “for an aggregate checker assigning zero in every tracked coordinate” |
| `introduction.tex:95--97` | stable origins through arbitrary history 未写 source safety | contribution 可简写，但正式 theorem 必须加 `Safe(S)` |
| `introduction.tex:99` | “deployable”高于当前 narrow integration | 改 `implementation-oriented`，或要求 end-to-end native mediation evidence |
| `model.tex:98--102` | 声称 current **or bound** claim 与 spec coherence | 当前只有 optional current bridge；删 bound，或补 bound/init/preservation proof |
| `model.tex:111--120` | weighted theorem本身被写成 actual witness-load theorem | 区分 algebraic disposition partition 与 controller-row coherence |
| `model.tex:162--169` | global freshness/epoch install 是 prose obligation、非 theorem | 保留，但明确列为 trusted assumption，别让 abstract 暗示 cross-epoch result |
| `semantics.tex:27--28` | relation 被描述为显式 local atom + target scan | 新 defended gate 尚未成为 `TokenPositiveTrace` grammar；加 bridge/relation或改措辞 |
| `semantics.tex:36` | “origin set and token specification unchanged” | 写“initial token identity set is fixed; the same external epoch spec remains applicable”；origin map 本身会 transport |
| `semantics.tex:108--109` | “Every authority mutation advances”比 paper-facing monotonic theorem强 | 逐 constructor 证明严格 `+1`，或写“the unified theorem proves version monotonicity” |
| `results.tex:6` | “All results … mechanized” | Audit root 未覆盖新 token/weighted theorem，当前不成立 |
| `results.tex:63--67` | RTC theorem 缺 source `Safe` premise | 改为“If `Safe(S)` and …” |
| `results.tex:88--90` | spec 像 state 内字段一样“unchanged” | 改成 fixed external spec + initial-set equality 的精确表述 |
| `results.tex:99--102` | “same partition rather than unrelated ledgers”可能暗示与 old quantitative rows coherence | 写“two projections over the token disposition”; 明说尚未证明等于 claim-indexed stored rows，或补 bridge |
| `results.tex:119--120` | “changing any resource bound cannot repair … all vectors erase” | 改成 all-zero aggregate checker 的精确 statement；承认 token-indexed unit coordinates 等价于引入 identity |
| `results.tex:148--150` | theorem 推出 authenticated roots “must” | witness 只推出 owner topology；roots 改 `may be required by admission dependencies` |
| `algorithm.tex:34--37` | `Refine` 在模型 operation list 中未定义；validation 也用 Refine，而 formal example 是 parallel Fork | 统一叫 transfer/parallel Fork，或正式定义 Refine 并纳入 relation |
| `algorithm.tex:109--110` | “permits incremental checking”没有实现/成本证据 | 写“admits an affected-fiber implementation”并标为 design implication，或给 microbenchmark |
| `algorithm.tex:114--115` | 列出的 semantic cache key 像已证明全局 sound | 改成 conservative implementation key；说明 lower bound 只证明 topology dependency |
| `validation.tex:24--31` | audit root 覆盖 every theorem 的断言当前错误 | 完成 frozen audit 后再保留；将 audit log 纳入 artifact |
| `validation.tex:53` | “zero-demand Refine”与理论 `parallel Fork` 命名不一致 | 统一 operation 名称，避免 prototype/model disconnect |
| `validation.tex:117--119` | “other audited datasets … none”是不可复核的广泛 negative claim | 给 dataset selection/table，或写“in the audited sample listed in Appendix …” |
| `validation.tex:129--145` | extractor contract 用肯定语气，但 recheck 已找到 timestamp/false-marker/TOCTOU 漏洞 | 修复、双 rerun 后更新；此前标 provisional |
| `validation.tex:147--156` | qualitative shapes/counts来自尚未 final rerun 的 selection | rerun 前不要作为 final empirical fact；rerun 后仍只作 workload/telemetry evidence |
| `validation.tex:165--174` | allowlisted aggregate 与 privacy guarantee 稍强；缺 retention policy | 改成 path-sensitive schema enforcement 后再称 allowlisted；补 minimization/access/retention/deletion |
| `related.tex:13--17` | atomic conversion + joint partition 被当主要 novelty，最易被 Bowers/outbox 反驳 | 把 exact transport/RTC theorem 放前面，已有原子 ratification放后面 |
| `related.tex:53--60` | Atomix/Cordon 被粗略归为 scope/progress/recoverability，像 strawman | 用 property matrix 逐项比较同一 claim |
| `discussion.tex:75--79` | proof scope 包含 truthful immutable specs，但没有 bound coherence/preservation | 精确区分 trusted external spec、initial set，以及 optional current coherence |
| `conclusion.tex:96--97` | weighted accounting被暗示为 actual controller resource accounting | 若不补 coherence，只称 token-spec weighted projection |

## 10. 模拟 CSF 评分

| 维度 | 当前分数 | 理由 |
|---|---:|---|
| Originality | 3/5 | agent history occurrence transport + RTC origin 有潜在新意；token/outbox/partition 本身已有 |
| Technical soundness | 2/5 | 新 theorem 很强，但 Audit 未闭环、relation/gate 有歧义、bound coherence 缺失、部分 prose 漏 premise |
| Significance | 4/5 | fork/restore/merge + external effects 是真实且扩大的 runtime 问题，原则可迁移到 RL/multi-agent/workflow |
| Clarity | 4/5 | title、counterexample、三层状态清楚；formal object 混用和 contribution 层级仍需修 |
| Evaluation / evidence | 3/5 | Lean + controlled monitor 很适合 CSF；private trace 当前 REVISE，且 native integration 很窄 |
| Reproducibility | 2/5 | public formal/runtime 可潜在复现；Audit 尚未覆盖；private count 不可独立复现且 extractor 尚需修 |
| Ethics / double blind | 3/5 | 风险意识良好，但需补 retention/minimization、修 privacy schema、消除 fingerprint material |
| Overall | **2/5 Weak Reject** | 核心可救且有趣，但 strongest claims 尚未形成一个闭环、无歧义的 theorem-to-runtime contract |

### Top-5 blockers

1. **Formal closure：** 把 strengthening + weighted theorem 纳入 Audit/Main；明确一个 paper `TokTrace`；逐条 theorem mapping；消除“all results mechanized”的当前假断言。
2. **Coherence gap：** 当前 weighted partition 只是 token-spec/disposition 的代数投影；没有 bound witness coherence，也没有与旧 quantitative plan rows 的 bridge。要么补证明，要么降 claim。
3. **Novelty defense：** 正面比较 Consumable Credentials、ACRFence、Commit-Time Authorization、Atomix、Cordon、Rebound；把 exact lineage transport iff 和 RTC origin stability 作为主贡献。
4. **Private trace REVISE：** 修 timestamp boundary、`trigger_turn` 和 two-pass TOCTOU，在 immutable snapshot 上双 rerun；否则删除/明确 provisional counts，并完成双盲/伦理补充。
5. **Scope discipline：** 收紧 zero-vector、observation/root-cache、deployability、strict version advancement 和 spec immutability 表述；统一 Refine/Fork terminology。

## 11. 最小可接受修订路线

不需要再加一个大机制或大规模实验。最高 paper-value 的顺序是：

1. **Formal gate closure：** frozen Audit 导入并打印全部 paper-facing token/strengthening/weighted/observation theorem；fresh kernel audit；生成一张 paper claim-to-theorem appendix table。
2. **选一个 coherence 策略：** 若时间紧，诚实降级为“two projections over an immutable token disposition”，删除 actual bound-load/old-row coherence；若要保留强统一故事，则补 current+bound coherence、initialization、all-step preservation 和旧 quantitative row bridge。
3. **重写 abstract/contributions/results：** 两个 headline theorem 是 local iff 和 RTC existing-origin stability；partition/SQLite/trace 都降为 supporting evidence。
4. **related-work property matrix：** 用同一组 properties 对最接近的六项工作做 same-claim comparison；加入 Rebound。
5. **修私有 extractor 并 rerun，或暂时删除具体 private counts：** 这不会伤害 theory paper 的核心。保留“paper formation trajectory as one retrospective case”即可。
6. **加一张状态/occurrence 图，压缩 validation mechanics：** 帮 reviewer 一眼看出复制的是 representation，不是 controller authority occurrence。

### Gate routing

- 先回到 **formal EXPERIMENT/VALIDATION gate**：Audit/Main、defended relation bridge、coherence 决策、trace extractor recheck；
- 随后进入 **WRITE gate**：abstract/contributions、claim scope、related-work matrix、图；
- 不建议现在启动新的大规模 benchmark。若还有实验预算，唯一优先项是一个 production-shaped native history event 到 monitor descriptor 的 end-to-end contract test，而不是更多 synthetic fixture 数量。

## 最终判断

这篇工作的 agent 特异性不是“LLM 需要 token”，而是：agent runtime 把 history copying、多个 live continuation、semantic Merge、在线生成计划和异步 heterogeneous effects 变成常态；于是经典的一次性授权必须从单一路径 consumption，提升为**跨 history algebra 的 occurrence conservation**。这既比单纯 workspace rollback 更广，也比一般 capability possession 更细。

如果论文把这一点证明得完全闭环，它会是一个有原则、可被工业 runtime 采用、也符合 CSF 的理论贡献。当前最需要的不是增加名词，而是让每个强句都落在一个明确、已审计的 theorem 上，并把已有的 nonce/outbox/linear credential 部分主动让给 prior work。
