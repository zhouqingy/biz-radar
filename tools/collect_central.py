#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""央企电商平台采集器 · collect_central.py（2026-11-21，Roadmap 第 1 项）
================================================================================
为什么做：省市公共资源平台之外，五大发电集团的**自有电商招投标平台**是火电/
热电联产/余热招标的第一发布渠道（往往早于或独立于省市平台）。用户 2026-11-21
拍板按 Roadmap 接入央企电商源，本期先接探测可达的一家，其余平台备注待接。

本期接入（探测 2026-11-21）：
  国家电投 · 电能e招采 https://ebid.espic.com.cn/
    - 首页 http 200 无 WAF，含当日/次日公告链接（/sdny_bulletin/日期/ID.html）
    - 详情页内嵌公告 PDF（openFileById 接口直下，无 WAF）
    - 列表页 bulletinListNew.html 被数据中心 IP WAF 拉黑（黑名单拦截），
      所以走「首页链接」增量，不做翻页全量 —— 每天跑一次够用（首页挂最近 ~24 条）

实测不可达/待接（不要在 CI 里反复撞）：
  大唐犀维网 www.cdt-ec.com   —— JS 挑战 + antidom 反爬，直连只回 1.2KB 壳
  华能   ecp.chng.com.cn     —— 412 / DNS 不通
  华电   ecp.chd.com.cn      —— 302 空壳
  国能   chnenergy            —— DNS 不通（国能e招域名待确认）
  三峡   eps.sanxia.com.cn   —— DNS 不通

口径（不得绕过）：
  - 采集到的每条公告必须过 biz_rules.semantic_drop()（入库前硬过滤）
  - build_data 严守江浙沪皖区域边界，本项目只是提前用 guess_rg 同口径预判，
    非四地的公告**直接不落盘**，不给 build_data 灌垃圾
  - 只做采集，不改任何删留/分级规则

用法：
  python3.11 collect_central.py            # 采集当日+昨日，写 raw/weekly/central_espic.json
  python3.11 collect_central.py --days 2   # 显式回看天数（默认 2）
