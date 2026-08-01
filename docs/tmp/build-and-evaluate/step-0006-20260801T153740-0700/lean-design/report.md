# Step 0006 — Boundary II Lean 可机械化性设计

## 结论先行

**可机械化，而且现有 Lean 定义已经足够表达论文中的真实操作语义；不应另造一个把结论藏进定义里的抽象 checker。** 最小可信实现是在一个新模块 `AuthorityContinuity/Serialization.lean` 中：

1. 固定源状态中的 owner 分组和稳定 operation assignment；
2. 用现有 `LifecycleState.PrepareOK`、`prepareState` 和 `CoreStep.prepare` 定义“某个 owner 顺序实际可执行”；
3. 先证明 `preparedCore` 的 batch-normalization/composition 定理；
4. 再证明最终 support 当且仅当所有 owner permutation 都能通过真实 `PrepareOK`；
5. 把“到达 atomic result”作为 composition 的推论，而不是塞进 enabledness 定义。

建议的 headline theorem 是：

```lean
theorem universal_owner_serializable_iff_final_support
    (hWF : A.LWF) (hAC : AC A.auth)
    (hAtomic : A.PrepareOK U assignment) :
    UniversallyOwnerSerializable A U assignment ↔
      FinalOwnerSupport A.auth U
```

其中 `UniversallyOwnerSerializable` 必须量化所有 source-fixed owner permutations，并由连续的、现有的 `PrepareOK` 证据生成；不能定义成 final support 的同义词。

**定理不是 definitional tautology，但数学核心比论文叙事看起来更小。** 在 exact cumulative filtering、`Nat` 非负 demand、source-fixed owner groups 和 immediate deterministic cleanup 固定后：

- “最终结果与 atomic batch 相同”主要是一个 batch normalization/交汇合定理；
- 真正有操作内容的是“任意顺序都不会在轮到某 owner 前把它 tombstone”；
- 该性质由 final-support witness 对所有 prefix 的继承性充分刻画，反向由“把 unsupported owner 放最后”得到。

因此 mechanization 能排除隐藏漏洞并给出工业可用的单次 final-support certificate，但单靠此 theorem 很难形成“全新基础数学”。更稳妥的贡献表述是：**对 cleanup-aware conditional-to-durable promotion，final support 是 factorial schedule checking 的一个必要且充分的一次性 certificate；失败时还能构造一个必失败的 last-owner order。**

另一个事实需要纠正：工程并非严格意义的 “mathlib-free”。`lean/lakefile.lean` 固定了 Mathlib `v4.30.0`，`Model.lean` 直接 import Mathlib。准确说法应是“无项目自定义公理、无 domain-specific 外部证明库，Lean/Mathlib 均固定为 v4.30.0”。

## 已审计范围与当前缺口

我阅读了全部 paper-facing promotion/cleanup 定义、`PrepareOK`、`CoreStep.prepare`、theorem audit，以及论文 Boundary II 与现有 Python witness。相关现状如下。

### 已有、可直接复用的定义

| 层 | 现有对象 | 作用 |
|---|---|---|
| authority core | `State`, `WF`, `AC` | status partition、finite allowed family、owner support、capacity invariant |
| exact guard | `promotedLoad`, `remainingConditionalLoad`, `guardedAllowed`, `guardClosure_iff` | 一个 batch promotion 后的精确安全 family |
| cleanup | `rawPromotion`, `unsupportedOwners`, `preparedStatus`, `cleanedAllowed`, `preparedCore` | promotion 后立即 terminalize unsupported owners |
| cleanup fact | `cleanedAllowed_eq_guardedAllowed` | cleanup 不再改变 guard 的 denotation；它改变 status/epochs |
| lifecycle target | `prepareState` | 同一 durable step 更新 authority、branch epoch 和 tickets |
| real enabledness | `PrepareOK` | nonempty、tentative/open、base capacity、assignment coverage/injectivity/freshness |
| real LTS | `CoreStep.prepare` | 从 `PrepareOK` 生成真实 paper-facing Prepare transition |
| preservation | `prepare_preserves_wf_ac`, `prepare_preserves_active_exact` | 每个已 admission 的 prefix 保持生命周期不变量 |

精确位置：`Lifecycle.lean:125–165` 是 promotion/cleanup target；`Lifecycle.lean:175–203` 是 exact guard 与 cleanup-denotation fact；`Lifecycle.lean:241–358` 是 status/load/preservation 辅助事实；`Lifecycle.lean:375–427` 是 `prepareState` 和 `PrepareOK`；`Lifecycle.lean:990–1001` 是真实 `CoreStep.prepare`。

