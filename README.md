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
- 日志中不输出异常原文（避免泄漏 secret URL）。

## 测试
```
pip install -r requirements.txt pytest
pytest
```
