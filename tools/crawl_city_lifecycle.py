#!/usr/bin/env python3
"""城市公共资源交易平台「全生命周期」采集器（多城市模板版）
═══════════════════════════════════════════════════════
用户目标（2026-10-24 确认）：
  出口A 与我相关的（业务严筛由 build_web 侧 biz_rules.judge 做）：
     招标计划/提前公示 → 立项线索档；公告 → 能投的标；结果 → 已出结果
  出口B 全量不筛 → 情报库（rivalperf 同库物理隔离），重点是评标情报：
     谁进候选人、各报多少、谁中了多少钱 —— 判断对手风向的核心
设计原则：南通只是第一个实例，换城市只改 CITY 配置。
接口要点（南通 EWB-FRONT 架构）：
  POST /rest/infolist/getJyInfoList，表单 params={"siteGuid":...,"categorymum":...,
  "pageIndex":从0开始,"pageSize":..}  ← 前端 Util.ajax 把对象包成 params=JSON
合法合规：只抓法定公开公告，0.4s/请求，不碰登录/附件，仅内部决策用。
"""
import json, os, re, sys, time, html, argparse, subprocess

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
SITE = 'https://ggzyjy.nantong.gov.cn'

# ── 城市配置：新城市只需在这里加一段 ─────────────────────────
# cols: 生命周期阶段 → 栏目编号列表（南通「建设工程」系列）
CITIES = {
    '南通': {
        'api': SITE + '/EWB-FRONT/rest/infolist/getJyInfoList',
        'host': SITE,
        'guid': '7eb5f7f1-9041-43ad-8e13-8fcb82ea831a',
        'cols': {
            'plan':    ['003001009'],            # 招标计划（准备招）
            'prep':    ['003001002'],            # 招标文件提前公示
            'notice':  ['003001003', '003001004'],  # 招标公告/资审（在招）
            'cand':    ['003001005', '003001007'],  # 中标候选人/定标结果（评标情报）
            'result':  ['003001006'],            # 中标结果（招完）
            'contract':['003001008'],            # 合同公告
        },
        'plat': '南通市公共资源交易平台',
    },
}

BAD_T = ('转让', '挂牌', '竞价', '拍卖', '竞买', '产权交易', '报废处置',
         '车辆', '废旧物资', '物资处置')   # 产权/货物处置类：宁钢教训


def post(api, guid, cat, page, size=20):
    body = ('params=' + json.dumps({
        'siteGuid': guid, 'searchTitle': '', 'diqu': '',
        'categorymum': cat, 'pageIndex': page, 'pageSize': size},
        ensure_ascii=False)).encode()
    cmd = ['curl', '-s', '-m', '25', '-X', 'POST', api,
           '-H', 'User-Agent: ' + UA,
           '-H', 'Content-Type: application/x-www-form-urlencoded',
           '--data-binary', body]
    p = subprocess.run(cmd, capture_output=True)
    try:
        return json.loads(p.stdout.decode('utf-8', 'ignore'))
    except Exception:
        return {}


