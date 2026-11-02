# 阶段1：规则环境、连续重置与实例隔离

## 2026-11-02 · 阶段2基础动作入口已离线接入

新增显式`RuleEnvironment(control='primitives')`，支持等待、移动、攻击移动、攻击可见P2、停止、原地待命；默认rule模式不变。外部模式停用P1规则Controller，沿用原环境生命周期/裁判/隔离与token，新增候选预检查和独立完整基础动作日志。尚未开实机或训练模型，不是完整学习执行器；详细字段、8游戏秒过期检查和局限见[LEARNING_ACTIONS](LEARNING_ACTIONS.md)。下方旧“仅rule_tick”适用于默认规则模式。

## 2026-11-02 · 并发为可选提速，优先完成单实例训练接口

用户明确不要求同时开启4个实例；已有单实例连续重置、双实例隔离和受控异常恢复足以推进阶段2开发。四实例/100局吞吐作为后续效率与规模稳定性任务，不作为训练主线前置。尚未验证的长期稳定性、worker卡死/独立看门狗和最小化继续登记，不据此宣称长期无人值守训练已就绪。

新增`learning.four_instance_probe`及81–84实例：四worker在共同ready后需各推进至少20游戏秒/5step/1接受；81正常关闭、单次reset，其他三个保持绑定并继续推进，新旧/跨实例令牌隔离。父探针600墙钟秒、worker总540墙钟秒、每局1800游戏秒，失败不续局，另有有界清理。该流程当前未实机通过。

| 尝试 | 原始报告（artifacts/） | 结果 |
|---|---|---|
| 首次 | four-instance-live-20261102.json | 5.608墙钟秒，注册PermissionError；部分启动记录不完整，清理原记录的瞬时未知保留，后查无进程。 |
| 第二次 | four-instance-retry-live-20261102.json | 50.465墙钟秒，83启动读到100而非400；82进入后协作停止，其他未完整启动。 |
| 第三次 | four-instance-final-live-20261102.json | 56.653墙钟秒，84的25次身份采样均100，5秒只读等待超时；82协作停止，81/83部分记录。 |

三次均未完成共同运行或81重置，不计四实例稳定性/吞吐样本。各`*-failed-review-20261102.json`、`*-failed-review-index-20261102.json`和`*-failed-snapshots-20261102`保存原始证据；缺result/trajectory/timing等的局明确缺输入，未伪造完整复盘。

离线四进程注册压力复现owner.json读取共享拒绝，`attach_match.read_atomic_json`只对PermissionError作7次有界重试，缺失/损坏仍报错。修复后每进程100次、合计400次注册通过，不是400局游戏。`cleanup_owned`支持明确实例范围、核对venv子worker身份，先结束所属启动器让独立Job清理游戏，再退出worker；最终仍存在或未知身份即失败，瞬时AccessDenied与终止错误单独保留。

启动速度目前只有5秒只读等待，仍必须实际400才ready；它未解决第三次实测的100%。命令行已含400，各实例speed.txt均300，不能据此推断闭源启动器根因。现有`Game.set_speed`经目标PID通道可设置速度，但本轮尚未接入启动流程；用户调整优先级后停止此方向，不再开局。

最终2037全量离线通过（`four-instance-speed-full-tests-final-20261102.log`），第三次后运行Python未修改，实际进程为空；未提交/push。下一步按单实例推进阶段2完整动作适配、校验与训练数据读取，现有`rule_tick`仍不等于学习动作执行器。

## 2026-11-02 · 单实例异常退出后独立重开验证通过

运行循环现在先检查自有游戏进程是否仍存活，再读取守卫/共享内存；已退出时仅使用缓存观察记录`process_exit`，奖励null。清理只向完整身份仍匹配的自有游戏发送end_game，死亡或PID复用时跳过该命令；客户端资源与本局启动器仍按原流程清理。环境不会自动重开，调用方必须在清理、审计、源码/依赖和STOP门禁通过后显式reset。

