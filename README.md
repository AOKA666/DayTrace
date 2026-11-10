# DayTrace — Windows 活动记录与个性化识别

更新日期：2026-11-10。

## 最新界面操作（Qt）

- “今日”和“历史记录”已合并为“时间线”：默认今天，切换日期查看历史，点击“回到今天”恢复今天的自动刷新。

- 今日时间线每秒独立刷新已保存活动，不等待 AI；原有短暂停留门槛保留，未知活动仅一处待确认。
- 识别与学习可直接管理自动分类规则；AI 纠正记录只显示改错前后的分类，普通补分类不计为纠正。规则建议入口和 AI 复盘功能已移除。

- 点击右上角“开始记录”即可启动采集；绿色“● 正在记录”标识表示运行中，暂停后变为黄色“记录已暂停”。
- 左侧新增“我的”：集中管理分类、子分类、分类颜色和标签。分类从设置移到这里，支持一级分类和一级子分类（如“工作 / 编程”）。
- 新建分类、标签时点击可视化色块选择颜色，无需输入颜色代码；子分类继承父分类颜色，修改父色会同步子分类。标签颜色重启后保留。
- 待确认活动只需选择分类（必选）和标签（可选、多选，例如 `#AI编程出海`），不再填写名称和项目。确认窗口内可新建分类或标签，新建后自动选中并同步到“我的”。
- 活动卡片显示已选择的标签，也可用顶部搜索框搜索标签。设置和我的页隐藏日期栏。AI 复盘功能已移除。
- 首次打开会将个人数据结构迁移至 v7，保留已有活动和分类；新标签只在本地保存，不加入云端请求。旧 Tk 界面不提供本轮的新选择流程。

以下早期操作记录保留作兼容参考，当前 Qt 界面以本节和[验收说明](docs/validation/diary-ui.md)为准。

DayTrace 当前通过命令行记录前台应用、窗口标题、活动时间和无输入空闲，支持显式开启 UI Automation 可见文字提取，以及单独授权后的本地 OCR。数据保存在本地 SQLite。

默认桌面界面已改为 AI 时间日记：纵向活动卡片、历史搜索、待确认、个人档案和学习规则。云端默认关闭，明确开启后可后台批量识别新活动；截图留存为独立本地开关。**真实全天准确率、真实模型调用和新版视觉验收尚未完成，浏览器扩展未实现。** Chrome 标签名来自前台窗口标题，不代表取得完整正文；使用 VS Code 不等于完成编程任务。

运行新版（Qt 日记壳，需先 `pip install -r requirements-ui.txt`）：`.\.venv\Scripts\python.exe .\daytrace.py ui`。隔离示例：`.\.venv\Scripts\python.exe .\tools\preview_diary.py`。回退：`ui --tk-diary`（Tk 日记）或 `ui --legacy`（旧表格 UI）。实现边界、授权范围和本机截图验收见 [时间日记改版说明](docs/validation/diary-ui.md)。以下较早阶段记录中的旧 UI 和逐批授权说明，以该文档为准。

## 打开个性化识别界面

### 本轮界面与截图更新

**2026-11-08 最新操作：** 截图设置现已简化为窗口底部的“开启截图留存”单一开关，无需填写应用/区域/尺寸。勾选后，重新执行 `.\.venv\Scripts\python.exe daytrace.py start --content` 即使用该数据库的设置，自动对当前前台窗口按需截图；关闭开关后运行中的采集会撤销截图许可（等待当前短事务完成后生效）。默认关闭，本地保留最多 7 天、不上传，隐私排除/密码/不完整安全扫描/遮挡等保护继续适用。全窗口自动模式支持最多 1600 万像素；下文“截图留存设置”表单及手工命令描述仅适用于旧版或兼容 CLI，不再是 UI 操作要求。

