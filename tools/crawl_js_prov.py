#!/usr/bin/env python3
"""江苏省公共资源交易平台（省站 jsggzy.jszwfw.gov.cn）采集器
═══════════════════════════════════════════════
2026-10-24 破解：全省 13 市公告归集到省站一个 ES 全文检索接口，
POST JSON /inteligentsearch/rest/esinteligentsearch/getFullTextDataNew
  - cnum="001"（建设工程体系）
  - condition 过滤 categorynum + zhuanzai(地市，如"南通市")
  - time 过滤 infodate（按月切块翻页，避免深分页）
栏目编号（已实测枚举）：
  003001010 招标计划 21868 | 003001001 招标公告 121339
  003001007 中标候选人公示 114651 | 003001008 中标结果公告 113879
  003001011 中标合同 17837（暂不采）
  （水利 003002xxx / 交通 003003xxx / 政采 003004xxx / 产权 003006xxx 暂不采）
记录自带 content 摘要（含招标人等），详情页 linkurl 可直接 GET。
注意：该站证书链异常，requests 需 verify=False（脚本用 curl -k）。
schema 与 nt_lifecycle/ah_lifecycle 一致，build_data/build_web 直接复用。
合法合规：法定公开公告，0.35s/请求，不碰登录，仅内部决策用。
"""
import json, os, re, sys, time, argparse, subprocess, datetime, gzip

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
OUT = os.path.join(RAW, 'js_lifecycle.json')

CATS = {'plan': '003001010', 'notice': '003001001',
        'cand': '003001007', 'result': '003001008',
        # 2026-10-24 用户确认接入：水利 / 交通 / 政府采购三个体系
        'sl-plan': '003002005', 'sl-notice': '003002001',
        'sl-cand': '003002003', 'sl-result': '003002004',
        'jt-plan': '003003005', 'jt-notice': '003003001',
        'jt-cand': '003003003', 'jt-result': '003003004',
        'cg-notice': '003004002', 'cg-result': '003004006'}
CITIES = ['南京市', '无锡市', '徐州市', '常州市', '苏州市', '南通市', '连云港市',
          '淮安市', '盐城市', '扬州市', '镇江市', '泰州市', '宿迁市']

BASE = 'https://jsggzy.jszwfw.gov.cn'
API = BASE + '/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew'


def fetch(url, data=None):
    cmd = ['curl', '-sk', '-m', '30', url, '-H', 'User-Agent: ' + UA,
           '-H', 'Referer: ' + BASE + '/']
    if data is not None:
        cmd += ['-X', 'POST', '-H', 'Content-Type: application/json;charset=utf-8',
                '--data', data]
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout.decode('utf-8', 'ignore')


def query(cat_num, city, d1, d2, pn, rn=100):
    """按栏目+地市+日期区间(含)翻一页；d1/d2 'YYYY-MM-DD HH:MM:SS'"""
    p = {
        "token": "", "pn": pn, "rn": rn, "sdt": "", "edt": "", "wd": "",
        "inc_wd": "", "exc_wd": "", "fields": "title", "cnum": "001",
        "sort": '{"infodatepx":"0"}', "ssort": "title", "cl": 200,
        "terminal": "", "time": None, "highlights": "title",
        "statistics": None, "unionCondition": None, "accuracy": "",
        "noParticiple": "1", "isBusiness": "1",
        "condition": [
            {"fieldName": "categorynum", "isLike": True, "likeType": 2,
             "equal": cat_num, "equalList": None},
            {"fieldName": "zhuanzai", "isLike": True, "likeType": 2,
             "equal": city, "equalList": None},
        ],
    }
    if d1:
        p['time'] = json.dumps([{"fieldName": "infodate", "startTime": d1,
                                 "endTime": d2, "index": 1}])
    txt = fetch(API, json.dumps(p, ensure_ascii=False))
    try:
        return json.loads(txt).get('result') or {}
    except Exception:
        return {}


def strip_hl(s):
    return re.sub(r'</?em[^>]*>', '', s or '')


def crawl_city_cat(cat, cat_num, city, days):
    """按月切块采集一个(栏目,地市)组合"""
    items, seen = [], set()
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    cur = start
    empty_streak = 0
    while cur <= end:
        nxt = min(datetime.date(cur.year, cur.month, 1), end)
        # 本月块：cur ~ 月末 或 end
        if cur.month == 12:
            me = datetime.date(cur.year, 12, 31)
        else:
            me = datetime.date(cur.year, cur.month + 1, 1) - datetime.timedelta(days=1)
        me = min(me, end)
        d1 = cur.strftime('%Y-%m-%d') + ' 00:00:00'
        d2 = me.strftime('%Y-%m-%d') + ' 23:59:59'
        total = None
        pn, blank = 0, 0
        while True:
            res = query(cat_num, city, d1, d2, pn)
            total = int(res.get('totalcount') or 0)
            recs = res.get('records') or []
            if not recs:
                blank += 1
                if blank >= 2:
                    break
            for r in recs:
                iid = '江苏:' + (r.get('infoid') or r.get('id') or str(len(items)))
                if iid in seen:
                    continue
                seen.add(iid)
                items.append({
                    'id': iid, 'city': city.rstrip('市'), 'rg': '江苏',
                    'cat': cat, 't': strip_hl(r.get('title') or ''),
                    'd': (r.get('infodateformat') or (r.get('infodate') or '')[:10]),
                    'url': BASE + (r.get('linkurl') or ''),
                    'area': r.get('zhuanzainew') or city,
                    'snip': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ',
                                   strip_hl(r.get('content') or '')))[:300],
                })
            pn += len(recs)
            if pn >= total or not recs:
                break
            time.sleep(0.35)
        cur = me + datetime.timedelta(days=1)
    print('  %-4s %-14s %6d 条' % (cat, city, len(items)), flush=True)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill-days', type=int, default=3)
    ap.add_argument('--cats', default='plan,notice,cand,result,sl-plan,sl-notice,sl-cand,sl-result,jt-plan,jt-notice,jt-cand,jt-result,cg-notice,cg-result')
    ap.add_argument('--cities', default='')
    args = ap.parse_args()
    cats = {k: v for k, v in CATS.items() if k in args.cats.split(',')}
    cities = [c for c in CITIES if not args.cities or c in args.cities.split(',')]

    # gz 兼容：CI 里仓库只存 .gz（省体积），读到哪个用哪个
    old = []
    for _p in (OUT, OUT + '.gz'):
        if os.path.exists(_p):
            try:
                old = json.load(gzip.open(_p, 'rt', encoding='utf-8') if _p.endswith('.gz') else open(_p)).get('items', [])
                break
            except Exception:
                old = []
    known = {x['id'] for x in old}
    allitems = list(old)

    for cat, num in cats.items():
        for city in cities:
            got = crawl_city_cat(cat, num, city, args.backfill_days)
            add = [x for x in got if x['id'] not in known]
            known.update(x['id'] for x in add)
            allitems += add

    os.makedirs(RAW, exist_ok=True)
    json.dump({'items': allitems}, open(OUT, 'w'), ensure_ascii=False)
    print('总计 %d 条 -> %s' % (len(allitems), OUT))


if __name__ == '__main__':
    main()
