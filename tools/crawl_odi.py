#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""境外投资备案采集（浙江投资在线审批平台）2026-11-04

为什么这条线值得单独做
----------------------
49 号文之后，境内企业**所有**境外投资都要在发改委备案，备案信息里就带
「投向哪个国家、投多少、干什么」。这是一条比新闻稿更靠前、更硬的信息源 ——
新闻出来的时候往往已经签完谅解备忘录了，备案是**可查、可核实**的第一手登记。

实测到的样本长这样（项目名本身就带金额）：
    南华期货…向横华国际增资1.54亿美元用于境外期货经纪业务和清算等项目
    天能电池集团…在越南设立天能越南新能源有限责任公司项目
    浙江罗尔科精密…在摩洛哥建设年产能3000吨金属成型零部件项目

接口为什么这么绕
----------------
`publicannouncement.do?method=itemList` 只认一个过滤参数 `item_name`（项目名关键词），
试过 item_type / ITEM_TYPE / type 全都不生效（返回全库 246046 条，说明被忽略）。
而「境外投资」这个词在项目名里几乎不出现（counts=1）—— 因为名字写的是
「在XX国新设/并购/增资…」。所以只能**按国家名穷举**捞，再去重。

这是有代价的：没被我列进国家表的小国（比如东帝汶、斐济）会漏。
但主要投资目的地都盖住了，实测「中国香港」一人就 406 条。
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
API = 'https://tzxm.zjzwfw.gov.cn/publicannouncement.do?method=itemList'
HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Referer': 'https://tzxm.zjzwfw.gov.cn/tzxmweb/ztwpages/resultsPublicity/'
               'notice_of_publicity_new.html',
}

# 国家/地区表：按大洲分组，方便后面标 region
GEO = {
    '东南亚': ['越南', '印尼', '印度尼西亚', '泰国', '马来西亚', '柬埔寨', '老挝',
               '菲律宾', '新加坡', '缅甸', '文莱', '东帝汶'],
    '南亚中东': ['印度', '孟加拉', '巴基斯坦', '斯里兰卡', '沙特', '阿联酋', '迪拜',
                 '卡塔尔', '巴林', '阿曼', '科威特', '约旦', '以色列', '土耳其',
                 '伊朗', '伊拉克'],
    '非洲': ['埃及', '摩洛哥', '阿尔及利亚', '突尼斯', '尼日利亚', '埃塞俄比亚',
             '肯尼亚', '坦桑尼亚', '南非', '加纳', '几内亚', '刚果', '赞比亚',
             '津巴布韦', '马里', '乌干达', '卢旺达', '塞内加尔', '科特迪瓦',
             '莫桑比克', '安哥拉', '纳米比亚', '博茨瓦纳', '苏丹', '利比亚'],
    '欧洲': ['匈牙利', '波兰', '德国', '荷兰', '法国', '西班牙', '意大利', '葡萄牙',
             '塞尔维亚', '罗马尼亚', '保加利亚', '捷克', '斯洛伐克', '奥地利',
             '瑞士', '瑞典', '丹麦', '芬兰', '挪威', '比利时', '爱尔兰', '英国',
             '俄罗斯', '乌克兰', '白俄罗斯', '卢森堡', '希腊', '克罗地亚'],
    '中亚独联体': ['哈萨克斯坦', '乌兹别克斯坦', '塔吉克斯坦', '吉尔吉斯斯坦',
                   '土库曼斯坦', '阿塞拜疆', '格鲁吉亚', '亚美尼亚', '蒙古'],
    '美洲': ['美国', '墨西哥', '巴西', '智利', '阿根廷', '秘鲁', '哥伦比亚',
             '厄瓜多尔', '委内瑞拉', '加拿大', '巴拿马', '哥斯达黎加', '古巴'],
    '大洋洲': ['澳大利亚', '新西兰', '斐济', '巴布亚新几内亚'],
    '港澳台': ['中国香港', '香港', '中国澳门', '澳门', '中国台湾', '台湾'],
}
# 日本韩国单独放，避免「韩国」误吃「韩国商人」之类；反正只是打标签用
GEO['东亚'] = ['日本', '韩国']

