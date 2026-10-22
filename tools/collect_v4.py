#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四地公共资源交易平台增量采集器 · collect_v4.py

为什么重写：
  老流程的数据靠手工跑，9 月 380 条、10 月只剩 44 条。根因有三：
    1) 江苏站只解析出 IPv6（240e:...），沙箱 IPv6 不通 → 整站抓不到
       实际 getent ahostsv4 能拿到 180.101.234.24，走 http 即可
    2) HTTPS 对该站不可用，必须用 http
    3) 没有定时任务，全靠手动

接口：/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew
  江苏、浙江、合肥三站同构（ES 全文检索），上海站单独处理。

关键参数（从 sites 的 transactionInformation.js 逆出）：
  sdt/edt  起止日期
  wd       关键词
  sort     {"infodatepx":"0"} → 按发布时间倒序（"0"=倒序，不是 ASC）
  cnum     001=交易信息
  rn       每页条数

用法：
  python3 collect_v4.py --days 7                # 最近 7 天
  python3 collect_v4.py --days 30 --out x.json  # 最近 30 天，指定输出
  python3 collect_v4.py --days 7 --merge        # 并入主库 raw/industry.json
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'

# 站点配置：base 是接口前缀，host 是原文域名前缀
SITES = {
    '江苏': {
        'api': 'http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'http://jsggzy.jszwfw.gov.cn',
        'plat': '江苏省公共资源交易平台',
        'level': '省级',
    },
    '浙江': {
        'api': 'https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://ggzy.zj.gov.cn',
        'plat': '浙江省公共资源交易服务平台',
        'level': '省级',
    },
    '合肥': {
        'api': 'https://ggzy.hefei.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://ggzy.hefei.gov.cn',
        'plat': '合肥公共资源交易中心',
        'level': '市级',
        'sort': '{"webdate":"0"}',     # 合肥没有 infodatepx 字段，用 webdate
    },
    # 2026-10-21 新增：市级站就是「最原始发布平台」，公告和附件都在这里，
    # 省级平台上的同名公告往往只是转发。probe_sites.py 实测三者接口同构可用。
    '苏州': {
        'api': 'https://ggzy.suzhou.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://ggzy.suzhou.gov.cn',
        'plat': '苏州市公共资源交易中心',
        'level': '市级', 'rg': '江苏',
        'sort': '{"infodate":"0"}',    # 苏州只认 infodate
    },
    '常州': {
        'api': 'https://ggzy.changzhou.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew',
        'host': 'https://ggzy.changzhou.gov.cn',
        'plat': '常州市公共资源交易中心',
        'level': '市级', 'rg': '江苏',
        'sort': '{"webdate":"0"}',
    },
    # 市级站要归到省：合肥归安徽
}
# 省份归属：市级站点按所属省写库
PROV_OF = {'江苏': '江苏', '浙江': '浙江', '合肥': '安徽',
           '苏州': '江苏', '常州': '江苏'}

# 关键词：精准优先。宽泛词（如光「污水」）会带出大量村级管网小工程，
# 对设计院/EPC 毫无价值，一律换成带业务属性的组合词。
KW_CORE = ['热电联产', '热电', '背压', '供热', '热网', '余热发电', '余热利用',
           '煤气发电', '燃气发电', '燃气轮机', '锅炉', '汽轮机', '发电机组',
           '电厂', '超超临界', '燃煤', '综合能源', '能源站', '集中供冷']
KW_ENV = ['脱硫', '脱硝', '除尘', '超低排放', '烟气治理', '烟气脱硫',
          '废水零排放', '零排放', '工业废水', '高盐废水', '脱硫废水', '中水回用',
          '土壤修复', '场地修复', '地下水修复', '生态修复', '污染地块',
          'VOCs', '挥发性有机物']
KW_ENERGY = ['光伏', '储能', '新能源', '多能互补', '源网荷储', '绿电', '氢能']
KW_ALL = KW_CORE + KW_ENV + KW_ENERGY

# 明显不相关的标题（房屋招租、食堂、绿化养护等）
KW_NOISE = ['房屋招租', '招租', '租赁权', '食堂', '食材', '绿化养护', '保洁', '物业', '印刷',
            '车辆', '保险', '会计', '审计服务', '法律服务', '服装', '家具', '办公设备',
            '医院', '学校', '幼儿园', '学生', '宿舍', '运动场', '球场', '停车场',
            '电梯', '空调采购', '办公用品', '保安', '劳务派遣', '会议服务', '酒店']

# 工程类信号：电力/能源工程的实质标的
KW_ENGINEER = ['EPC', '总承包', '设计', '勘察', '施工', '安装', '改造', '技改', '扩建',
               '新建', '工程', '设备采购', '成套', '系统集成']


