#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
微信（搜狗微信频道）文章线索采集。

用途：补两类信息——
  1) 竞对/伙伴企业公众号自己发的「中标喜报 / 签约 / 开工」——比招标公告出得更早，
     且是对方自己曝光的动向，官网与交易中心都拿不到。
  2) 行业媒体号（北极星系、火电工程等）的政策解读、市场快讯——补行业动态。

重要边界：
  - 搜狗微信按「相关度」排序、无服务端时间筛选，所以必须客户端按发布日期过滤，
    且结果集本身可能不完整（热门词容易捞到多年前的老文）。
  - 文中没有金额/业主/截止时间等结构化字段，链接是搜狗临时中间链（有时效），
    **因此产出只进「微信线索」页签与竞对档案动态，绝不进商机库主表**。
  - 合规：仅限内部低频、少量使用，遇到反爬/限流立即停止，不做密集轮询。

用法：
  python3.11 mine_wechat.py                 # 跑全部关键词
  python3.11 mine_wechat.py --days 30       # 只保留近 30 天
  python3.11 mine_wechat.py --dry           # 只打印不落盘
"""
import argparse, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT_FILE = os.path.join(RAW, 'wechat_leads.json')
KEY_FILE = os.path.join(RAW, 'wechat_keywords.json')

# ---- 检索脚本定位：技能目录名是随机 id，可能变动，必须动态探测 ----
def find_search_script():
    bases = ['/root/.codebuddy/skills', os.path.expanduser('~/.codebuddy/skills')]
    hits = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if 'node_modules' in dirpath:
                continue
            for fn in filenames:
                if fn == 'search_wechat.js':
                    hits.append(os.path.join(dirpath, fn))
    return hits[0] if hits else None


# ---- 关键词：行业词 + 竞对/伙伴单位名 ----
DEFAULT_KEYWORDS = {
    "行业词": [
        "热电联产 中标", "热电联产 项目", "余热发电 项目", "余热发电 中标",
        "垃圾焚烧发电 中标", "生物质热电 项目", "煤气发电 项目",
        "脱硫脱硝 中标", "污水处理 EPC", "海水淡化 项目",
        "环境修复 中标", "燃煤火电 中标", "燃煤机组 EPC",
        "光伏 储能 中标", "综合能源 项目",
    ],
    # 竞对/伙伴单位名：命中即写入该单位档案的近期动态
    "单位名": []
}


def load_keywords():
    """关键词优先读 raw/wechat_keywords.json，缺失则用默认行业词。
    单位名会自动从已入库的竞争对手/合作生态档案名里取简称。"""
    kw = dict(DEFAULT_KEYWORDS)
    if os.path.exists(KEY_FILE):
        try:
            user = json.load(open(KEY_FILE, encoding='utf-8'))
            if isinstance(user, dict):
                for k, v in user.items():
                    kw[k] = v
        except Exception as e:
            print('[WARN] wechat_keywords.json 解析失败，用默认词：%s' % e)

    # 从档案库补单位名（取前 40 家，避免请求过多被限流）
    # 实测：用工商全称检索命中率极低（搜狗按相关度排，常返回股权/考察/纪念类噪音），
    # 必须压缩成「字号简称 + 事件词」，例如「浙江菲达环保科技股份有限公司」→「菲达环保 中标」。
    if not kw.get('单位名'):
        names = []
        for fn in ('industry.json', 'partners.json'):
            p = os.path.join(RAW, fn)
            if not os.path.exists(p):
                continue
            try:
                d = json.load(open(p, encoding='utf-8'))
            except Exception:
                continue
            arr = d if isinstance(d, list) else (d.get('competitors') or d.get('partners') or [])
            for x in arr:
                n = short_name(x.get('name') or '')
                if len(n) >= 3:
                    names.append(n)
        seen, out = [], []
        for n in names:
            if any(n[:4] in s or s[:4] in n for s in seen):
                continue
            seen.append(n)
            out.append(n)
        kw['单位名'] = out[:40]
    return kw


# 省市/行政区划与公司类后缀，抽取字号时要剥掉
_CITY_PREFIX = re.compile(r'^(中国|江苏省|浙江省|安徽省|上海市|江苏省|江苏|浙江|安徽|上海|'
                          r'无锡|南京|苏州|杭州|宁波|合肥|福建|山东|北京|天津|河北|河南|湖北|湖南|'
                          r'四川|重庆|广东|广西|江西|陕西|山西|辽宁|吉林|黑龙江|云南|贵州|甘肃|内蒙古|新疆)')
_CORP_SUFFIX = re.compile(r'(有限责任公司|股份有限公司|股份公司|有限公司|集团公司|集团总公司|'
                          r'研究院|设计院|工程公司|科技公司|技术公司)*$')


def short_name(name):
    """工商全称 → 可用于检索的字号简称。
    例：浙江菲达环保科技股份有限公司 → 菲达环保；福建龙净环保股份有限公司 → 龙净环保"""
    n = re.sub(r'[（(].*?[)）]', '', name or '').strip()
    n = n.split('/')[0].strip()                 # 处理「A / B」并列名
    n = _CITY_PREFIX.sub('', n)
    n = _CORP_SUFFIX.sub('', n)
    n = re.sub(r'(有限|股份|集团)*$', '', n).strip()
    return n[:6] if len(n) > 6 else n


def run_one(script, query, num, timeout=120):
    try:
        p = subprocess.run(['node', script, query, '-n', str(num)],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, 'timeout'
    txt = (p.stdout or '')
    m = re.search(r'\{.*\}', txt, re.S)
    if not m:
        return None, (txt or p.stderr or '')[:160].replace('\n', ' ')
    try:
        return json.loads(m.group(0)), ''
    except Exception as e:
        return None, '解析失败 %s' % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30, help='只保留最近 N 天的文章（默认 30）')
    ap.add_argument('--num', type=int, default=10, help='每个关键词取多少条（默认 10，最大 50）')
    ap.add_argument('--dry', action='store_true', help='只打印不落盘')
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 个关键词（调试用）')
    args = ap.parse_args()

    script = find_search_script()
    if not script:
        print('[失败] 未找到 search_wechat.js（微信检索技能缺失或已改名），本次不产出')
        sys.exit(3)
    print('[检索脚本] %s' % script)

    kw = load_keywords()
    queries = []
    for cat, ws in kw.items():
        for w in ws:
            # 实测：单位简称单独搜会命中股权/考察/纪念类噪音，加事件词才能捞到中标喜报
            q = (w + ' 中标') if cat == '单位名' else w
            queries.append((cat, w, q))
    if args.limit:
        queries = queries[:args.limit]

    cutoff = time.time() - args.days * 86400
    items, seen_url, seen_title = [], set(), set()
    stat = {'命中': 0, '过旧跳过': 0, '重复跳过': 0, '请求失败': 0}

    for cat, unit, q in queries:
        data, err = run_one(script, q, args.num)
        if err:
            print('  ! %-22s %s' % (q[:22], err))
            stat['请求失败'] += 1
            continue
        arts = (data or {}).get('articles', [])
        got = 0
        for a in arts:
            dt = (a.get('datetime') or '').strip()
            if dt:
                try:
                    ts = time.mktime(time.strptime(dt, '%Y-%m-%d %H:%M:%S'))
                except Exception:
                    ts = 0
                if ts and ts < cutoff:
                    stat['过旧跳过'] += 1
                    continue
            url = (a.get('url') or '').strip()
            title = (a.get('title') or '').strip()
            if not title:
                continue
            key = url or title
            if key in seen_url or title in seen_title:
                stat['重复跳过'] += 1
                continue
            seen_url.add(key)
            seen_title.add(title)
            items.append({
                't': title,
                'url': url,
                'snip': (a.get('summary') or '').strip()[:200],
                'd': dt[:10],
                'src': (a.get('source') or '').strip(),
                'cat': '竞对动态' if cat == '单位名' else '行业动态',
                'hit': q,
                'unit': (unit if cat == '单位名' else ''),
            })
            got += 1
        print('  · %-24s 新增 %d 条' % (q[:24], got))
        stat['命中'] += got
        time.sleep(1.5)          # 控制节奏，避免触发反爬

    items.sort(key=lambda x: (x.get('d') or ''), reverse=True)
    print('\n[汇总] 关键词 %d 个 · 采集 %d 条（过旧跳过 %d，重复 %d，失败 %d）'
          % (len(queries), len(items), stat['过旧跳过'], stat['重复跳过'], stat['请求失败']))
    for c in ('竞对动态', '行业动态'):
        n = sum(1 for x in items if x['cat'] == c)
        print('   %s：%d 条' % (c, n))

    if args.dry:
        for x in items[:15]:
            print('   - [%s] %s | %s | %s' % (x['cat'], x['d'], x['src'], x['t'][:44]))
        return

    payload = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'days': args.days, 'items': items}
    json.dump(payload, open(OUT_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n已写入 %s（%d 条）' % (OUT_FILE, len(items)))


if __name__ == '__main__':
    main()