- 时长单位为秒；已修正显示成 `?` 的编码错误。自动刷新采用行/单元格增量更新，不再清空重建整张表。
- 窗口下方可设置“最短停留（秒）”，支持 0–300，默认 5；保存后下次启动采集生效。CLI `--min-dwell-seconds 8` 可覆盖本次设置。低于阈值只留下匿名 `gap · 短暂停留`；未观测或不可读区间显示 `gap · 记录缺口`。不回写旧历史。空闲回溯把已记录活动缩短到阈值以下时，新的处理逻辑会匿名化该片段并清理关联证据。
- “截图留存设置”可填写许可应用、相对窗口的物理像素区域、窗口尺寸及最多 7 天的保留期限，并生成明确授权的启动命令。此按钮本身不启动采集或截图。需停止旧采集后执行命令。
- 截图仅对达到停留阈值、正文不足、且安全检查通过的当前活动按需进行，至少间隔 60 秒。隐私排除、空闲、锁屏、短暂 gap 不截图；UIA 扫描不完整/超时/密码/区域遮挡等情况仍跳过。不是见到“未知”就截图，也无法为过去的缺口补图。
- 单独 `--screenshots` 仍只用于 OCR，原图不落盘；额外 `--retain-screenshots` 才启用留存。保存于 `<数据库路径>.screenshots`，不会上传。OCR 检出敏感文本或低质量时不保存图片；这不能保证识别所有画面秘密，仍须明确许可安全区域。
- 在时间线展开分组，将鼠标停在具体片段约半秒，可预览未过期截图；缩略图只存在内存中。详情支持“仅删除该活动截图”，活动删除和私人化同步清理图片；到期在采集定期清理或应用操作时删除，停机期间不会有后台清理服务，过期图不会展示。

若只改停留阈值，不需要开启截图：

```powershell
.\.venv\Scripts\python.exe daytrace.py start --content --min-dwell-seconds 8
```

截图需要先取得实际窗口尺寸和选择安全区域；可用 `window-info --delay 5`，在等待期间切换至目标 Chrome 窗口（只输出应用与尺寸，不截图）。Chrome `no_text/partial` 的具体页面兼容性仍需实机确认，授权截图不能绕过安全检查。

本机已验证的 Python 为 3.12.13 x64（默认 `python` 是 3.11.9，不能直接替代）：

```powershell
cd C:\Users\27819\Desktop\DayTrace
.\.venv\Scripts\python.exe daytrace.py ui
# 不采集、不联网的合成评估：
.\.venv\Scripts\python.exe daytrace.py evaluate
```

使用已有自定义数据库时，在 `ui` 前加 `--db "完整数据库路径"`。首次打开会事务迁移 v2→v3，请先正常停止采集；迁移后的数据库可继续使用原采集命令。打开界面不会启动监测。

本机已创建 `.venv` 并安装 `comtypes==1.4.17`；监测与界面统一使用 `.venv\Scripts\python.exe`。独立的 `.local\bin\python3.12.exe` 不带此依赖，直接用它运行 `start --content` 会出现 `uia / dependency_missing`。本次仅安装 UIA 依赖，OCR 的可选依赖需另行安装。

先填写档案并确认保存，再到“候选任务 / 规则管理”添加任务；在时间线选择日期并“本地重新分析”。双击活动查看文本证据、填写实际任务、选择是否记住纠正。以后相似内容会参考已保存案例；批准组合规则后才自动标为已识别。修改规则或案例会使自动结果失效，点击重新分析更新；人工确认保留。

时间线每 5 秒自动刷新（编辑弹窗或任务运行时暂缓），保留未保存的档案内容、选中项和展开状态。没有任务名时显示未过期窗口标题，Chrome/Edge 去掉浏览器后缀作为页面标签；这不是 URL 或任务识别。相同标题与应用、或相同任务的记录可折叠汇总，展开后逐段查看和纠正；总时长为各段之和，不包含中间其他活动，不跨空闲/隐私/未知区间或会话分组。没有标题时不会仅按软件合并。自动刷新不触发云端请求。

`uia / no_text` 表示未取得可读正文，`partial` 表示只有部分正文，均不意味着窗口标题不存在。详情会单独显示正文状态；这些兼容性状态仍需按目标应用验证。`STOPPED | collection inactive` 表示采集已结束，单凭这行不能判断停止原因。

