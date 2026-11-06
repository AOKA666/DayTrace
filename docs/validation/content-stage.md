# 屏幕内容提取阶段

更新：2026-11-05。只交付本地内容采集，不含 AI、任务分类、浏览器扩展或产品 UI。

## 启动与查询

在已打开的 VS Code PowerShell 终端、项目根目录执行。旧的活动采集器先 Ctrl+C 停止；不能对同一数据库同时运行两个采集器。

```powershell
# 目标环境为 Python 3.12 x64；当前 .venv 已验证。
.\.venv\Scripts\python.exe -m pip install -r requirements-content.lock.txt
.\.venv\Scripts\python.exe daytrace.py content-doctor --ocr

# 建议首次使用独立测试数据库。开启正文，截图仍关闭。
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" start --content --exclude Bitwarden.exe --exclude-window "私人文档"
```

另开一个 PowerShell 终端：

```powershell
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" content
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" content --show-text
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" content --show-text --json
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" pause
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" resume
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" stop
```

`content` 默认仅显示时间、应用、来源、状态和字数；`--show-text` 明确输出正文，可能包含私人信息。`--json` 使用 ASCII 转义的标准 JSON 行，PowerShell `ConvertFrom-Json` 会还原中文，避免 UTF-8 管道解码错误。直接控制台显示异常时先运行：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
```

停止后可清空这个测试库（删除全部记录）：

```powershell
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" delete --yes
```

省略 `--db` 时使用原有 activity.sqlite3，启动时自动执行 v1→v2 迁移，保留旧活动记录。仅查询不会迁移；旧库尚未启动新版时，不能查询尚不存在的内容表。

## OCR 授权与限制

截图默认关闭。仅 `--content` 不会调用截图接口。OCR 还要求：明确开启、许可应用、物理像素区域、预期窗口尺寸，以及用户确认区域没有敏感内容。授权仅当前启动有效；不写入永久设置。

先执行下面命令，然后在 5 秒内切换到目标窗口；只显示应用名和尺寸，不截图、不读正文：

```powershell
.\.venv\Scripts\python.exe daytrace.py window-info --delay 5
```

假设结果是 `notepad.exe`，窗口宽 1000、高 700，且你已经核实窗口内相对左上角 `(30,100)`、宽 800、高 400 的区域没有敏感内容，才使用下面的**示例**；必须替换为实际值：

```powershell
.\.venv\Scripts\python.exe daytrace.py --db "$env:LOCALAPPDATA\DayTrace\content-test.sqlite3" start --content --screenshots --ocr-app notepad.exe --ocr-window-size 1000,700 --ocr-region 30,100,800,400 --acknowledge-safe-region
```

区域坐标相对整个窗口左上角，包括边框与标题栏，采用物理像素。最大 400 万像素。授权绑定第一次满足条件的该应用窗口；同应用另一窗口、窗口尺寸或位置变化会使授权失效，必须停止并重新明确授权。本实现保守地把移动和缩放的窗口几何事件都视为授权失效，防止缩放后又恢复原尺寸导致旧许可复用；事件队列溢出同样撤销许可。透明/分层窗口跳过截图。

自动回退只在 UIA 正常完成、有效文本少于 20 字且隐私扫描完整时执行；至少间隔 60 秒。UIA 超时、拒绝访问、工作进程失败、树截断、密码节点或区域安全性不明时，不自动截图。不能通过开启截图绕过权限或保护。

即使 UIA 返回无文本，也不能仅凭“未发现密码框”判断安全；区域明确授权是必要条件，另有前台身份、尺寸和遮挡检查。用户应选择合成测试文档，避免把整个浏览器或支付页面作为许可区域。没有浏览器扩展，无法可靠判断所有隐私模式、URL 或自绘密码区域。

截图仅在 OCR 子进程内存中处理；不保存文件或图像 BLOB，不发送网络请求。模型随固定 RapidOCR wheel 本地安装；模型缺失时失败，不自动下载。OCR 采用 CPU 两个计算线程、一个并行调度线程，检测边长上限 960；小字可能因此识别不佳。低质量结果保留状态，不补全文字。

## 结构与算法

- 新增 `content/`：policy（脱敏/相似度）、uia（COM 提取）、desktop（身份与区域校验）、ocr、worker、coordinator、diagnostics。
- `002_content.sql` 创建 `content_samples`：事件与会话外键、采集时间、来源、状态、文本、哈希、重复引用、字数、耗时、质量、策略代际、会话内窗口令牌、到期时间。应用、标题、设备、平台通过事件关联获取，避免重复保存。
- UIA 与 OCR 每次操作各使用独立可终止子进程，同时最多一个内容子进程。UIA 遍历预算 1.4 秒，父进程总超时 2.5 秒（含 Python/COM 启动）；OCR 总超时 30 秒。Windows Job Object 限制 UIA 384 MiB、OCR 1024 MiB 提交内存。这是硬上限，不是实际常驻占用目标。
- UIA 上限 300 节点、32 层、8000 字符。先检查密码和可见性，再读取 TextPattern.GetVisibleRanges；不读取 DocumentRange 或 ValuePattern。静态文本和超链接可回退到 Name。容器只有在子树已完整检查、没有隐藏/密码内容且没有子节点已覆盖正文时才允许读取。
- WinEvent 前台/标题事件触发采样；可用的子控件 Name/Value 变化只作为无正文的内容变化提示，2 秒内合并。未提供通知的应用用 15 秒采样兜底。窗口稳定 800 毫秒，触发采样全局最短间隔 2 秒；静态窗口 15 秒一次。只记录文本快照，不记录每次输入或按键。
- 去重在规范化和脱敏之后执行；同会话同窗口的相同正文或长文本相似度 ≥98%（长度差 ≤3%）仅保存 duplicate 和原证据引用。短文本必须完全一致。缓存最多 64 个窗口；暂停/非活动状态清空，避免旧授权内容复用。相似去重可能忽略很小的改动，不能把重复状态理解为页面完全未变。
- 暂停、停止、窗口/标题变化、空闲、锁屏和休眠取消旧工作；落库前再次核对窗口及代际、活动事件和会话状态。数据库仍由主采集循环串行写入，内容子进程不能写库。
- 证据、内容哈希和重复元数据整体保留 7 天；事件删除级联删除内容。prune 和启动/周期清理处理过期数据，查询主动过滤过期记录；全库删除仍要求停止并清理 WAL/SHM。

主要状态：`success`、`partial`（有用但截断）、`no_text`、`duplicate`、`excluded`、`timeout`、`unavailable`、`dependency_missing`、`worker_failed`、`ocr_failed`、`low_quality`、`unsafe_region`、`region_invalid`、`stale`。窗口变化导致的不可靠在途结果通常直接丢弃，不补写正文。

## 隐私默认值与边界

默认排除 1Password、Bitwarden、KeePass/KeePassXC、Dashlane、LastPass、Enpass 的常见进程名。窗口标题对隐身/InPrivate/private browsing、银行、支付、付款、支付宝等中英文词做保守排除；自定义 `--exclude-window` 为不区分大小写的子串匹配。

应用排除发生在标题读取前。标题排除必须先在内存读取标题判断，命中后不持久化标题、应用身份或正文，仅留下匿名 excluded 事件/区间和内容状态。UIA 正文出现敏感场景词时丢弃正文；此前可见的非敏感活动标题不会因这一正文判断而追溯删除。

这些是启发式规则，会误排普通资料，也会漏掉没有标识的私密页面。浏览器隐私模式不一定写在顶层标题中，不能承诺完整识别。敏感环境应整应用排除；不记录密码控件不代表能检测任意明文秘密。没有读取剪贴板、键盘、浏览器历史、离屏文档或后台标签页。

## 实际验证与待验收项目

环境：Windows 交互式桌面，Python 3.12.13 x64。固定依赖见 requirements-content.lock.txt。ONNX Runtime 1.31.1 初次 DLL 加载失败；最终验证组合使用 1.23.2，并通过虚拟环境内 msvc-runtime 和显式 DLL 搜索目录补齐运行库，没有提权安装。

- 70 项自动测试通过：旧库迁移、外键/保留、隐私节点、长度/节点限制、超时、去重、频率、暂停恢复、切换竞态、OCR 许可/尺寸/遮挡、安全失败、像素释放、默认零截图、离线网络拒绝、子进程终止、父进程崩溃后的 Job 自动终止及已有活动采集回归。
- `content-doctor --ocr`：限时、限内存子进程中合成中英文图片识别成功；禁用网络连接时仍能推理，截图数 0。最终一次测量总耗时 2047 ms，峰值工作集 145.0 MiB，进程 CPU 时间 1.906 秒（包括导入及初始化）。不是长期 CPU 百分比。模型使用安装包内文件并校验固定 SHA-256。
- `tests/fixtures/visible_window_probe.py`：真实 Windows RichEdit TextPattern 读取成功，密码框和隐藏文本未被输出；UIA 工作进程耗时 1172 ms、峰值工作集 34.6 MiB、CPU 时间 0.312 秒，截图 0。传统 Edit 控件不保证提供 TextPattern，正常降级 no_text。
- 同一探针 `--integration`：20 秒真实采集、SQLite 事件关联和内容成功写入，integrity_check=ok、外键错误 0、截图 0。测试期间前台发生变化；首次试验只有 no_text，重验有 success。临时数据库已删除，不在仓库保留真实活动数据。这不是稳定的目标应用兼容性评测。
- **尚未验证**：Chrome/VS Code/现代记事本逐项长时兼容性、真实截图与 OCR 完整流程、多显示器混合 DPI、真实锁屏/休眠、长时平均 CPU/总进程内存。自动化截图测试使用模拟像素；本轮没有为用户开启真实截图。

手工验收顺序：在 Chrome 普通标签、VS Code 合成文件、记事本合成文档分别停留至少 20 秒；查看 content 状态与正文是否对应当前窗口；切换/滚动/编辑后确认新内容与事件关联；静止时正文不重复存储。随后 pause，确认内容记录数不增长，再 resume；用自定义排除词测试匿名状态；停留超过空闲阈值后确认不再采集。最后仅在明确安全的测试区域授权 OCR，测试无文本回退、遮挡、移动和缩放后拒收行为。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests/fixtures/visible_window_probe.py
# 以下命令会短暂显示测试窗口并进行 20 秒真实采集，结束清除临时库：
.\.venv\Scripts\python.exe tests/fixtures/visible_window_probe.py --integration
```

