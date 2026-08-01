# places.json 数据契约

这是整个 skill 的核心。**AI 的全部产出都收敛到这个文件**，三个视图都从它渲染，用户的选择也写回它。

**硬规则：不要发明字段。** 需要新字段时先改本文件和 `scripts/validate.py`，再使用。

---

## 顶层结构

```jsonc
{
  "schema_version": 1,
  "trip":       { ... },   // 本次行程参数
  "categories": [ ... ],   // 分类定义 + 配额
  "places":     [ ... ]    // 景点数组
}
```

---

## `trip`

| 字段 | 类型 | 必填 | 说明 |
|---|---|:--:|---|
| `destination` | string | ✅ | 目的地，用户语言 |
| `destination_local` | string | | 当地语言名，与用户语言相同时可省 |
| `destination_en` | string | | 英文名，导出用 |
| `country` | string | ✅ | ISO 3166-1 alpha-2，如 `JP` |
| `bbox` | `[minLon,minLat,maxLon,maxLat]` | ✅ | 目的地包围盒，**用于坐标越界校验** |
| `timezone` | string | ✅ | IANA 时区，如 `Asia/Tokyo` |
| `output_language` | string | ✅ | BCP-47，如 `zh-CN` / `en`。决定正文语言 |
| `local_language` | string | ✅ | 当地语言。与 `output_language` 不同时才需要 `name_local` |
| `dates` | `{start,end}` | | `YYYY-MM-DD`。未定日期时省略，天气与限时活动模块会降级 |
| `days` | int | ✅ | 天数 |
| `party` | string | ✅ | 同行人，如「情侣 2 人」 |
| `pace` | string | ✅ | 体力强度，如「中等，日均步行 12km 可接受」 |
| `bases` | array | | 落脚点 `[{name, coord, nights}]` |
| `generated_at` | string | ✅ | `YYYY-MM-DD`，数据生成日 |
| `verified_at` | string | ✅ | `YYYY-MM-DD`，最后联网核验日。**与今日相差 >30 天时页面显示过期提醒** |

---

## `categories`

分类配额制。小城市达不到 `min` 时**不许凑数硬编**，如实说明即可（校验只给 P1 警告）。

```jsonc
{ "id": "museum", "label": "博物馆·美术馆", "min": 3, "max": 8 }
```

默认配额见 `research-playbook.md`。

---

## `places[]`

### 身份与分类

| 字段 | 类型 | 必填 | 说明 |
|---|---|:--:|---|
| `id` | string | ✅ | 全局唯一，建议 `<城市缩写>-<三位序号>`，如 `os-018` |
| `name` | string | ✅ | **用户语言**名称 |
| `name_local` | string | 条件 | 当地语言名称，**必须能在地图里搜到**。`local_language ≠ output_language` 时必填 |
| `name_en` | string | | 英文名。导出 Google My Maps 时比用户语言可靠 |
| `category` | string | ✅ | 必须是 `categories[].id` 之一 |
| `tier` | `S`\|`A`\|`B`\|`C` | ✅ | 推荐分级。S=必去，C=顺路才去 |
| `scale` | enum | ✅ | 游玩尺度，见下 |
| `parent_id` | string | | 微景点可指向同区域主景点，清单里会折叠在它下面。**同片区没有合适主景点时留空即可**——强行指定会造出假的从属关系（实测：渡船口、街边小神社都属这类） |
| `area` | string | ✅ | 所属片区，如「中之岛」。**D 阶段按此聚类排路线**，务必前后一致 |

`scale` 取值：`spot`（5–15 分钟打卡点）、`30min`、`1-2h`、`2-3h`、`half-day`、`full-day`

### 位置

```jsonc
"coord": { "lon": 135.4959, "lat": 34.6937 }
```

**必须用对象，不许用数组。** 数组形式在 GeoJSON/MapLibre 是 `[lon,lat]`、在 Leaflet 是 `[lat,lng]`，一旦写反，大阪会跑到印度洋里，而且看起来完全正常。用具名键彻底消灭这类 bug。

### 开放信息（**A 阶段首轮就必须联网拿到**）

不拿到这些，用户筛选就是白工——选了半天最后发现不开门。

| 字段 | 类型 | 必填 | 说明 |
|---|---|:--:|---|
| `hours` | string | ✅ | 如 `10:00-17:00`；全天开放写「全天」 |
| `last_entry` | string | | 最后入场时间。**行程当日最后一个景点必须填** |
| `closed_days` | `int[]` | ✅ | ISO 周几，1=周一…7=周日。全年无休填 `[]`。**结构化字段，供冲突校验用** |
| `closed` | string | ✅ | 闭馆说明全文，如「周一；换展期间闭馆；年末年始」。无则填「无」 |
| `ticket` | string | ✅ | 如 `¥1300（特别展 ¥1500）`；免费写「免费」 |
| `booking` | enum | ✅ | `required` 必须预约才能进 / `recommended` 可现场但建议预约 / `none` |
| `booking_url` | string | 条件 | `booking ≠ none` 时应填（缺失为 P2） |
| `status` | enum | ✅ | `open` / `renovating` / `seasonal_closed` / `permanently_closed` |
| `status_note` | string | 条件 | `status ≠ open` 时必填，说明起止时间 |
| `duration_min` | int | ✅ | 建议游玩分钟数，D 阶段排时间轴用 |

