# 已运行游戏的接管试验 · 0.1.60

## 接管控制台

本机已安装独立控制窗口，Windows登录后自动打开，也可从桌面“OpenWar3AI Console”重新打开。
窗口显示接管状态、当前意图、战术、英雄/蜘蛛/科技和操作日志；点击“停止接管”交还手动操作，
“继续接管”恢复AI。按钮收到机器人状态确认后才显示成功。停止仅暂停当前局，后续新局仍按自动接管设置执行；
关闭控制台不停止AI，也不会因下一次开游戏而重新弹出。全局停用仍用auto-takeover-stop.cmd。
面板每秒刷新，意图/战术来自最近日志，并显示采样时间；旧运行器的意图采样约15游戏秒，不伪称逐帧实时。
控制台只使用现有session命令文件，无鼠标键盘自动操作。重装控制台快捷方式可运行install_console.ps1，无需管理员权限。

## 已安装：Windows登录后自动接管KK练习局

本机已按用户授权注册任务 `OpenWar3AI-KK-AutoTakeover-38993`，使用当前用户的交互会话和最高可用权限。
首次安装通过Windows正常管理员授权；以后登录会启动后台助手，从KK启动新游戏进程后自动加载，
满足不死族、双出生点1v1、100%倍率等条件就自动恢复AI，无需聊天提醒、手动启动助手或逐局授权。
常驻没有20分钟空闲超时；若当前旧助手正在控制一局，会等待其退出并继续处理后续新进程。
电脑练习是用户授权范围；工具目前不从平台房间判断是否真人对手，因此使用者仍应仅在约定的练习房间使用。
对手策略保存于 `artifacts/auto-takeover-config.json`，当前enemy_race=1（人族），不是自动识别种族。

- 停用：双击 `auto-takeover-stop.cmd`，释放AI并持久停用，游戏保持打开。任务保留注册，但下次登录入口读到disabled会退出。
- 重新启用/安装：`auto-takeover-enable.cmd`，使用标准Windows授权流程。
- 查看：`artifacts/auto-takeover-service.json`记录常驻状态，`bot.py auto-load-status`记录当前实际加载助手状态，`bot.py attach-status`记录接管状态。
- 暂停/释放当前局仍用 `attach-pause` / `attach-release`；不会在同一进程中强行重新抢回控制。随后KK新启动的游戏仍自动接管，除非已全局停用。
- 同一游戏进程返回菜单后再换图，当前不会自动重连；支持的是KK启动新的War3.exe。重启电脑后需正常登录当前Windows账户。

安装结果与当前旧局未被打断已核验；下一局自动加载及重新登录触发还需实机验证。
两次手动触发连接后已观察到AI实际开始建造祭坛和通灵塔，完整对局/联机同步尚未验证。

## 历史单次入口与底层参数

0.1.58 实机进展：KK进程9976在普通权限下初始化消息发送失败；正常Windows管理员授权后，
同一游戏完成handshake_ready、SDK ready=true并连接到本机0号槽位，AI保持暂停。
世界发布计数两秒内736→768；采样时游戏时钟均217.45，不能算游戏模拟持续推进或策略指令已执行。
该时点仅验证加载/初始化/读取；后续已观察到本机建造行为，联机同步仍待。

以后双击 `auto-load-practice.cmd` 会通过 `auto_load_entry.py` 请求正常Windows管理员授权，
授权后在后台等待下一次KK开局；取消授权则不启动，不关闭UAC或绕过系统权限。
底层 `bot.py auto-load` 不自动提权，适合已经具有合适权限的终端。

## 新增：游戏启动时自动加载运行时（实验性）

0.1.57 增加独立32位加载器和启动监听，补上此前只会连接既有接口的缺口。
这不是上游提供的正式KK支持：依据固定发布启动器的初始化调用实现，后续已在本机完成KK实机握手、连接和实际建造观察，完整对局稳定性仍待。
现阶段仅用于用户指定的KK对电脑练习局，不根据假设宣称平台已兼容。