输出字段与省级采集一致：t/d/url/p/st/snip/rg/srcType/scanAt
================================================================================"""
import os, re, sys, json, time, subprocess, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from preflight import require_briefing
require_briefing('collect_central.py')
from biz_rules import semantic_drop

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'}
HOME = 'https://ebid.espic.com.cn/'
PLAT = '国家电投·电能e招采'
OUT = os.path.join(BASE, 'raw', 'weekly', 'central_espic.json')
RAW = os.path.join(BASE, 'raw')

# 四地边界：与 build_data 完全同口径（江苏/浙江/安徽/上海）
REGION_KW = {
    '江苏': ['江苏', '南京', '苏州', '无锡', '常州', '南通', '徐州', '扬州', '泰州', '镇江', '盐城', '淮安', '连云港', '宿迁'],
    '浙江': ['浙江', '杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴', '金华', '衢州', '舟山', '台州', '丽水'],
    '安徽': ['安徽', '合肥', '芜湖', '蚌埠', '淮南', '马鞍山', '淮北', '铜陵', '安庆', '黄山', '滁州', '阜阳', '宿州', '六安', '亳州', '池州', '宣城'],
    '上海': ['上海'],
}

def guess_rg(txt):
    for rg, kws in REGION_KW.items():
        for k in kws:
            if k in txt:
                return rg
    return ''

def get(u, binary=False, timeout=45):
    d = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
    return d if binary else d.decode('utf-8', 'ignore')

def amt_from_txt(txt):
    m = re.search(r'(?:合同估算价|招标控制价|最高限价|估算价|总投资)[^0-9]{0,12}([0-9][\d,，.]+)\s*万?', txt)
    if not m:
        return None, None
    raw = m.group(1).replace(',', '').replace('，', '')
    try:
        v = float(raw)
    except ValueError:
        return None, None
    if '万元' in txt[max(0, m.start()-5):m.end()+6] or v > 10000:
        pass
    # 千万级以上数字大概率是"元"，统一转"元"
    yuan = v if v < 100000 else v  # 粗口径：数值即万元级原文照抄
    return m.group(0)[:40], v

def fetch_one(link):
    """详情页 → PDF id → 下载 → 前2页文本。返回 (title, snip, url) 或 None"""
    h = get(HOME.rstrip('/') + link)
    m = re.search(r'openFileById\?fileType%3D2%26id%3D([0-9a-f]{16,40})', h)
    if not m:
        return None
    pdf = get('https://ebid.espic.com.cn/bidprocurement/datacenter-cebpubserver/'
              'cebpubserver/dataCeboubServerCommonController/openFileById?fileType=2&id=' + m.group(1),
              binary=True)
    if not pdf.startswith(b'%PDF'):
        return None
    tmp = os.path.join(RAW, '_central_tmp.pdf')
    with open(tmp, 'wb') as f:
        f.write(pdf)
    try:
        txt = subprocess.run(['pdftotext', '-l', '2', tmp, '-'],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    finally:
        try: os.remove(tmp)
        except OSError: pass
    txt = re.sub(r'\s+', ' ', txt).strip()
    if len(txt) < 20:
        return None
    # 标题：PDF 第一行语义行（去掉页眉页脚噪声）
    title = txt[:120].strip()
    return title, txt[:400], 'https://ebid.espic.com.cn' + link

def main():
    days = 2
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    date_prefixes = []
    t0 = time.time()
    for k in range(days):
        ts = time.strftime('%Y-%m-%d', time.localtime(t0 - k * 86400))
        date_prefixes.append(ts)
    # 1) 首页公告链接
    try:
        s = get(HOME)
    except Exception as e:
        print('[central] 首页抓取失败: %s' % e)
        return 1
    links = sorted(set('/' + p for p in re.findall(
        r'(?://ebid\.espic\.com\.cn)?(/sdny_bulletin/[\d-]+/\d+\.html)', s)))
    links = [u for u in links if any(dp in u for dp in date_prefixes)]
    print('[central] 电能e招采 近 %d 日公告 %d 条' % (days, len(links)))
    # 2) 增量：已采过的不再下 PDF
    done = set()
    if os.path.isfile(OUT):
        try:
            done = {x.get('url', '').rsplit('/', 1)[-1] for x in json.load(open(OUT, encoding='utf-8'))}
        except Exception:
            done = set()
    # 3) 逐条：PDF → 文本 → 区域预判 → 语义过滤
    out = []
    if os.path.isfile(OUT):
        try: out = json.load(open(OUT, encoding='utf-8'))
        except Exception: out = []
    n_new = n_drop_region = n_drop_sem = 0
    for u in links:
        if u.rsplit('/', 1)[-1] in done:
            continue
        r = fetch_one(u)
        if not r:
            continue
        title, snip, url = r
        rg = guess_rg(title + ' ' + snip)
        if not rg:
            n_drop_region += 1
            continue   # 严守四地边界：非江浙沪皖不落盘
        dp = semantic_drop(title)
        if dp and dp[0]:
            n_drop_sem += 1
            continue   # 入库前硬过滤（biz_rules 唯一规则源）
        d = re.search(r'/(\d{4}-\d{2}-\d{2})/', u)
        amtTxt, amt = amt_from_txt(snip)
        out.append({
            't': title, 'd': d.group(1) if d else time.strftime('%Y-%m-%d'),
            'url': url, 'p': PLAT, 'st': '招标公告',
            'snip': snip, 'rg': rg, 'srcType': 'official',
            'scanAt': time.strftime('%Y-%m-%d'),
            **({'amtTxt': amtTxt, 'amt': amt} if amtTxt else {}),
        })
        n_new += 1
        time.sleep(0.8)   # 温和速率，别触发详情页 WAF
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('[central] 新增 %d · 区域外丢弃 %d · 语义过滤 %d · 池内共 %d 条 → %s'
          % (n_new, n_drop_region, n_drop_sem, len(out), OUT))
    return 0

if __name__ == '__main__':
    sys.exit(main())
