# -*- coding: utf-8 -*-
"""
对手/业主「全网业绩库」采集（2026-10-24 新增）

用户原话：
  「中国联合工程有限公司 这个怎么只有EPC的业绩，这种对手和客户是需要所有的业绩的」
  「对手，业主是需要通过另一套关键词自己搜，其中找商机库里面如果有的数据可以拿过来用，
    但是我觉得大部分还是得靠自己去搜」
  「搜到的数据不能放在找商机那个里面，单独放着，不然会污染找商机库的数据」

设计（跟用户逐条对齐）：
  · 用**单位名核心词**当关键词，直接去各省公共资源交易平台全文检索——
    命中的是该单位作为中标人/业主/参与方的**所有公告**，不分业务、不卡分层，
    完整保留，用来判断「这家最近在往哪个方向走」（风向）。
  · 结果写 raw/rival_perf.json，**完全不经过 merged.json**：
    找商机库的入库链路（biz_rules.judge 严筛）一步都不沾，物理隔离。
  · 找商机库里已有的该单位记录，前端展示时叠加显示（"拿过来用"），
    但数据本体不重复存。

用法：
  python3 crawl_rival_perf.py                 # 默认 TOP40 对手 + TOP40 业主
  python3 crawl_rival_perf.py --top 60        # 各取前 60 家
  python3 crawl_rival_perf.py --only 中国联合  # 只补某几家（调试用）
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_v4 import UA, SiteError, clean, mk, post

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')
OUT = os.path.join(RAW, 'rival_perf.json')

# 与 pull_full_daily 同一套站点；insecure/follow 是各站实测出来的硬要求
SITES = [
    ('浙江', 'https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
     'https://ggzy.zj.gov.cn', {'rnMax': 20, 'sort': '{"infodate":"0"}'}, False, False),
    ('江苏', 'https://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
     'https://jsggzy.jszwfw.gov.cn', {'sort': '{"infodate":"0"}'}, True, False),
    ('合肥', 'https://ggzy.hefei.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
     'https://ggzy.hefei.gov.cn', {'sort': '{"webdate":"0"}'}, False, False),
]


def core_name(name):
    """把全名压成搜索词。
    「中国能源建设集团江苏省电力设计院有限公司」整串丢给分词器，命中的反而少——
    搜索接口做的是分词匹配，多一个词就多一层 AND。取「最有个性的连续核心」：
    去掉「集团/股份/有限/责任/公司」这类所有单位都有的尾缀，剩下的才区分人。"""
    s = re.sub(r'（[^）]*）|\([^)]*\)', '', name).strip()
    s = re.sub(r'(股份有限|有限责任|集团有限|有限公司|责任公司|股份有限公司)$', '', s)
    s = re.sub(r'(集团|公司|总院|研究院|设计院)$', '', s)
    # 太短的核心词（如「华光」）会命中大量无关公告，保底 4 字
    return s if len(s) >= 4 else name[:8]


def crawl_one(kw, per_site_max=120, pause=0.4):
    """单个关键词，跨站搜索，去重聚合。返回 (records, stat)。"""
    out = {}
    stat = []
    # 产权/货物处置类标题直接挡掉：马鞍山钢铁那次 150 条全是「46台车辆转让挂牌」，
    # 是合肥站产权交易栏目的公告，不是工程业绩 —— 标题前 30 字含这些词就丢
    _BAD_T = ('转让', '挂牌', '竞价', '拍卖', '竞买', '产权交易',
              '报废处置', '车辆', '废旧物资', '物资处置')
    for nm, api, host, cfg, insecure, follow in SITES:
        rn = int(cfg.get('rnMax', 50))
        got = 0
        page = 0
        while got < per_site_max and page < 8:
            try:
                r = post(api, mk(wd=kw, pn=page * rn, rn=str(rn), fields='title',
                                 sort=cfg.get('sort', '{"infodate":"0"}')),
                         insecure=insecure, follow=follow)
            except SiteError as e:
                stat.append('%s:FAIL(%s)' % (nm, str(e)[:40]))
                break
            recs = (r or {}).get('records') or []
            if not recs:
                break
            for x in recs:
                t = clean(x.get('title'))
                # 标题必须真含关键词：es 是分词匹配，「中国 联合 工程」隔开的也算命中，
                # 那种噪声留进来会把画像刷成大杂烩
                if not t or kw[:4] not in t.replace(' ', ''):
                    continue
                if any(b in t[:30] for b in _BAD_T):
                    continue
                uid = x.get('infoid') or hashlib.md5((t + (x.get('infodate') or '')).encode()).hexdigest()
                key = nm + ':' + uid
                if key in out:
                    continue
                link = x.get('linkurl') or ''
                out[key] = {
                    't': t, 'd': (x.get('infodate') or x.get('webdate') or '')[:10],
                    'rg': nm, 'p': nm + '省公共资源交易平台' if nm != '合肥' else '合肥公共资源交易中心',
                    'url': (host + link) if link.startswith('/') else link,
                }
                got += 1
            page += 1
            if page * rn >= int(r.get('totalcount') or 0):
                break
            time.sleep(pause)
        stat.append('%s:%d' % (nm, got))
        time.sleep(0.3)
    return list(out.values()), stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=40, help='对手/业主各取前几家')
    ap.add_argument('--only', default='', help='只跑名字含此词的（调试）')
    args = ap.parse_args()

    g = json.load(open(os.path.join(RAW, 'graphs.json'), encoding='utf-8'))

    def score(x):
        return (x.get('n') or 0) + (x.get('amt') or 0)
    rv = sorted(g.get('rivals') or [], key=score, reverse=True)[:args.top]
    by = sorted(g.get('owners') or g.get('buyers') or [], key=score, reverse=True)[:args.top]
    targets = [(x.get('name') or '', 'rival') for x in rv] + \
              [(x.get('name') or '', 'owner') for x in by]
    if args.only:
        targets = [t for t in targets if args.only in t[0]]

    old = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding='utf-8'))
    db = old.get('db') or {}
    done = old.get('done') or {}

    for name, kind in targets:
        if not name:
            continue
        prev = done.get(name)
        kw = core_name(name)
        recs, stat = crawl_one(kw)
        db[name] = {
            'kind': kind, 'kw': kw, 'n': len(recs),
            'items': sorted(recs, key=lambda r: r.get('d') or '', reverse=True)[:200],
        }
        done[name] = kw
        print('[%s] %s 搜「%s」→ %d 条  (%s)' % (kind, name[:18], kw, len(recs), ' '.join(stat)))
        # 每家落一次盘：跑一半断网也不至于全丢
        json.dump({'updated': time.strftime('%F %T'), 'db': db, 'done': done},
                  open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        time.sleep(0.5)

    n_all = sum(v['n'] for v in db.values())
    print('\n✅ 共 %d 家，业绩合计 %d 条 → %s' % (len(db), n_all, OUT))


if __name__ == '__main__':
    main()
