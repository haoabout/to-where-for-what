# travel-planner

一个给 AI 编程助手用的旅行规划 skill。产出**单个 `trip.html`**——景点清单、地图、攻略三个视图合在一个文件里，双击就能打开，也能直接发给同行的人。

筛选和排程全在页面里完成，AI 不介入：

```
A 搜索景点 →(AI)→ ┌ ① 景点清单 ⇄ ② 地图（筛选 + 排程）┐ →(AI)→ ③ 攻略
                  └      你自己来回，实时联动         ┘
```

## 安装

```bash
npx skills add <owner>/<repo>
```

<!-- TODO(发布前)：把 <owner>/<repo> 换成真实的 GitHub 地址 -->

支持 Claude Code、Codex、Cursor、OpenCode 等 70+ 工具（走 [Vercel skills CLI](https://github.com/vercel-labs/skills)）。装完直接说「帮我规划去大阪的行程」就会触发。

手动安装：把 `skills/travel-planner/` 整个目录拷进 `~/.claude/skills/`（或你的工具对应的 skills 目录）。

**依赖**：Python 3.9+，标准库即可，不需要 pip install。地图和天气要联网。

## 它做什么

**A · 穷举景点**　按分类配额搜 35–50 个候选，开放时间、闭馆日、预约要求、门票、修缮状态**第一轮就联网拿全**——否则你筛了半天，最后发现那天不开门。每个景点必须带真实来源 URL。

**B+C · 你来筛和排**　地图视图里三栏并排：景点清单 ｜ 日程 ｜ 地图。

- 每个点选**想去 / 待定 / 不想去**，marker 立刻变色
- 把地点拖进某一天，或点它的圆点；天内顺序拖着调，或用 ↑↓
- 地图上按顺序连成当天颜色的虚线，**绕路一眼看得见**
- 一个点可以出现在多天，也可以一天出现两次
- 改动几秒后自动写回 `places.json`，不用记得点保存

**D · 生成攻略**　AI **按你排的日程**写，不重新分组。逐日时间轴、交通表、光线与摄影时段、注意事项。费用汇总和景点对照表由页面从数据自动生成，永远和你的选择一致。

## 页面里有什么

- **地图**：OSM 矢量底图（两个独立数据源互为备份）+ 从 OSM 抓的**地铁线路与车站，用官方线路配色**
- **天气**：浏览器端实时拉 Open-Meteo。16 天内是预报，超出则退回过去 8 年同期均值并明确标注
- **导出**：CSV（可直接导入 Google My Maps）、KML
- **降级链**：矢量 → 光栅 → 无 WebGL 用 Leaflet → 全挂时静态散点图。每一级都实测过

## 长期偏好

存在 `~/.travel-planner/preferences.md`，跨行程复用：交通习惯、体力、兴趣权重、忌口、预算档、攻略详略。

**刻意放在 skill 目录之外**——你更新或重装 skill 时（git pull、下载 zip、删掉重装都算）不会碰到它。skill 目录里只有模板。

## 产出

```
<trips_root>/2026-09-osaka/
├── brief.md          # 行程参数
├── places.json       # ★唯一数据源
├── transit.geojson   # 地铁线路与车站
├── route.md          # 攻略正文
└── trip.html         # 构建产物
```

`places.json` 是唯一真相，页面只是它的渲染。所以清单和地图不可能对不上。行程存在哪由你决定，第一次用时会问一次并记进偏好文件。

## 已知限制

- **小红书、B 站抓不到**（反爬 + 登录墙）。影视动漫打卡地只能靠搜索引擎找二手整理，覆盖不如专门社区
- **地铁配色依赖 OSM 的 `colour` 标签**。冷门城市可能缺，缺了会用备用色板（会避开已用色）
- **交通时长和票价是查询当日的**。行程往往在几十天后，时刻表和票价都可能变，出发前要重查
- **`file://` 双击打开时没有自动保存**，得手动点保存按钮（浏览器不允许网页在无用户手势时写文件）。推荐用 `--serve`
- 攻略正文里的信息由 AI 联网核实后写入，**但仍应抽查几条来源链接**再出发

## 开发

```bash
python3 dev/test_validate.py                          # 校验器回归（43 个用例）
python3 skills/travel-planner/scripts/build.py <行程目录> --serve
```

`dev/` 里是开发期的东西（回归测试、能力探针、原始草稿），不参与安装。

本机开发建议软链接，改完立刻生效：

```bash
ln -s "$PWD/skills/travel-planner" ~/.claude/skills/travel-planner
```

## 许可

[MIT](LICENSE)。内联的 [SortableJS](https://github.com/SortableJS/Sortable) 1.15.7 同为 MIT，见 [`assets/vendor/README.md`](skills/travel-planner/assets/vendor/README.md)。

地图数据 © [OpenStreetMap](https://www.openstreetmap.org/copyright) 贡献者。
