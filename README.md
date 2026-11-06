# DayTrace — Windows 本地活动与内容采集

更新日期：2026-11-06。

DayTrace 当前通过命令行记录前台应用、窗口标题、活动时间和无输入空闲，支持显式开启 UI Automation 可见文字提取，以及单独授权后的本地 OCR。数据保存在本地 SQLite。

**尚未实现 AI 行为分析、任务归类、每日总结、饼图/时间线报告、浏览器扩展或产品 UI。** Chrome 标签名来自前台窗口标题，不代表已获取 URL 或完整网页正文；使用 VS Code 不能直接推断为完成了编程任务。

## 环境与安装

目标环境：Windows 交互式桌面、Python 3.12 x64、PowerShell。请在已打开的 PowerShell 或 VS Code 终端执行，不要双击脚本。已有 `.venv` 时无需重复创建。

```powershell
cd C:\Users\18441\Desktop\DayTrace
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

最新完整回归 **88 项通过**。默认测试使用合成数据，不读取真实桌面。simulate 为历史活动算法即时回放：active 1320 秒、idle 420 秒、paused 60 秒，未启用新 5 秒门槛，不能替代真实运行验收。

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