先运行 `auto-load-practice.cmd`，再从KK正常启动魔兽；也可在项目目录运行：

```powershell
.venv\Scripts\python.exe -u -B auto_load_entry.py
```

默认只处理下一次新启动的游戏，等待最多20分钟。仅接受实际观察到的
`C:\Program Files (x86)\kkduizhan\Platform.exe` 直接启动的、配置目录下的 `War3.exe`，
现有进程会跳过。加载完成还必须通过不死族、1v1地图、100%倍率和对局就绪检查；连接后先暂停。
对手种族默认3（不死族），其他种族用 `--enemy-race 1/2/4`。

首次加载验证通过后，可选择持续监听及自动接管：

```powershell
.venv\Scripts\python.exe -u -B auto_load_entry.py --watch-restarts --auto-resume
```

上述旧命令仅在其进程运行期间处理后续新游戏；登录常驻模式使用前述已安装任务。
每次空闲最多等待20分钟，已有运行对局不会因空闲上限中断。

```powershell
.venv\Scripts\python.exe -B bot.py auto-load-status
.venv\Scripts\python.exe -B bot.py attach-pause
.venv\Scripts\python.exe -B bot.py attach-resume
.venv\Scripts\python.exe -B bot.py auto-load-stop
```

停止助手会请求它自己的机器人释放控制并退出加载助手，保留游戏进程；运行时可能已经固定驻留在游戏内，
停止助手不等于卸载DLL，完整退出游戏后才清除。失败不对同一PID重复安装；保留具体阶段错误。

加载器不替换游戏文件或KK文件，不调用远程内存补丁、权限绕过、模拟鼠标键盘或关闭游戏；权限通过用户确认的Windows UAC流程取得。
使用固定SHA256的render_hook.dll、WH_GETMESSAGE线程钩子、独立控制共享内存及InstallNative握手；
DLL装入、握手信号、SDK接口就绪、实际部队执行是不同验收阶段。
Windows钩子的32位匹配要求见[微软接口说明](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowshookexw)。
本机已完成编译、32位自检、错误进程预检和521项回归，以及一次KK真实加载/暂停连接；命令同步仍未验证。
每次日志保存在 `artifacts/auto-load-日期-时间-PID/`，包括目标身份、源码快照、loader.log、bot.log和接口检测结果。

## 手动连接已有接口

下述attach命令负责连接已有OpenWar3AI桥接；KK加载另由前述实验加载器完成，不能据此宣称通用平台兼容。
普通 KK 启动的魔兽并不会因此自动获得接口。固定上游的 `tools/play.py --attach`
同样要求游戏已经由其运行时建立了桥接；本项目的实验加载器不是上游正式支持的KK加载API。
若检测提示没有桥接，attach到此停止；需先完成加载器初始化，不能通过换PID或反复连接解决。
以下attach命令本身不加载DLL；新增auto-load才会尝试上面说明的加载流程。不实现保护绕过或游戏/平台文件替换。

## 怎么试

先确认游戏已通过受支持方式加载并初始化 OpenWar3AI 运行时；不要为了检测反复在 KK 开局。
本机或局域网测试使用 1v1 对电脑的普通近战地图，己方选不死族，正常100%倍率。
只支持与本机已验证的1.27a Game.dll一致的版本、两个出生点地图；RPG、多队伍和观战不适用。
平台是否允许此接口及多人命令同步仍未验证，接口连接成功不等于平台兼容通过。

在项目目录 `D:\codex\war3 AI\openwar3-undead` 打开 PowerShell：

```powershell
.venv\Scripts\python.exe -B bot.py attach-check
```

输出 `[]`：没有找到已识别名称的运行中魔兽进程。
输出 `ready: false`：按 `reason` 查看是版本、对局状态、地图还是桥接问题；不会开始操作。
0.1.56 在 SDK 初始化失败时额外输出 `bridge_state`、`next_step` 和原始 Windows 错误码：