GEO_ORDER = []   # 长名优先，防止「印度」吃掉「印度尼西亚」
for _reg, _ks in GEO.items():
    for _k in _ks:
        GEO_ORDER.append((_k, _reg))
GEO_ORDER.sort(key=lambda x: -len(x[0]))

# 动词 → 投资方式
ACT = [('新设', '新设子公司/机构'), ('设立', '新设子公司/机构'), ('投资设立', '新设子公司/机构'),
       ('并购', '并购'), ('收购', '并购'), ('增资', '增资扩股'),
       ('建设', '绿地建厂'), ('新建', '绿地建厂'), ('投资建设', '绿地建厂'),
       ('合资', '合资'), ('参股', '参股'), ('上市', '境外上市'),
       ('分拆', '境外上市'), ('发行', '境外上市'), ('债券', '境外融资')]

# 金额：实测写法混杂，统一折成亿美元
# 币种列表是实测出来的，别凭想象加 —— 690 条里真实出现过的只有这几种：
#   万美元 24 / 万欧元 3 / 亿美元 1 / 万美金 1
# 坑：名字里大量「1.76万吨」「100万件」是产能不是钱，正则必须绑死币种后缀；
# 早先版本把「万元」也算进去，结果「1000万元产值」被当成投资额。
_RE_MONEY = re.compile(
    r'(\d+(?:\.\d+)?)\s*(亿美元|亿美金|万美元|万美金|亿元|万元|'
    r'亿欧元|万欧元|亿日元|万日元|亿港元|万港元|亿港币|万港币|'
    r'亿卢比|万卢比|亿韩元|万韩元|亿英镑|万英镑|亿卢布|万卢布|'
    r'亿泰铢|万泰铢|亿新币|万新币|亿澳元|万澳元|亿加元|万加元)', re.I)
_MONEY_K = {'亿美元': 1.0, '亿美金': 1.0, '亿元': 1.0,
            '万美元': 0.0001, '万美金': 0.0001, '万元': 0.0001,
            '亿欧元': 1.08, '万欧元': 0.000108,      # 按 1 EUR≈1.08 USD 粗折
            '亿日元': 0.0065, '万日元': 0.00000065,
            '亿港元': 1.0, '亿港币': 1.0, '万港元': 0.0001, '万港币': 0.0001,
            '亿卢比': 1.0, '万卢比': 0.0001,
            '亿韩元': 0.00072, '万韩元': 0.000000072,
            '亿英镑': 1.27, '万英镑': 0.000127,
            '亿卢布': 0.011, '万卢布': 0.0000011,
            '亿泰铢': 0.028, '万泰铢': 0.0000028,
            '亿新币': 0.74, '万新币': 0.000074,
            '亿澳元': 0.66, '万澳元': 0.000066,
            '亿加元': 0.73, '万加元': 0.000073}

# 业务相关性：我们做的是工业水、热电、余热、环保，纯金融/贸易/电商的境外备案没价值
BIZ_HIT = ('能源', '电力', '热电', '发电', '光伏', '风电', '储能', '电池', '新能源',
           '环保', '环境', '水务', '水处理', '污水', '固废', '资源', '循环',
           '冶金', '冶炼', '钢铁', '有色', '铜', '铝', '镍', '锂', '钴', '材料',
           '化工', '化纤', '水泥', '造纸', '纺织', '印染', '医药', '食品',
           '工业园', '产业园', '经济特区', '基础设施', '建设', '工程',
           '矿业', '矿产', '冶炼厂', '不锈钢', '碳素', '炭素')
BIZ_NOISE = ('期货', '证券', '基金', '融资租赁', '保理', '跨境电商', '贸易有限公司',
             '国际贸易', '进出口', '商务咨询', '企业管理咨询', '投资管理',
             '品牌管理', '文化传媒', '影视', '游戏', '酒店管理', '餐饮')


def _req(kw, page=0, size=50, retry=2):
    d = urllib.parse.urlencode({'item_name': kw, 'pageNo': str(page),
                                'pageSize': str(size)}).encode()
    for i in range(retry + 1):
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(API, data=d, headers=HDR), timeout=25)
            j = json.loads(r.read().decode('utf-8', 'ignore'))
            blk = j[0] if isinstance(j, list) else j
            return int(blk.get('counts') or 0), blk.get('itemList') or []
        except Exception:
            if i == retry:
                return -1, []
            time.sleep(1.2 * (i + 1))


