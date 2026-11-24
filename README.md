# BidRadar

**面向广告出价算法工程师的研究与 AI 实践雷达。**

把分散的论文、工业实践和工具更新变成有重点、有出处、能验证的阅读队列。帮助你更快判断：**方法改了什么、实验支持什么结论、证据还缺什么、下一步值得试什么。**

[![Weekly AI Radar](https://github.com/KAMCHIU-LAB/bidradar/actions/workflows/weekly-radar.yml/badge.svg)](https://github.com/KAMCHIU-LAB/bidradar/actions/workflows/weekly-radar.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Research and AI practice radar for advertising bidding engineers. Tracks papers, industrial work, coding tools, and model updates with source links and evidence limits.

[看一份简报样例](examples/brief.md) · [快速开始](#快速开始) · [每周 AI 雷达](docs/weekly-radar.md) · [运行与排障](docs/operations.md)

## 两种使用方式

| | 研究简报 | 每周 AI 雷达 |
|---|---|---|
| 关注内容 | 出价、预算约束、CVR、延迟反馈、广告 Agent | 出价算法、AI 编程工具、模型与推理新进展 |
| 如何整理 | Codex 提炼与独立复审，按证据和工作相关性筛选 | 关键词规则初筛，保留日期、原文和采集状态 |
| 如何运行 | 手动生成；macOS 每15天自动处理 | GitHub Actions 每周一北京时间09:00云端运行 |
| 阅读结果 | 本地预览；配置后可发个人飞书群 | 飞书简报和可下载的 Markdown 制品 |
| 模型成本 | 需要已登录的 Codex，可用额度内运行 | 不调用模型，不消耗模型额度 |

简报关注研究证据；雷达关注持续发现。**两者都保留原始链接与判断边界，不把预印本、离线指标或厂商演示包装成已验证的线上效果。**

Python 3.11+ · Python标准库 · Codex CLI（仅研究简报需要）· 飞书可选

## 适合怎样的日常工作

| 你在关注什么 | 工具帮你整理什么 |
|---|---|
| 生成式出价与预算约束 | 方法改在哪里，实验是否保留预算、成本和比较条件 |
| CVR、延迟反馈与价值估计 | 上游预测方法怎样连接到出价问题，哪些收益不能直接外推 |
| 广告Agent与工程实践 | 工具调用、执行验收和故障处理有哪些可借鉴做法 |
| 多家公司发布的新资料 | 分别总结可核查发现，再给有依据的联合观察 |

内置主题聚焦广告出价。它是个人研究工作流，不追求收录所有 AI 新闻；目标是缩短发现到验证的距离，并留下可复查的依据。

## 先看输出

以下摘自公开资料简报样例。评分是编辑判断，效果为作者报告，未经独立复现。

> **重点阅读**
>
> **1. [出价冷启动探索](https://github.com/alimama-tech/ISGE)｜本期发现**<br>
> 重构误差衡量轨迹稀缺度。开源核心训练与集成脚本。默认含模拟器辅助诊断。<br>
> 借鉴稀缺轨迹补数与执行模式隔离。<br>
> 含金量7/10 · 相关性10/10
>
> **值得跟进**
>
> **2. [低活用户转化率补全](https://hub.baai.ac.cn/view/59630)｜观察·本期发现**<br>
> 语义群组迁移高活用户先验。节选称淘宝低活用户离线GAUC优于生产模型。社区署名未独立核验。<br>
> 借鉴出价价值预估的群体先验。<br>
> 含金量待评 · 相关性8/10

[完整样例](examples/brief.md)还包含本期看点、旧文补读和公司动态，可直接在GitHub阅读，无需配置或模型额度。样例展示格式与筛选判断，不作为推荐准确率的评测。

### 每期保留的信息

- **每篇最多100个可见字符**：方法、成果、必要条件、阅读用途和评分均计入；链接地址不计。
- **默认最多20篇，正文最多2,000字符**：资料不足时少发；超限时整篇减少，保留结论边界。
- **重点、观察和旧文分开**：跟进项最多2篇，旧文补读最多1篇；旧文保留原始月份。
- **阅读与依据分开**：正文方便阅读；候选取舍、分项评分、原文短引文和采集状态留在本机。

## 快速开始

### 1. 获取项目并初始化

需要Python 3.11+和curl。AI提炼与复审另需已登录、可用的Codex CLI，会消耗账号模型额度；无需安装第三方Python包。macOS是当前使用与调度平台，Windows不支持，Linux手动运行尚未验证。

```sh
git clone https://github.com/KAMCHIU-LAB/bidradar.git
cd bidradar
python3 --version
python3 bidradar.py init
```

若系统Python较旧，将命令中的 `python3` 换成已安装的 `python3.12` 等版本。配置生成在 `~/.config/bidradar/config.toml`，不会覆盖已有配置。

### 2. 先生成本地简报

检查私有配置中的 `[review].model`，改为账号实际可用的模型。**本地采集和预览无需填写飞书凭证。**

```sh
python3 bidradar.py collect       # 采集公开资料，不调用模型
python3 bidradar.py brief         # 提炼并独立复审，保存预览
python3 bidradar.py quality       # 查看篇幅、引用与复审检查，不调用模型
python3 bidradar.py digest        # 重新保存当前预览，不调用模型
```

预览在 `~/Library/Application Support/BidRadar/digests/`，依据在同级 `reviews/`。macOS访达按 `Shift + Command + G` 可粘贴目录。尚无通过复审的成稿时，只生成状态说明；`quality` 会提示缺少有效简报。

### 3. 接入个人飞书机器人（可选）

在私有配置的 `[feishu]` 中填写自定义机器人的Webhook和签名密钥，并启用机器人签名校验。配置权限须为600。

```sh
chmod 600 ~/.config/bidradar/config.toml
python3 bidradar.py notify-check      # 向机器人发送一次连接确认
python3 bidradar.py digest --send     # 发送已通过复审的简报
```

### 4. 配置本机研究简报的周期推送（macOS，可选）

```sh
python3 bidradar.py install-schedule
```

需先完成飞书连接确认。默认每天09:00检查周期，并缓存InfoQ、量子位的短RSS；**每15天集中采集、审阅、推送一次**。AI处理后送达，睡眠或断网可能延迟执行。电脑保持唤醒时可锁屏运行，程序不修改电源设置。

### 5. 运行每周 AI 雷达

公开仓库已配置 GitHub Actions，自动在每周一北京时间09:00采集并向飞书推送。云端发送需要仓库设置中的 `FEISHU_WEBHOOK_URL` 与 `FEISHU_SIGNING_SECRET` 两项 Actions Secrets。查看 [Weekly AI Radar 工作流](https://github.com/KAMCHIU-LAB/bidradar/actions/workflows/weekly-radar.yml) 可下载最近90天的报告。

想在本机立即生成一份，不用 Codex 或飞书配置：

```sh
python3 weekly_radar.py
```

完整来源范围、筛选方法与覆盖限制见[每周雷达说明](docs/weekly-radar.md)。

## 调整阅读节奏

编辑私有配置，完整字段见 [配置模板](config.example.toml)。

| 配置 | 默认值 | 作用 |
|---|---|---|
| `[brief].max_items` | `20` | 简报篇数上限，含重点、观察和旧文 |
| `[brief].max_chars_per_item` | `100` | 单篇可见字符上限，可设得更短 |
| `[brief].max_body_chars` | `2000` | 正文总长度上限 |
| `[schedule].interval_days` | `15` | 集中审阅与推送间隔 |
| `[schedule].hour` | `9` | 每日检查时间，采用本机时区 |
| `[review].lookback_days` | `15` | 手动窗口回溯天数，不得短于执行间隔 |
| `[review].daily_limit` | `6` | 每日及每自动周期的调用上限，两个计数分别累计 |

来源入口可在 `[[sources]]` 中增删。新增域名还需检查HTTPS主机白名单；出价主题与模型关注方向目前写在代码中。扩展其他研究领域需同步调整规则，参见 [实现说明](docs/engineering.md)。

## 如何筛选与核对

```mermaid
flowchart LR
    A[公开论文 / 文章 / 仓库] --> B[时间核验与去重]
    B --> C[主题筛选与有界节选]
    C --> D[模型生成短报]
    D --> E[结构与逐字引文检查]
    E --> F[独立上下文复审]
    F --> G[本地预览 / 飞书]
```

数字保留指标、线上/离线与必要比较条件；成本上涨不能直接写成ROI提升。关键词命中不能证明公司归属，转载也不算第二项独立研究。

含金量由技术增量0–3、证据0–4、工业意义0–3组成；相关性由出价业务0–5、技术连接0–3、可迁移性0–2组成。主推双项均须达到7分，缺证据可标“待评”。评分尚未经过系统人工标定。

复审绑定具体成稿及渲染内容。自动流程最多修订一次并重新复审，未通过则保留状态。预算与失败记录持久化，重启不刷新；投递结果不确定时停止自动重发，先核对群记录。

## 来源与使用边界

配置包含arXiv、团队技术博客、精选GitHub仓库、智源社区、InfoQ和量子位等入口。社区署名不等于官方认证，RSS与精选仓库不能覆盖公司全部发布内容。

当前读取摘要、README、订阅文本和可取得的文章节选。尚未实现PDF全文解析、完整语义去重、论文自动复现或全渠道覆盖，也没有量化推荐准确率与漏报率。关键研究仍需打开原文核验。

## 数据与隐私

私有配置、数据库、阅读标签、备注和日志留在用户目录；模型仅接收筛选后的公开资料、公开投递历史摘要和阅读标签。**个人备注不进入模型输入或飞书正文**。CLI在独立临时目录处理输入，限制工具使用并拒绝异常工具事件；模型仍可能误判原文。

仓库不包含飞书凭证、运行数据库、私人阅读记录或公司内部材料。不要将这些内容作为Issue、样例或提交附件上传。

## 项目导航

| 入口 | 内容 |
|---|---|
| [公开简报样例](examples/brief.md) | 先判断输出是否适合自己的工作 |
| [运行说明](docs/operations.md) | 命令、预算、来源故障、投递恢复与调度 |
| [实现与取舍](docs/engineering.md) | 模块职责、证据检查、持久化与当前限制 |
| [贡献指南](CONTRIBUTING.md) | 补充来源、规则和脱敏反馈 |
| [配置模板](config.example.toml) | 来源与运行参数 |
| [离线检查](tests/) | 使用虚构资料与隔离数据库的现有检查代码 |

## License

项目代码使用 [MIT License](LICENSE)。链接到的论文、文章与第三方仓库保留各自权利；项目许可证不覆盖它们。
