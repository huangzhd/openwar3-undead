# 阶段0训练轨迹白名单 v1

最新实机234922：12个点查询与native P1一致、18个实体样本一致；180.000秒截止，266帧/144对请求回执结构通过，最大间隔1.175秒。此前长空档未复现，根因仍未定位，不能据单局宣布稳定性通过。开局骷髅棒购买和墓地建造仍阻塞，下一步先离线排查，再补动作适配；阶段0/actor不批准。完整证据见本局visibility-guard-live-review.json及HANDOFF顶部。

最新修复：规则bot显式玩家Game.visible已绑定P1/P2独立native查询，缺绑定/错误为未知，默认本机玩家保留原路径；轨迹PointVisibility复用undead/player_visibility.py。1951项离线检查通过，修复后234922限时样本结果见上文；下方232830为修复前的历史反例。

2026-11-01：实现与离线隔离测试完成，首轮实机采集部分通过但发现阻塞项；不是已批准的训练集或学习actor。实现位于 `learning/trajectory.py`，接入 `run_match.py` 的P1观战陪练路径，默认关闭。

此前实测232830：232帧、106组点查询、91对请求回执，白名单结构与截断null奖励检查通过。显式P1查询得到112 true/100 false/0 unknown；10个实体样本掩码与native一致。两次独立对照确认旧SDK P1点查询在P1不可见而P0可见时返回true，因此规则示范公平性不通过。174.255→207.805秒有33.55秒采样空档，180秒目标超出27.805秒；未定位具体慢调用，连续性/开销不验收。84份冻结源码一致、停局清理完成，证据见 `artifacts/20261101-232830/trajectory-live-review.json`。

## 入口

仅离线检查，不启动游戏：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B bot.py sparring --opponent kfai-human --trajectory --check
```

后续获准实测时，去掉 `--check` 并加 `--minutes 3`。无自动学习或续局。`--strategy-trace` 可独立组合，其日志仍为 `opponent-strategy.jsonl`，不进入轨迹。

每局独立排他创建 `artifacts/<run>/trajectory.jsonl`。启用时冻结全部 `learning/*.py`；原始events、策略诊断和全图裁判数据不可直接拼接为actor输入。

## 数据记录

| 事件 | 内容 | 限制 |
|---|---|---|
| header | schema、固定P1/epoch、规则策略身份、限制 | `training_actor_approved=false`；地图/源码身份由同目录result和source-manifest关联 |
| observation | id及白名单观察 | 仅此事件的observation对象为未来actor观察候选，仍须实机审计 |
| point_visibility | 已登记地图的公开出生候选坐标、P1可见性与查询时钟 | 去除slot，不标注真实敌方出生；异步查询，不假装与某帧原子同步，当前不并入observation |
| action_request | id、观察id、时钟、资格判断和筛选后的动作 | 不是执行器；资格不足时载荷null，原规则命令仍原样提交 |
| action_receipt | 同一id、接口接受/拒绝/未知、有限状态码 | `effect=unverified`；缺回执/传输异常不是成功，异常原文不进入轨迹 |
| terminal | 终止/截断、最后观察id、受限原因和奖励 | 只有独立裁判确认的自然胜负为+1/-1；限时/手停/接口错误等截断，奖励null |

观察白名单包括：己方六项资源；己方及本帧P1可见实体的句柄、类型、归属、存活、位置、血蓝/上限和等级；仅己方已知的六格背包与技能编号/等级/CD；仅己方建筑生产类型、队列和进度。未知保留null。全玩家资源、地址、可见位掩码、first_seen、敌方命令/目标/技能/背包/生产及额外字段全部排除。地上物品和地形网格暂不纳入，避免把SDK视野半径近似当成严格可见证据。

非己方记忆只由合法可见帧更新，带last_seen_clock；隐藏死亡、消失和SDK记忆清除均不改变它。可见死亡可记录alive=false。按进程、P0观战身份、P1控制身份、epoch和单调游戏时钟/发布序号校验；跨局/倒退拒绝，暂停不重复生成决策帧。

## 点可见性与动作限制

固定SDK的Game.visible使用q_visible，上游文档称其为本机玩家视角，调用参数未指定玩家。232830两次实机对照现已确认本环境player=1仍读到P0点视野；该结论依据对照样本，不是仅靠SDK文本推测。SDK也明确禁止fair/player车道调用JASS。

新记录器使用独立本机dev客户端，仅调用Player(1)与IsVisibleToPlayer(x,y,P1)，前后核验进程/epoch；错误返回未知，不回退P0或视野半径。原始状态不序列化，只返回受限可见性结果，退出单独清理。模拟负例及232830实际点查询通过，10个实体visible_mask样本与native一致；不覆盖所有实体、隐身或死亡分支。

原规则bot的Game.visible路径现已修复，但新代码尚未实机验证，当前仍不能宣称公平专家示范。记录器检查动作源归属/存活、当前目标可见性、句柄与已记录观察；回执和后续可见状态分开保存，不自动把血量变化归因到某条动作。extra/mode及商店等非己方动作源暂不输出完整载荷；它是被动采集器，不是完整可重放动作编码，也未实现学习动作的冷却/资源/目标类型等执行前置校验。

## 阶段计时与截止

run_guard.py在显式限时本地练习/陪练或trajectory启用时生效，不扩展到普通不限时练习。runtime-timing.jsonl独立记录阶段begin/end、≥100ms慢调用和统计，不进入actor。世界读取及原生lane.run前后检查新鲜游戏时间、墙钟截止；原生等待≤0.25秒并按剩余预算缩短，显式限时诊断单阶段预算2墙钟秒。超限记game_time_limit/automation_deadline/stage_time_limit；查询错误处理不能吞掉中断控制流，动作回执可能未知，绝不补成功。退出先解除检查包装，再关闭轨迹与游戏。

这是协作式保护：不能强行终止不返回的C调用、无检查点的Python代码或系统挂起。原33.55秒空档的具体慢阶段需下一局计时定位，不能仅凭新增保护就认定卡顿已修复。

## 验证与下一步

新增20项检查；全量1936项通过（12.966秒），日志 `artifacts/trajectory-full-tests-20261101.log`。覆盖真实SDK数据结构、30组隐藏世界扰动后的观察一致性、隐藏死亡/消失、未知资源、暂停/旧帧/换局、P0/P1点可见性差异、过期/隐藏目标、拒绝/缺失/异常回执、奖励分类、CLI默认关闭及模拟runner冻结/记录/清理。首次集成夹具缺resources方法，修正后通过，失败日志 `trajectory-tests-expanded-20261101.log` 保留。CLI组合检查日志 `trajectory-cli-check-20261101.log` 确认未开游戏。

点查询与计时/截止保护已离线修复（新增15项、全量1951项通过，visibility-guard-full-tests-verified.log）。下一步有界实机验证；先依据runtime-timing定位采样空档，再补完整动作适配与实际效果记录/对齐。阶段0仍未验收，不开始模仿学习、PPO或批量对局。
