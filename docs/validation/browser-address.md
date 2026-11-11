# 浏览器网址和同域名停留验收

## 短暂返回补充验收（2026-11-11）

用户最终定义为逐段过滤：设置 5 秒后点击“保存采集与日记显示”，确认显示“已保存”，重新启动采集。在同一窗口的不同域名 A/B 测试 A 3 秒→B 1 秒→A 2 秒，应全部过滤；A 10 秒→B 2 秒→A 10 秒，应保留两段 A，显示合计约 20 秒，不包含 B。B 停留达到 5 秒则保留 B，两个 A 不跨它合并。暂停、空闲、无痕/排除界面或无法读取的窗口仍是硬边界。UIA 地址栏采样有延迟，可重复测试并用 interval_id 和原始起止时间核对；不能据此保证每个瞬时页面都被读取。相同域名连续切标签仍沿用先前的不切片规则。

底层仍有两段 A，合并只影响显示，不帮助短片段通过阈值，不把 B 归入 A 的任务，也不生成旧记录中没有的页面证据。旧的累计准入实现已停用。

2026-11-11：代码与自动化测试完成；真实 Chrome / Edge 地址栏兼容性及资源占用尚未验收。未为测试读取用户当前网页。自动化全部使用合成窗口/地址和临时 SQLite；全量 206 项通过。

## 日常使用

停止旧采集进程并重启 DayTrace，再在 UI 点击开始记录。新采集器会尝试读取前台浏览器地址栏；不需要开启截图。时间线显示“浏览 · trends.google.com”，已有人工/AI 名称仍保留，卡片附带域名。点击详情查看实际采集到的页面标题、时间和脱敏网址。读取失败时仍记录标题，不虚构网址。

同一前台浏览器窗口内，每 2 秒切换一次同域名页面，累计超过 5 秒后，应有一段连续浏览记录。换到其他域名、应用、窗口，或暂停/空闲后重新计时。不同子域名算不同主机；不会把 google.com 和 trends.google.com 归成同一站点。只表示持续浏览，不推断完成了什么任务。

## 独立 PowerShell 验收

在项目目录运行，使用单独测试库（不要同时启动同一测试库的另一个采集进程）：

```powershell
.\.venv\Scripts\python.exe daytrace.py --db .\local-validation\browser-test.sqlite3 start --duration 90 --min-dwell-seconds 5
```

90 秒内打开不含私人内容的 Chrome 页面，在 trends.google.com 内每 2 秒切换页面/标签，持续 15 秒；切到其他站点 6 秒，再回到 Trends 6 秒。还可验证地址栏输入时不记录未提交输入、暂停后无新增网址、无痕窗口被排除。无需开启正文或截图。

采集自动停止后：

```powershell
.\.venv\Scripts\python.exe daytrace.py --db .\local-validation\browser-test.sqlite3 records --table browser --show-titles
.\.venv\Scripts\python.exe daytrace.py --db .\local-validation\browser-test.sqlite3 records --table intervals --show-titles
```

核对：同域浏览页面共享 interval_id，title / url 保留读到的变化，captured_ms 为采样时间，domain 一致；中间其他域名有独立区间，返回后新建区间；duration_ms 是连续浏览时长。小于 5 秒的整个站点访问没有页面证据。网址无 query / fragment / 登录凭据，后台标签不采集。详情和 CLI 会显示真实网址，请勿提交输出到仓库。

## 限制

- 通过标准 [UI Automation ValuePattern](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationvaluepattern) 读取特定可见地址栏；不读取历史数据库、不安装扩展、不操作地址栏。
- 适配依赖地址栏语言、浏览器 UIA 支持。全屏隐藏地址栏、权限拒绝、未识别语言、UIA 超时均可能取不到网址。当前匹配中英文常见地址栏名称，尚未做逐版本实机认证。
- 读取有约 1 秒轮询间隔和进程/UIA 延迟；高速连续切换时不能保证每页均被观察到。无法确认域名时沿用标题级阈值，不猜测同站点关系。
- URL 去掉查询与片段，同标题且只改查询参数的页面不另外保存参数变化。路径脱敏不是完美秘密识别。浏览器未给出协议时不猜测 HTTPS。
- 页面证据保留 7 天，网站时间区间沿用 90 天；旧记录无法补取网址。新增 URL 不发送给现有 AI。
- 384 MB 是子进程内存限制，2.5 秒是外层超时，均不是实际性能测量。仍需在用户电脑记录 CPU、内存与浏览器版本。