def pull():
    """按国家名穷举拉全量。同一项目会因多个国家关键词/分页被重复拉，靠 deal_code 去重。"""
    seen = {}
    stat = []
    for kw, reg in GEO_ORDER:
        c, lst = _req(kw, 0, 50)
        if c < 0:
            stat.append((kw, -1, 0))
            continue
        got = list(lst)
        # 超过 50 条就翻页
        page = 1
        while len(got) < c and page < 12:
            c2, more = _req(kw, page, 50)
            if not more:
                break
            got.extend(more)
            page += 1
        n_new = 0
        for it in got:
            code = it.get('deal_code') or it.get('SENDID') or it.get('projectuuid')
            nm = it.get('apply_project_name') or ''
            # 只留真的境外投资备案（名字里必须带境外地名，防国家名撞车：
            # 「马里」会吃「马里奥」、「刚果」偶尔吃公司名）
            if not code or code in seen:
                continue
            if not _find_geo(nm):
                continue
            if '境外' not in (it.get('ITEM_NAME') or '') and not _find_geo(nm):
                continue
            seen[code] = it
            n_new += 1
        stat.append((kw, c, n_new))
        time.sleep(0.4)
    return list(seen.values()), stat


def _find_geo(name):
    """从项目名里认国家/地区。

    防误判是硬需求 —— 实测栽过：「韩国强（韩科迪）17KW非自然人户用屋顶分布式光伏」
    被「韩国」吃掉，一条乡村户用光伏混进了境外投资库。所以：
      · 国家名后面紧跟「强/省/人/货/城/剧」这类字的，判为撞名，跳过
      · 「印度」后面是「尼西亚」时归印尼（靠长名优先已经处理）
    """
    n = name or ''
    # 「中国奥地利人工智能与先进制造联合实验室」——「中国+国名」是联合机构名，
    # 不是投到那个国家去的项目。实测被它混进来一条。
    if re.match(r'^中国(?!香港|澳门|台湾)', n) and not re.search(r'在|向|对', n):
        return None
    # 户用/屋顶小额光伏一律不算对外投资 —— 实测混进来
    # 「龙港市骊泰新能源有限责任公司（王荷兰）20kW分布式光伏项目」，
    # 「荷兰」其实是人名「王荷兰」。带括号人名 + kW 级，直接判否。
    if re.search(r'\d+\s*k[wW]\b', n) and re.search(r'[（(][^）)]{2,4}[）)]', n):
        return None
    # 「建德国家气象观测站」——「建德国家」里有「德国」，是地名撞车
    if '国家' in n and not re.search(r'在|向|对|投资', n):
        return None
    BAD_NEXT = {'强', '省', '人', '货', '城', '剧', '语', '式', '商', '药', '菜', '餐'}
    for k, reg in GEO_ORDER:
        p = n.find(k)
        while p >= 0:
            nxt = n[p + len(k): p + len(k) + 1]
            if nxt and nxt in BAD_NEXT:
                p = n.find(k, p + 1)
                continue
            return k, reg
    return None