需要云端模型时，填写兼容 Chat Completions 的完整 HTTPS 地址、模型并设置密钥，停止采集后点击“预览并授权云端批次”。每批单独确认，不会自动补发历史数据。没有配置模型时仍能进行本地纠正与学习。详情、限制、回退及两天验收步骤见 [个性化阶段验证](docs/validation/personalization-stage.md)。

### 接入 DeepSeek

界面现已预填 `https://api.deepseek.com/chat/completions` 与 `deepseek-flash`，仍不自动联网。按 [DeepSeek 官方说明](https://api-docs.deepseek.com/zh-cn/) 在官方平台申请 API Key，然后在档案页点击“设置密钥”输入；不要把密钥写进代码或聊天。密钥保存到 Windows Credential Manager。

先建立候选任务，再选择时间线日期，停止采集后点击“预览并授权云端批次”，检查本次文字范围并确认发送。DeepSeek 官方域名使用 `max_tokens=2000`、非流式 JSON 输出和关闭思考模式的请求；其他自定义地址继续使用原兼容参数。17 项相关自动测试通过，尚未使用真实 DeepSeek Key 联调，不代表真实服务已连接成功。

## 环境与安装

目标环境：Windows 交互式桌面、Python 3.12 x64、PowerShell。请在已打开的 PowerShell 或 VS Code 终端执行，不要双击脚本。已有 `.venv` 时无需重复创建。

```powershell
cd C:\Users\27819\Desktop\DayTrace
# 首次安装：
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-content.lock.txt
.\.venv\Scripts\python.exe daytrace.py doctor
.\.venv\Scripts\python.exe daytrace.py content-doctor --ocr
```

若 py -3.12 不可用，用 py -0p 查找 Python 3.12，再通过其完整路径创建虚拟环境。当前验证环境为 Python 3.12.13 x64。纯活动采集使用标准库；UIA 使用 comtypes；OCR 使用 RapidOCR、ONNX Runtime CPU 和 mss 等可选依赖。content-doctor --ocr 只识别内存中的合成图片，不截取用户桌面。

## 启动与控制

以下启动方式选一种，同一数据库不能同时运行两个采集器：

```powershell
# 只记录应用、标题和时长：
.\.venv\Scripts\python.exe daytrace.py start
# 同时开启可见正文采集，截图仍关闭：
.\.venv\Scripts\python.exe daytrace.py start --content
```

采集占用当前终端并显示状态，按 **Ctrl+C** 正常停止。没有自动开机启动或隐藏后台服务。在第二个终端控制：

```powershell
.\.venv\Scripts\python.exe daytrace.py status
.\.venv\Scripts\python.exe daytrace.py pause
.\.venv\Scripts\python.exe daytrace.py resume
.\.venv\Scripts\python.exe daytrace.py stop
```

控制命令等待确认；若超时，请查询 status，不能假定已生效。暂停不读取新的标题和正文。异常退出后只恢复至最后持久化检查点，之后空档记 unknown。start --duration 1800 可在 30 分钟后自动停止。

## 5 秒页面停留门槛

- 同一应用/窗口/标题连续停留 **不足 5 秒**：不保存该页面的应用身份、标题或正文，仅保留匿名 unknown 时间空档。
- 达到 **5 秒**：从首次进入该页面时开始计时，前 5 秒计入时长，之后才允许正文采集。
- 切换窗口或标题后重新计时。短暂插入不计入前后应用；空闲、暂停、锁屏、排除状态继续记录。
- 正文还受 800 毫秒防抖、触发采样最短 2 秒、静态窗口 15 秒兜底及提取耗时限制，不保证第 5 秒就产生正文。
- 默认 300 秒没有输入进入 idle；这不等于离开或不专注。--idle-seconds 可调整空闲阈值。

更改采集代码后需停止旧进程再重新启动；旧历史不追溯删除。当前依靠窗口身份与标题判断页面变化，不能可靠区分同名标签或不改变标题的页面切换。

## 精简查看与 Chrome 标签名

```powershell
.\.venv\Scripts\python.exe daytrace.py content --limit 20
# 明确查看正文，可能包含私人内容：
.\.venv\Scripts\python.exe daytrace.py content --show-text --limit 20
# 原始逐条样本：
.\.venv\Scripts\python.exe daytrace.py content --raw
# 未合并的 JSON Lines；正文需另加 --show-text：
.\.venv\Scripts\python.exe daytrace.py content --json
```

默认按**同一次页面停留**合并连续采样，正文、来源或状态变化也合为一行。Chrome 直接显示记录中的窗口标题，去掉末尾 Google Chrome 后缀；VS Code 不再因同一次停留内的内容采样重复刷行。切走再回来仍分段，即使标题相同。

合并行时间为**首末采样时间**，不是准确的活动起止或时长。不同状态合并显示，例如 excluded+partial。--show-text 只展示最近样本或其有效重复引用，不因最新样本被排除而回显更早正文。展示调整无需重启采集器，重新查询即可。

| 状态 | 含义 |
|---|---|
| success | 取得可访问文本，不保证涵盖全部页面 |
| partial | 部分内容，可能达到限制或有局部读取失败 |
| duplicate | 相同或高度相似正文，引用已有证据；原始模式可见 |
| no_text | 正常扫描后未取得文字 |
| scan_limited | 达到扫描上限，仍未取得文字 |
| excluded | 隐私规则拒绝本次内容采集 |
| timeout / unavailable | 超时或接口不可用 |
| dependency_missing / worker_failed | 缺少依赖或工作进程失败 |
| ocr_failed / low_quality | OCR 失败或质量较低 |
| unsafe_region / region_invalid / stale | 区域不安全、许可失效或窗口已变化 |

content 只显示内容采样；未启用 --content 的活动请用 records 查看。

## 活动时间与数据库

```powershell
.\.venv\Scripts\python.exe daytrace.py records --table intervals --limit 30
.\.venv\Scripts\python.exe daytrace.py records --table events --limit 30 --show-titles
.\.venv\Scripts\python.exe daytrace.py records --table summary
```

records 输出 JSON Lines，时间为 UTC 毫秒，duration_ms 为毫秒；summary 的 seconds 为秒，按状态汇总历史记录。默认不显示标题，需 --show-titles。运行中的区间只累计至最近检查点；空闲检测可能回溯修订 active 区间。

默认数据库：`%LOCALAPPDATA%\DayTrace\activity.sqlite3`。每次启动创建新会话，但保留旧历史。自定义 --db 必须放在子命令前，启动、控制和查询使用同一路径：

```powershell
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" start --content --exclude Weixin.exe --exclude-window "私人文档"
# 另一个终端：
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" content --limit 20
```

--exclude 接受进程名或完整可执行路径，可重复使用，不是通配符。--exclude-window 对标题做不区分大小写的子串匹配。默认排除常见密码管理器及可辨认的银行支付、隐私浏览场景；规则有误报和漏报，不能保证识别所有敏感页面。

先停止采集，再删除默认数据库的**全部历史记录**：

```powershell
.\.venv\Scripts\python.exe daytrace.py delete --yes
```

自定义库需加相同 --db。删除包含数据库及 WAL/SHM，下次 start 创建空库，不能通过软件恢复。不承诺 SSD 物理擦除。prune 清理过期数据，也要求停止采集。当前不支持按时间范围删除。

## UIA 诊断与可选 OCR

```powershell
.\.venv\Scripts\python.exe daytrace.py content-doctor
# 执行后 5 秒内切到目标窗口，默认只检查结构计数：
.\.venv\Scripts\python.exe daytrace.py uia-structure --delay 5
# 临时读取可见文字，只输出状态和字数，不保存正文：
.\.venv\Scripts\python.exe daytrace.py uia-structure --delay 5 --check-text
```

截图默认关闭，--content 不会开启截图。OCR 需要同时指定 --screenshots、--ocr-app、--ocr-region、--ocr-window-size 和 --acknowledge-safe-region。先核实应用和安全区域，不要直接套用未知尺寸。完整授权示例见 [内容阶段说明](docs/validation/content-stage.md)。

OCR 最短间隔 60 秒，只在 UIA 正常完成、正文不足且安全检查通过时回退。UIA 超时、权限拒绝或扫描不完整不会自动截图。窗口移动/缩放使已绑定的区域许可失效。原图仅在内存处理，不保存、不上传；模型缺失或校验失败时不自动联网下载。

## 中文显示

旧 PowerShell 出现中文乱码时，先在当前终端执行：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
```

content --json 使用 ASCII 转义，ConvertFrom-Json 会还原中文。不需要为编码显示问题删除数据。

## 测试与实际验证状态

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$sim = Join-Path $env:TEMP ('daytrace-sim-' + [guid]::NewGuid().ToString() + '.sqlite3')
.\.venv\Scripts\python.exe daytrace.py --db $sim simulate
.\.venv\Scripts\python.exe daytrace.py --db $sim records --table summary
```

截至 2026-11-10 完整回归 **193 项通过**（新增目录和选择式确认等测试）。默认测试使用合成数据，不读取真实桌面。simulate 为历史活动算法即时回放：active 1320 秒、idle 420 秒、paused 60 秒，未启用新 5 秒门槛，不能替代真实运行验收。

- 原活动采集版本完成过 30 分钟实机验收，不等于当前全部功能已完成长时验收。
- 真实 RichEdit 测试窗口读取成功，密码框和隐藏内容未输出；离线中英文 OCR 合成图片验证通过。
- VS Code 和 Chrome 的短时探针已取得非零 partial 文本，**尚不证明正文完整**；微信未单独验证。
- 真实截图 OCR、多屏混合 DPI、完整锁屏/休眠矩阵、最新 5 秒规则的实机效果及 8 小时资源指标尚待验证。
- 单次诊断峰值工作集约 UIA 35 MiB、OCR 145 MiB，不是长期平均占用保证。

详细结果与手工验收：[原活动阶段](docs/validation/activity-stage.md)、[内容阶段](docs/validation/content-stage.md)。

## 隐私与存储约束

- 不监听或记录按键，不读剪贴板、密码控件、浏览器历史或后台标签页，不提权绕过保护。
- UIA 限前台可见内容，最多 300 节点、32 层、8000 字符；独立进程限时运行。暂停、切换等使旧结果失效，父进程崩溃时终止内容子进程。
- 应用排除先于标题读取；标题排除需在内存检查，命中后不保存应用身份、标题或正文。脱敏和敏感词过滤不能保证发现任意秘密。
- SQLite 使用外键、WAL、串行业务写入与版本迁移；单调时钟测时长，系统校时另记事件。标题和正文保留 7 天，活动事件和区间保留 90 天。数据库本身未加密。
- 诊断日志不含正文；--show-text、--show-titles 是用户明确查看数据。
- .gitignore 排除数据库、日志、截图目录、模型、凭据和环境缓存；不得提交真实活动数据或密钥。

需求与后续计划见 [PRD.md](PRD.md)、[PLAN.md](PLAN.md)；开发约定见 [AGENTS.md](AGENTS.md)。

## 简洁时间线（2026-11-08）

桌面首页用六行、每行四小时的色块展示全天，底部按分类汇总时长；点击片段查看详情和纠正，悬停沿用已有截图预览。主时间线不再显示类别、项目、状态等表格列，也不显示顶部“操作完成”横幅。自动刷新只更新变化的色块。

点击“添加分类”填写名称并选择颜色，再点击“AI 分类”预览脱敏批次并授权发送。AI 只选择已添加的分类，人工确认结果保留；密钥在“个人设置”中配置。云端默认关闭，当前仍需停止采集后执行分类，不上传截图。分类名称与颜色会随个人记忆导出、删除。
