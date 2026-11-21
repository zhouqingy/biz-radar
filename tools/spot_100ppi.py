# -*- coding: utf-8 -*-
"""硫磺 / 硫酸现货基准价 · 生意社（2026-11-18 用户拍板加）

为什么加（用户原话口径）：
    我们做金属冶炼配套的脱硫环节有「烟气制酸」业绩/工艺：硫磺 → 浓硫酸，
    镍铁湿法冶炼（HPAL）要大量耗酸。硫磺降价 → 硫酸市价承压 → 冶炼厂
    烟气制酸副产品收入缩水（略负面）；酸便宜 → 湿法项目酸耗成本下降 →
    印尼镍湿法推进意愿 ↑（正面，配套供汽/供电需求 ↑）。两个必须成对看。

数据源（实测验证 2026-11-18）：
    生意社商品分析页 rawmex/detail-427.html（硫磺 山东 ≥99%工业级固体）
                       rawmex/detail-236.html（硫酸）
    页面给：基准价、涨跌幅、更新时间、三个月均/高/低、一年/两年/三年位置。
    ⚠ 安检：首次请求返回 JS challenge，要把页面里的 32 位 hash 设成
       HW_CHECK cookie 再重试一次（见 _get）。
    ⚠ 这是现货日价，不是期货——没有新浪日 K 那种全历史接口，
       历史曲线从启用日起自建：每天把当日价 append 进 raw/spot_hist.json，
       由 gen_metal_hist.py 汇进 data.metalhist.js，曲线随积累逐渐成形。

用法：
    python3 spot_100ppi.py            # 抓当日价，更新缓存 + 历史档
    python3 spot_100ppi.py --dry      # 只看不落盘
"""
import json
import os
import re
import sys
import time
import urllib.request
import http.cookiejar

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
CACHE = os.path.join(RAW, 'spot_cache.json')
HIST = os.path.join(RAW, 'spot_hist.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

# (code, name, 生意社 detail id, hint, 分组)
SPOTS = [
    ('SULFUR', '硫磺', 427, '制酸原料：硫磺跌 → 硫磺制酸成本线下移，市售硫酸承压，冶炼烟气制酸副产品收入缩水（客户侧略负面）', '酸化工'),
    ('ACID', '硫酸', 236, '烟气制酸收入端+镍钴湿法(HPAL)酸耗成本：酸价跌 → 印尼镍湿法项目推进意愿 ↑，配套供汽/供电需求 ↑', '酸化工'),
]


def _get(url, timeout=25):
    """带 HW_CHECK 安检处理的 GET。返回页面文本。"""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    hds = {'User-Agent': UA, 'Referer': 'https://www.100ppi.com/'}

    def once():
        req = urllib.request.Request(url, headers=hds)
        return op.open(req, timeout=timeout).read().decode('utf-8', 'ignore')

    page = once()
    if '正在进行安全检查' in page:
        m = re.search(r'var\s+_0x2\s*=\s*"([0-9a-f]{32})"', page)
        if m:
            # 把 cookie 直接塞进请求头重试（CookieJar 对手动 set 支持一般）
            hds['Cookie'] = 'HW_CHECK=' + m.group(1)
        time.sleep(1.0)
        page = once()
    return page


def parse_detail(pid):
    """从 rawmex/detail-<pid>.html 解析基准价块。"""
    h = _get('https://www.100ppi.com/rawmex/detail-%d.html' % pid)
    t = re.sub(r'<script[^>]*>.*?</script>', '', h, flags=re.S)
    t = re.sub(r'<[^>]+>', '|', t)
    t = re.sub(r'\s+', '', t)
    # 基准价块：…元/吨| | |<价>| |元/吨| |<涨跌%>| |更新时间：|MM-DD HH:MM|
    m = re.search(r'\|(\d{2,6}(?:\.\d+)?)\|+元/吨', t)
    if not m:
        return None
    price = float(m.group(1))
    cm = re.search(r'\|+([+-]?\d+(?:\.\d+)?)%\|', t[m.end():m.end() + 120])
    if not cm:
        return None
    out = {'price': price, 'chg': float(cm.group(1))}
    mm = re.search(r'更新时间：\|(\d{2}-\d{2})(\d{2}:\d{2})', t)
    if mm:
        out['at'] = mm.group(1) + ' ' + mm.group(2)
    mv = re.search(r'三个月均价：\|([\d.]+)', t)
    if mv:
        out['m3avg'] = float(mv.group(1))
    hi = re.search(r'三个月最高：\|([\d.]+)', t)
    if hi:
        out['m3hi'] = float(hi.group(1))
    lo = re.search(r'三个月最低：\|([\d.]+)', t)
    if lo:
        out['m3lo'] = float(lo.group(1))
    pos = re.search(r'一年位置：\|([^|]+)', t)
    if pos:
        out['ypos'] = pos.group(1)
    return out


def fetch_spot(dry=False):
    today = time.strftime('%Y-%m-%d')
    items, ok = [], 0
    for code, name, pid, hint, grp in SPOTS:
        try:
            d = parse_detail(pid)
        except Exception as e:
            print('[WARN] 生意社 %s 抓取失败: %r' % (name, e))
            d = None
        if not d:
            continue
        ok += 1
        items.append({'code': code, 'name': name, 'unit': '元/吨',
                      'price': d['price'], 'chg': d['chg'],
                      'date': today, 'at': d.get('at') or '15:00',
                      'hint': hint, 'grp': grp, 'spot': 1,
                      'm3avg': d.get('m3avg'), 'm3hi': d.get('m3hi'),
                      'm3lo': d.get('m3lo'), 'ypos': d.get('ypos')})
        if not dry:
            _append_hist(code, today, d['price'])
        time.sleep(1.0)
    if not ok:
        return None
    if not dry:
        json.dump({'updated': today, 'src': '生意社现货基准价(100ppi.com)',
                   'items': items}, open(CACHE, 'w', encoding='utf-8'),
                  ensure_ascii=False)
    return items


def _append_hist(code, date, price):
    try:
        hist = json.load(open(HIST, encoding='utf-8'))
    except Exception:
        hist = {}
    arr = hist.setdefault(code, [])
    if arr and arr[-1][0] == date:
        arr[-1][1] = price          # 当天重跑只更新，不堆重复点
    else:
        arr.append([date, price])
    # 只留近 5 年
    cut = '2021-'
    hist[code] = [x for x in arr if x[0] >= cut or True][-1300:]
    json.dump(hist, open(HIST, 'w', encoding='utf-8'), ensure_ascii=False)


def load_cached():
    """实时抓取失败时回退上次成功快照（与期货 METALS_CACHE 同款兜底）。"""
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding='utf-8')).get('items') or []
        except Exception:
            return []
    return []


if __name__ == '__main__':
    dry = '--dry' in sys.argv
    it = fetch_spot(dry=dry)
    if it:
        for x in it:
            print('%s %s %.2f %s%.2f%%  %s  3月均 %s' % (
                x['date'], x['name'], x['price'],
                '+' if x['chg'] > 0 else '', x['chg'], x.get('at'),
                x.get('m3avg')))
    else:
        print('现货抓取全部失败')
        sys.exit(1)
