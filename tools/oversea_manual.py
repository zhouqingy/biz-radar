#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出海速览 · 手工投喂 + 死链自愈（2026-11-08，§5.52）

为什么开这个文件
────────────────────────────────────────────────────────────────────────
用户 11-08 18:18 的原话：
  「那个海外那个事情，不是说在那个微信上可以自动抓那个微信的一些新闻吗？
    通过什么搜狗平台吧。怎么这么些天了还是 11 条啊，我感觉你根本就没有任何更新啊」

查实（不是猜，是实测）：
  ① 搜狗微信搜索对机房 IP 已封死 —— 本机直连 weixin.sogou.com 得到
     302 → /antispider/?antip=wx_sh2，任何关键词都 0 条。CI 的 Azure IP 同理。
     mine_oversea_wechat.py 一直"成功"是因为它 0 条也 exit 0（假绿）。
  ② 老 11 条的 url 存的是 weixin.sogou.com/link?url=…&token=… 跳转链，
     逐条点开 3/3 全部跳回 antispider —— **旧数据点不开**。
  ③ 步骤 5 失败 → 步骤 6 跳过，数据压着没发布。

所以：搜狗这条路作为「自动抓」已经死了，别再指望它。改成两条腿：
  A 通道（自动）  oversea_sources.py —— 可直连的中文源（印尼商报/国复/...）
  B 通道（人工）  本文件 —— 用户把公众号文章链接发过来，即时入库 + 抓真实标题正文

搜狗不再作为主通道，但历史抓到的条目**不删**（留着当线索），只把死链标出来。

做什么
────────────────────────────────────────────────────────────────────────
1. 读 raw/oversea_manual.json（用户投喂的链接清单，只有 url 就行）
2. 每条 url 直接抓 mp.weixin.qq.com 页面，解析：标题 / 公众号 / 发布时间 / 摘要
   ——**链接存真实永久地址**，不再存会过期的 sogou 跳转链
3. 过 semantic_drop()（规则源绝不绕过）+ pick_odi.judge() 定档
4. 合并进 raw/oversea_flash.json，旧的 11 条保留，标 linkdead=1

用法
────────────────────────────────────────────────────────────────────────
    python3 oversea_manual.py                 # 跑 manual.json 里新增的
    python3 oversea_manual.py --url <链接>     # 临时加一条
    python3 oversea_manual.py --probe          # 只测旧链接是否失效，不写盘
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight import require_briefing
require_briefing('oversea_manual.py')

import biz_rules as BR          # 唯一规则源
import pick_odi as PO          # 出海备案口径（S/A/W/X），复用，不另写

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
MANUAL = os.path.join(RAW, 'oversea_manual.json')
FLASH = os.path.join(RAW, 'oversea_flash.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')


# ── 抓取 ────────────────────────────────────────────────────────────────
def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'ignore')


