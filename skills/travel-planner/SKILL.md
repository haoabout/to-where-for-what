---
name: travel-planner
description: 规划一次旅行，产出可交互的行程页（景点清单 + 地图 + 攻略，单个 HTML 文件）。当用户说「帮我规划去 XX 的行程」「XX 几日游怎么安排」「想去 XX 玩，帮我看看有什么值得去的」「帮我做份 XX 攻略」，或提到穷举景点、筛选景点、排路线、做旅行攻略时使用。也用于在已有行程上继续：重新筛选、调整路线、补充景点。Plan a trip and produce an interactive itinerary page (shortlist + map + guide in one HTML file). Use when the user asks to plan a trip, find things to do in a city, build a travel guide, or design a day-by-day route.
---

# 旅行规划

把一次旅行拆成四个阶段，产出**单个 `trip.html`**（三视图：景点清单 / 地图 / 攻略）。

```
A 搜索景点 →(你)→ ┌ ① 景点清单 ⇄ ② 地图（筛选 + 排程）┐ →(你)→ ③ 攻略
                  └   用户自由来回，你不介入        ┘
```

**筛选和排程都不需要你介入**——地图视图里三栏并排：景点清单 | 日程 | 地图。
用户改了选择 marker 立刻变色，把地点分到各天、排出顺序也全在页面里完成。
你只在 A（搜索）和 D（写攻略）两处工作。

---

## 三条硬规则

违反任何一条，产出就是坏的。

**1. 不许手写 HTML。**
你只产出 `places.json` 和 `route.md`，跑 `build.py` 生成页面。模板已经处理好了三视图、地图降级、天气、响应式、明暗配色。手写 HTML 会得到样式不一致、有 bug 的页面。

**2. 不许发明字段。**
`places.json` 的字段全部定义在 [references/data-schema.md](references/data-schema.md)。契约外的字段模板不会渲染，内容会**静默丢失**。确需新字段就先改 schema 和校验器。

**3. 不许写没联网确认过的信息。**
每个景点必须有 `sources`（真实 URL）。`status` 未经确认一律不许填 `open`。校验器会拦，但拦得住格式拦不住编造——你自己要守住。

---

## 运行环境适配

- **Claude Code / 支持结构化提问的环境**：用 AskUserQuestion 做开场问卷和阶段确认。
- **Codex / 纯对话环境**：直接用普通对话询问，**不要假设结构化提问工具存在**。一次最多问 1-3 个最关键的问题；信息缺口不影响开工时，先做合理假设并在回复里写明。

判断依据是你实际有没有那个工具，不要猜。

---

## 偏好文件

长期偏好存在 **`~/.travel-planner/preferences.md`**，跨行程、跨项目复用。

**刻意放在 skill 目录之外**：用户更新或重装 skill 时（不管是 git pull、下载 zip 还是直接删掉重装）都不会碰到它。skill 目录里只有 `preferences.template.md` 模板。

启动时：

1. 读 `~/.travel-planner/preferences.md`。不存在就把 `<SKILL_ROOT>/preferences.template.md` 的内容原样写过去，并告诉用户"第一次用，我先建了个偏好文件"。
2. 文件里有、但模板新增的段落缺失时，**只补不改**——问用户那一项，然后追加。**绝不整体重写**，那会丢掉用户攒下的偏好。

**用你自己的读写工具做这两步，不要走 shell。** `mkdir -p`、`[ -f ... ]`、`cp` 都是
POSIX 专有的，Windows 的 PowerShell / cmd 下会直接失败——而这是整个流程的第一步，
断在这里用户连开始都开始不了。

---

## 跑脚本用哪个解释器

**不要写死 `python3`。** Windows 上 python.org 的安装包只装 `python.exe` 和 `py.exe`，
**不装 `python3.exe`**；而系统自带一个同名的应用执行别名，作用是**打开微软商店**。
所以 Windows 用户跑 `python3 build.py` 最常见的结果不是报错，是弹出商店页面。

第一次要跑脚本时探一次，之后整场对话都用探到的那个（下文一律写作 `<PY>`）：

| 顺序 | 试 | 说明 |
|---|---|---|
| 1 | `py -3 --version` | Windows 官方启动器，最可靠 |
| 2 | `python --version` | 要确认输出是 3.x，不是 2.7 |
| 3 | `python3 --version` | macOS / Linux 上的常态 |

需要 Python 3.9 以上。都不通就告诉用户去装，别硬跑。

---

## 开工前 · 先看有没有已经在做的行程

用户说「继续」「接着上次」「改一下我那个 XX 行程」时，**不要从开场问卷重来**。