技术来源：[Microsoft GetVisibleRanges](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationtextpattern)、[RapidOCR 官方配置](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml)。具体兼容性以本地固定依赖测试结果为准，不以最新网页示例代替验证。

## 持续 no_text 的修复与复测（2026-11-06）

旧实现的 8 层限制、空矩形容器剪枝、全局截断过滤会漏掉深层可见文本，已修复。原安全过滤和资源上限保持，深度改为 32；范围读取出错或子树检查不完整时，不能据此开启 OCR。新增 scan_limited 状态，避免将扫描不完整误报为完全没有文本。

先在旧采集窗口 Ctrl+C，使用**原来的 --db 与排除参数**重新启动。若一直使用默认数据库：

```powershell
.\.venv\Scripts\python.exe daytrace.py start --content
# 另一个终端，查看最新记录（旧 no_text 记录不自动改写）：
.\.venv\Scripts\python.exe daytrace.py content --show-text --limit 10
```

必要时运行下列诊断，并在 5 秒内切到目标窗口：

```powershell
.\.venv\Scripts\python.exe daytrace.py uia-structure --delay 5
# 显式允许临时读取可见文字，但只输出字数与状态，不写库、不截图：
.\.venv\Scripts\python.exe daytrace.py uia-structure --delay 5 --check-text
```