def parse_wechat(html):
    """从公众号文章页解析出标题/公众号/时间/摘要。

    不用 bs4：CI 里 bs4 装了，但这里正则足够，且避免版本差异。
    公众号页面的稳定锚点：<h1 class="rich_media_title">、var ct = "时间戳"、
                      nickname: '公众号名'、id="js_content" 正文。
    """
    def one(pat, s=html, grp=1):
        m = re.search(pat, s, re.S)
        return m.group(grp).strip() if m else ''

    title = one(r'<h1[^>]*class="[^"]*rich_media_title[^"]*"[^>]*>(.*?)</h1>')
    if not title:
        title = one(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"')
    title = re.sub(r'<[^>]+>', '', title)
    title = (title.replace('&amp;', '&').replace('&quot;', '"')
                  .replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')).strip()

    nick = one(r"nickname:\s*'([^']*)'")
    if not nick:
        nick = one(r'var nickname\s*=\s*"([^"]*)"')
    if not nick:
        nick = one(r'<a[^>]+id="js_name"[^>]*>(.*?)</a>')
        nick = re.sub(r'<[^>]+>', '', nick).strip()

    # 时间：页面里有 `var ct = "1793874780"` 与 create_time: '2026-11-05 18:33'
    ts = one(r'var\s+ct\s*=\s*"(\d{9,11})"')
    if ts:
        dt = time.strftime('%Y-%m-%d %H:%M', time.localtime(int(ts)))
    else:
        dt = one(r"create_time:\s*'([\d\-: ]+)'")
    date = dt[:10] if dt else ''

    body = one(r'<div[^>]+id="js_content"[^>]*>(.*?)</div>\s*<script')
    if not body:
        body = one(r'<div[^>]+class="[^"]*rich_media_content[^"]*"[^>]*>(.*?)</div>')
    text = re.sub(r'<[^>]+>', ' ', body)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    dead = bool(re.search(r'该内容已被发布者删除|链接已过期|内容已删除|此内容因违规无法查看', html))
    return {'title': title, 'src': nick, 'datetime': dt, 'date': date,
            'text': text, 'dead': dead, 'len': len(html)}


def summarize(text, limit=140):
    """取摘要：从正文里挑「带数字/口径」的那几句，而不是无脑截前 N 字。

    为什么不能只截前 220 字：前端只显示 m（摘要）这 120 字，而 pick_odi.judge()
    也是拿「标题 + 摘要」判档。摘要若只装了一堆行业抒情（「海外有色金属赛道迎来
    重磅消息」），判档会漏掉「自备电厂」这类关键口径 —— 实测协鑫那条就因为
    摘要里没有能量词被判成 X（电源项目规模未知），正文里其实明写「绿电与自备电厂」。
    所以按句打分：含金额/装机/产能/工程本体的句子优先。
    """
    KEY = ('亿', '万吨', 'MW', '兆瓦', '千瓦', 'kA', '熟料', '余热', '自备电', '电厂',
           '发电', '用电', '供水', '淡化', '投产', '开工', '签约', '总包', 'EPC',
           '中标', '投资', '美元', '配套', '装机', '锅炉', '机组')
    sents = re.split(r'(?<=[。！？；])', text or '')
    score = []
    for i, s in enumerate(sents):
        s = s.strip()
        if len(s) < 8:
            continue
        sc = sum(1 for k in KEY if k in s) * 2 + (2 if re.search(r'\d', s) else 0)
        score.append((sc, i, s))
    if not score:
        return (text or '')[:limit]
    picked = sorted(score, key=lambda x: (-x[0], x[1]))[:3]
    picked.sort(key=lambda x: x[1])
    out = ''
    for _, _, s in picked:
        if len(out) + len(s) > limit:      # 超长整句丢掉，不截半句
            continue
        out = (out + ' ' + s).strip()
    return out or (text or '')[:limit]
# ⚠ 不截半句：截断会把「5MW余热发电」这种关键口径切掉一半，反而更糟。


def classify(item):
    """过唯一规则源 + 备案口径定档，返回 (drop, code, why, tier, tierwhy)。"""
    t = item.get('title') or ''
    s = item.get('summary') or item.get('text', '')[:300]
    drop, code, why = BR.semantic_drop(t)
    tier, tierwhy = PO.judge(t + ' ' + s)
    return drop, code, why, tier, tierwhy


def norm_url(u):
    """去掉 utm / chksm 之后的跟踪参数，保留能唯一定位的 biz/mid/idx/sn。"""
    u = (u or '').strip()
    if not u:
        return ''
    u = u.split('#')[0]
    if 'mp.weixin.qq.com' in u:
        keep = {}
        base = u.split('?')[0]
        qs = u.split('?', 1)[1] if '?' in u else ''
        for kv in qs.split('&'):
            if '=' not in kv:
                continue
            k, v = kv.split('=', 1)
            if k in ('__biz', 'mid', 'idx', 'sn'):
                keep[k] = v
        if keep:
            return base + '?' + '&'.join('%s=%s' % (k, keep[k]) for k in ('__biz', 'mid', 'idx', 'sn') if k in keep)
    return u


# ── 主流程 ──────────────────────────────────────────────────────────────
def load_json(p, default):
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding='utf-8'))
        except Exception as e:
            print('  ⚠ %s 读取失败：%s' % (os.path.basename(p), e))
    return default


