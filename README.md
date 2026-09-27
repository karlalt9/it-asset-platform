# IT 资产巡检平台 (IT Asset Platform)

把"逐台手工检查办公电脑"这件事,做成一套可以自动采集、集中存储、按规则预警的小型运维系统。

终端侧是 PowerShell 采集脚本(即 `pc-health-check` 的升级版),服务端是 FastAPI + SQLite,前端是 Vue 3 看板。

![CI](https://github.com/karlalt9/it-asset-platform/actions/workflows/ci.yml/badge.svg)

<!-- 建议补充截图: 运行 python -m app.seed --reset 后截取看板首页,存到 docs/screenshot-overview.png 并在这里引用 -->

## 它解决什么问题

在制造企业 IT 部实习时,确认一台电脑的配置和运行状态要手动查一遍:系统版本、内存占用、磁盘余量、防火墙是否开启。机器一多,这件事就变成重复劳动,而且没人知道哪台机器快满了、哪台机器三个月没重启过。

这个项目把流程拆成三段:

1. 终端定时采集本机状态,生成结构化数据;
2. 服务端集中存储,按可配置的阈值规则判定异常;
3. 看板呈现资产台账、告警和趋势,支持导出和标记处理。

网络不通的时候终端不会丢数据,恢复后自动补发;同一条问题持续存在时不会反复刷屏,修好之后自动关闭。

## 功能一览

| 模块 | 能力 |
|---|---|
| 终端采集 | 系统信息、处理器、内存、磁盘分区、硬盘介质、防火墙、病毒防护、待重启状态 |
| 上报链路 | 设备指纹识别、Token 鉴权、幂等入库、本地离线队列、指数重试 |
| 资产台账 | 主机名、使用人、部门、位置、硬件配置,支持搜索筛选与 CSV 导出 |
| 规则引擎 | 阈值规则写在 JSON 里,支持 6 种比较运算和多分区逐项判定,改完即生效 |
| 告警管理 | 同规则合并累加、指标恢复自动关闭、人工标记处理并留备注 |
| 数据看板 | 设备在线情况、未处理告警分布、近 7 天告警趋势、单机指标趋势 |

## 系统架构

```
┌──────────────────────────────┐
│  Windows 终端                │
│  pc-health-check.ps1         │
│  采集 -> 设备指纹 -> JSON    │
│  上报失败 -> queue/*.json    │
└──────────────┬───────────────┘
               │ POST /api/v1/agents/report
               │ X-Agent-Token
               v
┌──────────────────────────────┐
│  FastAPI 服务端              │
│  ┌────────────────────────┐  │
│  │ 幂等入库 (设备+报告)   │  │
│  │ 指标长表 (metrics)     │  │
│  │ 规则引擎 (rules.json)  │  │
│  │ 告警合并与自动恢复     │  │
│  └────────────────────────┘  │
│  SQLite / PostgreSQL         │
└──────────────┬───────────────┘
               │ REST API
               v
┌──────────────────────────────┐
│  Vue 3 看板                  │
│  总览 / 设备资产 / 告警中心  │
│  ECharts 趋势图 + CSV 导出   │
└──────────────────────────────┘
```

## 快速开始

### 方式一:双击脚本(Windows 最省事)

先装好两个环境:

| 需要什么 | 下载地址 | 安装时注意 |
|---|---|---|
| Python 3.12 | <https://www.python.org/downloads/> | 务必勾选 Add python.exe to PATH |
| Node.js 20 LTS | <https://nodejs.org/> | 保持默认选项即可 |

然后双击项目根目录的 `start-all.bat`,它会打开两个窗口分别启动服务端和看板。首次运行会自动创建虚拟环境、安装依赖、生成演示数据,大约需要几分钟。

等两个窗口都出现地址提示后,用浏览器打开 <http://localhost:5173>。

只想启动其中一个,双击 `start-server.bat` 或 `start-web.bat`。

想重新来一遍(清空数据、重建环境),先关掉那两个窗口,再删掉 `server\.venv` 和 `server\data` 两个目录,然后重新双击即可。

### 方式二:Docker 一键启动

```bash
git clone https://github.com/karlalt9/it-asset-platform.git
cd it-asset-platform
# 打开 .env,把两个令牌都改成自己的随机字符串
docker compose up -d --build
```

打开 <http://localhost:8080> 即可看到看板,接口文档在 <http://localhost:8080/docs>。

想先看效果而不是手工造数据,执行一次演示数据脚本:

```bash
docker compose exec api python -m app.seed --reset
```

### 方式三:命令行手动启动

启动服务端:

```bash
cd server
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed --reset
uvicorn app.main:app --reload
```

另开一个终端启动前端:

```bash
cd web
npm install
npm run dev
```

前端开发地址 <http://localhost:5173>,已配置 `/api` 代理到 `127.0.0.1:8000`。

## 部署 Agent

在需要纳管的电脑上运行一次:

```powershell
.\pc-health-check.ps1 -ServerUrl http://10.0.0.5:8000 -Token 你的令牌
```

注册成计划任务,每 4 小时自动上报一次:

```powershell
.\install-task.ps1 -ServerUrl http://10.0.0.5:8000 -Token 你的令牌 -IntervalHours 4 -StartNow
```

也可以把脚本同目录的 `config.example.json` 复制成 `config.json` 并填好地址和令牌,之后直接双击 `run.bat` 就能上报。

卸载计划任务:

```powershell
.\uninstall-task.ps1
```

### Agent 参数

| 参数 | 说明 |
|---|---|
| `-OutputPath` | 本地报告保存路径,默认 `reports\体检报告_时间.txt` |
| `-Json` | 额外导出一份 JSON |
| `-NoFile` | 只在屏幕显示,不保存本地报告 |
| `-ServerUrl` | 管理平台地址 |
| `-Token` | 上报令牌 |
| `-QueueDir` | 离线队列目录,默认脚本同目录 `queue` |
| `-ConfigPath` | 配置文件路径,默认脚本同目录 `config.json` |
| `-NoUpload` | 只做本地体检,不上报 |

不带 `-ServerUrl` 和 `-Token` 时,脚本行为与原来的单机体检工具完全一致。

### 接入局域网内的其他电脑

默认情况下服务端只监听本机,要让其他电脑上报,按三步走。

**第一步:让服务端监听局域网。** 用 `start-server.bat` 启动时会自动监听 `0.0.0.0`,窗口里会打印局域网地址和两个令牌:

```
局域网地址:   http://192.168.3.25:8000   (其他电脑用这个地址上报)
Agent 上报令牌: <你的上报令牌>
看板读取令牌:   <你的读取令牌>
```

注意:**只需要把上报令牌告诉别人电脑上的 Agent**,读取令牌留在自己手里。Agent 拿着上报令牌只能写入数据,读不到任何设备信息和告警内容,也不能修改资产记录。

如果是手工启动,记得把 `--host 127.0.0.1` 换成 `--host 0.0.0.0`。

**第二步:放行防火墙端口。** 用管理员身份打开 PowerShell 执行一次(只需一次):

```powershell
New-NetFirewallRule -DisplayName "IT 资产巡检平台" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

**第三步:在目标电脑上部署 Agent。** 把 `agent` 整个文件夹复制过去,在该目录下运行:

```powershell
.\pc-health-check.ps1 -ServerUrl http://192.168.3.25:8000 -Token <你的上报令牌>
```

想让它自动定时上报,注册成计划任务即可:

```powershell
.\install-task.ps1 -ServerUrl http://192.168.3.25:8000 -Token <你的上报令牌> -IntervalHours 4 -StartNow
```

目标电脑只要有 Windows 自带的 PowerShell 就行,不需要装 Python、Node.js 或其他运行环境。上报成功后,这台机器就会出现在看板的设备列表里。

如果要在其他电脑上打开看板,再放行 5173 端口(前端已配置为监听所有网卡),用浏览器访问 `http://192.168.3.25:5173` 即可。

两个令牌都写在项目根目录的 `.env` 文件里(该文件已被 `.gitignore` 排除,不会提交到仓库),可以随时改成自己的随机字符串。

## 目录结构

```
it-asset-platform/
├── server/                  服务端
│   ├── app/
│   │   ├── api/             REST 接口(上报/设备/告警/统计)
│   │   ├── models.py        数据模型
│   │   ├── schemas.py       出入参校验
│   │   ├── ingest.py        上报入库流程
│   │   ├── rules.py         规则引擎
│   │   ├── seed.py          演示数据生成
│   │   └── main.py          应用入口
│   ├── config/rules.json    告警阈值规则
│   └── tests/               单元测试与接口测试
├── agent/                   终端采集脚本
│   ├── pc-health-check.ps1  采集 + 上报
│   ├── install-task.ps1     注册计划任务
│   ├── uninstall-task.ps1   移除计划任务
│   └── run.bat              双击运行
├── web/                     Vue 3 看板
├── scripts/dev.ps1          启动脚本的实际逻辑
├── start-server.bat         双击启动服务端
├── start-web.bat            双击启动前端看板
├── start-all.bat            双击启动两者
└── docker-compose.yml
```

## 关键设计

这部分是几个值得展开讲的决定。

### 1. 设备指纹而不是计算机名

设备标识由计算机名、主板序列号、物理网卡 MAC、系统盘卷序列号组合后取 SHA256 前 32 位。只认计算机名的话,机器改个名就会被当成新设备,资产表很快会变脏;而单看 MAC,换网卡或插拔 USB 网卡也会误判。多字段组合并允许任一字段缺失,是在"稳定性"和"不误合并"之间的折中。

### 2. 幂等上报

每次采集生成一个 `report_id`(GUID),服务端对 `(device_id, report_id)` 建唯一约束。重复提交会被识别成 `duplicate` 并直接返回,不产生任何副作用。

这个设计让重试逻辑可以写得很"大胆":网络超时、补发历史队列、服务端短暂不可用,都可以无条件重试,不用担心写脏数据。离线队列里保存的就是带 `report_id` 的完整请求体,补发时原样提交即可。

### 3. 指标用长表存

指标存在 `metrics` 表里,一个指标一行(`metric_key` + `dimension` + `metric_value` + `recorded_at`),而不是在报告表里铺一堆列。

原因是查询形态:画"某台机器近 7 天磁盘使用率趋势"时,长表只需要 `WHERE device_id=? AND metric_key=? AND recorded_at>?`;宽表则要写死列名,每加一个指标就改一次表结构。`dimension` 字段用来区分同一指标的多个实例,例如 `disk.used_percent` 在 C 盘和 D 盘各有一个点。

### 4. 规则写在配置文件里

阈值规则放在 `server/config/rules.json`,支持 `< <= > >= == !=` 六种比较运算。服务端按文件修改时间判断是否需要重新加载,改完保存即生效,不用重启。

规则长度小、变更频率低、需要评审和留痕,放进 Git 比放进数据库更合适;真要做可视化管理界面,也只需要在这个文件之上包一层读写。

### 5. 告警合并与自动恢复

同一条规则对同一台设备的同一个对象持续命中时,不会每 4 小时新增一条告警,而是把已有告警的命中次数加一、刷新最近命中时间。否则一台磁盘满了的机器几天就能刷出上百条记录,看板直接失去意义。

反过来,当本次上报**包含该规则的指标**且不再命中时,告警会被自动关闭并标记 `resolved_by = auto`。这里有个细节:如果指标这次根本没采到(比如读取失败),就不能判定为恢复,否则会把"没读到数据"误当成"问题解决了"。

### 6. 离线队列有上限

上报失败时,完整请求体写入 `queue/` 目录,下次运行先补发再采集本次数据。补发时服务端不可用会立刻停止重试,不做无意义的连续请求。

队列最多保留 200 条,超出后按时间淘汰最旧的。一台机器长期离线时,不能让它把磁盘写满。

### 7. 上报和读取用两个不同的令牌

把令牌拆成两个,是因为两者的分发范围完全不同:

* **上报令牌**要部署到每一台被纳管的电脑上,等于人手一份,它只够调用上报接口;
* **读取令牌**只掌握在运维自己手里,用于看看板、补录资产信息、处理告警。

这样即使某台机器的 Agent 配置被同事看到、或者整个文件夹被拷走,对方也只能往平台里写数据,读不到任何主机名、使用人、告警内容,更不能修改记录。

两个令牌的校验都使用固定时间比较(`hmac.compare_digest`),避免通过响应时间差反推令牌内容。令牌只放在 `.env` 里,不进版本库。

## 配置项

服务端全部通过环境变量配置:

| 变量 | 默认值 | 说明 |
|---|---|---|
| `IAP_DATABASE_URL` | `sqlite:///server/data/iap.db` | 换成长连接串即可切到 PostgreSQL |
| `IAP_DATA_DIR` | `server/data` | SQLite 数据目录 |
| `IAP_RULES_FILE` | `server/config/rules.json` | 规则文件路径 |
| `IAP_AGENT_TOKEN` | `dev-agent-token` | 终端 Agent 的上报令牌,部署前务必修改 |
| `IAP_READ_TOKEN` | `dev-read-token` | 看板读取令牌,只有拿到它的人能查看和修改数据 |
| `IAP_OFFLINE_AFTER_MINUTES` | `1440` | 超过这个时间没有上报就判定为离线 |
| `IAP_CORS_ORIGINS` | `localhost:5173` 等 | 允许的前端来源 |

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/agents/report` | 接收巡检上报(需要 `X-Agent-Token`) |
| GET | `/api/v1/devices` | 设备列表,支持关键字、状态、分页 |
| GET | `/api/v1/devices/{id}` | 设备详情、未处理告警、最近巡检 |
| PATCH | `/api/v1/devices/{id}` | 补录使用人、部门、位置、备注 |
| DELETE | `/api/v1/devices/{id}` | 删除设备及其巡检记录、指标和告警 |
| GET | `/api/v1/devices/{id}/metrics` | 指标时间序列 |
| GET | `/api/v1/devices/export/csv` | 导出资产清单(带 BOM,Excel 直接打开) |
| GET | `/api/v1/alerts` | 告警列表,支持等级与状态筛选 |
| PATCH | `/api/v1/alerts/{id}/resolve` | 标记告警已处理并填写备注 |
| GET | `/api/v1/stats/overview` | 看板总览数据 |
| GET | `/api/health` | 健康检查 |

完整交互式文档由 FastAPI 自带,运行后访问 `/docs`。

## 测试

```bash
cd server
python -m pytest -q
```

覆盖范围:

- 规则引擎:比较运算边界值、多分区独立判定、模板渲染、非法配置拒绝;
- 入库流程:首次上报建库、重复上报幂等、同设备多次上报复用记录、告警创建与合并、恢复自动关闭、指标缺失不误判;
- 接口层:鉴权失败、上报幂等、设备增改查、告警处理、总览统计、CSV 导出。

## 已知限制

- 采集项目前以硬件与系统状态为主,没有做软件清单、补丁清单和进程级的取证;
- 看板接口默认在内网开放,没有做用户体系;如果需要多人使用,应补一层登录与角色控制;
- 固态盘数量最多统计 3 块物理盘,极端配置下会不准确;
- SQLite 适合单机或小规模部署,设备量上千台时应切换到 PostgreSQL 并给指标表加分区或定期归档。

## 后续计划

- 增加软件清单与补丁合规检查;
- 支持按部门下发不同阈值规则;
- 告警接入企业微信或邮件通知;
- 指标数据按保留策略自动归档。

## 许可

MIT License,详见 [LICENSE](LICENSE)。
