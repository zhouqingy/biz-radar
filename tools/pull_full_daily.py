# -*- coding: utf-8 -*-
"""
按日期全量拉取（2026-10-24 新增，用户：三个省那么多个市就上了这么几个项目？）

背景与诊断：
  旧采集（collect_v4.py）是「关键词搜索」模式——45 个关键词，每个最多 200 条。
  这个模式的盲区：**公告标题里没出现这 45 个词的相关项目，永远进不了库**。
  实测全库 1521 条里 97% 来自 5 个源，且大量真实项目（综合能源、供能、
  碳管理、园区改造类）的标题措辞不在关键词表里。

  而浙江/江苏的省级平台本身就是**全省归集站**（实测 ggzy.zj.gov.cn 首页就有
  【金华市】【温岭市】【永康市】等 11 地市的公告），不存在"还要去接 41 个市级站"
  的问题——问题是我们只挖了省平台的一小角。

做法：
  wd 传空 = 不带关键词的全量检索，按日期窗口翻页。先拉回来，业务相关性
  交给下游 build_web.py 里的 biz_rules.judge 严筛（那条链路已经存在且很严），
  采集端只做最粗的噪声过滤（is_noise）。

  这样数据量上限就从「45 词 × 200 条」的天花板变成「按日期翻到底」的真实水位。

用法：
  python3 pull_full_daily.py --days 7            # 近 7 天，默认四站
  python3 pull_full_daily.py --probe             # 只试拉昨天一天，看总量再决定
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_v4 import (UA, KW_NOISE, PROV_OF, SiteError, clean, is_noise,
                        mk, post, stage_of)

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')

FULL_SITES = {
    '浙江': {
        'api': 'https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://ggzy.zj.gov.cn',
        'plat': '浙江省公共资源交易服务平台',
        'level': '省级', 'rnMax': 20,
    },
    '江苏': {
        'api': 'https://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://jsggzy.jszwfw.gov.cn',
        'plat': '江苏省公共资源交易平台',
        'level': '省级',
        'insecure': True,   # 证书链不完整，curl 必须 -k（2026-10-24 实测 rc=60）
    },
    '合肥': {
        'api': 'https://ggzy.hefei.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://ggzy.hefei.gov.cn',
        'plat': '合肥公共资源交易中心',
        'level': '市级', 'sort': '{"webdate":"0"}',
    },
    '安徽': {
        'api': 'https://ggzy.ah.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://ggzy.ah.gov.cn',
        'plat': '安徽省公共资源交易服务平台',
        'level': '省级',
    },
    '上海': {
        'api': 'https://www.shggzy.com/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://www.shggzy.com',
        'plat': '上海市公共资源交易平台',
        'level': '市级',
        'follow': True,     # 接口先 302，必须 -L（2026-10-24 实测）
    },
}


import html as _htm


def clean_body(s):
    """records 里的 content 是**双重转义**的 HTML：&lt;span id=...&gt;。
    直接 re 去标签会得到一堆 &lt; 文本，必须先用 html.unescape 还原，
    再去标签，最后把实体再解一次（&nbsp; &amp; 这类二次出现的）。"""
    s = _htm.unescape(s or '')
    s = re.sub(r'<(script|style)[^>]*>.*?</\\1>', ' ', s, flags=re.S | re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = _htm.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


_AMT_RE = [
    re.compile(r'(?:预算金额|招标控制价|最高限价|项目总投资|总投资额?|概算投资|建安投资|'
               r'招标金额|中标价|中标金额|合同金额|采购预算)\s*[:：]?\s*'
               r'([0-9]+(?:\.[0-9]+)?)\s*(亿元|万元|元)'),
    re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*(亿元|万元)\s*(?:人民币)?(?:，|。|；|）|\))'),
]


def pick_amt(title, body):
    """从正文里抽金额，返回 amtTxt（保留原文措辞，供下游二次解析）。
    标题里的金额优先——那种通常是「总投资 5.2 亿元」这类确定性最高的。"""
    for src in (title, body):
        for rx in _AMT_RE:
            m = rx.search(src or '')
            if m:
                v = float(m.group(1))
                unit = m.group(2)
                if unit == '亿元' and v < 0.01:      # 0.005 亿这种明显是噪声
                    continue
                if unit == '元' and v < 100000:      # 十万元以下的都不是我们关心的
                    continue
                if unit == '万元' and v < 100:
                    continue
                return m.group(0)[:40]
    return ''



def is_noise2(title):
    """在全量模式上再叠一层：全量池子里 80% 是房建/水利/交通/政府采购，
    这些留下去只会把下游严筛拖得更慢。这里只留「可能有能源/环保/工业属性」的。"""
    if is_noise(title):
        return True
    # 交易中心会在平台上跑演练流程，标题带着「测试/演练/压力测试」。
    # ⚠ 只认**标题前 20 字**里的：真项目标题中部也常有这些词——
    #   「苍山化工园区污水处理改造提升项目设备采购及安装调试工程」
    #   「...新能源发电建模仿真与测试中心实验室建设项目」
    # 全标题匹配会把这类正经项目一并误杀（2026-10-24 实测误杀 3 条），得不偿失。
    _head = title[:20]
    if any(k in _head for k in ('测试', '演练', '压测', '测-试', '验证-w')):
        return True
    KEEP = ['电厂', '电站', '发电', '电力', '能源', '热电', '热力', '供热', '供冷',
            '锅炉', '汽轮机', '燃机', '燃气轮机', '烟气', '脱硫', '脱硝', '除尘',
            '超低排放', '废水', '污水', '水处理', '零排放', '中水', '给水',
            '土壤', '修复', '环保', '环境', '生态', '固废', '垃圾', '危废',
            '光伏', '风电', '储能', '充电', '氢能', '绿色', '低碳', '节能',
            '减排', '双碳', '碳', '余热', '余压', '煤气', '焦化', '冶金',
            '钢铁', '有色', '铝', '铜', '锌', '镍', '冶炼', '熔炼',
            '烟囱', '冷却塔', '输煤', '除灰', '脱白', 'EPC', '总承包',
            '清洁', '新能源', '源网荷储', '多能互补', '绿电', '绿证',
            '蒸汽', '综合供能', '园区', '开发区', '工矿', '厂区']
    return not any(k in title for k in KEEP)


def crawl_site(name, cfg, stop_date, pause=0.4, max_page=400):
    """单站全量翻页（2026-10-24 重写）。

    实测发现（probe 日志）：
      · sdt/edt 参数**不生效**——wd='能源' 带日期 total=0，去掉日期 total=9547；
        所以旧采集的日期窗口很可能一直是摆设，靠的是相关度排序恰好捞到新公告。
      · 浙江站的日期排序字段是 infodate（infodatepx 是乱序）。
    新做法：按 infodate 倒序翻页，翻到第一条公告日期 < stop_date 就停，
    日期过滤在本地做，不再依赖对端参数。
    """
    rn = int(cfg.get('rnMax', 50))
    fields = cfg.get('fields', 'title')
    out = {}
    page = 0
    total = -1
    oldest = ''
    while page < max_page:
        r = post(cfg['api'], mk(wd=cfg.get('wd', ''), pn=page * rn,
                                rn=str(rn), fields=fields,
                                sort=cfg.get('sort', '{"infodate":"0"}')),
                 insecure=cfg.get('insecure', False), follow=cfg.get('follow', False))
        if not r:
            break
        recs = r.get('records') or []
        if total < 0:
            total = int(r.get('totalcount') or 0)
        if not recs:
            break
        stop = False
        for x in recs:
            d = (x.get('infodate') or x.get('infodatepx') or x.get('webdate') or '')[:10]
            oldest = min(oldest or d, d) if d else oldest
            if d and d < stop_date:
                stop = True
                continue
            title = clean(x.get('title'))
            body = clean_body(x.get('content'))
            if not title or is_noise2(title):
                continue
            uid = x.get('infoid') or x.get('id') or hashlib.md5(
                (title + (x.get('infodate') or '')).encode()).hexdigest()
            if uid in out:
                continue
            link = x.get('linkurl') or ''
            out[uid] = {
                'id': hashlib.md5((cfg['plat'] + uid).encode()).hexdigest()[:10],
                't': title,
                'rg': PROV_OF.get(name, name),
                'st': stage_of(title),
                'd': d,
                'p': cfg['plat'],
                'platLevel': cfg['level'],
                'srcType': 'official-full',
                'url': (cfg['host'] + link) if link.startswith('/') else link,
                'cat': x.get('categorynum') or '',
                # 正文摘要：2026-10-24 补。原来只取 title，把 records 里现成的
                # content 扔了——下游 judge 只能看到干巴巴一句标题，
                # 「有金额」「工艺词」「EPC 属性」全都判不出来，iv/w 自然也判不出来。
                # content 是同一个请求的返回体，拿它零额外代价。
                'snip': body[:400],
                'amtTxt': pick_amt(title, body),
            }
        page += 1
        if stop:
            break
        time.sleep(pause)
    return list(out.values()), total, oldest, page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--probe', action='store_true',
                    help='只试拉昨天一天，看各站真实总量，不落盘不并库')
    ap.add_argument('--sites', default='浙江,江苏,安徽,合肥,上海')
    ap.add_argument('--out', default='')
    ap.add_argument('--pause', type=float, default=0.4)
    a = ap.parse_args()

    today = date.today()
    stop = str(today - timedelta(days=a.days))
    wins = [(stop, stop)]  # 只用于打印，实际抓取不依赖日期参数
    # 泛词集：接口必须有 wd（空词 total=0），但泛词能覆盖几乎全部工程公告。
    # 「能源」9547 条、「工程」155 万条——泛词负责池子，相关性交给下游严筛。
    WIDE_KW = ['能源', '发电', '热电', '电力', '锅炉', '环保', '污水', '废水',
               '水处理', '土壤', '修复', '光伏', '储能', '余热', '煤气', '烟气',
               '脱硫', '节能', '蒸汽', '供热', '总承包', 'EPC']
    sites = [x.strip() for x in a.sites.split(',') if x.strip()]
    allrec = []
    for name in sites:
        cfg = FULL_SITES.get(name)
        if not cfg:
            print('!! 未知站点', name)
            continue
        n_site = 0
        for kw in WIDE_KW:
            cfg2 = dict(cfg); cfg2['wd'] = kw
            try:
                recs, total, oldest, pages = crawl_site(name, cfg2, stop, pause=a.pause)
            except SiteError as e:
                print('  [%s] kw=%s 失败: %s' % (name, kw, str(e)[:80]))
                break
            print('  [%s] kw=%s total=%s 拉到页=%s 最旧=%s 保留=%s' %
                  (name, kw, total, pages, oldest, len(recs)))
            n_site += len(recs)
            allrec.extend(recs)
            if a.probe:
                break
            time.sleep(0.3)
        print('  [%s] 小计 %s 条' % (name, n_site))

    if a.probe:
        print('\nprobe 完成（未落盘）。确认水位后去掉 --probe 真正拉取。')
        return
    # id 去重（跨词重复）
    seen = {}
    for x in allrec:
        seen.setdefault(x['id'], x)
    allrec = list(seen.values())
    # 落进 raw/weekly/：build_data.py 遍历这个目录做增量合并，
    # 落别处的话每天抓取的结果压根进不了 merged.json（新加这个脚本时踩过）。
    fn = a.out or os.path.join(RAW, 'weekly',
                               'full_daily_%s.json' % today.strftime('%Y%m%d'))
    json.dump(allrec, open(fn, 'w', encoding='utf-8'), ensure_ascii=False)
    print('\n✅ 落盘 %s 条 → %s' % (len(allrec), fn))


if __name__ == '__main__':
    main()