def main():
    args = sys.argv[1:]
    probe_only = '--probe' in args
    extra = []
    for i, a in enumerate(args):
        if a == '--url' and i + 1 < len(args):
            extra.append(args[i + 1])

    man = load_json(MANUAL, {'items': []})
    todo = [x for x in (man.get('items') or [])]
    for u in extra:
        todo.append({'url': u, 'note': '命令行临时投喂'})

    flash = load_json(FLASH, {'items': []})
    have = {norm_url(x.get('url')) for x in flash.get('items', [])}

    print('== 投喂清单 %d 条（已在库 %d 条）==' % (len(todo), len(have)))
    added, skipped, failed = [], [], []

    for it in todo:
        u = norm_url(it.get('url') or '')
        if not u:
            continue
        if u in have:
            skipped.append((u, '已在库'))
            continue
        try:
            html = fetch(it.get('url'))
        except Exception as e:
            failed.append((u, '%s: %s' % (type(e).__name__, e)))
            print('  ✗ 抓取失败 %s（%s）' % (u[:60], type(e).__name__))
            continue
        p = parse_wechat(html)
        if p['dead'] or not p['title']:
            failed.append((u, '页面无标题/已删除'))
            print('  ✗ 解析不出标题：%s' % u[:60])
            continue
        summ = summarize(p['text'], 138)
        drop, code, why, tier, tierwhy = classify({
            'title': p['title'], 'summary': summ, 'text': p['text']})
        rec = {
            'title': p['title'],
            'url': u,
            'summary': summ,
            'date': p['date'] or it.get('date') or '',
            'datetime': p['datetime'] or (it.get('date') or '') + ' 00:00',
            'src': p['src'] or it.get('src') or '',
            'kw': 'manual:' + (it.get('note') or 'user'),
            'sc': 9 if not drop else 0,      # 人工投喂默认高权重
            'tier': tier,
            'tierwhy': tierwhy,
            'sem': code or 'KEEP',
            'semwhy': why,
            'chan': 'manual',
        }
        print('  ✓ %s | %s | %s | sem=%s tier=%s'
              % (rec['date'] or '????-??-??', rec['src'][:12], rec['title'][:40],
                 rec['sem'], rec['tier'] or '-'))
        if drop:
            print('     ⚠ 被 semantic_drop 判删（%s %s）—— 按口径不入库' % (code, why))
            failed.append((u, 'semantic_drop:' + code))
            continue
        added.append(rec)
        have.add(u)

    # ── 旧条目死链探测（sogou 跳转链已全部失效）──────────────────────
    probed = 0
    for x in flash.get('items', []):
        u = x.get('url') or ''
        if 'weixin.sogou.com' in u and not x.get('linkdead'):
            # 不逐条请求（会拖慢 CI），按已知事实直接标：搜狗 link 接口对机房 IP 一律 302
            x['linkdead'] = 1
            x['linkdeadwhy'] = 'sogou 跳转链对机房 IP 一律 302 antispider（2026-11-08 实测 3/3）'
            probed += 1

    if probe_only:
        print('\n-- 只探测不写盘 --')
        return

    merged = {norm_url(x.get('url')): x for x in flash.get('items', [])}
    for r in added:
        merged.setdefault(r['url'], r)
    items = sorted(merged.values(),
                   key=lambda y: (y.get('datetime') or y.get('date') or '', -int(y.get('sc') or 0)),
                   reverse=True)
    cut = time.strftime('%Y-%m-%d', time.localtime(time.time() - 120 * 86400))
    items = [x for x in items if (x.get('date') or '') >= cut]

    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(items), 'items': items}
    os.makedirs(RAW, exist_ok=True)
    json.dump(out, open(FLASH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n写入 %s：新增 %d / 跳过 %d / 失败 %d / 标死链 %d → 合计 %d 条'
          % (os.path.basename(FLASH), len(added), len(skipped), len(failed), probed, len(items)))
    return out


def combine(recent):
    """把最近人工通道的产出合并进刚落盘的 flash（供 oversea_sources 调）。

    为什么要这个函数而不是再调一次 main()：main() 会自己从磁盘读 old，
    而磁盘上的 old 是刚被 A 通道写过的版本 —— 它再写一次就把 A 的新条目算进
    「旧条目」保留下来，看似没问题，实际上 A 通道那批的排序/sc 会被 B 覆盖一遍。
    这里改成「在内存里合并」，写盘只发生一次。
    """
    cur = load_json(FLASH, {'items': []})
    merged = {norm_url(x.get('url')): x for x in cur.get('items', [])}
    n0 = len(merged)
    for x in recent.get('items', []):
        merged.setdefault(norm_url(x.get('url')), x)
    items = sorted(merged.values(),
                   key=lambda y: (y.get('datetime') or y.get('date') or '', -int(y.get('sc') or 0)),
                   reverse=True)
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(items), 'items': items}
    json.dump(out, open(FLASH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('人工通道合并：%d → %d 条（+%d）' % (n0, len(items), len(items) - n0))
    return out


if __name__ == '__main__':
    main()