新增`learning.recovery_probe`：两个独立worker，81号仅一次故障注入及一次恢复reset，82号持续推进。故障方式为`owned_launcher_job_exit`：验证本次cohort、当前worker、唯一launcher/game的PID/创建时间/名称及父子进程关系，仅终止所属launcher；等待原游戏实际退出后，才检查process_exit、清理并reset。注入前后保存各阶段证据，退出无法确认时不重开。每worker总墙钟240秒、每局600游戏秒，父探针运行上限300秒，另有有界清理。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m learning.recovery_probe --output artifacts/recovery-probe-unique.json
```

首次`artifacts/recovery-live-20261102.json`直接终止游戏时收到AccessDenied，故障注入未确认、没有恢复reset，两局正常关闭；原始失败与四复盘保存在`recovery-failed-live-review-20261102.json`。固定上游farm.py已注明游戏会修改DACL、终止启动器会由独立Job释放该局游戏；据此更换注入方法，未提权或按进程名全局终止。

修正后`artifacts/recovery-job-live-20261102.json`用时69.518墙钟秒通过：

| 对局 | PID | 规则step / 接受回执 | 结束时钟 | 结束类型 |
|---|---:|---:|---:|---|
| 81故障局，144916 | 22208 | 89 / 33 | 88.205 | process_exit |
| 81重开局，144958 | 25656 | 8 / 8 | 13.005 | environment_close |
| 82持续局，144917 | 16988 | 101 / 46 | 107.930 | environment_close |

81旧局确认清理后才reset；重开耗时约22.76秒，run_id/PID/episode均更新，旧局令牌被拒绝且未消费新令牌。新局时钟5.630→13.005且接受8条命令。82全程保持同一绑定：确认故障后11.505→重开就绪后96.240，88step/新增33接受；之后继续到107.930，8step/新增7接受。计数起点为已确认进程退出后的`fault_observed`，不把注入前握手期间的行动计入恢复期间。

三局各97份源码与72项依赖一致，实例清理及全局最终无残留通过；原始result/events/audits保留，四复盘/hero/opening/C1–C8及独立核对见`recovery-job-live-review-20261102.json`，首次失败独立引用。最终2024全量测试通过（`recovery-job-full-tests-final-20261102.log`），无失败/错误/跳过；早期定向测试调用曾因tests内模块导入路径报1错误，改用discover后通过并保留日志。复验后未改Python、未提交/push。

本次验证受控启动器退出造成游戏进程消失后的恢复，不代表任意崩溃、worker自身退出或底层调用卡死都能自动恢复。下一步推进四实例的小规模有界稳定性验证，再逐步完成100局与吞吐验收；最小化、通用独立看门狗和学习模型尚未完成。

## 2026-11-02 · 双实例短时验证通过

新增显式`RuleEnvironment(instance_id=81, cohort=<32位UUID>)`及82号实例。每个实例必须使用独立Python worker，分别持有实例锁、owner/session/STOP文件；普通73号入口保持原行为。运行记录使用含实例编号的唯一run_id，底层`inst81/inst82`目录、`War3-81.exe/War3-82.exe`及PID绑定的状态/命令/回执通道独立。SDK会修改进程级WAR3_PID，因此同一Python worker创建两个活动实例会被拒绝。

只允许同一cohort、仍存活且完整进程身份匹配的伙伴同时运行；未知或无关游戏仍拒绝。每次关闭仅处理本实例持有的PID/创建时间/名称，不按进程名批量关闭。全局STOP停止两局，实例目录STOP仅停止该实例。清理审计新增`process_scope=owned_instance`，其中空进程列表只证明本实例退出；全机清理由父探针另行核验。

地图生成与启动到ready使用有界启动锁串行执行，已启动的游戏继续决策。显示设置由父探针在无游戏时配置一次，worker只读校验；不会在另一局运行时写共享分辨率。上游`render_hook.log`仍是共享诊断，不作为逐实例隔离证据；逐局events/trajectory和instN.out分别保留。

有界验证入口（每次使用新的输出名）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m learning.parallel_probe --output artifacts/parallel-probe-unique.json
```

父探针运行期限240墙钟秒，之后另有有界清理；worker每局180墙钟秒/300游戏秒。无自动续局。失败先请求协作关闭，再仅清理本次确认身份的worker及其子进程/实例记录；未知或剩余进程使报告失败。

`artifacts/parallel-live-20261102.json`实测46.185墙钟秒通过，两个worker独立，双方ready至第一局开始关闭有约1.125秒重叠：

| 实例 | 游戏PID | 决策步数 | 接受回执 | 游戏结束时钟 |
|---|---:|---:|---:|---:|
| 81 | 22312 | 87 | 36 | 85.430 |
| 82 | 13388 | 15 | 9 | 20.580 |

重叠期间81号时钟81.730→85.430、82号6.380→10.080。82号拒绝一次来自81号的令牌且本局令牌未被消费。81号清理确认后，82号从15.305继续到20.580游戏秒，完成6次规则step并新增1条接受回执。两局均主动`environment_close`、截断奖励null，不是自然胜负或长期吞吐样本。

两局各96份冻结源码、72项依赖一致；全机最终无活动游戏/worker，未改运行源码、未提交/push。2016项全量测试通过，0失败/错误/跳过（`artifacts/parallel-full-tests-final-20261102.log`）；四复盘/C1–C8和独立核对见`artifacts/parallel-live-review-20261102.json`。

下一步验证单实例异常退出后的清理及独立重开，确认同伴继续运行，再逐步扩大到4实例/100局稳定性与吞吐测试。本次没有实机模拟崩溃、最小化、长期并发或模型训练，不代表阶段1整体完成。

## 先前单实例接口与连续重置

2026-11-02实现并实测`reset/observe/step/result/close`与两次连续重置。仍使用原来的`run_match`对局循环、规则控制器、P1白名单、裁判和清理，不另建策略实现。普通CLI/面板通过连续消费同一循环保持既有行为。

## 接口

