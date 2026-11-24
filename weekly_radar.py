#!/usr/bin/env python3
"""Weekly first-party AI reading queue; stdlib + BidRadar's system-proxy HTTP client.

Independent of private config, model calls, database, and Feishu delivery.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

from bidradar import curl_request, plain, stamp

ROOT = Path(__file__).resolve().parent
OUTPUT = Path.home() / 'Documents/总结性文稿/AI每周雷达'
STATE = Path.home() / 'Library/Application Support/BidRadar/weekly'
LABEL = 'local.bidradar.ai-weekly'
SOURCES = [
    ('arxiv-bidding', 'arXiv 出价与决策', 'algorithm', '', '预印本摘要；未独立复现'),
    ('meituan', '美团技术团队', 'research', 'https://tech.meituan.com/rss.xml', '官方工程博客；作者自述'),
    ('google', 'Google Research', 'research', 'https://research.google/blog/rss/', '官方研究博客；作者自述'),
    ('meta', 'Meta Engineering', 'research', 'https://engineering.fb.com/feed/', '官方工程博客；作者自述'),
    ('huggingface', 'Hugging Face 官方博客', 'research', 'https://huggingface.co/blog/feed.xml', '平台官方博客；贡献者文章需核对署名'),
    ('openai', 'OpenAI 官方动态', 'research', 'https://openai.com/news/rss.xml', '官方研究/产品公告；厂商自述'),
    ('claude-code', 'Claude Code Releases', 'tools', 'https://github.com/anthropics/claude-code/releases.atom', '官方版本说明；未验证实际提效'),
    ('codex', 'Codex Releases', 'tools', 'https://github.com/openai/codex/releases.atom', '官方版本说明；未验证实际提效'),
    ('vllm', 'vLLM Releases', 'tools', 'https://github.com/vllm-project/vllm/releases.atom', '官方版本说明；未验证性能'),
]
TOPICS = [
    ('出价/预算约束', r'\b(?:auto[- ]?bidding|bidding|budget pacing|bid optimization)\b|出价|竞价|预算控制'),
    ('价值预估/延迟反馈', r'\b(?:conversion rate|conversion value|delayed feedback|calibration|cvr|roas)\b|转化率|延迟反馈|校准'),
    ('因果/离线决策', r'\b(?:off[- ]policy|offline reinforcement|counterfactual|causal inference|contextual bandit)\b|反事实|因果推断|离线强化'),
    ('推荐与生成式建模', r'\b(?:recommendation|recommender|generative retrieval)\b|推荐系统|生成式推荐'),
    ('开发与实验提效', r'\b(?:agent|agents|coding|code review|evaluation|evals|inference|vllm|mcp|tool use|debugging)\b|智能体|代码生成|推理加速|评测'),
    ('模型方法与新进展', r'\b(?:llm|language model|reasoning|post[- ]training|distillation|multimodal|fine[- ]tuning)\b|大模型|后训练|蒸馏|多模态'),
]
LANES = [('algorithm', '与你的出价工作相关', 5), ('tools', '开发、实验与推理工具', 4), ('frontier', '模型新进展', 3)]


def parse_feed(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('feed_doctype_rejected')
    root = ET.fromstring(raw)
    ns = '{http://www.w3.org/2005/Atom}'
    if root.tag == ns + 'feed':
        rows = []
        for item in root.findall(ns + 'entry'):
            url = next((x.get('href', '') for x in item.findall(ns + 'link')
                        if x.get('rel', 'alternate') == 'alternate'), item.findtext(ns + 'id', ''))
            if 'arxiv.org/api/errors' in item.findtext(ns + 'id', ''):
                raise ValueError('arxiv_query_error')
            rows.append((item.findtext(ns + 'title', ''), url,
                         item.findtext(ns + 'published', '') or item.findtext(ns + 'updated', ''),
                         item.findtext(ns + 'summary', '') or item.findtext(ns + 'content', '')))
    elif root.tag == 'rss' and root.find('channel') is not None:
        rows = [(x.findtext('title', ''), x.findtext('link', ''),
                 x.findtext('pubDate', '') or x.findtext('{http://purl.org/dc/elements/1.1/}date', ''),
                 x.findtext('description', '') or x.findtext('{http://purl.org/rss/1.0/modules/content/}encoded', ''))
                for x in root.findall('./channel/item')]
    else:
        raise ValueError('unsupported_feed_format')
    result = []
    for title, url, date, text in rows:
        if not date:
            match = re.match(r'https://tech\.meituan\.com/(\d{4})/(\d{2})/(\d{2})/', url)
            if match:
                date = '-'.join(match.groups()) + 'T00:00:00+08:00'
        url = re.sub(r'^http://arxiv.org/', 'https://arxiv.org/', url)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            continue
        if parsed.hostname == 'arxiv.org':
            url = re.sub(r'v\d+$', '', url)
        result.append(dict(title=plain(title), url=url, date=stamp(date) if date else '', text=plain(text)))
    return result


def classify(item, source_lane):
    text = item['title'] + ' ' + item['text'][:6000]
    hits = [name for name, pattern in TOPICS if re.search(pattern, text, re.I)]
    if source_lane == 'tools':
        if re.search(r'alpha|beta|preview|nightly|\brc\d*\b', item['title'], re.I):
            return None
        return 'tools', hits or ['开发与实验提效'], 3
    if not hits:
        return None
    if any(name in hits for name, _ in TOPICS[:4]):
        return 'algorithm', hits, 10 if TOPICS[0][0] in hits else 6
    return ('tools' if TOPICS[4][0] in hits else 'frontier'), hits, 2


def source_url(source, start, end):
    if source[0] != 'arxiv-bidding':
        return source[3]
    terms = '(ti:autobidding OR ti:"auto-bidding" OR (ti:bidding AND abs:advertising) OR ti:"budget pacing" OR (ti:"delayed feedback" AND abs:advertising) OR (ti:"off-policy evaluation" AND abs:recommendation))'
    query = terms + ' AND submittedDate:[' + start.strftime('%Y%m%d%H%M') + ' TO ' + end.strftime('%Y%m%d%H%M') + ']'
    return 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode(dict(
        search_query=query, start=0, max_results=100, sortBy='submittedDate', sortOrder='descending'))


def collect(source, start, end):
    try:
        url = source_url(source, start, end)
        for attempt in range(2):
            try:
                code, _, raw = curl_request(url)
                break
            except Exception as exc:
                if attempt or str(exc) not in {'curl_exit_6', 'curl_exit_7', 'curl_exit_28', 'curl_exit_35', 'curl_exit_56'}:
                    raise
                time.sleep(3.1)
        if code != 200:
            raise ValueError('http_' + str(code))
        rows = parse_feed(raw)
        kept, undated = [], 0
        for row in rows:
            if not row['date']:
                undated += 1
                continue
            if not start <= dt.datetime.fromisoformat(row['date']) <= end:
                continue
            decision = classify(row, source[2])
            if decision:
                lane, hits, score = decision
                row.update(source=source[1], source_id=source[0], evidence=source[4],
                           lane=lane, hits=hits, score=score)
                kept.append(row)
        note = '成功：读取 {}，窗口内相关 {}，缺日期 {}（跳过）'.format(len(rows), len(kept), undated)
        if source[0] == 'arxiv-bidding' and len(rows) >= 100:
            note += '；达到100条上限，可能漏采'
        return kept, dict(source=source[1], ok=True, note=note)
    except Exception as exc:
        # No secret-bearing URL or process environment in logs.
        return [], dict(source=source[1], ok=False, note='失败：' + type(exc).__name__ + ' ' + str(exc)[:120])


def select(rows):
    selected, seen, counts = [], set(), {}
    for lane, _, limit in LANES:
        candidates = sorted((r for r in rows if r['lane'] == lane), key=lambda r: (r['score'], r['date']), reverse=True)
        chosen = 0
        for row in candidates:
            key = (lane, row['source_id'])
            if row['url'] in seen or counts.get(key, 0) >= 2:
                continue
            selected.append(row)
            seen.add(row['url'])
            counts[key] = counts.get(key, 0) + 1
            chosen += 1
            if chosen == limit:
                break
    return selected


def markdown(rows, statuses, start, end):
    lines = ['# 出价工程师的 AI 每周雷达', '',
             '时间窗口（UTC）：{} 至 {}。'.format(start.isoformat(timespec='minutes'), end.isoformat(timespec='minutes')), '',
             '这是规则初筛的阅读队列，最多12条；不是AI精读结论，也不代表行业完整覆盖。优先原始发布日期；Atom缺少published时用updated，版本说明可能因此按更新时间计。', '',
             '每周建议：15分钟扫标题 → 15分钟选到3篇 → 30分钟精读1篇 → 30分钟做1个小验证。', '']
    for lane, title, _ in LANES:
        lines += ['## ' + title, '']
        items = [r for r in rows if r['lane'] == lane]
        if not items:
            lines += ['本期未筛到条目；不等于该方向没有新进展，请结合采集状态判断。', '']
        for r in items:
            title_safe = r['title'].replace('[', '［').replace(']', '］')
            lines += ['- [{}]({})'.format(title_safe, r['url']),
                      '  - 发布：{}；来源：{}。'.format(r['date'][:10], r['source']),
                      '  - 入选原因（关键词）：{}。'.format('、'.join(r['hits'])),
                      '  - 证据边界：{}。'.format(r['evidence'])]
            if r['text']:
                excerpt = r['text'][:260].replace('\n', ' ')
                lines += ['  - 原文节选（非总结）：' + excerpt + ('…' if len(r['text']) > 260 else '')]
        lines.append('')
    lines += ['## 本周怎么落地', '',
              '- 算法：核对约束、数据、基线、离线/线上指标；出价收益需同时看预算消耗、CPA/ROAS与稳定性。',
              '- 工具：在同一个真实小任务上对照，记录用时、正确率、人工修正次数和费用，再决定是否纳入工作流。',
              '- 精读提问：解决什么问题？比现有方法改了什么？证据到哪一步？什么条件下能迁移到我的系统？', '',
              '## 来源与覆盖状态', '',
              'RSS和版本订阅只保留有限历史；某些高频来源可能在一周内挤掉旧条目。arXiv限100条；每来源每栏目最多2条。规则会漏报或误收，未读PDF、未执行仓库代码、未核验性能。', '']
    lines += ['- {}：{}'.format(s['source'], s['note']) for s in statuses]
    return '\n'.join(lines) + '\n'


def send_feishu(report, webhook, secret):
    """Send the generated public-source digest without exposing webhook details."""
    parsed = urllib.parse.urlsplit(webhook)
    if parsed.scheme != 'https' or parsed.hostname != 'open.feishu.cn' or not parsed.path.startswith('/open-apis/bot/v2/hook/'):
        raise ValueError('invalid_feishu_webhook')
    timestamp = str(int(dt.datetime.now(dt.timezone.utc).timestamp()))
    signature = base64.b64encode(hmac.new((timestamp + '\n' + secret).encode(), b'', hashlib.sha256).digest()).decode()
    text = report.read_text(encoding='utf-8')
    if len(text) > 18000:
        text = text[:17980] + '\n\n（消息过长，完整报告请下载 GitHub Actions 制品。）'
    code, _, raw = curl_request(webhook, headers={'Content-Type': 'application/json'},
                                body={'msg_type': 'text', 'content': {'text': text},
                                      'timestamp': timestamp, 'sign': signature})
    if code != 200:
        raise ValueError('feishu_http_' + str(code))
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('feishu_invalid_response') from None
    if response.get('code') != 0:
        raise ValueError('feishu_api_error_' + str(response.get('code', 'unknown')))
    print('飞书周报已发送。', flush=True)


def run(output):
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=7)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda s: collect(s, start, end), SOURCES))
    rows = select([r for batch, _ in results for r in batch])
    statuses = [s for _, s in results]
    output.mkdir(parents=True, exist_ok=True)
    name = 'AI每周雷达-' + end.astimezone().strftime('%Y-%m-%d-%H%M%S-%f')
    report = output / (name + '.md')
    report.write_text(markdown(rows, statuses, start, end), encoding='utf-8')
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / 'latest.json').write_text(json.dumps(dict(report=str(report), sources=statuses,
        selected=rows, generated_at=end.isoformat()), ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(report), flush=True)
    print('来源成功 {}/{}；入选 {} 条'.format(sum(s['ok'] for s in statuses), len(statuses), len(rows)), flush=True)
    return 0 if all(s['ok'] for s in statuses) else 1


def schedule(remove=False):
    if sys.platform != 'darwin':
        raise SystemExit('定时安装仅支持 macOS')
    path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    domain = 'gui/' + str(os.getuid())
    if remove:
        subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
        path.unlink(missing_ok=True)
        print('已移除每周任务；保留报告。')
        return
    if path.exists():
        raise SystemExit('任务配置已存在；请先用 --remove-schedule 移除再安装。')
    STATE.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(Label=LABEL, ProgramArguments=[sys.executable, str(Path(__file__).resolve())],
                WorkingDirectory=str(ROOT), StartCalendarInterval=dict(Weekday=1, Hour=9, Minute=0),
                RunAtLoad=False, StandardOutPath=str(STATE / 'schedule.log'),
                StandardErrorPath=str(STATE / 'schedule.log'))
    with path.open('wb') as f:
        plistlib.dump(data, f)
    os.chmod(path, 0o600)
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, text=True)
    if result.returncode:
        path.unlink()
        raise SystemExit('任务加载失败：' + result.stderr.strip())
    print('已安装：每周一09:00（Mac本机时区）；只生成本地报告。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--install-schedule', action='store_true')
    group.add_argument('--remove-schedule', action='store_true')
    parser.add_argument('--send-feishu', action='store_true', help='send using FEISHU_WEBHOOK_URL and FEISHU_SIGNING_SECRET')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.install_schedule or args.remove_schedule:
        schedule(args.remove_schedule)
        return 0
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'run.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('已有采集任务运行，跳过本次。')
            return 0
        result = run(args.output)
        if args.send_feishu:
            webhook = os.environ.get('FEISHU_WEBHOOK_URL', '')
            secret = os.environ.get('FEISHU_SIGNING_SECRET', '')
            if not webhook or not secret:
                raise SystemExit('飞书 Secrets 未配置。')
            latest = json.loads((STATE / 'latest.json').read_text(encoding='utf-8'))
            send_feishu(Path(latest['report']), webhook, secret)
        return result


if __name__ == '__main__':
    sys.exit(main())
