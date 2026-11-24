# 每周跟进 AI：出价研究 + 开发提效 + 模型进展

`weekly_radar.py` 是独立的每周阅读队列入口。不读取私有配置、调用模型或发送飞书消息。需要 Python 3.11+ 与 curl，无第三方依赖。

## GitHub 云端定时运行（推荐）

仓库公开时，GitHub 标准 hosted runner 执行 Actions 工作流免费；工作流位于 `.github/workflows/weekly-radar.yml`。每周一北京时间09:00运行，可在仓库的 **Actions → Weekly AI Radar** 查看状态并下载 `ai-weekly-radar-*` 报告制品。制品保留90天。首次部署后可在该页面通过 **Run workflow** 手动触发一次。

工作流会把周报发到飞书，并把 Markdown 报告保存为可下载制品；报告不会提交到仓库。需在仓库 Settings → Secrets and variables → Actions 添加 `FEISHU_WEBHOOK_URL` 和 `FEISHU_SIGNING_SECRET` 两个 Actions Secrets，值取自个人飞书自定义机器人配置。Secrets 只注入发送步骤，不写进代码或日志。下载制品需要登录并拥有仓库读取权限。定时事件可能在 GitHub 高负载时延迟；公开仓库如果60天没有活动，GitHub 会自动禁用定时工作流。周报作为制品保留90天。

云端任务开始工作后，若不希望本机重复运行，在 Mac 项目目录运行：

```sh
python3.12 weekly_radar.py --remove-schedule
```

下面的 launchd 安装方式保留给想完全本机运行的情况。

## 使用

本机可用解释器为 `/opt/homebrew/opt/python@3.12/bin/python3.12`。以下命令在项目目录执行：

```sh
/opt/homebrew/opt/python@3.12/bin/python3.12 weekly_radar.py
/opt/homebrew/opt/python@3.12/bin/python3.12 weekly_radar.py --install-schedule
/opt/homebrew/opt/python@3.12/bin/python3.12 weekly_radar.py --remove-schedule
```

报告默认保存到 `~/Documents/总结性文稿/AI每周雷达/`，每次生成新文件，不覆盖历史。最近报告路径与采集明细在 `~/Library/Application Support/BidRadar/weekly/latest.json`，定时日志在同目录 `schedule.log`。

安装后每周一09:00按 Mac 本机时区运行。睡眠时可能延至唤醒，关机、退出登录、断网会影响运行；不会在聊天中主动推送。临时网络错误最多重试一次，仍失败的来源写入报告并返回非零退出码，无额外后台重试。已有的15天研究/飞书任务不受影响。

## 值得跟什么

| 线索 | 每周重点 | 一手入口 |
|---|---|---|
| 业务算法 | 自动出价、预算pacing、价值预估与延迟反馈、离线评估、因果与bandit、生成式推荐 | arXiv作者摘要；美团、Google Research、Meta官方工程/研究博客 |
| 开发与实验 | Coding Agent、调试与评测、工具调用、推理部署 | Claude Code、Codex、vLLM官方Releases；Hugging Face官方博客 |
| 新方法 | 推理、后训练、蒸馏、多模态；关注能迁移到工程的问题 | OpenAI官方动态、Google Research；人工补读Anthropic工程与研究页 |

自动采集地址列在脚本顶部 `SOURCES`，主题正则列在 `TOPICS`。可删掉不用的工具，再添加你实际使用的项目官方RSS/Atom地址；脚本不执行来源里的代码。

手动补读：[Anthropic Engineering](https://www.anthropic.com/engineering)、[Anthropic Research](https://www.anthropic.com/research)、[阿里妈妈公开研究](https://github.com/alimama-tech)。没有可靠订阅入口时，人工检查比假装自动覆盖更稳妥。

## 用漏斗筛选，别把阅读变成第二份工作

建议每周约90分钟：15分钟扫队列，15分钟筛到最多3篇，30分钟精读1篇，30分钟做一个小验证。复杂复现另开任务。

先问“与我的哪个问题有关”，再问“相对现有方案有什么增量”。用下面四项各0–2分做个人判断：业务相关、技术增量、证据充分、试用成本可控。6分以上精读，4–5分收藏，低于4分略过。这是建议的人工标尺，脚本仅关键词初筛，没有自动完成这些判断。

- **算法证据**：有无真实预算/成本约束？离线还是线上？baseline是否公平？收益能否同时保住CPA/ROAS、消耗与稳定性？预印本、模拟器结果、线上A/B不能混为一谈。
- **工具证据**：拿同一真实小任务对照，记录耗时、正确率、人工修正次数、费用；演示视频和厂商benchmark只是试用线索。
- **一手核验**：打开作者论文、官方仓库或版本说明。转载、热榜、公众号可做发现入口，不能替代原始证据。
- **留下一点积累**：每周只记录“本周1个结论、1个实验、1个暂不采用的理由”，一个月后看哪些真改善了工作。

精读时可把原文或摘要连同以下提示词交给你使用的模型：

> 我是广告出价算法工程师。请仅基于提供的材料，解释：解决的问题、相对baseline的改进、实验指标和比较条件、证据局限、与预算/CPA/ROAS或日常开发的关系，以及一个60分钟内可做的验证。区分原文事实和迁移推断。未提供的数据写“未知”，不要把摘要包装成全文结论。

## 覆盖边界

只收过去7天原始发布的内容；Atom没有published时用updated，版本说明因此可能以更新时间计。arXiv按submittedDate查询，最多100篇，达上限会标记。RSS与GitHub Atom均只保留有限条目，高频源可能漏掉周内早期内容。没有跨来源语义去重，只有URL去重；每来源每栏目最多2篇，最多12条，不凑数。未抓PDF全文、未实测工具、没有声称覆盖所有公司或所有模型。

验证：`python3.12 -m unittest discover -s tests -p 'test_weekly_radar.py'`。日期窗口、版本规范化、失败标记、去重、来源上限与预发布过滤有离线检查；真实来源仍需联网试跑。