def is_noise(title):
    if any(n in title for n in KW_NOISE):
        return True
    # 纯房屋/土地类交易
    if ('房屋' in title or '厂房' in title or '地块' in title) and ('出租' in title or '出让' in title or '产权' in title):
        return True
    # 村级/乡镇小市政：管网、泵站、接管、保洁类，设计院不参与
    small = ['村', '乡镇', '镇区', '社区', '小区']
    smallwork = ['管网', '泵站', '接管', '疏通', '清淤', '巡查', '托管', '维修养护',
                 '保洁', '垃圾亭', '公厕', '村道', '户户通', '十必接']
    if any(s in title for s in small) and any(w in title for w in smallwork):
        return True
    return False


def post(api, payload, timeout=45, retry=2):
    body = json.dumps(payload, ensure_ascii=False)
    for k in range(retry + 1):
        p = subprocess.run(
            ['curl', '-s', '-m', str(timeout), '-X', 'POST', api,
             '-H', 'Content-Type: application/json;charset=utf-8',
             '-H', 'User-Agent: ' + UA, '-d', body],
            capture_output=True, text=True)
        try:
            o = json.loads(p.stdout)
            # 苏州/常州/合肥等市级站是双层嵌套：{"code":200,"content":"{\"result\":{...}}"}
            # content 是**转义后的 JSON 字符串**，必须二次解析，否则永远取不到 result。
            inner = o.get('content') if isinstance(o, dict) else None
            if isinstance(inner, str):
                o = json.loads(inner)
            return o['result']
        except Exception:
            if k < retry:
                time.sleep(1.5)
    return None


def mk(**kw):
    pm = {
        'token': '', 'pn': 0, 'rn': '50', 'sdt': '', 'edt': '',
        'wd': '', 'inc_wd': '', 'exc_wd': '',
        'fields': 'title', 'cnum': '001', 'sort': '{"infodatepx":"0"}', 'ssort': 'title',
        'cl': 200, 'terminal': '', 'condition': None, 'time': None,
        'highlights': 'title', 'statistics': None, 'unionCondition': None,
        'opCondition': None, 'opType': 0, 'accuracy': '',
        'noParticiple': '', 'searchRange': None, 'isBusiness': '1',
    }
    pm.update(kw)
    return pm


def clean(s):
    """去掉高亮标签和多余空白"""
    s = re.sub(r'<em[^>]*>|</em>', '', s or '')
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def grade(title):
    """排级：A=热电/电力工程实质标的，B=环保能源相关，C=可能沾边
    关键改进：命中核心词但属于纯设备零购/租赁/后勤的，降到 C。"""
    core = any(k in title for k in KW_CORE)
    env = any(k in title for k in KW_ENV)
    energy = any(k in title for k in KW_ENERGY)
    eng = any(k in title for k in KW_ENGINEER)
    if core and eng:
        return 'A'
    if (core or env) and eng:
        return 'B'
    if env or energy:
        return 'B'
    if core:
        return 'C'   # 如「医院燃气锅炉采购」——有关键词但没有工程属性
    return 'C'


def stage_of(title):
    if '中标候选人' in title:
        return '中标候选人公示'
    if '中标结果' in title or '中标公告' in title or '成交公告' in title:
        return '中标结果公示'
    if '招标公告' in title or '采购公告' in title or '招标信息' in title:
        return '招标公告'
    if '变更' in title or '澄清' in title or '更正' in title:
        return '变更公告'
    if '合同' in title:
        return '合同公告'
    if '终止' in title or '废标' in title or '流标' in title:
        return '终止公告'
    return '其他公告'


