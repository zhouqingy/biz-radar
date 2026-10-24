#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
三个新行业（数据中心 / 化肥 / 水泥）的「中资出海」项目采集。

为什么加这三个行业（2026-10-19 同事提议）：
  它们都是「产业出海 → 带动配套能源环保需求」的典型场景，与公司主业直接对口：
  · 水泥    —— 水泥窑余热发电 + 自备电厂 + 脱硝除尘，公司最成熟的市场
  · 数据中心 —— 巨量电力需求（光伏+储能+柴油发电机）+ 水冷/废水 + 海岛项目海水淡化
  · 化肥    —— 合成氨/磷化工高耗能，必配自备热电站 + 余热回收 + 废水零排放

数据源：巨潮资讯网公告（上市公司「对外投资/拟建/备案」公告，是质量最高的提前量：
有业主、有金额、有时间点，比发改委批复更早）。
边界：只返回标题无正文；未上市公司（海螺、红狮等）不在此渠道，靠竞对官网/新闻补。

产出：raw/sector_oversea.json，字段带 sector（行业）+ geo（国家/地区）+ stage（阶段）
"""
import os, re, sys, json, time, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(RAW, 'sector_oversea.json')
API = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'

SECTOR_KW = {
    '数据中心': ['数据中心', 'IDC', '算力', '智算', '超算', '人工智能计算'],
    '化肥': ['化肥', '合成氨', '尿素', '磷化工', '磷肥', '氮肥', '复合肥', '磷酸铁'],
    '水泥': ['水泥', '熟料', '水泥窑'],
}
# 出海热点地（中资产业出海最集中的国家/地区）
GEO = ['印尼', '越南', '老挝', '柬埔寨', '泰国', '马来西亚', '菲律宾', '缅甸',
       '沙特', '阿联酋', '伊拉克', '埃及', '摩洛哥', '土耳其',
       '几内亚', '赞比亚', '刚果', '津巴布韦', '坦桑尼亚', '埃塞俄比亚',
       '秘鲁', '智利', '巴西', '塞尔维亚', '哈萨克斯坦', '乌兹别克斯坦',
       '印度', '孟加拉', '巴基斯坦']
GEO_GENERIC = ['海外', '境外', '对外投资', '一带一路', '出海', '境外投资', '印尼']
# 出海动词：标题有这些也算出海（不要求出现具体国家名）
OVERSEA_VERB = ['对外投资', '海外投资', '境外投资', '海外建厂', '境外建厂', '出海',
                '海外生产基地', '境外生产基地', '海外项目', '境外项目']
# 噪音：财务投资、基金、理财、股权运作等不是产业项目出海，一律丢
NOISE = ['投资基金', '财务资助', '委托理财', '理财', '增资', '股权激励', '优先股',
         '募集资金', '募集', '减持', '回购', '担保', '授信', '借款', '委托贷款',
         '套期保值', '期货', '外汇', '银行', '股东', '权益变动', '业绩承诺',
         '发行', '分红', '章程', '董事会换届', '聘任', '辞职', '变更']
# 产业出海项目必须出现的实词
REAL = ['建设', '项目', '生产线', '基地', '工厂', '园区', '产线', '工程', 'EPC', '总承包',
        '开工', '投产', '竣工', '点火', '达产', '子公司', '产能', '装置', '机组']
# 阶段判定
STAGE = [
    ('已投产', ['投产', '竣工', '达产', '点火', '试生产', '商业运营']),
    ('在建', ['开工', '建设进展', '施工', '主体封顶', '安装']),
    ('已披露计划', ['拟', '计划', '董事会', '决议', '备案', '获批', '核准', '框架协议', '意向']),
    ('已签约', ['签约', '签订', '中标', '承接', '总承包']),
]
# 三行业中资出海的主力企业（按公司名检索其公告，比按行业词检索准得多：
# 出海公告标题通常是「关于对外投资设立XX子公司的公告」，不含行业词）
SECTOR_FIRMS = {
    '水泥': ['海螺水泥', '天山股份', '冀东水泥', '华新水泥', '塔牌集团', '上峰水泥',
             '万年青', '祁连山', '宁夏建材', '尖峰集团', '福建水泥', '四川双马', '亚泰集团'],
    '数据中心': ['润泽科技', '奥飞数据', '数据港', '光环新网', '科华数据', '依米康',
                 '佳力图', '英维克', '申菱环境', '网宿科技', '证通电子', '中贝通信', '恒为科技'],
    '化肥': ['云天化', '新洋丰', '史丹利', '金正大', '芭田股份', '川金诺', '澄星股份',
             '云图控股', '司尔特', '六国化工', '湖北宜化', '华鲁恒升', '鲁西化工',
             '阳煤化工', '兴发集团', '川恒股份', '司尔特'],
}

# 与本公司业务的关联点（用于页面展示"为什么与我们有关"）
LINK = {
    '数据中心': '供电（光伏+储能+柴油发电机）、变配电 EPC、水冷/废水处理、海岛项目海水淡化',
    '化肥': '自备热电站（煤/气发电）、余热回收、脱硫脱硝、废水零排放',
    '水泥': '水泥窑余热发电、自备电厂、脱硝除尘、余热供暖',
}


def q(key, days=500, column='szse'):
    end = time.strftime('%Y-%m-%d')
    st = time.strftime('%Y-%m-%d', time.localtime(time.time() - days * 86400))
    data = urllib.parse.urlencode({
        'pageNum': 1, 'pageSize': 50, 'column': column, 'tabName': 'fulltext',
        'plate': '', 'stock': '', 'searchkey': key, 'secid': '', 'category': '',
        'trade': '', 'seDate': '%s~%s' % (st, end),
        'sortName': '', 'sortType': '', 'isHLtitle': 'true'}).encode()
    r = urllib.request.Request(API, data=data, headers={
        'User-Agent': UA, 'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice'})
    return json.loads(urllib.request.urlopen(r, timeout=45).read().decode('utf-8'))


def guess_sector(t):
    for s, ws in SECTOR_KW.items():
        if any(w in t for w in ws):
            return s
    return ''


def guess_geo(t):
    for g in GEO:
        if g in t:
            return g
    for g in GEO_GENERIC:
        if g in t:
            return g
    return ''


def guess_stage(t):
    for st, ws in STAGE:
        if any(w in t for w in ws):
            return st
    return '未明确'


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    firms = []
    for sec, fs in SECTOR_FIRMS.items():
        for f in fs:
            firms.append((sec, f))
    keys = ['印尼', '越南', '沙特', '几内亚', '埃及', '摩洛哥', '秘鲁', '泰国', '赞比亚',
            '海外投资', '对外投资', '境外投资', '海外生产基地']
    print('按 %d 家出海企业检索公告（近 %d 天）' % (len(firms), days))
    FIRM_TASKS = firms

    seen, items = set(), []

    def take(sec_hint, r):
        for a in (r.get('announcements') or []):
            t = re.sub(r'</?em>', '', a.get('announcementTitle') or '')
            sec = guess_sector(t) or sec_hint
            if any(w in t for w in NOISE):
                continue                       # 财务类，不是产业项目
            if not any(w in t for w in REAL):
                continue                       # 没有实体项目词，说明不是建项目
            geo = guess_geo(t)
            verb = next((v for v in OVERSEA_VERB if v in t), '')
            if not geo and not verb:
                continue
            if not geo:
                geo = verb
            if t in seen:
                continue
            seen.add(t)
            items.append({'t': t, 'sec': re.sub(r'</?em>', '', a.get('secName', '')),
                          'sector': sec, 'geo': geo,
                          'stage': guess_stage(t),
                          'd': time.strftime('%Y-%m-%d', time.localtime(a['announcementTime'] / 1000)),
                          'url': 'http://static.cninfo.com.cn/' + (a.get('adjunctUrl') or '')})

    # A) 按企业名检索（主力来源）
    for sec, firm in FIRM_TASKS:
        for col in ('szse', 'sse'):
            r = None
            for _t in range(2):
                try:
                    r = q(firm, days, col); break
                except Exception:
                    time.sleep(1.5)
            if r:
                take(sec, r)
        time.sleep(0.4)

    # B) 按出海关键词检索（补充，捕获清单外的公司）
    for k in keys:
        for col in ('szse', 'sse'):
            r = None
            for _try in range(3):
                try:
                    r = q(k, days, col); break
                except Exception as e:
                    if _try == 2:
                        print('  [%s/%s] 失败 %s' % (k, col, type(e).__name__))
                    time.sleep(2.5)
            if r is None:
                continue
            for a in (r.get('announcements') or []):
                t = re.sub(r'</?em>', '', a.get('announcementTitle') or '')
                sec = guess_sector(t)
                if not sec:
                    continue
                if any(w in t for w in NOISE):
                    continue
                if not any(w in t for w in REAL):
                    continue
                geo = guess_geo(t)
                verb = next((v for v in OVERSEA_VERB if v in t), '')
                if not geo and not verb:
                    continue          # 行业命中后，还要有出海证据（地名 或 出海动词）
                if not geo:
                    geo = verb
                if t in seen:
                    continue
                seen.add(t)
                items.append({
                    't': t, 'sec': re.sub(r'</?em>', '', a.get('secName', '')),
                    'sector': sec, 'geo': geo,
                    'stage': guess_stage(t),
                    'd': time.strftime('%Y-%m-%d', time.localtime(a['announcementTime'] / 1000)),
                    'url': 'http://static.cninfo.com.cn/' + (a.get('adjunctUrl') or ''),
                })
        time.sleep(1.2)

    items.sort(key=lambda z: z['d'], reverse=True)
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': items},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    from collections import Counter
    print('\n命中 %d 条' % len(items))
    print('行业:', dict(Counter(x['sector'] for x in items)))
    print('地区:', dict(Counter(x['geo'] for x in items).most_common(8)))
    print('阶段:', dict(Counter(x['stage'] for x in items)))
    for x in items[:10]:
        print('  [%s/%s/%s] %s | %s' % (x['sector'], x['geo'], x['stage'], x['t'][:52], x['sec'][:10]))


if __name__ == '__main__':
    main()
