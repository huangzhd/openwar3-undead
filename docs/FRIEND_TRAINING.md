# dayuan 自动战斗训练包

适用：Windows 10/11 64 位、魔兽争霸 III 冰封王座 **1.27a（Game.dll 版本 1.27.0.52240）**。
只写“1.27”不能确定兼容，1.27b 不支持。启动时会自动检查。

## 放在哪里

先把 ZIP 完整解压，得到 `dayuan-training` 文件夹。把整个文件夹放到魔兽游戏目录中，与 `War3.exe`、`Game.dll` 同一层：

```text
你的魔兽目录（任意盘、任意路径）
├─ War3.exe
├─ Game.dll
├─ war3.mpq
├─ War3x.mpq
├─ Maps
└─ dayuan-training
   ├─ 启动训练.cmd       ← 双击这个
   ├─ 使用说明.txt
   ├─ python
   ├─ vendor
   └─ 其他文件……
```

不要放到 Maps 里，不要只复制一个 CMD，不要在压缩包预览窗口里直接运行。
整个游戏文件夹搬到别处后，仍然按这个结构摆放即可，不需要填写路径。

## 怎么用

1. 先关闭已打开的魔兽游戏。
2. 双击 `dayuan-training/启动训练.cmd`。无需安装 Python、Git 或 Codex，也无需联网下载依赖。
3. 第一次会显示准备进度，从你自己的游戏文件中提取所需数据；成功后打开「dayuan 训练面板」。以后会复用这些数据。
4. 选择对战种族（人族/兽族/不死族/暗夜）、关卡（1–10）、难度（简单/困难）、倍速（0.25/0.5/1/2/4/8 倍）。我方固定为 dayuan 不死族。
5. 点击「开始所选关卡」，自动载入训练地图并由 dayuan 控制战斗。面板还可以调速、认输、重开、切关和切换人工/自动控制。

打开面板本身不会开局。关卡结束不会自动进入下一关；关闭面板也不等于退出游戏。请用面板认输或正常退出游戏。
游戏不要最小化；失焦或最小化时运行时可能暂停，需要回到游戏窗口。

## 启动失败

- **文件夹位置不对**：对照上面的结构，确认 `dayuan-training` 的上一层直接有 War3.exe 和 Game.dll。
- **版本不兼容**：需要完整的 1.27a / 1.27.0.52240。
- **运行组件缺失或损坏**：重新完整解压，不要混用其他版本的 DLL 或脚本。
- **权限不足**：游戏和训练包都要能写入文件；把整个游戏目录放在你可写的位置，例如 `D:/Games/War3`，保留上述结构。
- **已经打开**：使用已有面板，不要重复双击。游戏还在运行时先退出游戏。
- **旧包报 `splitlines` / `Encryption is not supported yet`**：这是旧 MPQ 提取器的兼容性问题，不能据此判断安装目录错误或缺少 SLK。使用 2026-11-02 MPQ 修复补丁，将其中的 `dayuan-training` 文件夹合并覆盖到游戏目录的同名文件夹，再双击原来的启动入口。需要同时更新 `training_launcher.py` 和 `portable_game_data.py`；包内原有 StormLib DLL 保持不变。首次重开会重新提取并生成数据，无需手工复制 SLK/TXT。
- **其他错误**：保留 `dayuan-training/artifacts/portable-launcher.log`、`portable-setup.log` 和最近的 `training-panel-start-*.log`，发给提供训练包的人排查。

训练包包含运行环境、dayuan 源码及训练地图，不包含魔兽游戏安装文件；游戏数据在首次启动时从你的安装目录生成。第三方说明见 THIRD_PARTY.txt。

修复版用包内固定哈希的 StormLib 按已知路径只读提取，不依赖 MPQ 内部文件清单。沿用 War3Patch → War3xLocal → War3x → war3 的优先级；只有内部文件确实不存在才查询下一包，损坏/读取失败不会静默降级为旧数据。原始游戏 MPQ 不修改；来源和数据哈希写在本机 `vendor/OpenWar3AI-ffd7dd25a3c2478f457b74bde89d23e605b24243/data/game/dayuan-data-sources.json`。