### 当前没有的内容

`lean/README.md:100–108` 明确声明 Boundary I/II 不在 mechanization scope。当前没有：

- source-fixed owner group；
- owner permutation/schedule；
- sequential Prepare run；
- prefix/full-batch load monotonicity；
- self-promotion 对 owner-containing configurations 的 load-neutrality；
- `preparedCore` sequential/atomic normalization；
- final support 与 universal enabledness 的 iff；
- 论文中的 positive/unsupported Lean witness。

Python artifact 只验证两个固定实例；它没有一般定理。

## 推荐的新模块与核心定义

### 模块边界

最小新增 proof module：

```text
AuthorityContinuity.Model
  -> AuthorityContinuity.Checker
  -> AuthorityContinuity.Lifecycle
  -> AuthorityContinuity.Serialization   (new)
  -> AuthorityContinuity.Audit/Main
```

`Serialization.lean` 只需 import `AuthorityContinuity.Lifecycle`。不需要修改 `State` 或重写 `Prepare`。具体 finite witnesses 可以先放在同一文件末尾的 `SerializationExamples` namespace；若超过约 150 行，再拆成 `SerializationExamples.lean`。

不要让预检依赖一个先验的 generic `PromotionSystem` typeclass。先证明 authority-native 版本；一般抽象仅在 native proof 成功后提取，否则很容易把 `prefix antitone`、`self-neutral` 或甚至 universal enabledness 直接放进 interface，造成循环的“机械化”。

### 1. Source-fixed owner partition

建议定义：

```lean
def ownerGroup (A : State Coord Claim Branch)
    (U : Finset Claim) (b : Branch) : Finset Claim :=
  U.filter fun c => A.status c = .tentative b

def batchOwners (A : State Coord Claim Branch)
    (U : Finset Claim) : Finset Branch :=
  Finset.univ.filter fun b => (ownerGroup A U b).Nonempty
```

必须使用**源状态** `A`，而不是在每个 prefix 后重新分组。否则 cleanup 后消失的 claim 会从 pending schedule 中静默消失，错误地把 cancellation 当作成功。

需要的 partition lemmas：

- `ownerGroup_subset_batch`；
- `ownerGroup_nonempty_iff_mem_batchOwners`；
- 不同 owners 的 groups disjoint；
- 在 `hAtomic.member_open` 下，所有 groups 的 union 恰为 `U`；
- 每个 `c ∈ U` 有唯一 source owner。

### 2. Fixed assignment restricted to one group

使用 atomic batch 已给出的 stable assignment，而不是给每一步重新寻找 operation ID：

```lean
def restrictAssignment (assignment : Operation -> Option Claim)
    (V : Finset Claim) (e : Operation) : Option Claim :=
  match assignment e with
  | some c => if c ∈ V then some c else none
  | none => none
```

这使 sequential run 和 atomic run 使用同一批 claim/effect bindings。由 atomic `PrepareOK` 可推出每组的 `assigned_mem`、`covered`、`assignment_injective`；前面 groups 的 tickets 不会占用后面 group 的 operation IDs，因此可推出 step-local `fresh`。

若只证明一个新造的 authority-level `PromotionEnabled`，会漏掉 tickets、freshness、open branch/grant epoch，不能充分支持论文所称的 “executable ordering”。它可以作为内部 lemma，但 headline 必须回到真实 `PrepareOK`/`CoreStep.prepare`。

### 3. Owner schedule 与真实 sequential run

建议 schedule 是 `List Branch`：

```lean
def OwnerSchedule (A : State Coord Claim Branch)
    (U : Finset Claim) (order : List Branch) : Prop :=
  order.Nodup ∧ order.toFinset = batchOwners A U
```

然后定义一个 relation；每个 cons 都要求当前状态上的真实 `PrepareOK`：

```lean
inductive SerialPrepare
    (source : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) :
    LifecycleState Coord Claim Branch Grant Operation ->
    List Branch ->
    LifecycleState Coord Claim Branch Grant Operation -> Prop
  | nil (current) : SerialPrepare source U assignment current [] current
  | cons {current final b rest}
      (ok : PrepareOK current
        (ownerGroup source.auth U b)
        (restrictAssignment assignment (ownerGroup source.auth U b)))
      (tail : SerialPrepare source U assignment
        (prepareState current
          (ownerGroup source.auth U b)
          (restrictAssignment assignment (ownerGroup source.auth U b)))
        rest final) :
      SerialPrepare source U assignment current (b :: rest) final
```

