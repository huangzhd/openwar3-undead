# 阶段2读取器与模型编码

2026-11-02实现，仍为诊断数据和接口适配。没有训练或加载模型，也未批准学习actor。入口为`learning.dataset`，模型编码为`learning.model_codec`。

## 读取与导出

```powershell
.venv/Scripts/python.exe -X utf8 -B -m learning.dataset audit artifacts/20261102-224602
.venv/Scripts/python.exe -X utf8 -B -m learning.dataset export artifacts/20261102-224602 --model-tensors --out artifacts/new-model-export
.venv/Scripts/python.exe -X utf8 -B -m learning.dataset verify artifacts/new-model-export
```

输出目录必须不存在，不覆盖历史文件。默认排除wait，`--include-wait`显式保留。所有输入先通过验证才创建输出目录。index记录原始输入哈希、排除计数、分组依据与输出哈希；`dataset_use=diagnostic_only`、`training_actor_approved=false`始终保留，不能因导出成功宣称训练集已获批准。

verify检查导出文件哈希、条数、来源分组、路径、样本身份及模型契约，不启动游戏或模型，也不将本地index一致性等同于原始证据真实性认证。文件损坏或不匹配返回非零退出码。

验证内容包括冻结源码与manifest摘要、依赖清单和局末清理审计、P1/PID/epoch及版本绑定、观察字段白名单与时序、请求/预检查/回执/后续观察配对，以及外部完整动作与SDK实际命令的参数一致性。源码核验针对本局冻结副本，不要求历史局等于当前工作区。依赖依据本局记录的摘要和局末审计；这些本地证据不是密码学签名或第三方真实性认证。

只读取契约、源码清单、源码审计、result、trajectory和primitive-actions，不读取events、全图裁判细节或primitive-diagnostics。result只提供终局与验证信息，不能进入当前模型输入。原生规则v1缺少完整extra/mode，明确拒绝其训练标签，不能用隐藏诊断补齐。

按源码、依赖、地图、接口版本、对手、公平性、速度与公开边界分目录，避免默默混用不同实验。失败局保留在index，导出0条；拒绝、未知回执、缺后续观察均记排除原因。截断奖励保持null。效果字段只描述后续可观察变化，`causally_attributed=false`；不能把回执接受或血量变化当作逐动作因果标签。

每条样本保留决策/后续观察编号及next_sample_contiguous，index另记是否保留全部请求、相邻样本连续性与实际终局转换是否保留。筛掉最后一条wait后，不把终局奖励向前搬到上一条动作，也不伪造其truncated标志。稀疏诊断记录不能直接当作连续RL轨迹。audit遇拒绝返回非零退出码，便于自动检查识别失败。

## 模型接口

`encode_observation`产出数值特征：己方资源、当前实体、己方能力/物品、生产队列、历史可见记忆和树木目击。未知值使用值与known掩码，区别于真实零值。位置按公开地图边界归一化，四字码编码为4个ASCII数值。模型输入不含PID、原始句柄、地址、订单、全图资源或未来结果。

`encode_action`将完整动作变成操作类别、当前实体/树木索引、产品类别与归一化坐标；`decode_decision`只按当前观察绑定恢复SDK动作参数，验证索引、坐标、schema及白名单。`prepare_command(frame,predict)`只调用调用方提供的模型一次并返回带原token的primitive命令，之后由`env.step`执行现有归属/时效/经济/视野检查。无战术回退，无自动重试，也不提供训练好的predict函数。

动作/产品词表按显式固定顺序编号，模型决定schema为dayuan-model-decision-v2，必须携带model_contract()返回的sha256。tensor导出index记录完整契约、字段顺序和缩放；不匹配的模型契约在解码前拒绝。早期v1诊断导出保留，不直接加载成v2模型输出。

`supported_operations`仅表示协议支持范围，不是完整合法动作掩码。树木是带seen_clock的历史目击而非实时存活保证；经济动作对受损建筑就绪仍保守。技能、英雄生产、升级研究、物品及完整战斗合法性仍待实现。实时引擎在推理期间继续运行，旧决策可能被拒；没有独立闲置客户端watchdog。

## 本轮证据

220637六动作、222548经济、224602伐木探针分别得到9、6、2条非wait诊断样本；224133树对象适配失败局保留，0条样本。四局各自分组，共17条，输出`artifacts/model-diagnostic-export-20261102/index.json`。这些短探针不代表有效模仿学习教师或战术覆盖，不以样本数量宣称模型性能。

最终v2模型契约导出为`artifacts/model-contract-v2-export-20261102`，verify与17条真实动作往返均通过。早期model-diagnostic-export目录仅为旧模型决定v1的历史诊断输出。