实机仅观察计数：VS Code 218 字符、Chrome 86 字符，均为 partial。Chrome 测试经用户明确配合；正文未输出或持久化。该结果不等于完整正文兼容性通过，微信尚未单独实测。新增自动测试覆盖深层节点、空矩形容器、完整兄弟分支保留、空矩形文本范围不读取、扫描上限状态和局部 COM/OS 错误。

修复后的完整回归：76 项 unittest 通过，耗时 29.552 秒，包含内容隐私测试、Windows 边界与原活动采集回归。未开启截图或云端发送。

## 精简显示（2026-11-06）

`content` 默认将同一活动事件内连续重复样本合并为一行，时间显示首末采样时间（不表示精确活动时长）。Chrome 同时显示已保存的窗口标题作为当前标签名；即使正文状态是 no_text 也可以显示标题。标题保留期仍为 7 天，不读取后台标签或 URL。切换事件、暂停或会话边界不会被合并。

```powershell
.\.venv\Scripts\python.exe daytrace.py content --limit 20
# 原始逐条样本：
.\.venv\Scripts\python.exe daytrace.py content --raw
```

无需重启正在运行的采集器，直接重新查询即可；--db 仍需和采集时一致。--show-text 会解析未过期的重复引用显示原正文，--json 始终输出未合并的结构化样本（含关联窗口标题）。

## 页面停留门槛（2026-11-06）

最新真实采集要求同一窗口/标题停留至少 5 秒：不足 5 秒不保存应用、标题或正文，只留下匿名 unknown 时间空档；达到 5 秒后保留从进入时开始的完整活动时段，再允许正文采集。切换、暂停、空闲等不会把未达标页面带入后续记录，短插入不计入前后应用时长。当前依靠标题变化判断标签切换，不能区分同名标签。

此项涉及运行中的采集逻辑，需在原监测窗口 Ctrl+C，再按原来的 --db、排除参数运行 start --content；仅重新查询不能让旧进程启用该规则。旧记录不自动删除。门槛针对活动页面，空闲/暂停/锁屏等状态继续记录；正文提取还受额外防抖、限频和窗口有效性检查影响。

## 同一页面全部采样合并（2026-11-06）

content 精简展示现在按活动事件 ID 合并同一次停留，不再仅合并相似正文。页面更新导致不同 partial 内容，或 partial/excluded 状态交替，也会合成一行；不同状态以 `excluded+partial` 等形式保留。显示的时间仍是首末采样范围，不是准确停留起止。--show-text 仅显示最近样本或其有效引用的正文；--raw/--json 可查看逐条原始样本。切到其他页面再回来即使标题相同也不合并。

这次仅修改查询展示，无需重启采集器。重新执行 `content --limit 20` 即可；不是删除历史记录，也没有放宽采集或敏感内容过滤。