`CoreStep.prepare ok` 随即证明每个 relation edge 都是现有 closed LTS 的真实 step。`SerialPrepare` 只允许 Prepare，因此“无 lifecycle interleaving”不是一个自然语言假设，而由 relation 的语法强制。

### 4. Final support 与 universal serializability

```lean
def FinalOwnerSupport (A : State Coord Claim Branch)
    (U : Finset Claim) : Prop :=
  ∀ b ∈ batchOwners A U,
    ∃ C ∈ LifecycleState.guardedAllowed A U, b ∈ C

def UniversallyOwnerSerializable
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation -> Option Claim) : Prop :=
  ∀ order, OwnerSchedule A.auth U order ->
    ∃ target,
      SerialPrepare A U assignment A order target ∧
      target.auth = (prepareState A U assignment).auth
```

这里的 equality 正好覆盖论文写的 `(D,Q,X,front(T))`：`State.status` 区分 durable/tentative/terminal/unissued，`State.allowed` 是 `front(T)` 的 extensional denotation；capacity/demand 在 Prepare 中不变。不要要求 frozen guard AST syntactically equal：serial run 会留下多行 prefix guards，atomic run 只有 full-batch row，论文和 Python artifact 都只承诺 denotational equality。

若 full run 还有余力，可加一个可执行 certificate：

```lean
def checkFinalOwnerSupport (A) (U) : Bool :=
  finiteAll (batchOwners A U) fun b =>
    (guardedAllowed A U).any fun C => decide (b ∈ C)

theorem checkFinalOwnerSupport_sound_complete :
  checkFinalOwnerSupport A U = true ↔ FinalOwnerSupport A U
```

这给 runtime 一个明确算法：构造一次 final guard，对每个 batch owner 做一次 support query；无需枚举 `n!` 个 orders。

## Proof dependency graph

```text
atomic PrepareOK
  |
  +--> source owner-group partition + restricted assignments
  |
  +--> every subset of U is source-valid and has <= final promoted base load

promotionTotal(A,S,C,k)
  := promotedLoad A S k + remainingConditionalLoad A S C k
  |
  +--> normalized per-claim load formula
  |      (tentative c is charged iff c in S or owner(c) in C)
  |
  +--> prefix monotonicity:
  |      S subset U -> promotionTotal(A,S,C,k) <= promotionTotal(A,U,C,k)
  |
  +--> final-guard subset of every prefix guard
  |
  +--> owner self-neutrality:
         b in C -> load(A,U\U_b,C,k) = load(A,U,C,k)

exact cleanup definitions
  |
  +--> preparedCore allowed = guardedAllowed
  +--> explicit status characterization after one batch
  +--> preparedCore composition/normal form:
         preparedCore (preparedCore A S) V
           = preparedCore A (S union V)
         for disjoint source-valid S,V
  +--> fold over any owner order equals atomic preparedCore

final support
  |
  +--> support witness survives every prefix
  +--> later owner group remains tentative/open
  +--> restricted assignment remains fresh
  +--> real PrepareOK for every next group
  +--> all owner schedules produce SerialPrepare run
  +--> fold normal form gives atomic authority result

not final support
  |
  +--> choose unsupported b
  +--> order all other source owners, then b
  +--> if an earlier group fails: witness already obtained
  +--> otherwise prefix normal form is prepare(U \ U_b)
  +--> self-neutrality says b has no support at that prefix
  +--> immediate cleanup terminalizes U_b before its turn
  +--> final PrepareOK.member_open is impossible
  +--> a failing permutation exists
```

## 建议的 lemma/theorem 清单

### Load/guard layer

1. `promotionTotal_eq_sum_indicator`：把 `promotedLoad + remainingConditionalLoad` 规格化为逐 claim 的 0/1 charge。这会显著降低后续 Finset sum proof 的难度。
2. `promotionTotal_mono_batch`：`S ⊆ U` 时 total load 非递减。
3. `guardedAllowed_antitone_batch`：`guardedAllowed A U ⊆ guardedAllowed A S`。
4. `ownerGroup_self_neutral`：若 `b ∈ C`，从 `U \ U_b` 到 `U` 的 load 不变。
5. `owner_support_before_own_group_iff_final`：在包含 `b` 的 configuration 上，last-owner prefix guard 与 final guard 等价。