def fetch_site(name, cfg, sdt, edt, per_kw=200, pause=0.35):
    """按关键词逐个检索，聚合并去重

    2026-10-21 踩坑：fields 里塞了 zhuanzainew / zhuanzai / webdate 这些
    市级站（合肥、苏州）根本不存在（也没建索引）的字段时，接口不报错，
    而是直接返回 {"result":{"error":null}}——没有 totalcount、没有 records。
    看起来像"0 条命中"，实际是查询作废。所以 fields 必须按站配置，
    且 post() 要能识别双层嵌套 {code, content:"..."}。
    """
    seen = {}
    stat = []
    # 字段按站配置：市级站（合肥/常州）没有 infodate 的索引，带上就整条查询作废。
    # 默认给最小集 title，返回体里 webdate / infoid / categorynum 都自带，够用了。
    fields = cfg.get('fields', 'title')
    for kw in KW_ALL:
        got = 0
        rn = 50
        page = 0
        while got < per_kw:
            r = post(cfg['api'], mk(sdt=sdt, edt=edt, wd=kw, pn=page * rn,
                                    rn=str(rn), fields=fields,
                                    sort=cfg.get('sort', '{"infodatepx":"0"}')))
            if not r:
                break
            recs = r.get('records') or []
            if not recs:
                break
            for x in recs:
                title = clean(x.get('title'))
                if not title:
                    continue
                if is_noise(title):
                    continue
                uid = x.get('infoid') or x.get('id') or hashlib.md5(
                    (title + (x.get('infodate') or '')).encode()).hexdigest()
                if uid in seen:
                    continue
                link = x.get('linkurl') or ''
                seen[uid] = {
                    'id': hashlib.md5((cfg['plat'] + uid).encode()).hexdigest()[:10],
                    't': title,
                    'rg': PROV_OF.get(name, name),
                    'st': stage_of(title),
                    'g': grade(title),
                    'd': (x.get('infodate') or x.get('infodatepx') or '')[:10],
                    'p': cfg['plat'],
                    'platLevel': cfg['level'],
                    'srcType': 'official',
                    'url': (cfg['host'] + link) if link.startswith('/') else link,
                    'attach': clean(x.get('attachname') or ''),
                    'cat': x.get('categorynum') or '',
                    'author': clean(x.get('author') or ''),
                    'sdt': sdt, 'edt': edt,
                }
                got += 1
            total = r.get('totalcount') or 0
            page += 1
            if (page * rn) >= min(total, per_kw):
                break
            time.sleep(pause)
        stat.append((kw, got))
        time.sleep(pause)
    return list(seen.values()), stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7, help='抓最近多少天')
    ap.add_argument('--perkw', type=int, default=200, help='每个关键词最多取多少条')
    ap.add_argument('--sites', default='江苏,浙江,合肥')
    ap.add_argument('--out', default='')
    ap.add_argument('--merge', action='store_true', help='并入 raw/industry.json')
    args = ap.parse_args()

    today = datetime.date.today()
    sdt = (today - datetime.timedelta(days=args.days)).isoformat()
    edt = today.isoformat()
    print('[collect_v4] %s ~ %s · 站点：%s' % (sdt, edt, args.sites))

    allitems = []
    report = {}
    for name in [x.strip() for x in args.sites.split(',') if x.strip()]:
        cfg = SITES.get(name)
        if not cfg:
            print('  跳过未知站点', name)
            continue
        t0 = time.time()
        items, stat = fetch_site(name, cfg, sdt, edt, args.perkw)
        hit = [(k, v) for k, v in stat if v]
        print('  %-4s 取回 %-4d 条（关键词命中 %d/%d）耗时 %.0fs'
              % (name, len(items), len(hit), len(stat), time.time() - t0))
        if hit:
            print('       ' + ' · '.join('%s:%d' % (k, v) for k, v in sorted(hit, key=lambda z: -z[1])[:8]))
        report[name] = {'n': len(items), 'kw': dict(stat)}
        allitems.extend(items)

    # 去重（跨站可能有转载）
    uniq = {}
    for x in allitems:
        key = (x['t'], x['d'])
        if key not in uniq:
            uniq[key] = x
    items = sorted(uniq.values(), key=lambda z: z['d'], reverse=True)

    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'window': [sdt, edt],
        'total': len(items),
        'byGrade': {g: sum(1 for x in items if x['g'] == g) for g in 'ABC'},
        'bySite': report,
        'items': items,
    }
    path = args.out or os.path.join(RAW, 'collect_%s.json' % today.isoformat())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n合计去重 %d 条 · A级 %d / B级 %d / C级 %d → %s'
          % (len(items), out['byGrade']['A'], out['byGrade']['B'], out['byGrade']['C'], path))

    # 打印最新 A 级，肉眼验一下
    top = [x for x in items if x['g'] == 'A'][:12]
    if top:
        print('\n最新 A 级（热电核心）：')
        for x in top:
            print('  %s [%s] %s' % (x['d'], x['st'][:5], x['t'][:56]))

    if args.merge:
        merge(path)


def merge(path):
    """把采集结果并入分省主库 raw/{省份拼音}.json
    主库是 list[dict]，字段与老格式对齐（金额单位是元，不是万元）。"""
    PROV_FILE = {'江苏': 'jiangsu.json', '浙江': 'zhejiang.json',
                 '安徽': 'anhui.json', '上海': 'shanghai.json'}
    new = json.load(open(path, encoding='utf-8'))['items']
    byp = {}
    for x in new:
        byp.setdefault(x['rg'], []).append(x)

    grand_add = 0
    for rg, rows in byp.items():
        fn = PROV_FILE.get(rg)
        if not fn:
            continue
        mp = os.path.join(RAW, fn)
        old = json.load(open(mp, encoding='utf-8')) if os.path.exists(mp) else []
        if isinstance(old, dict):
            old = old.get('items', [])
        have = set()
        for x in old:
            t = re.sub(r'\s+', '', x.get('t') or '')
            have.add((t, (x.get('d') or '')[:10]))
        added = 0
        for x in rows:
            k = (re.sub(r'\s+', '', x['t']), x['d'])
            if k in have:
                continue
            have.add(k)
            old.append({
                't': x['t'], 'city': '', 'rg': x['rg'], 'st': x['st'],
                'buyer': '', 'win': '', 'amt': None, 'amtTxt': '',
                'd': x['d'], 'dl': None, 'p': x['p'], 'url': x['url'],
                'mode': '', 'snip': '', 'attach': x.get('attach') or '',
                'platLevel': x.get('platLevel'), 'srcType': 'official',
            })
            added += 1
        json.dump(old, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        grand_add += added
        print('  [merge] %s: %d → %d（新增 %d）' % (fn, len(old) - added, len(old), added))
    print('[merge] 合计新增 %d 条' % grand_add)


if __name__ == '__main__':
    main()
