# 上游机器启动流程（38993）

项目历史位置为 `D:\codex\war3 AI\openwar3-undead`，游戏默认位置为 `C:\Users\38993\Downloads\War3_1.27a\Warcraft III Frozen Throne 1.27a publish`。使用 upstream 配置：八图使用公共目录内的标准文件名和上游包指纹；本机 KK 哈希包单独记录，不覆盖公共目录。

首次准备依赖仍按 README“本地环境”执行。每次接续先读 AGENTS、PLAN、HANDOFF 最新状态和矩阵，核对 session、attachment、最新 result/events。本机与上游 artifacts 分别留在各自机器；不能重放旧授权、旧截止或重复启动已有对局。拉取本次 0.1.108 交付后，先运行下述检查；本机验证不能代替上游机器实际验证。

在上游项目目录执行：

```powershell
.\start-upstream.ps1 check
```

脚本通过自身位置使用该项目的 .venv，即使项目文件夹移动也不需要修改 Python 绝对路径。检查八图和运行时后，仅把 upstream 标识、当前游戏路径和 Python 路径写入已忽略的 vendor/openwar3.json，并在变更前备份到 artifacts。检查不启动游戏；已有对局时禁止切换配置或另开局。

获得当次实测授权、确认无现存对局后，再按最新矩阵执行，例如：

```powershell
.\start-upstream.ps1 play --map NI --enemy-race 4 --difficulty 4 --speed 400
```

这是入口示例，不是新的开局授权。正常对局不限游戏时间，Agent 仍须按剩余授权墙钟预算传入 `--until`。每局独立核验终局、实际难度、源码快照和清理，保存失败日志，并同步 PLAN、STATUS、HANDOFF 与矩阵。只用 OpenWar3AI，不改原图、不装自启动、不用 computer-use、不自动提交。

若游戏实际安装位置与历史位置不同，首次传一次正确路径，之后复用本机 vendor 配置：

```powershell
.\start-upstream.ps1 --game-dir '上游真实游戏目录' check
```

通过标准：machine=upstream、八图严格指纹匹配、bot check 依赖全 true；开局前两个活动进程列表为空。2026-10-13 已在 38993 上游机器实际执行 check：八图指纹、全部依赖及无活动进程检查通过；0.1.108 完整857项离线测试通过（artifacts/01108-upstream-handoff-tests.log）。尚未在本机启动0.1.108自然对局，不能把入口/离线验证写成胜局复现。