> **`status` 不许猜。** 未经联网确认，一律不许填 `open`。这是防「到了发现在修缮」的唯一闸门。

### 路线编排燃料

缺了这三个字段，D 阶段的路线只能靠 AI 现编。

| 字段 | 类型 | 必填 | 说明 |
|---|---|:--:|---|
| `indoor` | bool | ✅ | 是否室内。**雨天备选池**从这里取 |
| `night` | bool | ✅ | 是否适合夜间/有夜景价值。晚上时段只排 `true` 的 |
| `area` | string | ✅ | （见上）同一天尽量只走 1–2 个 area |

### 内容

| 字段 | 类型 | 必填 | 说明 |
|---|---|:--:|---|
| `pitch` | string | ✅ | 一句话亮点，清单卡片上显示 |
| `detail` | string | ✅ | 两三段介绍，详情弹窗显示 |
| `photo_index` | int 1–5 | ✅ | 出片指数 |
| `photo_note` | string | | 画面描述与拍摄建议，如「庭园竹径，上午顺光最好」（缺失为 P2） |
| `tags` | string[] | | 如 `["冷门","影视打卡","室内避雨"]` |
| `media` | object | | 影视动漫打卡专用：`{title, title_local, scene}` |
| `museum` | object | | 博物馆深度模块，结构见 `museum-module.md` |

### 图片与来源

```jsonc
"images": [
  { "url": "https://…", "credit": "© 大阪市", "source_url": "https://…" }
],
"sources": [
  { "title": "官网 · 开放时间", "url": "https://…" }
]
```

- `sources` **必须非空**，且每条 `url` 必须是 `http(s)`。这是防幻觉的主闸门——**没有来源的景点一律 P0 拒绝**。
- `images` 可选。每张必须带 `credit`。页面用 `onerror` 自动隐藏失效图，`validate.py --check-links` 会把死链标出来。

### 用户选择（页面写回，AI 不要预填）

| 字段 | 类型 | 说明 |
|---|---|---|
| `choice` | `null`\|`yes`\|`maybe`\|`no` | AI 生成时一律 `null` |
| `choice_reason` | string | 用户选「不想去」时的理由 |

---

## 完整示例

```jsonc
{
  "id": "os-018",
  "name": "中之岛美术馆",
  "name_local": "大阪中之島美術館",
  "name_en": "Nakanoshima Museum of Art, Osaka",
  "category": "museum",
  "tier": "A",
  "scale": "2-3h",
  "area": "中之岛",
  "coord": { "lon": 135.4914, "lat": 34.6914 },

  "hours": "10:00-18:00",
  "last_entry": "17:30",
  "closed_days": [1],
  "closed": "周一（逢假日则次日休）；换展期间闭馆",
  "ticket": "常设 ¥1200，特别展另计",
  "booking": "recommended",
  "booking_url": "https://nakka-art.jp/",
  "status": "open",
  "duration_min": 120,

  "indoor": true,
  "night": false,

  "pitch": "黑立方体外观，藏品以大阪近代美术与佐伯祐三为核心。",
  "detail": "2022 年开馆…（两三段）",
  "photo_index": 4,
  "photo_note": "五层挑空的红色扶梯是最出片的机位，逆光时段避开正午。",
  "tags": ["建筑", "室内避雨"],

  "images": [
    { "url": "https://…/nakka.jpg", "credit": "© Nakanoshima Museum", "source_url": "https://nakka-art.jp/" }
  ],
  "sources": [
    { "title": "官网 · 开馆时间与门票", "url": "https://nakka-art.jp/" }
  ],

  "choice": null,
  "choice_reason": ""
}
```

---

## 校验分级

`scripts/validate.py` 按三级拦截，**P0 存在时退出码为 1**。

### P0 · 拒绝

- 缺必填字段，或必填字符串为空
- `id` 重复
- 枚举值非法（`tier` / `scale` / `status` / `booking` / `choice`）
- `category` 不在 `categories` 里
- `coord` 缺失、非数字、超出经纬度范围，或**落在 `trip.bbox` 之外**
- `sources` 为空，或含非 `http(s)` 的 URL
- `status ≠ open` 却没有 `status_note`
- **闭馆日覆盖整个行程**——`closed_days` 与行程每一天都撞上，即这个景点你去不了
- `parent_id` 指向不存在的 id

### P1 · 警告

- `--check-links` 时发现死链（`sources` / `images` / `booking_url`）
- 分类数量低于 `min` 或高于 `max`
- `local_language ≠ output_language` 却缺 `name_local`
- 两个景点坐标几乎重合（<25 米），疑似重复录入
- `verified_at` 距今超过 30 天
- 行程当日最后一个景点缺 `last_entry`（需 route.md 才能判断，D 阶段再查）

### P2 · 提示

- 缺 `photo_note`
- `booking ≠ none` 却缺 `booking_url`
- 缺 `images`
- `detail` 短于 60 字
