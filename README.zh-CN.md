# Medium Roam · 五分熟旅行

[English](README.md) · **简体中文**

一个面向 AI 编程助手的旅行规划 skill。产出为**单个 `trip.html`**——景点清单、地图、攻略三个视图合并在一个文件内,可直接双击打开,也可发送给同行者。

筛选与排程全部在页面内完成,AI 不介入:

```
A 搜索景点 →(AI)→ ┌ ① 景点清单 ⇄ ② 地图（筛选 + 排程）┐ →(AI)→ ③ 攻略
                  └      用户自行操作，实时联动        ┘
```

## 安装

```bash
npx skills add haoabout/medium-roam
```

支持 Claude Code、Codex、Cursor、OpenCode 等 70+ 工具（基于 [Vercel skills CLI](https://github.com/vercel-labs/skills)）。安装后，提出行程规划请求——如「帮我规划去大阪的行程」——即可触发。

手动安装：将 `skills/medium-roam/` 拷入 `~/.claude/skills/`（或所用工具对应的 skills 目录）。

**依赖**：Python 3.9+，仅标准库，无需 pip install。地图与天气需要网络连接。

## 它做什么

**A · 穷举景点**　按分类配额搜索 35–50 个候选景点，开放时间、闭馆日、预约要求、门票、修缮状态**在第一轮联网时核实齐全**，避免筛选完成后才发现闭馆冲突。每个景点必须附带真实来源 URL。

**B+C · 筛选与排程**　地图视图三栏并排：景点 ｜ 日程 ｜ 地图。

- 每个景点标记**想去 / 待定 / 不想去**，marker 即时变色
- 将地点拖入某一天，或点击其圆点即可排进当日行程；行程内顺序可拖动调整，或使用 ↑↓键
- 地图按访问顺序连成当天颜色的虚线，**绕路情况一目了然**
- 同一地点可出现在多天，也可在一天内出现两次
- 改动数秒后自动写回 `places.json`，无需手动保存

**D · 生成攻略**　AI **按已排定的日程**撰写，不重新分组。逐日时间轴、交通表、光线与摄影时段、注意事项。费用汇总、出发前待办与景点对照表由页面从数据自动生成，与筛选结果始终一致。待办清单列出需预约的到访（逐次一行）与未核实完的信息，勾选即写回数据，打印后可当纸面清单；临近出发仍有必订未订项时，校验器会提醒。

攻略默认按 **A4 分页**排版：一节一页，字号统一，页脚带页码，左侧提供快速跳页导航。「导出 PDF」经浏览器打印实现。`route.md` 中的 `---` 即为分页符。

## 页面里有什么

- **地图**：OSM 矢量底图（两个独立数据源互为备份）+ 从 OSM 获取的**地铁线路与车站，使用官方线路配色**。两套矢量底图各有明暗两版，由地图右上角开关切换；页面本身为固定浅色底 + 点阵纹理 + 纸面层，不提供独立的明暗切换
- **交通**：在日程列顶部点一次，即可用 OSM 路径规划逐段算出步行 / 驾车路线（每段可单独切换），按真实路径画在地图上，段行显示耗时与距离，日盒底部给出当日合计。公交段不做路由——没有开放时刻表可用——只保留一条虚线和你自己写的备注
- **天气**：浏览器端实时拉取 Open-Meteo。16 天内为预报，超出范围回退到过去 8 年同期均值并明确标注
- **导出**：CSV（可直接导入 Google My Maps）、KML；攻略按 A4 分页，经浏览器打印导出 PDF
- **降级链**：矢量 → 光栅 → 无 WebGL 时用 Leaflet → 全部失效时静态散点图

## 界面语言

行程页界面语言跟随 `trip.output_language`：中文使用内置中文界面，其余使用内置英文。其他语言由 AI 在创建行程时将模板字符串表翻译后写入 `places.json` 的 `ui` 字段（契约见 `references/data-schema.md`）。星期与日期名称由 `Intl` 自动本地化。

## 长期偏好

存于 `~/.medium-roam/preferences.md`，跨行程复用：交通习惯、体力、兴趣权重、忌口、预算档、攻略详略。

**刻意置于 skill 目录之外**——更新或重装 skill（git pull、下载 zip、删除重装）均不触及此文件。skill 目录内仅包含模板。

## 更新

任何更新方式都不会影响个人数据：`~/.medium-roam/preferences.md` 与行程目录均在 skill 目录之外，重装亦不受影响。

已安装版本记录在 `skills/medium-roam/SKILL.md` frontmatter 的 `version:` 字段；同目录的 `CHANGELOG.md` 记录版本间的差异，并明确标注行为变化，建议更新前查阅。

**修改过 skill 文件的用户**（SKILL.md 规则、`build.py`、模板等），建议以 git 方式安装，并将修改提交为本地 commit；此后 `git pull --rebase` 即为带冲突标记的三方合并。这是本地修改在更新后得以保留的唯一可靠方式——zip 覆盖会将其静默丢弃。轻量的个人偏好和规则建议写入 `preferences.md`，该文件不受任何更新影响。

**向 AI 询问是否需要更新时**，AI 会执行 SKILL.md（"Updating this skill"）中的判定流程：存在 git 元数据时检查 `git status`；否则将本地文件与 `version:` 对应的发布版本比对——未修改的安装直接覆盖更新，已修改的逐文件三方合并，且始终以整个 skill 目录为合并单位（`build.py` 与模板存在耦合）。更新完成后对现有行程重新运行 `validate.py`，以捕获数据契约的变化。

## 产出

```
<trips_root>/2026-09-osaka/
├── brief.md          # 行程参数
├── places.json       # ★唯一数据源
├── transit.geojson   # 地铁线路与车站
├── route.md          # 攻略正文
└── trip.html         # 构建产物
```

`places.json` 是唯一数据源，页面只是其渲染结果，因此清单与地图不会出现不一致。行程的存放位置由用户决定，首次使用时询问一次并记入偏好文件。

## 已知限制

- **地铁配色依赖 OSM 的 `colour` 标签**。冷门城市可能缺失，缺失时使用备用色板（避开已用颜色）
- **交通时长与票价为查询当日数据**。出行往往在数十天之后，时刻表与票价均可能变动，出发前应重新核实
- **以 `file://` 双击打开时无自动保存**，需手动点击保存按钮（浏览器不允许网页在无用户手势时写入文件）。推荐使用 `--serve`
- 攻略正文信息由 AI 联网核实后写入，**出发前仍建议抽查数条来源链接**

## 开发

改动 `skills/medium-roam/scripts/` 或 `assets/template-trip.html` 后，提交前必须跑全套三份测试并保持全绿。三者全程不联网，秒级完成。

```bash
python3 dev/test_enrich_images.py   # 图片候选管线
python3 dev/test_validate.py        # 数据契约校验器
python3 dev/test_server.py          # build.py --serve 本地保存服务

python3 skills/medium-roam/scripts/build.py <行程目录> --serve
```

`dev/` 为开发期内容（回归测试、能力探针），不参与安装，详见 [dev/README.md](dev/README.md)。

本机开发建议使用软链接，修改即时生效：

```bash
ln -s "$PWD/skills/medium-roam" ~/.claude/skills/medium-roam
```

## 许可

[MIT](LICENSE)。内联的 [SortableJS](https://github.com/SortableJS/Sortable) 1.15.7 同为 MIT，见 [`assets/vendor/README.md`](skills/medium-roam/assets/vendor/README.md)。

地图数据 © [OpenStreetMap](https://www.openstreetmap.org/copyright) 贡献者。