### Cleanup/normal-form layer

6. `preparedCore_status_iff`：对 durable/tentative/terminal 分别给出 source-relative characterization。
7. `guardedAllowed_after_preparedCore`：第二个 exact guard 的 denotation 等于 source 上 union batch 的 guard。
8. `preparedCore_union`：disjoint source-valid batches 的 sequential target 等于 union batch target。
9. `serialPrepare_auth_normal_form`：任意成功 prefix 的 authority state 等于源状态对累计 groups 的 `preparedCore`。
10. `serialPrepare_full_auth_eq_atomic`：任意完整成功 owner schedule 到达 atomic authority target。

### Lifecycle enabledness layer

11. `restrictAssignment_prepareOK`：从 atomic `PrepareOK`、当前 prefix normal form 和 next-owner support 推出 next group 的真实 `PrepareOK`。
12. `final_support_serial_run`：final support 为任意 owner schedule 构造完整 `SerialPrepare`。
13. `unsupported_owner_last_disabled`：final unsupported owner 放最后时不存在完整 `SerialPrepare`。
14. `universal_owner_serializable_iff_final_support`：headline iff。
15. `not_final_support_failure_certificate`：返回 unsupported `b` 和一个 `others ++ [b]` failing order，作为 scheduler/diagnostic corollary。
16. `checkFinalOwnerSupport_sound_complete`：可执行 single-final-state certificate（推荐但非最小 theorem 的逻辑前提）。

## Preflight 设计

Preflight 必须走当前 pinned Lean project 和真实 `PrepareOK`，不能只 `#eval` 一个新 Boolean。

### Positive case

- `Coord = Fin 1`
- `Branch = Fin 2`，owners `a,b`
- `Claim = Fin 2`，`ca@a = 1`, `cb@b = 1`
- `capacity = 2`
- `allowed = {empty,{a},{b}}`（exclusive/downward closed）
- `U = {ca,cb}`，两个 fresh operation IDs 分别绑定这两个 claims

应 kernel-check：

1. source `LWF`, `AC`, `ActiveExact`；
2. atomic `PrepareOK`；
3. final family 同时 support `a,b`；
4. `[a,b]` 与 `[b,a]` 均有真实 `SerialPrepare`；
5. 两个 target 的 `.auth` 都等于 atomic target `.auth`。

### Unsupported-owner counterexample

直接复现论文和 Python artifact 的最小实例：

- `capacity = 2`
- exclusive owners `s,t`
- `cs@s = 1`
- `ct@t = 1`
- 未 promotion 的 `u@t = 1`
- `U = {cs,ct}`

Atomic final guard 只保留 `empty` 和 `{s}`；`t` 无 final support，atomic cleanup 使 `u` terminal。

应 kernel-check：

- `s` first 后 `{t}` load 为 3，cleanup terminalizes `ct,u`；因此 `t` group 的下一步 `PrepareOK.member_open` 不可能成立；
- `t` first 保留两边 support，随后 `s` 能成功；最终 authority state 与 atomic cleanup 相同；
- `FinalOwnerSupport` 为 false，`UniversallyOwnerSerializable` 为 false，但至少一个 order 成功。这验证结论是 “not every order”，不是 “no serial order”。

### Preflight acceptance rule

一次真实 `lake build AuthorityContinuity` 通过；上述 concrete declarations 无 `sorry`/项目 axiom；`#print axioms` 只出现仓库白名单中的 `propext`、`Quot.sound`、`Classical.choice`。若 positive 或 negative case 与 Python 结果不一致，停止 general proof 并先修模型对应关系。

## Full-run acceptance criteria

只有同时满足以下条件，才能声称 Boundary II 已 mechanized：