对话是新开的，但行程数据一直在磁盘上——**它跟对话 session 没有任何关系**。
重新搜一轮不只是浪费，还会把用户上次筛的 `choice` 和排的 `itinerary` 全冲掉。

1. 按下一节的顺序找到行程根目录，看里面有没有匹配的行程，有就读它的 `places.json`
2. 那就是全部真相：`choice` 是用户筛的，`itinerary` 是用户排的天和顺序
3. `trip.html` 是构建产物，**不要读它，也不要手改**——重新 build 一次就有了

重跑一次 build 就能把页面恢复到上次的样子：

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<行程> --serve
```

**不确定是哪个行程就把根目录下的行程列出来让用户选**，不要猜。

如果用户说"我明明排过日程"而 `places.json` 里没有：多半是他用 `file://` 双击打开的
（那种方式没有自动保存），改动只在**那台机器、那个浏览器、那个地址**的 localStorage 里
（`file://` 和 `http://localhost` 是两份不同的存储），你读不到。
让他打开原来那个页面点一次「保存选择和日程」。

### 用户粗胚补全

行程页的地图上有搜索框（Nominatim），用户临时想去哪就搜一下、一键加进清单或
某一天——落进 `places.json` 的只有名称 + 坐标 + OSM 链接，带 `origin: "user"`，
没有任何研究型字段。这是设计好的分工：**用户加粗胚，你事后补全**。

在已有行程上继续工作时（不管用户要你干什么），先扫一遍：

1. 找 `places[]` 里 `origin == "user"` 且**没有 `tier`** 的点——这就是待补全清单
2. 对它们走 A2 的研究流程：联网核实开放时间/门票/预约，写 `pitch`、`detail`、
   定 `tier`/`scale`/`category`，补 `name_local`（契约见 data-schema.md「用户粗胚」）
3. **保留 `origin: "user"` 字段**（它是出处标记，不是待办标记），**保留用户已有的
   `choice` 和日程引用**——用户特意搜来加的点，`choice` 通常已是 `yes`，别动它
4. 补全后跑一遍 `validate.py`；坐标在 bbox 外只会报 P1，确认不是搜错了同名地点即可。
   若点真的在 bbox 外较远（如大阪行程加了奈良），在攻略里按实际通勤时间排路线

用户没提这些点时也要补——他在地图上加完就认为「这事交给 AI 了」。

---

## 行程文件存哪

**第一次用时问一次，记进 `preferences.md` 的 `trips_root`，之后不再问。**

不问就默认落在"用户当时开着 AI 的那个目录"下，会把行程塞进一个毫不相干的代码仓库，
换个目录再问「继续我的京都行程」就找不着了。

按这个顺序定：

1. `preferences.md` 里有 `trips_root` → 用它
2. 当前目录下已经有 `trips/` → 用它（不必打扰用户）
3. 否则问用户，默认建议 **`~/travel-plans/`**，把答案写进 `preferences.md`

默认值不用 `~/.travel-planner/trips/`（隐藏目录里放用户要打开和分享的 HTML 不方便），
也不用 `~/Documents`（不同语言的系统上目录名不一样）。

行程目录本身是 AI 建的，用户不需要碰任何文件对话框。下文的 `trips/<行程>/`
一律指 `<trips_root>/<行程>/`。

---

## 阶段 A · 搜索景点

### A1. 开场问卷

目的地是必问的。另外四项：

| 问什么 | 为什么 |
|---|---|
| **出行日期 + 天数** | 决定闭馆日冲突、季节限定、限时展览、天气。没有日期，这几块全做不了 |
| **抵达与离开的时间** | 见下方「为什么要问到几点」 |
| **同行人 + 体力强度** | 决定路线强度和景点取舍 |
| **落脚点** | 已订酒店给地址，没订给大致区域。决定每日路线的起终点 |

交通方式、预算档、兴趣权重**不在这里问**——它们在 `preferences.md` 里，问一次长期复用。

#### 为什么要问到几点

只问「几天」问不出这两种很常见的形态：

- **第一天下午三点才落地** —— 那天实际只有半天，塞满四个馆一定完不成
- **最后一天中午的飞机** —— 早上只够吃个早饭、逛一条商店街
- **前一晚就到了** —— 多出「第 0 天（抵达当晚）」，够在住处附近走走

问清楚之后：

| 情况 | 怎么落到数据里 |
|---|---|
| 抵达日 = `dates.start` 的前一天晚上 | 告诉用户排程页可以加「第 0 天」 |
| 首日或末日只有半天 | 写进 `trip.note`，D 阶段排路线时按半天算 |
| 都是整天 | 什么都不用做 |

