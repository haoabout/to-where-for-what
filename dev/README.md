# dev/ — 开发期验证工具

这里放的是**验证浏览器能力边界**的探测页，不属于 skill 本体，`npx skills add` 不会安装它们。

## capability-probe.html

探测 File System Access API 与相关能力在当前浏览器/协议下的真实可用性。

```bash
# file:// 方式
open dev/capability-probe.html

# http:// 方式（对比用）
python3 -m http.server 8901 --directory dev
# 然后访问 http://localhost:8901/capability-probe.html
```

### 已验证结论（2026-07-31，Chromium）

计划阶段曾根据 [MDN](https://developer.mozilla.org/en-US/docs/Web/API/Window/showSaveFilePicker)
和 Chrome 文档的「secure context (HTTPS)」表述，假设 `file://` 下
`showSaveFilePicker` 不可用。**实测推翻了这个假设：**

| | `file://` | `http://localhost` |
|---|---|---|
| `isSecureContext` | `true` | `true` |
| `showSaveFilePicker` | `function` | `function` |
| 实际调用 | 唤起原生保存对话框 | 唤起原生保存对话框 |

两种协议表现完全一致，均未抛 `SecurityError`。

**真正的能力分界是浏览器引擎，不是协议**（数据源：[MDN BCD](https://github.com/mdn/browser-compat-data)）：

| Chrome 86+ | Edge | Opera | Firefox | Safari 桌面 |
|---|---|---|---|---|
| ✅ | ✅ | ✅ | ❌ | ❌ |

因此 skill 里的保存能力检测**必须用特性检测**：

```js
const canWriteBack = typeof window.showSaveFilePicker === 'function';
```

不能用 `location.protocol === 'http:'` 判断——那会让 Chrome 用户在
双击打开文件时白白损失直写能力，也不会挡住真正需要降级的 Firefox/Safari 用户。

协议只影响**另一件事**：`file://` 不发 `Referer`，因此 OSM 官方瓦片不可用
（详见 `skills/travel-planner/references/` 中的地图章节）。这两个维度要分开判断。