1. **一般性**：theorem 量化任意 finite Coord/Claim/Branch，不依赖两个 fixed examples。
2. **真实 enabledness**：每个 prefix 使用现有 `PrepareOK` 或直接产生 `CoreStep.prepare`；不能用只检查 final support 的自定义 enabled predicate 代替。
3. **真实 cleanup**：使用现有 `unsupportedOwners`/`preparedStatus`/`prepareState`，并包含 terminal claims；不能只比较 allowed family。
4. **固定 batch/owner/assignment**：分组和绑定从 source state 冻结，且 atomic `PrepareOK` 是唯一 batch-validity premise。
5. **两方向**：final support -> all orders，以及 all orders -> final support 都由 kernel 证明。
6. **atomic equality**：所有成功的完整 schedules 都证明 `.auth = atomic.auth`，至少覆盖 durable、tentative、terminal 和 extensional allowed family。
7. **失败 certificate**：support 失败时构造一个具体 last-owner failing schedule；不能只得到经典逻辑的 `not all`。
8. **非循环**：任何 generic interface 都不能把 universal serializability、atomic equality 或等价 final-support premise 当 field。
9. **assumption mutations**：下节至少每个 load-bearing assumption 有一个 finite countermodel或一条 derivability proof。
10. **reproduction**：clean build、`audit.sh`、fresh `leanchecker` replay、existing Python tests/explorer 全部通过；headline theorem 加入 `Audit.lean`、audit whitelist 和 README matrix。

仅有 concrete preflight、仅 authority-level bespoke relation、或仅 sufficiency direction，都应判定为 mixed/incomplete，不能更新 paper 为“mechanized Boundary II”。

## Assumption mutation / independence tests

| Mutation | 预计破坏 | 最小 witness / 检查 |
|---|---|---|
| 去掉 immediate cleanup | necessity 失败 | unsupported `s/t` 实例；`s` first 后不 terminalize `ct`，于是两种顺序都可继续，尽管 final support false |
| prefix repair 允许保守过度裁剪 | sufficiency 失败 | positive `a/b` 实例；first step 使用 witnessed condition-on-owner shortcut，会 tombstone alternative owner，尽管 exact final support 两者都成立 |
| 比较 guard syntax 而非 denotation | atomic equality 失败 | serial target 有多条 prefix rows，atomic target 只有 full-batch row；allowed family 相同但 AST 不同 |
| 允许 interleaved Abort/Select/Revoke/Restore/Merge | final witness 不再控制 prefix enabledness | first group 后插入对 later owner 的 Abort 或 grant Revoke；final support from fixed source 仍 true，但 later Prepare 被禁用 |
| 每个 prefix 重新计算 owner groups | cancellation 被误报为成功 | unsupported `s/t`；`ct` 被 terminalize 后从 pending group 集合消失，错误 schedule 看似完成 |
| assignment 不固定或 operation ID 不 fresh | support 不再充分 | positive state 中让第二组复用第一组 operation ID，因 freshness 失败而 disable，与 support 无关 |
| claim 不要求 source-tentative / batch 不唯一 | normalization 和 terminal monotonicity 失效 | 把 terminal 或 durable ID 放进 `U`；`rawPromotion` 会把 terminal 改 durable或 `promotedLoad` double-charge，虽真实 `PrepareOK` 会拒绝 |
| demand 允许 signed refund，且 atomic repair 可重新开放 futures | prefix antitonicity/normalization 失败 | positive promotion 先裁掉 owner，later negative promotion 使 atomic final family 重开；frozen sequential guard无法恢复 |
| cleanup 非确定或只清部分 claims | same-target conclusion 失败 | 同一个 unsupported owner 的两个 remaining claims，两个合法 cleanup 选择 terminalize 不同子集，allowed 相同但 `X/Q` 不同 |
| owner group 不按 source owner、混合 unrelated owners | last-owner necessity proof失去 self-neutral step | 一个 group 同时含 `a,b` claims；“把 b 放最后”不再是合法 group permutation |
| 只检查 owners with remaining final bundles | 可能弱化 scheduler certificate | 应证明在 atomic-valid `Nat` 模型中该简化是否等价；若不能证明，坚持检查所有 source promoted owners |

尤其重要的三项是 exact-prefix、immediate-cleanup 和 fixed/no-interleaving；它们应在 paper theorem statement 中继续显式出现，而不是埋进实现。

## 预计难点与风险

### 1. `preparedCore_union` 是最大 proof burden

难点不是 allowed family 的交，而是 cleanup 会先把 source tentative claims 变成 terminal，第二步 load 又基于变化后的 status。建议先证明一个 source-relative per-claim load normal form，再证明：prefix 已 terminalize 的 owner 不出现在 prefix allowed family，因此这些 claims 对后继 guard 的 conditional load 为零。直接用 `simp` 展开三层 `Finset.filter/sdiff/sum` 很可能造成脆弱、超长 proof。

### 2. Lifecycle assignment freshness

