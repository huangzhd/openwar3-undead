# 更新日志

当前版本：**0.1.60-dev**；战术规则：**0.1.54**。日期均为北京时间。
本次发布汇总上次提交 `1222352` 之后的全部源码、测试与文档改动，包含10月11日晚及10月12日的工作。
开发阶段：P0完成，P1部分完成，P2–P4未开始。

## 2026-10-12

### 0.1.60-dev：独立接管控制台

- 新增中文桌面窗口：显示接管状态、最近游戏时间、当前意图、策略建议/实际战术、科技等级、蜘蛛数量、英雄等级和血量、最近操作。
- 提供“停止接管”和“继续接管”。停止对应暂停AI，交还手动操作，不关闭游戏、不取消已有订单；继续恢复AI。
- 按钮绑定当前会话并检查进程身份，收到机器人状态确认后才显示成功；换局、进程退出或PID复用时拒绝旧请求。
- 每秒增量读取日志；意图来自最近采样（旧运行器约15游戏秒），明确显示采样时间，不把指令接受当作行为完成。
- 增加当前用户的登录自启动和桌面快捷方式。**控制台在Windows登录时打开，不会在每次开游戏时重新弹出；手动关闭不停止后台AI。**
- 新增7项回归，完整533项测试通过；窗口已在本机运行并读取真实对局状态。按钮确认流程以模拟运行器验证，没有为测试而暂停正在进行的战斗。

主要文件：[bot_console.py](bot_console.py)、[console_state.py](console_state.py)、[install_console.ps1](install_console.ps1)、[tests/test_console.py](tests/test_console.py)。

### 0.1.59-dev：登录自启动与连续自动接管

- 新增当前Windows用户的登录计划任务，使用交互会话及正常管理员授权；安装时授权一次，不逐局弹出授权。
- 常驻助手连续监听配置路径下、由KK直接启动的新War3进程；对局就绪后自动加载并恢复AI，不需要聊天提醒。
- 取消常驻模式20分钟空闲退出与150秒对局就绪等待上限；当前旧助手持有连接时等待交接，不打断该局。
- 同一进程加载失败不循环重试，保留具体错误并继续等待新进程。
- 增加持久停用和重新启用入口；停用释放AI并保留游戏。当前保存的对手策略为人族，不自动识别敌方种族。
- 新增5项回归，完整526项通过；本机计划任务已安装并运行。重新登录触发、首个跨局自动接管仍待实测。

主要文件：[persistent_auto_load.py](persistent_auto_load.py)、[install_auto_takeover.py](install_auto_takeover.py)、[auto_load.py](auto_load.py)、[tests/test_persistent_auto_load.py](tests/test_persistent_auto_load.py)。

### 0.1.57–0.1.58-dev：KK运行时加载与本机接管

- 新增固定版本32位运行时加载器，检查游戏路径、PID创建时间、Game.dll及运行时哈希，通过定向窗口线程钩子和初始化握手建立接口。
- 记录加载阶段、原始Windows错误码、源码快照和目标身份；重复共享对象、未知版本和不完整接口不会盲目重复加载。
- 普通权限下初始化消息失败后，标准Windows管理员启动在同一局成功握手；新增管理员入口及精确绑定原目标的重试流程。
- 两次KK练习局已实际接管，游戏状态中观察到祭坛和通灵塔出现。首局随后由用户主动退出，不计崩溃或自然败局；第二局按用户确认的人族设置策略。
- 完整测试由518项增至521项。加载、接口读取和本机建造已获证据；跨客户端同步及完整KK对局稳定性尚未确认。

主要文件：[native/RuntimeAttach.cs](native/RuntimeAttach.cs)、[auto_load.py](auto_load.py)、[auto_load_entry.py](auto_load_entry.py)、[tests/test_auto_load.py](tests/test_auto_load.py)。

### 启动链路记录与0.1.56-dev诊断修复

- 新增只读KK启动记录器，采集目标游戏/父进程、启动参数和接口状态，避免把暂时AccessDenied误判为游戏退出。
- 桥接诊断区分映射不存在、权限拒绝、协议/配套接口不完整和进程变化，保留Windows原始错误码。
- “没有可用桥接”不再笼统解释为DLL未加载或平台拦截；模块枚举失败与共享内存不存在分别记录。
- 0.1.56完整505项通过；启动记录器修复后509项通过。首次错误和后续纠正均保留在验证文档中。

主要文件：[bridge_diagnostics.py](bridge_diagnostics.py)、[trace_kk_startup.py](trace_kk_startup.py)、[tests/test_bridge_diagnostics.py](tests/test_bridge_diagnostics.py)、[tests/test_startup_trace.py](tests/test_startup_trace.py)。

