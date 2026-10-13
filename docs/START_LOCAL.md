# 本机启动流程（huangzhiduo）

项目通常位于 `C:\Users\huangzhiduo\Documents\Codex\openwar3-undead`，游戏默认为 `D:\War3_1.27a\Warcraft III Frozen Throne 1.27a publish`。使用 local 配置：KK 哈希文件名与本机包指纹已单独记录在 `data/machine_profiles.json`，不要修改公共 `data/kk_map_pool.json`。

首次准备依赖仍按 README“本地环境”执行。每次拉取或接续先读 AGENTS、PLAN、HANDOFF 最新记录和地图矩阵，核对 session、attachment、最新 result/events；历史开局、截止或提交授权不可重放。夜间 artifacts 没有随 Git 同步，不能把上游文档当作本机原始日志。

在项目目录执行：

```powershell
.\start-local.ps1 check
```

也可从其他目录调用该脚本的完整路径；脚本通过自身位置找到项目 .venv，不依赖终端当前目录。它检查八图指纹和 OpenWar3AI 运行时，把 local 标识、游戏目录和当前 Python 路径保存在已忽略的 vendor/openwar3.json；变更前备份到 artifacts。检查不启动游戏。有运行对局时不切换配置或重开；配置完全相同时允许只读检查。

只有本聊天明确授权实测且无现存对局后，才按最新矩阵选择地图和敌族。例如 NI 暗夜：

```powershell
.\start-local.ps1 play --map NI --enemy-race 4 --difficulty 4 --speed 400
```

正常对局不设游戏时限；Agent 必须按已授权墙钟预算附加 `--until`，不得借不限游戏时长超出评估预算。每局完成后核对自然终局、源码快照、实际发狂敌族、复盘及进程清理，再决定下一局。1/2/3/4 对应人族/兽族/不死族/暗夜。仅通过 OpenWar3AI，不使用 computer-use、改图、自启动或自动提交。

只有实际移动游戏安装目录时才传一次 `--game-dir`，之后同机流程复用已保存路径，无需修改仓库文件：

```powershell
.\start-local.ps1 --game-dir '新的真实游戏目录' check
```

通过标准：machine=local、八图路径指纹通过、bot check 依赖全 true；准备开局时 active_processes 与 active_project_pids 都为空。命令成功不代表实机行为或胜率通过。