def parse_item(it):
    nm = (it.get('apply_project_name') or '').strip()
    g = _find_geo(nm) or ('', '')
    geo, region = g
    m = _RE_MONEY.search(nm)
    usd = None
    money_txt = ''
    if m:
        usd = round(float(m.group(1)) * _MONEY_K.get(m.group(2).lower().replace('usd', '美元'), 0), 4)
        money_txt = m.group(0)
    act = ''
    for w, a in ACT:
        if w in nm:
            act = a
            break
    # 业主：优先按公司后缀截，比按「在/向/对」切稳得多。
    # 原写法对「浙江逸腾药业有限公司年产500吨缬沙坦…」这种没有介词的名字会整条返回，
    # 结果页面「投资主体」和「备案项目」两列内容一模一样（截图里一眼就看出来了）。
    # 别再放「集团」当备选项 —— 正则非贪婪，遇到「杭氧集团股份有限公司」会在「集团」处
    # 提前停，owner 变成「杭氧集团」，剩下的「股份有限公司」留在项目列开头，很难看。
    mo = re.match(r'^(.{2,40}?(?:股份有限公司|有限责任公司|有限公司|控股公司|集团))', nm)
    if mo and mo.group(1).endswith('集团'):
        _m2 = re.match(r'^(\S{2,40}?(?:股份有限公司|有限责任公司|有限公司))', nm)
        if _m2:
            mo = _m2
    if mo:
        owner = mo.group(1)
    else:
        owner = re.split(r'在|向|对|与|通过', nm)[0][:30]
    owner = re.sub(r'^(关于)?', '', owner).strip(' ，,、')
    biz = [w for w in BIZ_HIT if w in nm]
    noise = [w for w in BIZ_NOISE if w in nm]
    return {
        'name': nm,
        'owner': owner,
        'geo': geo,
        'region': region,
        'act': act,
        'usd': usd,
        'moneyTxt': money_txt,
        'item': it.get('ITEM_NAME') or '',
        'dept': it.get('DEPT_NAME') or '',
        'deal': it.get('DEAL_NAME') or '',
        'date': (it.get('DEAL_TIME') or '')[:10],
        'code': it.get('deal_code') or '',
        'biz': biz,
        'noise': noise,
        'rel': ('noise' if noise and not biz else ('hit' if biz else 'other')),
        'src': '浙江投资在线审批平台（境外投资备案）',
    }


def load_firms():
    """把客户档案里的企业名拉出来，用于「这条备案是不是我们客户投的」判断。"""
    names = []
    p = os.path.join(ROOT, 'raw', 'clients_abroad.json')
    if os.path.exists(p):
        for c in json.load(open(p, encoding='utf-8')).get('clients', []):
            names.append(c['name'])
    p2 = os.path.join(ROOT, 'raw', 'clients_abroad2.json')
    if os.path.exists(p2):
        for c in json.load(open(p2, encoding='utf-8')).get('clients', []):
            names.append(c['name'])
    # 64 家客户主表（如果有）
    for fn in ('entprobe_firms.json', 'clients_full.json'):
        q = os.path.join(ROOT, 'raw', fn)
        if os.path.exists(q):
            try:
                d = json.load(open(q, encoding='utf-8'))
                for x in (d.get('firms') or d.get('items') or []):
                    if isinstance(x, dict) and x.get('n'):
                        names.append(x['n'])
            except Exception:
                pass
    # 「恒力集团（恒力石化）」这种带括注的，拆成两个名字
    out = set()
    for n in names:
        n = (n or '').strip()
        if not n:
            continue
        out.add(n)
        m = re.match(r'^(.+?)[（(](.+?)[）)]$', n)
        if m:
            out.add(m.group(1).strip())
            out.add(m.group(2).strip())
        out.add(re.sub(r'(集团|控股|股份|有限公司|股份有限)$', '', n))
    return sorted(x for x in out if len(x) >= 2)


def tag_firm(rec, firm_keys):
    nm = rec['name']
    hit = [k for k in firm_keys if len(k) >= 3 and k in nm]
    # 长的优先，只留最具体的一个（避免「华友钴业」和「华友」都命中）
    hit.sort(key=len, reverse=True)
    return hit[0] if hit else ''


def main():
    t0 = time.time()
    raw, stat = pull()
    firm_keys = load_firms()
    items = [parse_item(x) for x in raw]
    for r in items:
        r['firm'] = tag_firm(r, firm_keys)
    items.sort(key=lambda x: (x['date'] or '', x['name']), reverse=True)
    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'n': len(items),
        'geoKw': len(GEO_ORDER),
        'firms': len(firm_keys),
        'items': items,
    }
    p = os.path.join(ROOT, 'raw', 'invest_odi.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('采集 %d 条  ->  %s  （%.0f 秒）' % (len(items), p, time.time() - t0))
    from collections import Counter
    print('按地区', dict(Counter(x['region'] for x in items).most_common()))
    print('相关性', dict(Counter(x['rel'] for x in items)))
    print('金额可抽', sum(1 for x in items if x['usd']))
    print('命中客户', [ (x['firm'],x['name'][:30]) for x in items if x['firm'] ][:12])
    print('最近 5 条:')
    for x in items[:5]:
        print('   %s | %s | %s | %s' % (x['date'], x['geo'], x['moneyTxt'] or '-', x['name'][:52]))


if __name__ == '__main__':
    main()