| bridge_state | 含义与处理 |
|---|---|
| mapping_absent | 当前 Windows 会话找不到世界接口（错误2）；需解决运行时加载/初始化，不能直接断言 DLL 未加载或平台拦截。 |
| access_denied | 接口访问被拒绝（错误5），包括可读但 SDK 所需权限不足；核对用户、会话和权限，不重复加载 DLL。 |
| runtime_incomplete_or_incompatible | 世界接口存在，SDK 仍初始化失败；检查配套接口、协议和映射大小，保留 detail。 |
| mapping_open_error / mapping_changed_or_error | 其他 Windows 错误或检测途中接口变化；按原始错误排查。 |
| process_changed | 原进程已退出或身份变化，不能继续沿用旧 PID。 |

诊断仅打开并关闭既有共享内存句柄，不创建接口、读取其数据或写入游戏。

只有 `ready: true` 才尝试连接，下面把12345换成检测返回的游戏PID：

```powershell
.venv\Scripts\python.exe -u -B bot.py attach --pid 12345 --enemy-race 3
```

对手种族：1人族、2兽族、3不死族、4暗夜。需要与实际对手一致，目前不读取敌方私有元数据来推定种族。
连接后**初始暂停**，原终端保留运行。在另一个终端执行：

```powershell
.venv\Scripts\python.exe -B bot.py attach-resume
.venv\Scripts\python.exe -B bot.py attach-pause
.venv\Scripts\python.exe -B bot.py attach-release
```

上面三条分别是开始/恢复、暂停机器人、释放连接，按需要逐条运行。
也可双击根目录的 `attach-control.cmd`，使用扫描、恢复、暂停、释放和状态菜单。
`attach-status` 查看状态。控制命令返回的是请求，状态以运行器日志/`attach-status`确认。
退出菜单本身不会停止机器人；连接终端按 Ctrl+C 也会释放连接。

## 交还操作与边界

- 暂停只停止发送新命令并释放机器人单位租约；已有移动、采集和训练订单继续执行，你可手动覆盖。
- 恢复时重建短期微操状态，保留已观察过的英雄种类，避免旧撤退/购物指令接着抢控。
- 不调用加速、重开、认输、结束游戏、注册表偏好修改、进程终止或单机的全图胜负裁判。
- 游戏进程退出/PID复用、换局、己方槽位变化、时间重置、倍率变化或快照断开会结束接管，不自动连接下一局。
- SDK的本机槽位用于创建受玩家槽位限制的命令通道，策略使用 `fair=True` 视野。
- 不把上游默认地图当成实际房间地图。固定 Echo Isles 野怪/小动物目录禁用，只按实际可见目标探索；因此开局路线可能弱于本机固定图版本。
- 本地 `bot.py stop` 仍只停止本地单机运行器；接管应使用 `attach-release`。

日志和源码快照在 `artifacts/attach-日期-时间-标识/`。
结束结果为接管释放/错误，不凭有限视野伪造胜负。
0.1.56时完整505项测试通过，其中包含真实 Windows 临时共享内存的句柄释放检查；它不是游戏接管验证。
历史首次KK测试在SDK初始化处失败；后续已补充初始化和本机实际建造证据，同步/整局稳定性仍待。

## 上游加载接口与本地原型的区别

固定上游 prebuilt/README_ZH.md 明确启动器和运行时源码未开放。发布版启动器只有启动新游戏的参数，
没有已有 PID 的入口；二进制中可见窗口钩子、InstallNative 消息和握手事件，说明单独调用 LoadLibrary
不能作为初始化成功的证明。0.1.57进一步静态核对了这段调用的共享对象大小、名称、钩子类型和消息参数，
据此新增本地实验加载器；它不是正式开放的稳定初始化API，升级上游二进制必须重新核对。
下一步验证真实初始化和命令同步；加载器支持范围严格固定，错误日志保留，不以假设代替实机。
上游 README 还明确限制在本机、局域网或自建环境使用，不用于有反作弊的服务器；现有入口不代表 KK 获得支持。