authority normal form 不够。需要证明 earlier restricted assignments 只创建 earlier groups 的 tickets，global atomic injectivity/coverage 保证 later group 的 effect IDs 仍 fresh。应先给 `prepareState_opClaim` 建 fold lemma，而不是每个 schedule induction 中重复 case split。

### 3. List/Finset permutation bookkeeping

现有模型只要求 `DecidableEq Branch`，不应为了取 canonical order 强加 `LinearOrder Branch`。`OwnerSchedule` 用 `Nodup + toFinset`；“unsupported owner last” 的 list existence 用 finite-set induction构造。若为了 convenience 加 `[LinearOrder Branch]`，theorem 会得到一个与安全无关的额外 premise。

### 4. Active epochs 与 paper equality scope

Headline equality 应明确是 `.auth` equality，因为 paper theorem只列 `(D,Q,X,front(T))`。若扩展为整个 `LifecycleState` equality，还要证明 branch epochs 和 tickets 的 serial/atomic normalization；这可以作为 stronger corollary，但不应阻塞 core theorem。反之，enabledness仍必须通过 lifecycle `PrepareOK`，否则会漏掉 epoch/ticket failure。

### 5. Generic theorem 的 novelty 解释风险

如果把 proof 抽象到只剩：

- final family contained in all prefix families；
- own group is neutral on owner-containing configurations；
- cleanup deletes unsupported pending groups；

那么 iff 很可能在几十行内完成。这是有价值的 semantic decomposition，但也表明 theorem 是 generic support-erasing transition lemma。报告结果时必须把“generic independence/commutation 已知”与“authority promotion 提供了一个可一次查询的 final-support characterization”分开，不能用 mechanization 行数代替 novelty。

### 6. 预计规模

- definitions + partition/load lemmas：约 150–250 Lean lines；
- cleanup composition/normal form：约 250–450 lines；
- lifecycle `PrepareOK` lifting + universal iff：约 200–350 lines；
- examples/audit：约 100–180 lines。

总计约 700–1,200 lines 是可信范围。若超过约 1,500 lines，优先检查是否缺少正确的 source-relative normal form，而不是继续堆 `simp`。

## 定理是否其实 tautological？

### 不是 tautological 的部分

- `FinalOwnerSupport` 只观察一次 atomic final guard；它没有提 schedule、prefix 或 `PrepareOK`。
- `PrepareOK` 没有 final-support field；它检查当前 tentative/open/base/binding/freshness。
- immediate cleanup 修改 status 和 epoch，会让一个 algebraically valid later promotion 在 LTS 中变成不可执行。
- necessity 必须构造一个 owner-last order，并用 self-neutrality 证明该 owner 在轮到自己前已失去 support。

这些都不是 definitional reduction；Lean 必须证明真正的跨-prefix性质。

### 接近 elementary/generic 的部分

- `cleanedAllowed_eq_guardedAllowed` 已证明 cleanup 不改变 guard denotation；
- 非负 demand 使 full-batch family 自动包含于（准确说：是每个 prefix family 的子集）；
- owner 自己的 claims 在包含 owner 的 configuration 上从 conditional 移到 durable，total load 不变；
- 一旦 `preparedCore_union` 建立，任何成功 full order 到 atomic state 的 equality 基本是 normalization corollary。

所以 theorem 的“confluence”半边不应被包装成全新的并发理论。真正可 defend 的 nontrivial claim 是一个**精确、可执行、必要充分的 scheduler certificate**，连接了 generic commutation 条件与 agent runtime 中 irreversible owner cleanup / protected-effect sealing 的具体选择。

## 对 full experiment 的最终建议

1. 先做 positive/negative real-`PrepareOK` preflight；若失败，优先修 theorem statement，不要换成较弱 bespoke enabledness。
2. 先完成 authority-native `preparedCore_union` 与 lifecycle headline iff，再提取 generic support-erasing lemma。
3. 把 final-support Boolean checker 和 failing last-owner schedule 做成 corollaries；这比只证明存在性更有工业价值。
4. 将 theorem 的结果解释成 “serial-or-seal decision rule”：support 全过则任意 owner order；失败则给出不安全 order，但并不排除某个 verified order；需要 arbitrary-order dispatch 时 atomic seal。
5. 若 closest-work mapping 显示 generic lemma 已被现成 theorem 直接涵盖，mechanization仍可作为 model validation，但 paper 应把 Boundary II 降为实例化/工程原则，转向更强的 existential-order synthesis、minimum coordination 或 online observation theorem。