**`itinerary` 字段不要预填。** 页面打开时会按 `dates` 自动逐日建好空容器，
两处都造同一份数据迟早会对不上。契约见 [data-schema.md](references/data-schema.md)。

### A2. 搜索并产出 `places.json`

详细规则读 **[references/research-playbook.md](references/research-playbook.md)**：分类配额、搜索策略、防幻觉、图片获取、微景点处理。

要点：

- 总量 **35–50**，按分类配额分配，小城市不足**如实说明，不许凑数**
- 开放时间、闭馆日、预约状态、门票、修缮状态**第一轮就要拿到**——否则用户筛半天，最后发现那天不开门
- 坐标用 `{"lon":…, "lat":…}` 对象形式，不许用数组
- 图片 URL 必须从 API 拿，**不许手工拼**（见 playbook 里的 Wikimedia 教训）

### A3. 补齐坐标与配图 · 校验 · 构建

**坐标和配图不要自己填，跑脚本。** 它们是确定性的 API 调用，脚本比你准，
而且已经处理好了 Nominatim 的 1 req/s 限速、bbox 越界校验、
以及 Wikimedia 缩略图必须走 API 的问题。

```bash
<PY> <SKILL_ROOT>/scripts/enrich.py   trips/<行程>/places.json --coords --images
<PY> <SKILL_ROOT>/scripts/enrich.py   trips/<行程>/places.json --transit
<PY> <SKILL_ROOT>/scripts/validate.py trips/<行程>/places.json --check-links
<PY> <SKILL_ROOT>/scripts/build.py    trips/<行程> --serve
```

`--transit` 从 OSM 抓当地的地铁/轻轨线路与车站，产出 `transit.geojson`。
线路配色取自 OSM 的 `colour` 标签，也就是官方线路色。**单独跑一次**，
不要和 `--coords --images` 合并——Overpass 按 IP 分配执行槽，
紧接着连发容易吃限流。抓不到就跳过，地铁层是加分项，不阻塞出图。

`enrich.py` 补不上的会明确报出来（多半是查不到，或搜到的点落在 bbox 外），
这时才需要你人工处理——**它宁可留空也不会填一个看似合理的错坐标**。

**必须零 P0 才能交付。** P1 逐条看过再决定忽略还是修。

`--serve` 会起本地服务并打开浏览器。**优先用它**，因为 `file://` 下 OSM 官方底图会返回一张写着「Access blocked」的图片（HTTP 状态码还是 200，肉眼才看得出来）。

---

## 阶段 B + C · 用户筛选与排程（你不参与）

告诉用户分两步，都在同一个页面里做完：

**先筛选**

- 在清单里给每个点选**想去 / 待定 / 不想去**，选「不想去」时可以记个理由
- 随时切到地图看分布，改了选择 marker 会立刻变色，**不用回来找你**

**再排程**（地图视图，中间那一栏）

- 日程栏已按行程日期自动建好每一天，不需要新建
- 把地点放进某天：**从清单拖过去**，或选中那天后**点地点的圆点**
- 天内调顺序：拖，或用条目上的 ↑ ↓
- 地图上会把每天的点按顺序连成一条当天颜色的虚线，**绕路一眼可见**
- 一个地点可以出现在多天（世博会连着去两天），也可以一天出现两次（白天夜景各一次）
- 航班傍晚才落地就点日程栏右上角的 `+` 加「第 0 天」

**不用告诉用户去点保存。** `--serve` 起的服务下，改动会在几秒空闲后自动写回
`places.json`，状态显示在页面底部。只有用 `file://` 打开时才需要点「保存选择和日程」
（浏览器不允许网页在无用户手势时写文件），不支持直写的浏览器再退到「下载 JSON」
或「复制短码」。

短码里 `+ ? -` 三行是选择，`D1 D2 …` 行是日程（**行内顺序就是当天路线顺序**，
`(括号)` 是备注）。用户贴短码回来时，按它更新 `places.json` 的 `choice` 和
`itinerary`，然后重新 build。

然后**停下来等**。不要自作主张替用户筛选或排程——砍掉哪些、哪天去哪，
是取舍不是计算，那是用户的决定。

用户说排完了：重新读 `places.json`，确认 `choice` 分布与 `itinerary`，再进入 D。

---

## 阶段 D · 设计路线

详细规则读 **[references/route-design.md](references/route-design.md)**。

**`places.json` 里有 `itinerary` 时，按它写，不要重新分组。** 那是用户自己排的天
和顺序，推翻它等于把他刚做完的取舍作废。有异议就写进正文说明理由，让他自己改。
只有 `itinerary` 缺失或全空时，才由你按下面的规则提议一份。

