# vendor/

第三方代码，原样存放、不做修改，由 `build.py` 内联进 `trip.html`。

## sortable.min.js

| | |
|---|---|
| 库 | [SortableJS](https://github.com/SortableJS/Sortable) 1.15.7 |
| 许可 | MIT |
| 依赖 | 无 |
| 大小 | 44.4 KB（gzip 后约 15 KB） |

**为什么内联而不是走 CDN**：MapLibre 挂了有三级降级链，而且地图本来就要联网；
排序不需要网 —— 因为 unpkg 挂掉就排不了序，是自己给自己找的故障点。
用户可能几个月后才重新打开这个文件。

**为什么用库而不是自己写**：`fallbackTolerance`（区分点击与拖拽）、
`scrollSensitivity`（容器边缘自动滚动）、`pull:'clone'`（池子里拖走后原卡留下）
正好覆盖自己写最难的几块，其中 clone 语义与「清单栏不移除、只标灰」完全对应。

**更新方式**：

```bash
curl -sL -o sortable.min.js https://unpkg.com/sortablejs@<版本>/Sortable.min.js
```

更新后要跑一遍 `dev/` 下的端到端，重点看跨容器拖拽与容器内排序。
