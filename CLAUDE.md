旅行规划 skill 仓库:skill 本体在 `skills/medium-roam/`,`dev/` 是仓库层的回归测试(不随 skill 分发)。

## 验收标准

改动 `skills/medium-roam/scripts/` 或 `assets/template-trip.html` 后,提交前必须跑全套 dev/ 测试并保持全绿:

```bash
python3 dev/test_enrich_images.py   # 图片候选管线,全程无网络
python3 dev/test_validate.py        # 数据契约校验器
python3 dev/test_server.py          # build.py --serve 本地保存服务
```

断言失败要先甄别:是回归就修 scripts/,是契约被有意改掉就更新断言并在 commit 里写明依据。详见 `dev/README.md`。