### 0.1.55-dev：已有游戏会话的接管接口

- 新增检查、连接、暂停、恢复、释放、状态命令及操作菜单。连接默认暂停，释放不结束用户游戏。
- 限定本机不死族、双出生点1v1地图和100%倍率，使用玩家视野接口；换局、槽位改变、时钟回退、失联或进程变化后释放。
- 单实例互斥和会话令牌避免多个控制器争用；暂停/恢复保留已见英雄历史。
- 不将单机默认Echo Isles地图数据当作实际KK地图，接管时禁用固定中立营地和小动物目录。
- 新增14项回归，完整496项通过。

主要文件：[attach_match.py](attach_match.py)、[bot.py](bot.py)、[attach-control.cmd](attach-control.cmd)、[tests/test_attach_0155.py](tests/test_attach_0155.py)。

### 0.1.54-dev：埋地目标停滞与进攻目标反复切换

- 复盘确认两种问题：围绕埋地蜘蛛长时间无进展，以及第三英雄暂时离队导致练级/进攻目标反复切换。
- 保守忽略埋地形态 `ucrm`，出土恢复 `ucry` 后重新纳入；未实现自动购买反隐道具，也不声称能识别所有隐身状态。
- 进攻/骚扰时，近处交战连续8游戏秒没有明显位移或可观察净掉血，则暂时绕过该批目标10秒并沿原路线普通移动；新威胁、伤害和目标形态变化会解除绕过。
- 第三英雄只在首次出征前要求靠近主力；已出发后的短暂分离由队形恢复处理，死亡/缺失仍影响进攻条件。
- 新增12项回归及真实坐标夹具，完整482项通过。此前胜局使用0.1.53，不能算本次防停滞修复的实战通过。

主要文件：[undead/combat_progress.py](undead/combat_progress.py)、[undead/targeting.py](undead/targeting.py)、[undead/controller.py](undead/controller.py)、[tests/test_stall_0154.py](tests/test_stall_0154.py)。

## 2026-10-11

### 0.1.53-dev：败局复盘、撤退与续航

- 基地被围时，撤退按可见敌方射程与可走路径选择更安全落点，避免统一回家命令覆盖拉扯、把英雄送回敌军包围中。
- 打中立单位使用伤害缠绕时保留一发治疗所需法力；二本优先屠宰场和首雕像进入队列，再升级三本。
- 新增12项回归与败局位置夹具，完整470项通过。
- 一局发狂不死族实测于31:10获胜，首雕像比前局早约42.6秒，观察到DK有效撤离；巫妖仍曾死亡后复活。一局胜利不代表稳定胜率提升。

主要文件：[undead/retreat.py](undead/retreat.py)、[undead/economy.py](undead/economy.py)、[undead/controller.py](undead/controller.py)、[tests/test_recovery_0153.py](tests/test_recovery_0153.py)。

### 0.1.52-dev：实机启动和清理

- 调试台首次输入/画布初始化共享45秒预算，之后恢复正常命令超时，避免冷启动字体预热引发过早失败。
- 修复启动器/游戏退出竞态，正确处理进程消失、AccessDenied和PID复用；未确认退出时保留记录。
- 新增9项回归，完整458项通过；随后完成实机启动、实际采集/建造/英雄出产验证。
- 本机恢复记录包含固定上游版本、运行时哈希、地图核验和依赖安装；游戏文件及上游运行时不随仓库发布。

主要文件：[session.py](session.py)、[undead/debug_console.py](undead/debug_console.py)、[tests/test_startup_0152.py](tests/test_startup_0152.py)。

## 当前限制与记录入口

- P1仍未完成；完整KK对局稳定性、跨客户端同步、防停滞修复专项实战、自启动跨局/重新登录及真实按钮操作闭环仍有待验证。
- 自动接管针对KK新启动的War3进程；同一进程返回菜单后换图不会自动抢回已释放的控制。
- 操作指南：[README.md](README.md)、[docs/ATTACH.md](docs/ATTACH.md)。
- 逐次开发与验证记录：[docs/STATUS.md](docs/STATUS.md)；任务清单：[PLAN.md](PLAN.md)；交接：[docs/HANDOFF.md](docs/HANDOFF.md)。
- 上述文档保留失败、纠正和未验证项。历史段落中的“仍运行”“未提交”等是当时状态，不代表最新状态。
- 仓库包含源码、测试和精选测试夹具；`artifacts/`原始日志、`vendor/`、`.venv/`、游戏文件、本机生成的配置/快捷方式/计划任务不上传。其他机器需要按README准备依赖并自行安装入口。
