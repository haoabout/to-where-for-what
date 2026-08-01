---
name: travel-planner
description: 规划一次旅行，产出可交互的行程页（景点清单 + 地图 + 攻略，单个 HTML 文件）。当用户说「帮我规划去 XX 的行程」「XX 几日游怎么安排」「想去 XX 玩，帮我看看有什么值得去的」「帮我做份 XX 攻略」，或提到穷举景点、筛选景点、排路线、做旅行攻略时使用。也用于在已有行程上继续：重新筛选、调整路线、补充景点。Plan a trip and produce an interactive itinerary page (shortlist + map + guide in one HTML file). Use when the user asks to plan a trip, find things to do in a city, build a travel guide, or design a day-by-day route.
---

# 旅行规划

把一次旅行拆成四个阶段，产出**单个 `trip.html`**（三视图：景点清单 / 地图 / 攻略）。

```
A 搜索景点 →(你)→ ┌ ① 景点清单 ⇄ ② 地图 ┐ →(你)→ ③ 攻略
                  └  用户自由来回筛选  ┘
```

**B 和 C 之间不需要你介入**——地图只是同一份数据的另一个视图，用户改了选择 marker 会立刻变色。你只在 A（搜索）和 D（排路线）两处工作。

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

1. 读 `~/.travel-planner/preferences.md`。不存在就从 `preferences.template.md` 复制一份过去，并告诉用户"第一次用，我先建了个偏好文件"。
2. 文件里有、但模板新增的段落缺失时，**只补不改**——问用户那一项，然后追加。**绝不整体重写**，那会丢掉用户攒下的偏好。

```bash
mkdir -p ~/.travel-planner
[ -f ~/.travel-planner/preferences.md ] || cp "<SKILL_ROOT>/preferences.template.md" ~/.travel-planner/preferences.md
```

---

## 阶段 A · 搜索景点

### A1. 开场问卷

目的地是必问的。另外四项：

| 问什么 | 为什么 |
|---|---|
| **出行日期 + 天数** | 决定闭馆日冲突、季节限定、限时展览、天气。没有日期，这几块全做不了 |
| **同行人 + 体力强度** | 决定路线强度和景点取舍 |
| **落脚点** | 已订酒店给地址，没订给大致区域。决定每日路线的起终点 |

交通方式、预算档、兴趣权重**不在这里问**——它们在 `preferences.md` 里，问一次长期复用。

### A2. 搜索并产出 `places.json`

详细规则读 **[references/research-playbook.md](references/research-playbook.md)**：分类配额、搜索策略、防幻觉、图片获取、微景点处理。

要点：

- 总量 **35–50**，按分类配额分配，小城市不足**如实说明，不许凑数**
- 开放时间、闭馆日、预约状态、门票、修缮状态**第一轮就要拿到**——否则用户筛半天，最后发现那天不开门
- 坐标用 `{"lon":…, "lat":…}` 对象形式，不许用数组
- 图片 URL 必须从 API 拿，**不许手工拼**（见 playbook 里的 Wikimedia 教训）

### A3. 校验 + 构建

```bash
python3 <SKILL_ROOT>/scripts/validate.py trips/<行程>/places.json --check-links
python3 <SKILL_ROOT>/scripts/build.py trips/<行程> --serve
```

**必须零 P0 才能交付。** P1 逐条看过再决定忽略还是修。

`--serve` 会起本地服务并打开浏览器。**优先用它**，因为 `file://` 下 OSM 官方底图会返回一张写着「Access blocked」的图片（HTTP 状态码还是 200，肉眼才看得出来）。

---

## 阶段 B + C · 用户筛选（你不参与）

告诉用户：

- 在清单里给每个点选**想去 / 待定 / 不想去**，选「不想去」时可以记个理由
- 随时切到地图看分布，改了选择 marker 会立刻变色，**不用回来找你**
- 筛完点「保存筛选结果」写回 `places.json`；浏览器不支持直写时用「下载 JSON」或「复制短码」

然后**停下来等**。不要自作主张替用户筛选。

用户说筛完了：重新读 `places.json`（或用户贴回的短码），确认 `choice` 分布，再进入 D。

---

## 阶段 D · 设计路线

详细规则读 **[references/route-design.md](references/route-design.md)**。

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
python3 <SKILL_ROOT>/scripts/build.py trips/<行程> --serve
```

想单独分享攻略（不带筛选界面）：

```bash
python3 <SKILL_ROOT>/scripts/build.py trips/<行程> --standalone   # 输出 guide.html
```

---

## 文件布局

```
trips/2026-09-osaka/
├── brief.md          # 行程参数（开场问卷的答案）
├── places.json       # ★唯一数据源，三个视图都从它渲染
├── route.md          # 攻略正文（你写）
└── trip.html         # 构建产物，不要手改
```

`places.json` 是唯一真相。用户的选择原地更新到 `choice` 字段，不另存文件——所以清单和地图永远不可能对不上。

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
| 底图画不出地铁线路配色 | OpenFreeMap 有地铁几何和双语站名，但没有线路名和官方配色。线路级信息写在攻略正文里 |
| 超过 16 天的天气不是预报 | 自动退回历史同期均值，界面已标注，但你也要说一句 |
| 服务停止后功能降级 | `file://` 打开仍可读，但不能直写文件、不能用 OSM 底图 |

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
| `scripts/validate.py` | 每次改完 `places.json` |
| `scripts/build.py` | 生成/更新页面 |
