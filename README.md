# seat-monitor-open

教习所预约系统的空位监控。由 cron-job.org 每 15 分钟触发 GitHub Actions，单次运行内每 2 分钟刷新一次（共 8 次检查，约 14 分钟）。

## Secrets
`BASE` / `USER_ID` / `PASSWORD` / `BARK_KEY_1`（管理员，接收错误通知）/ `BARK_KEY_2`

## 触发
cron-job.org 对下面的地址发 POST（Header: `Authorization: Bearer <fine-grained token>`，token 仅授予本仓库 Actions: write），body `{"ref":"main"}`：

`https://api.github.com/repos/song4wk/seat-monitor-open/actions/workflows/watch.yaml/dispatches`

## 行为
- `concurrency: seat-watch`：上一轮未结束时新触发排队，不并行。
- 新出现的空位发 critical 通知；持续存在的空位每 30 分钟降级提醒一次（状态通过 `actions/cache` 在运行间保存）。
- 登录失败 / 页面异常 / 连续刷新失败时通知管理员，且 Actions 显示为失败。
- 每次运行的结果在 Actions 运行页的 Summary 查看（检查次数、空位数、通知次数、错误原因，不含具体空位）；有新空位或出错时还有 notice / error 注解。
- 日志中不输出异常原文（避免泄漏 secret URL）。

## 测试
```
pip install -r requirements.txt pytest
pytest
```

## 状态页部署
在仓库 Settings → Pages → Source 选择 **GitHub Actions**。工作流保存历史记录到
`status` 分支，并通过 Pages artifact 显式部署；不再使用分支自动发布。
运行记录存放在 runner 临时目录，仅 `notified.json` 用于跨运行缓存。
缓存中含空位标识（不含凭据），公开仓库缓存不能作为私密存储。

通知按接收人独立去重，只有 Bark API 确认成功后才累计通知次数。
摘要的通知数为成功发送的「空位 × 接收人」次数。失败会在下一次检查重试，
本轮有发送失败时标记异常。状态页分别展示运行结束时间与最后成功检查时间，
未检查显示为「未检查」。只读刷新对 502/503/504 最多重试两次，登录 POST 不重放。

`status` 分支每次都被一个只含最新状态的单提交覆盖，不会累积历史。
状态页超过 40 分钟没有新记录会显示红色「数据已过期」提示（cron-job.org 停止触发、某轮超时等）。
PR 和 main 的推送会自动运行 `tests.yaml`（pytest，Python 3.9 / 3.12）。
