#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器采集器 · biz_crawl.py
============================
解决「JS 渲染页面 / 需要登录的平台抓不到，只能靠 Agent 手动查」的问题。

背景：环境里已装好 playwright + chromium（含 headless shell），以前没用起来，
把一批高价值站点错误地判成"只能人工"。实际上：

  - JS 渲染的发改委列表页（江苏 / 上海）用 requests 抓是空壳，浏览器渲染后正常；
  - 列表页 URL 靠猜极易 404，正确做法是**先渲染首页让它自己吐出栏目链接**；
  - 需要登录的平台用 storage_state 保存 Cookie，登录一次后可长期复用。

三种用法：
  1) 发现入口   python3.11 biz_crawl.py --discover <首页URL>
  2) 抓列表     python3.11 biz_crawl.py --crawl <列表页URL> [--out xxx.json]
  3) 存登录态   python3.11 biz_crawl.py --login <登录页URL> --auth auth/xxx.json
                浏览器会打开，人工登录后脚本自动保存 Cookie 供后续复用。

产出字段与 raw/weekly/*.json 完全一致，可直接入库。
"""
import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.abspath(__file__))
AUTH_DIR = os.path.join(ROOT, 'auth')
RAW = os.path.join(ROOT, 'raw')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# ---- 业务相关性词表（命中才收，避免把监理/绿化/办公用品收进来）----
HIT = ('余热', '发电', '热电', '煤气', '燃气', '锅炉', '汽机', '机组', 'CCPP', 'TRT',
       # 2026-10-19 补：燃气（天然气）发电系列——我司「能源清洁高效利用/热电联产」本业，
       # 园区/数据中心自备电源大量走燃气路线，此前只靠单个「燃气」词漏掉「天然气/联合循环」写法
       '天然气', '燃气轮机', '燃机', '联合循环', 'LNG', '液化天然气',
       '分布式能源', '分布式发电', '三联供', '冷热电', 'CCHP', '内燃机发电',
       '光伏', '储能', '余热锅炉', '烧结', '焦化', '高炉', '转炉', '电炉',
       '超低排放', '脱硫', '脱硝', '除尘', '烟气', 'VOCs', '废气',
       '污水', '废水', '中水', '零排放', '海水淡化', '污泥', '固废', '危废',
       '土壤', '修复', '水处理', '给水', '排水', '热能', '综合利用', '能源')
# 这些 XXX 出现且同时是 EPC/总承包时仍算数（数量极少的例外）
STRONG = ('EPC', 'epc', '总承包', 'PC总承包')
# 明确不要的
DROP = ('监理', '造价咨询', '审计', '物业', '绿化', '保洁', '办公家具', '办公用品',
        '车辆', '保险', '培训', '体检', '劳务分包', '餐', '印刷', '物业', '安保',
        '法律顾问', '评估', '考古', '勘察设计招标', '维护外包',
        # 2026-10-12 补：宝华平台上这类"命中业务词但无跟进价值"的小东西
        '备件', '耐材', '莫来石', '钢丝绳', '润滑油', '轧辊', '轴承',
        '运维', '巡检', '抢修', '协议修复')
# 这些状态的公告收进来就是脏数据：项目已取消或走非公开流程
BAD_TAIL = ('撤项', '特殊情形', '流标', '废标', '终止')

DATE_IN_URL = re.compile(r'/(20\d{2})[-/]?(\d{2})[-/]?(\d{2})')
DATE_IN_TXT = re.compile(r'(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})')


def _norm_date(y, m, d):
    try:
        return '%04d-%02d-%02d' % (int(y), int(m), int(d))
    except Exception:
        return ''


def guess_date(url, txt=''):
    """日期优先取 URL（/20261012/ 这种最可靠），取不到再从文本里找"""
    for pat, src in ((DATE_IN_URL, url), (DATE_IN_TXT, txt)):
        m = pat.search(src or '')
        if m:
            dt = _norm_date(*m.groups())
            if dt:
                return dt
    return ''


def _ctx_args(auth=None, slow=0):
    kw = {'user_agent': UA, 'viewport': {'width': 1440, 'height': 900},
          'locale': 'zh-CN'}
    if auth and os.path.exists(auth):
        kw['storage_state'] = auth
    return kw


def _launch(playwright, headless=True):
    return playwright.chromium.launch(
        headless=headless,
        args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled'])


def discover(start, topn=25, wait=3500, auth=None):
    """渲染起点页面，吐出里面的候选栏目 / 公告链接"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _launch(p)
        ctx = b.new_context(**_ctx_args(auth))
        pg = ctx.new_page()
        try:
            pg.goto(start, timeout=45000, wait_until='domcontentloaded')
            pg.wait_for_timeout(wait)
        except Exception as e:
            print('[err] 打开失败 %s : %s' % (start, str(e)[:80]))
            b.close()
            return []
        items = pg.eval_on_selector_all(
            'a[href]',
            "els=>els.map(e=>({t:(e.textContent||'').trim().replace(/\\s+/g,' '),"
            "h:e.getAttribute('href')||''}))")
        title = pg.title()
        b.close()
    seen, out = set(), []
    for it in items:
        t, h = it['t'], it['h']
        if not t or len(t) < 4 or not h:
            continue
        if h.startswith(('javascript', '#', 'mailto')):
            continue
        full = urljoin(start, h)
        if full in seen:
            continue
        seen.add(full)
        out.append({'title': t[:60], 'url': full})
    print('### %s' % (title or start)[:60])
    print('    共 %d 个链接，取前 %d：' % (len(out), topn))
    for x in out[:topn]:
        print('    %-46s %s' % (x['title'][:46], x['url'][:92]))
    return out


def crawl(url, wait=3500, auth=None, min_title=8, only_hit=True,
          verbose=True, click=None, days=120):
    """渲染列表页 → 抽出业务相关的公告条目"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _launch(p)
        ctx = b.new_context(**_ctx_args(auth))
        pg = ctx.new_page()
        try:
            pg.goto(url, timeout=45000, wait_until='domcontentloaded')
            pg.wait_for_timeout(wait)
            pg.mouse.wheel(0, 3000)          # 触发懒加载
            pg.wait_for_timeout(1200)
            if click:                        # 有些站列表是空的，要点「搜索」才渲染
                try:
                    pg.click(click, timeout=6000)
                    pg.wait_for_timeout(wait + 2000)
                except Exception as e:
                    print('    [warn] 点击 %s 失败：%s' % (click, str(e)[:60]))
        except Exception as e:
            print('[err] %s : %s' % (url, str(e)[:80]))
            b.close()
            return []
        items = pg.eval_on_selector_all(
            'a[href]',
            "els=>els.map(e=>({t:(e.textContent||'').trim().replace(/\\s+/g,' '),"
            "h:e.getAttribute('href')||'',"
            "row:((e.closest('tr,li,div')||{}).innerText||'').slice(0,300)}))")
        b.close()

    out, seen = [], set()
    for it in items:
        t, h, row = it['t'], it['h'], it['row']
        if not t or len(t) < min_title or not h:
            continue
        if h.startswith(('javascript', '#', 'mailto')):
            continue
        full = urljoin(url, h)
        if full in seen:
            continue
        # 排除纯导航
        if re.match(r'^(首页|下一页|上一页|尾页|末页|更多|返回|列表)$', t):
            continue
        if only_hit:
            # DROP 一旦命中就剔，除非是 EPC/总承包这种明确的大工程。
            # （早期写法是 HIT 能一票否决 DROP，结果"备件协议修复"因为含"修复"
            #   被当成业务命中收了进来 —— 2026-10-12 修正）
            if any(d in t for d in DROP) and not any(k in t for k in STRONG):
                continue
            if not any(k in t for k in HIT):
                continue
            if any(b in t for b in BAD_TAIL):     # 撤项/流标/废标/特殊情形
                continue
        seen.add(full)
        dt = guess_date(full, row)
        # 宝华首页会把历史项目混在最新列表里，按日期砍一刀
        if days and dt:
            try:
                age = (time.time() - time.mktime(time.strptime(dt, '%Y-%m-%d'))) / 86400.0
                if age > days:
                    continue
            except Exception:
                pass
        out.append({'title': t, 'url': full, 'date': dt})
    if verbose:
        print('    命中 %d 条（链接总数 %d）' % (len(out), len(items)))
    return out


# ---- 地域推断：全国性平台（如宝华）必须剔除外省项目 ----
# 业主/厂名 → (省份, 城市)
GEO = {
    '梅钢': ('江苏', '南京市'), '梅山': ('江苏', '南京市'), '南钢': ('江苏', '南京市'),
    '马钢': ('安徽', '马鞍山市'), '马鞍山': ('安徽', '马鞍山市'),
    '宝钢': ('上海', '上海市'), '宝武': ('上海', '上海市'), '宝山': ('上海', '上海市'),
    '宁波宝新': ('浙江', '宁波市'), '宁波': ('浙江', '宁波市'),
    '沙钢': ('江苏', '苏州市'), '永钢': ('江苏', '苏州市'), '中天钢铁': ('江苏', '常州市'),
    '兴澄': ('江苏', '无锡市'), '江阴': ('江苏', '无锡市'),
    '铜陵有色': ('安徽', '铜陵市'), '合肥': ('安徽', '合肥市'),
    '杭州': ('浙江', '杭州市'), '温州': ('浙江', '温州市'), '嘉兴': ('浙江', '嘉兴市'),
    '南京': ('江苏', '南京市'), '苏州': ('江苏', '苏州市'), '无锡': ('江苏', '无锡市'),
    '常州': ('江苏', '常州市'), '南通': ('江苏', '南通市'), '徐州': ('江苏', '徐州市'),
    '连云港': ('江苏', '连云港市'), '扬州': ('江苏', '扬州市'), '镇江': ('江苏', '镇江市'),
}
# 出现这些外省地名直接不要（我们是江浙沪皖雷达）
OUT = ('山东', '山西', '河北', '河南', '新疆', '内蒙古', '甘肃', '青海', '宁夏', '陕西',
       '广东', '广西', '福建', '江西', '湖南', '湖北', '四川', '云南', '贵州', '辽宁',
       '吉林', '黑龙江', '海南', '西藏', '台湾', '香港', '澳门', '台湾',
       '湛江', '武钢', '鄂钢', '韶钢', '太钢', '重钢', '昆钢', '涟钢', '柳钢', '首钢',
       '包钢', '攀钢', '安钢', '唐山', '邯郸', '日照', '岚县', '防城港',
       # 2026-10-12 补：实跑遇到的省外基地简称
       '八钢', '八一钢铁', '新余钢铁', '新钢股份', '阳春新钢', '伊犁', '安阳', '酒钢',
       '东莞', '佛山', '惠州', '佛山', '揭阳', '泉州', '厦门')


def infer_region(title):
    """返回 (省份, 城市)；命中外省关键词返回 (None, None) 表示应剔除"""
    for kw in OUT:
        if kw in title:
            return None, None
    # 标题里直接写了省名的情况（如"安徽皖宝秀山石灰石矿"）
    for p in ('江苏', '浙江', '安徽', '上海'):
        if p in title:
            return p, ''
    for kw, v in GEO.items():
        if kw in title:
            return v
    return '', ''


def to_records(rows, plat, rg='', city='', default_st='招标公告'):
    """转成 raw/weekly 约定的 14 键格式"""
    recs = []
    for r in rows:
        t = r['title']
        # 用局部变量，别覆盖入参 rg——否则第一条的推断结果会被后面所有条沿用
        _rg, _city = rg, city
        st = default_st
        if '中标' in t:
            st = '中标公告'
        elif '招标计划' in t or '采购意向' in t or '预公告' in t:
            st = '招标计划'
        elif '资格预审' in t or '招标公告' in t or '招标' in t:
            st = '招标公告'
        if not rg:                       # 全国性平台：逐条推断地域
            _rg, _city = infer_region(t)
            if _rg is None:              # 命中外省 → 丢弃
                continue
        recs.append({
            't': re.sub(r'[\[【]\s*(招标公告|招标|中标结果公示|变更公告)\s*[\]】]\s*$', '', t).strip(),
            'rg': _rg, 'city': _city, 'st': st,
            'buyer': '', 'win': '', 'amt': None, 'amtTxt': '',
            'd': r.get('date') or '', 'dl': '', 'p': plat,
            'url': r['url'], 'snip': '', 'mode': '',
        })
    return recs


def do_login(url, auth, wait_sec=180):
    """打开浏览器让人手工登录，然后保存 storage_state"""
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.dirname(auth), exist_ok=True)
    with sync_playwright() as p:
        b = _launch(p, headless=False)
        ctx = b.new_context(**_ctx_args(None))
        pg = ctx.new_page()
        pg.goto(url, timeout=60000, wait_until='domcontentloaded')
        print('浏览器已打开 %s' % url)
        print('请在窗口里手工完成登录（含短信/扫码验证）。完成后回到这里按回车继续。')
        try:
            input('  → 登录完成后按 Enter：')
        except EOFError:
            time.sleep(wait_sec)
        ctx.storage_state(path=auth)
        b.close()
    print('登录态已保存：%s' % auth)
    print('提示：把它上传到共享盘，其它沙箱下载后即可复用，不必重复登录。')


# ---- 已验证可用的入口（2026-10-12 浏览器实测）----
SITES = {
    'baohua': {
        'name': '宝华智慧招标共享平台', 'rg': '', 'plat': '宝华智慧招标共享平台',
        # 由 https://www.baohuabidding.cn/ 自动发现得到
        'urls': ['https://www.baohuabidding.cn/shbhgjzb/jyxx/trade_notice.html',
                 'https://www.baohuabidding.cn/'],
    },
    'ah': {
        'name': '安徽省招标投标信息网', 'rg': '安徽', 'plat': '安徽省招标投标信息网',
        # 这个站列表是空的，必须点一下「搜索」按钮才会渲染数据 —— 用 click 描述这个动作
        'urls': ['https://www.ahtba.org.cn/site/trade/affiche/gotoTradeList?tradeType=01',
                 'https://www.ahtba.org.cn/site/trade/affiche/gotoTradeList?tradeType=02'],
        'click': 'text=搜索',
    },
    'jsfgw': {
        'name': '江苏省发改委', 'rg': '江苏', 'plat': '江苏省发展和改革委员会',
        'urls': ['https://fzggw.jiangsu.gov.cn/col/col284/index.html'],
    },
}


def main():
    ap = argparse.ArgumentParser(description='浏览器采集器')
    ap.add_argument('--discover', metavar='URL', help='发现页面里的候选链接')
    ap.add_argument('--crawl', metavar='URL', help='抓取列表页条目')
    ap.add_argument('--site', choices=list(SITES), help='用内置已验证入口')
    ap.add_argument('--login', metavar='URL', help='手工登录并存登录态')
    ap.add_argument('--auth', metavar='FILE', help='storage_state 登录态文件')
    ap.add_argument('--out', metavar='FILE', help='输出 JSON 路径')
    ap.add_argument('--all', action='store_true', help='不做业务关键词过滤，全收')
    ap.add_argument('--wait', type=int, default=3500, help='渲染等待毫秒')
    ap.add_argument('--days', type=int, default=120,
                    help='只保留最近 N 天的公告（0=不限）')
    a = ap.parse_args()

    if a.login:
        do_login(a.login, a.auth or os.path.join(AUTH_DIR, 'default.json'))
        return

    if a.discover:
        discover(a.discover, auth=a.auth)
        return

    targets = []
    meta = {'plat': '', 'rg': '', 'name': ''}
    if a.site:
        cfg = SITES[a.site]
        targets = cfg['urls']
        meta = {'plat': cfg['plat'], 'rg': cfg['rg'], 'name': cfg['name'],
                'click': cfg.get('click')}
    elif a.crawl:
        targets = [a.crawl]
        meta = {'plat': '', 'rg': '', 'name': a.crawl}

    if not targets:
        ap.print_help()
        return

    allrows = []
    for u in targets:
        print('[抓取] %s' % u)
        rows = crawl(u, wait=a.wait, auth=a.auth, only_hit=not a.all,
                     click=meta.get('click'), days=a.days)
        if not rows:
            print('      （无命中）现在尝试自动发现入口…')
            cand = discover(u, topn=8, wait=a.wait, auth=a.auth)
            # 挑看起来像列表栏目的继续抓
            for c in cand[:4]:
                if re.search(r'(list|List|trade|jyxx|affiche|col)', c['url']):
                    print('      → 跟进 %s' % c['url'][:80])
                    rows += crawl(c['url'], wait=a.wait, auth=a.auth, only_hit=not a.all)
                    break
        allrows += rows
        for r in rows[:8]:
            print('      %s | %s' % (r['date'] or '??', r['title'][:56]))

    # 按 url 去重
    seen, uniq = set(), []
    for r in allrows:
        if r['url'] in seen:
            continue
        seen.add(r['url'])
        uniq.append(r)

    recs = to_records(uniq, meta['plat'], meta['rg'])
    print('\n合计 %d 条（去重后）' % len(recs))
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(recs, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('已写入 %s' % a.out)
    else:
        json.dump(recs, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