def clean(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    return html.unescape(s).replace('[新]', '').strip()


def list_col(city, cat, code, stop_date, max_pages=60):
    """按日期倒序翻一个栏目，到 stop_date 停。返回 (items, last_date)"""
    cfg = CITIES[city]
    out, last = [], ''
    for pg in range(max_pages):
        d = post(cfg['api'], cfg['guid'], code, pg)
        rows = d.get('Table') or []
        if not rows:
            break
        for r in rows:
            t = clean(r.get('title'))
            dt = (r.get('infodate') or '')[:10]
            if not t or not dt:
                continue
            if dt < stop_date:
                return out, last
            last = max(last, dt)
            if any(b in t[:30] for b in BAD_T):
                continue
            u = r.get('infourl') or ''
            out.append({
                'id': city + ':' + hashlib.md5((t + dt).encode()).hexdigest()[:12],
                'city': city, 'cat': cat,
                't': t, 'd': dt,
                'url': u if u.startswith('http') else cfg['host'] + u,
                'rg': city,
            })
        time.sleep(0.4)
    return out, last


import hashlib

# ── 详情页抽取（评标情报核心）─────────────────────────────
def strip_html(s):
    s = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>', '', s or '')
    return html.unescape(re.sub(r'<[^>]+>', ' ', s))


def parse_amt(s):
    """统一转成「亿元」；裸元/万元/亿元都要区分（133595046元=1.336亿，
    之前裸元被当万除了一次，数字大了1万倍）"""
    if not s:
        return 0
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*(亿|万)?\s*元', str(s))
    if not m:
        return 0
    n = float(m.group(1).replace(',', ''))
    u = m.group(2)
    if u == '亿':
        return round(n, 4)
    if u == '万':
        return round(n / 10000, 4)
    return round(n / 1e8, 4)


def fetch_detail(url):
    cmd = ['curl', '-s', '-m', '25', url, '-H', 'User-Agent: ' + UA]
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout.decode('utf-8', 'ignore')


def parse_detail(raw_html):
    """从候选人/定标公示详情页抽结构化情报"""
    txt = re.sub(r'\s+', ' ', strip_html(raw_html))
    d = {}
    m = re.search(r'招标人名称[:：]?\s*([^\s]{4,30}?(公司|中心|局|处|厂|所|院|集团|管委会))', txt)
    if m: d['buyer'] = m.group(1)
    m = re.search(r'(投标报价|中标价格|中标价|报价)[:：]?\s*([\d,.]+)\s*元', txt)
    if m: d['win_amt'] = parse_amt(m.group(2) + '元')
    m = re.search(r'(招标控制价|最高限价|控制价)[:：]?\s*([\d,.]+)\s*元', txt)
    if m: d['control'] = parse_amt(m.group(2) + '元')
    m = re.search(r'评标时间[:：]?\s*([\d年月日/时:\s]{6,22})', txt)
    if m: d['kb_time'] = m.group(1).strip()
    # 拟中标人（定标公示） / 第一中标候选人（评标公示）
    m = re.search(r'拟中标人[:：]?\s*([^\s]{6,80})', txt)
    if m: d['win'] = re.sub(r'[;；]\s*$', '', m.group(1))
    if not d.get('win'):
        m = re.search(r'第一中标候选人[名order序：:]*\s*([^\s]{6,60})', txt)
        if m: d['win'] = m.group(1)
    # 候选人表：<tr> 里 ≥3 个 <td> 且首列是数字
    cands = []
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', raw_html):
        tds = [html.unescape(re.sub(r'<[^>]+>', '', c)).strip()
               for c in re.findall(r'<td[^>]*>([\s\S]*?)</td>', tr)]
        if len(tds) >= 3 and tds[0].isdigit():
            nm = tds[1].replace(' ', '')[:60]
            if not nm or len(nm) < 4:
                continue
            q = parse_amt(''.join(tds[2:5]) + '元') if len(tds) > 2 else 0
            # 定标公示表第3列是「得票(分)」（个位数），不是报价；
            # parse_amt 会把它换算成 0.0007 亿这种假报价 —— 小于 100 万的丢弃
            if q < 0.01:
                q = 0
            cands.append({'n': nm, 'leader': (tds[2] if len(tds) > 2 else '')[:12],
                          'quote': q})
    if cands:
        d['cands'] = cands[:12]
    d['contacts'] = re.findall(r'联系人[:：]\s*([\u4e00-\u9fa5·]{2,6})\s*联系电话[:：]\s*(1[3-9]\d{9}|0\d{2,3}-?\d{7,8})', txt)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--city', default='南通')
    ap.add_argument('--days', type=int, default=0, help='增量天数（0=用已存 lastDate）')
    ap.add_argument('--backfill-days', type=int, default=0, help='首次回补天数')
    ap.add_argument('--detail', type=int, default=1, help='是否抓候选人/定标详情（0=只抓列表）')
    ap.add_argument('--detail-limit', type=int, default=0, help='本次最多抓多少个详情页')
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    fp = os.path.join(RAW, 'nt_lifecycle.json')
    old = {'items': [], 'last': {}}
    if os.path.exists(fp):
        try:
            old = json.load(open(fp, encoding='utf-8'))
        except Exception:
            pass
    items = {x['id']: x for x in old.get('items') or []}

    stop = time.strftime('%Y-%m-%d', time.localtime(
        time.time() - (args.backfill_days or args.days or 1) * 86400))
    print('[%s] 采集 stop_date=%s' % (args.city, stop))

    for cat, codes in CITIES[args.city]['cols'].items():
        for code in codes:
            got, last = list_col(args.city, cat, code, stop)
            new = 0
            for x in got:
                if x['id'] not in items:
                    items[x['id']] = x
                    new += 1
            if last:
                old.setdefault('last', {})[cat + ':' + code] = last
            print('  %-8s %s → %d 条(新 %d) 累计 %d' % (cat, code, len(got), new, len(items)))
            time.sleep(0.3)

    # 详情页：只抓 cand 类（评标情报所在）
    if args.detail:
        todo = [x for x in items.values()
                if x['cat'] == 'cand' and 'detail' not in x]
        if args.detail_limit:
            todo = todo[:args.detail_limit]
        print('详情页抽取：%d 个' % len(todo))
        for i, x in enumerate(todo):
            dh = fetch_detail(x['url'])
            x['detail'] = parse_detail(dh)
            if (i + 1) % 50 == 0:
                print('  %d/%d …' % (i + 1, len(todo)))
                json.dump({'updated': time.strftime('%F %T'),
                           'items': list(items.values()), 'last': old.get('last', {})},
                          open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
            time.sleep(0.4)

    data = {'updated': time.strftime('%F %T'),
            'items': list(items.values()), 'last': old.get('last', {})}
    json.dump(data, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
    n_det = sum(1 for x in data['items'] if x.get('detail'))
    print('✅ 共 %d 条，其中含评标详情 %d 条 → %s' % (len(data['items']), n_det, fp))


if __name__ == '__main__':
    main()