要点：

- 按 `area` 聚类，**同一天尽量只走 1–2 个片区**
- 用 `closed_days` 排除冲突日；`night: true` 的排在晚上；下雨备选从 `indoor: true` 里取
- 写进 `trips/<行程>/route.md`，用 Markdown
- 列表项以 `09:30 ` 开头会自动变成时间轴，**不需要特殊语法**
- **不要**在 route.md 里手写费用汇总和景点对照表——页面会从数据自动生成，保证永不出错

路线里出现博物馆/美术馆时，调用 **[references/museum-module.md](references/museum-module.md)** 做深度展开。
出现影视动漫打卡地时，参考 **[references/media-pilgrimage.md](references/media-pilgrimage.md)**。

写完重新构建：

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<行程> --serve
```

想单独分享攻略（不带筛选界面）：

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<行程> --standalone   # 输出 guide.html
```

---

## 文件布局

```
<trips_root>/2026-09-osaka/          # 根目录见「行程文件存哪」
├── brief.md          # 行程参数（开场问卷的答案）
├── places.json       # ★唯一数据源，三个视图都从它渲染
├── transit.geojson   # 地铁线路与车站（enrich.py --transit 产出）
├── route.md          # 攻略正文（你写）
└── trip.html         # 构建产物，不要手改
```

`places.json` 是唯一真相。用户的选择原地更新到 `choice` 字段，不另存文件——所以清单和地图永远不可能对不上。

`trip.html` 是**某一次构建时的快照**：它自包含（分享给同行的人，对方双击就能看，
不需要服务、不需要这个仓库），但对方看到的只是构建那一刻的数据，包括所有
「不想去」的理由。用户在浏览器里的后续改动存在他自己的 localStorage 里，
**不在文件里**，别人打不开也看不到。所以每次写完 `places.json` 都要重新 build
——`--serve` 起的本地服务在收到保存时已经自动做了。

---

## 语言规则

- 正文以**用户语言**的地名为主。
- 中国以外的地点，**第一次**在正文出现时写「中文名（当地语言名）」，之后只写中文名。
- 当地语言名必须**能在地图里搜到**；中文名要自然、可读、前后一致。
- 没有通行译名时可以音译或意译，但同一份文档内**不得混用多个译名**。

---

## 交付前自检

跑一遍 **[references/checklist.md](references/checklist.md)**，尤其：

- [ ] `validate.py` 零 P0
- [ ] 抽查 3–5 个景点，**人工点开 `sources` 里的链接**确认信息属实
- [ ] 浏览器实际打开页面看过（不是只看代码）
- [ ] 攻略里的 ✅❌ 对照表与用户的 `choice` 一致（自动生成的，但要确认渲染了）
- [ ] 明确告诉用户哪些信息可能过期、哪些是估算

---

## 已知限制（要主动告诉用户，不要含糊）

| 限制 | 说明 |
|---|---|
| 小红书 / B 站抓不到 | 反爬 + 登录墙。影视打卡地只能靠搜索引擎找二手整理，可能不全 |
| 门票金额是估算 | `ticket` 是自由文本，特别展、体验项目、夜间加价通常另计 |
| 地铁线路来自 OSM，质量因城市而异 | 线路的官方配色取自 OSM 的 `colour` 标签。大阪实测 20/20 全有；冷门城市可能缺，此时退回自动分配色并在图例注明 |
| 超过 16 天的天气不是预报 | 自动退回历史同期均值，界面已标注，但你也要说一句 |
| 服务停止后功能降级 | `file://` 打开仍可读、矢量底图和地铁层照常，但不能直写文件、不能用 OSM 官方光栅底图（它要 Referer） |

---

## 资源导览

| 文件 | 什么时候读 |
|---|---|
| [references/data-schema.md](references/data-schema.md) | 写 `places.json` 之前，必读 |
| [references/research-playbook.md](references/research-playbook.md) | 阶段 A 搜索之前，必读 |
| [references/route-design.md](references/route-design.md) | 阶段 D 排路线之前，必读 |
| [references/museum-module.md](references/museum-module.md) | 路线含博物馆时 |
| [references/media-pilgrimage.md](references/media-pilgrimage.md) | 做影视动漫打卡地时 |
| [references/checklist.md](references/checklist.md) | 交付前 |
| `scripts/enrich.py` | 补坐标与配图，写完 `places.json` 主体后 |
| `scripts/validate.py` | 每次改完 `places.json` |
| `scripts/build.py` | 生成/更新页面 |
