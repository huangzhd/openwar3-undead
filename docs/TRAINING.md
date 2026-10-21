# UD决战操作训练图接入 · ud-training-0.1.0 WIP

2026-10-21：用户要求先上传当前代码。接入尚未完成，当前入口会因公平模式禁止JASS读取而报错；不把此版本作为可用训练版。

## 来源与独立副本

- 来源：[ufo19890607/Warcraft-III-](https://github.com/ufo19890607/Warcraft-III-/tree/71c0e1fdafc3cd523cbbd7feb7f3570d3de020c2)，固定提交`71c0e1fdafc3cd523cbbd7feb7f3570d3de020c2`。
- 文件：`converted-1.27/UD-decisive-V61-1.27.w3x`，SHA256 `bc10e7835f7a99e4c6e678bb9aae3193cb2149694ecec666af1df9d970897718`。
- 打包：[StormLib 9.40](https://github.com/ladislav-zezula/StormLib/releases/tag/v9.40)，压缩包和x64 DLL均固定SHA256，见`training_map.py`。原图和依赖下载到忽略的`vendor`，不提交第三方二进制。
- `training_map.py`从原图生成单关副本，只调整选族/选关、公开计分板状态和胜负后的停止流程。保留原图兵力、地形、对象数据、敌方AI及Player1Win/Player2Win判定条件；19个命名资源中除脚本外逐项回读一致。该静态核验不等于所有关卡实测。
- 副本位于`artifacts/training-maps`；启动时复制到当前配置游戏目录下`Maps/OpenWar3Training`。不覆盖用户原地图，也未修改公共八图目录。

## 已编写的入口

在项目根目录使用项目Python；尚未挂接`start-local.ps1`或普通`bot.py play`。

```powershell
.\start-local.ps1 check
.\.venv\Scripts\python.exe -B training.py check --matchup orc --level 2 --mode easy
.\.venv\Scripts\python.exe -B training.py stop
```

`check`只构建/核验地图，不启动游戏，首次可下载固定依赖；现有游戏会阻止重建。`stop`写入训练专用停止文件。普通对局STOP和矩阵保持独立。

以下为后续修复后的诊断命令，**当前不能完成接入验收，本轮上传后不执行**：

```powershell
.\.venv\Scripts\python.exe -B training.py play --matchup orc --level 2 --mode easy --speed 200 --seconds 55 --probe
```

参数已定义四族`human/orc/undead/nightelf`、1–10关、`easy/hard`和单局时限；只尝试了兽族第2关。未将参数可选写成40关可玩。`--probe`时限结束只表示探针结束，不能作为过关。

`TrainingController`草稿复用现有技能学习、集火、缠绕/Nova、后拉、雕像补给、毁灭驱散等组件，不调用普通造兵/练野/购物流程。尚未实际运行到控制循环；其他英雄、自定义单位、地图修改过的技能数值兼容性仍未审查完成。

## 实际验证和失败

| 证据 | 结果 |
| --- | --- |
| `artifacts/training-20261021-212550`、`212724` | 手写MPQ写入产生的副本报`war3map.j`数据损坏；Agent诊断停止，非自然胜负。该写入实现已删除。 |
| `artifacts/training-20261021-212938` | 改用StormLib后进入真实地图加载界面，用户截图及启动器`opening done`可佐证。最终因`JassError('公平模式（擂台规则）里不能用 JASS 通道')`失败。 |
| 三次探针结果 | 均`cleanup_confirmed=true`、`source_unchanged=true`，无训练自然胜负；最终session closed。 |
| `artifacts/pre-upload-20261021-training-tests.log` | 1358项现有测试通过，10.309秒；未编写新训练模块专项测试，不能以此证明接入正确。 |

具体阻塞在`TrainingSession.start`使用`fair=True`客户端调用`g.jass.Player/GetPlayerController`；后续`board_state`的JASS读取也有同类问题。SDK正常对战的生命周期核验另用审计客户端，训练入口尚未正确隔离。后续应限制审计数据只用于槽位和公开关卡状态，保持战术输入公平，不直接把训练策略改为`fair=False`。

加载画面出现“按下任意键以继续”；SDK有`press_to_continue()`，但当前训练生命周期尚未接入。一次事后独立调用因本轮已经关闭而失败，不能算自动继续成功。

## 完成标准与下一步

先补有界加载继续和公平策略/生命周期审计隔离，再以兽族第2关验证部队实际生成、己方API控制产生位移和伤害、技能耗蓝与实际效果、原图胜负信号及单关退出清理。之后再逐步核验其他关卡与自定义对象，并建立训练独立基线。

当前用户验收未完成；P0完成、P1部分完成、P2–P4未开始。普通`.174`三项离线修复的实机验收仍保留，训练探针不算普通矩阵胜负。没有恢复自动化或自动训练系列。