```python
from learning.environment import RuleEnvironment

with RuleEnvironment() as env:
    frame = env.reset(game_seconds=60, wall_seconds=180)
    while not frame['done']:
        frame = env.step({'kind': 'rule_tick', 'token': frame['token']})
    result = env.result()

    # 显式重置：确认旧局清理、源码和依赖后才启动新局。
    frame = env.reset(game_seconds=60, wall_seconds=180)
    env.close()  # 提前关闭属于environment_close，中止奖励为null。
```

| 方法 | 当前契约 |
|---|---|
| `reset(map_alias='LR', opponent='kfai-human', seed=None, policy_version=VERSION, game_seconds=60, wall_seconds=180, until=None)` | 只支持当前LR/KFAI规则版本；非None种子明确拒绝，未实现引擎可复现种子。返回ready帧；启动失败则返回done及净化结果，或在启动前拒绝非法请求。 |
| `observe(player=1)` | 返回最近一次P1白名单缓存，含`cached=True`、`read_time`与游戏clock；不查询P0/P2，不伪称当前实时状态。返回对象深复制。 |
| `step({'kind':'rule_tick','token':...})` | 仅推进一次既有规则决策，返回观察、净化命令回执、done及终止语义。恢复执行时重新检查进程、epoch、STOP、期限和裁判；不使用旧观察直接下令。 |
| `result()` | 未结束为None；结束后仅返回run_id、cleanup_confirmed和净化termination，原始诊断保存在本局文件。 |
| `close()` | 幂等关闭；活跃局记`environment_close`，清理并保存结果。context manager在异常退出时同样执行收尾。 |

`frame`包含`observation/token/receipts/cached/read_time/done/termination`。终局帧保留最后安全观察及尚未返回的回执；接受命令不等于观察到效果。没有高层模型动作、合法掩码或学习执行器，这些属于阶段2。

令牌绑定逻辑环境UUID、本次episode UUID、run_id、PID、epoch、P1、观察编号与递增nonce。每次step在触碰引擎前消耗当前令牌；旧局、跨环境或重复请求拒绝，即使两局epoch恰好相同也不能复用。修改调用方拿到的帧不会修改内部缓存。

## 实时引擎与限制

`step`是规则控制器的决策边界，**不会暂停魔兽引擎**。两次调用之间游戏继续推进；`reset`后若调用方不继续step，控制器不会自行行动。后台CLI会持续驱动step，普通sparring入口也继续自动运行。

墙钟期限在API/运行时检查点执行。同步生成器在yield期间不运行守卫，因此它不是独立看门狗；调用者必须使用context manager或finally调用close。不能保证强行中断不返回的底层C调用，也不宣称固定游戏帧数、确定性仿真或可直接训练模型。

默认不传instance_id时仍使用物理实例73及既有单实例session路径。`learning-environment.lock`持锁覆盖整局及清理确认，两个默认RuleEnvironment不能竞争同一实例。显式81/82隔离模式见顶部；旧CLI仍有活动游戏检查。

## 重置门禁

reset先关闭上一局，并检查原始result所有清理/证据错误、source-audit、session与真实活动进程。第二局启动前重新计算上一局manifest对应的当前源码及接口契约依赖，检查摘要和安全路径；文件变化、缺失、审计不全或进程状态未知均拒绝继续。STOP存在时拒绝reset，不擅自清除。清理无法确认的环境进入不可继续状态，不自动重试。

## 有界实测入口

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m learning.reset_probe `
  --episodes 2 --game-seconds 60 --wall-seconds 180 --total-wall-seconds 420
```

必须显式指定1–10局。每局和整体都有有限墙钟上限，另有100000次step兜底；接口故障、手停、截止或清理失败后不续局。不生成模型、不批准训练actor。第二局会主动提交一次旧局令牌验证拒绝，然后才用新令牌正常推进。通过还要求至少一个非终止规则step和真实游戏clock推进，启动已超时、没有执行决策不能误报通过。

## 本轮证据

`artifacts/environment-reset-live-20261102.json`：两局共66.975墙钟秒。

| 对局 | PID / epoch | 游戏秒 | 墙钟秒 | 实际规则step | 接受命令 |
|---|---|---:|---:|---:|---:|
| 20261102-115149 | 6924 / 1 | 60.780 | 34.48 | 59 | 15 |
| 20261102-115224 | 14864 / 1 | 60.105 | 31.95 | 60 | 15 |

第一局清理确认后才启动第二局，第二局旧令牌被拒绝；两局源码清单一致，各93冻结文件、72依赖核验通过，session关闭、无游戏残留。两局均按游戏时限截断，奖励null，不当作自然胜负。轨迹/四复盘/C1–C8及单独复核见`artifacts/environment-reset-live-review.json`和各局目录。

2003项全量离线测试通过（`artifacts/environment-full-tests-final-20261102.log`），覆盖普通runner回归、ready前零下令、单步净化回执、close、idle后截止、换epoch、旧令牌/重复请求、锁、源码/依赖变化、失败/STOP不续及空跑不能通过。没有提交/push。

上述为单实例轮次的证据；最新双实例验证见顶部。四实例合计100局、吞吐、最小化与通用独立看门狗仍未验收。
