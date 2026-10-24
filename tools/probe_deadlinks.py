#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
死链体检（2026-10-21）

用户反馈：宝山那个项目点「原文」跳不了。
根因不是链接写错，是**采集源本身就是空壳站**——
  知了标讯 / 谛听招标网 / 招标与采购网 / 中标网 / 招标网 / 必联网
这批站在百度里排前面，但详情页给你一个 200 状态码 + 13 字节的空 body，
或者要求登录才显示正文。抓的时候能抓到标题摘要，点进去就白屏。

这里做两件事：
  1) HEAD/RANGE 探测每条记录的 url，判活：真 200 且 body>2KB 才算活；
  2) 空壳域名的记录直接标 dead，不管探测结果（13 字节也是 200，骗得过状态码骗不过人）。

输出 raw/link_health.json：{ url: {"ok": true/false, "why": "...", "kb": 3.2} }
构建时读它，把死链在卡片上降级展示（不给「原文」主按钮，改成「原文可能打不开 + 用标题搜」）。
"""
import os, json, re, time, urllib.request, urllib.error, ssl
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'raw', 'link_health.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# 实测的空壳/登录墙域名。命中就不探了，直接判死——省时间也避免误判成活链。
# 加新域名前先手动 curl 看一眼，别听 SEO 站自己的宣传。
SHELL_DOMAINS = {
    'zhiliaobiaoxun.cn': '知了标讯：详情页返回 13 字节空壳，正文要会员',
    'infochina.cn': '谛听招标网：详情页空壳，正文要登录',
    'zhaobiao.cn': '招标网：详情页要求登录',
    'bidchance.com': '中标网：详情页空壳',
    'chinabidding.cn': '中国采购与招标网：详情页要求登录',
    'bidcenter.com.cn': '中国招标网：详情页要求登录',
    'qianlima.com': '千里马招标网：详情页要求登录',
    'ebnew.com': '必联网：详情页要求登录',
    'caigou2003.com': '采招网：详情页要求登录',
    'chinazbcg.com': '中国招标采购网：转载页，正文缺失',
}
# 明确正常的官方站，不用探（探了反而被反爬挡回来误判）
TRUST = ('ggzy.zj.gov.cn', 'ggzy.hefei.gov.cn', 'jsggzy.jszwfw.gov.cn',
         'shggzy.com', 'baohuabidding.com', 'baohuabidding.cn', 'suzhou.gov.cn',
         'ccgp.gov.cn', 'chnenergybidding.com', 'zfcg.czt.zj.gov.cn')


def probe(url):
    if not url or not url.startswith('http'):
        return {'ok': False, 'why': '无链接', 'kb': 0}
    host = re.sub(r'^https?://', '', url).split('/')[0].lower()
    for d, why in SHELL_DOMAINS.items():
        if host.endswith(d):
            return {'ok': False, 'why': why, 'kb': 0}
    for d in TRUST:
        if host.endswith(d):
            return {'ok': True, 'why': '官方站', 'kb': -1}
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,*/*',
        'Range': 'bytes=0-4095',          # 只拿前 4KB，够判活又不拖时间
    })
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            body = r.read(8192)
            code = r.getcode()
    except urllib.error.HTTPError as e:
        return {'ok': False, 'why': 'HTTP %d' % e.code, 'kb': 0}
    except Exception as e:
        return {'ok': False, 'why': (str(e)[:40] or 'network'), 'kb': 0}
    # 206 是 Range 请求的正常响应（服务器老实给了你要的那 4KB），不是错误。
    # 早先只认 200，把浙江投资在线、安徽招投标、常州交易中心一口气误判成死链 500 多条。
    if code not in (200, 206):
        return {'ok': False, 'why': 'HTTP %d' % code, 'kb': 0}
    kb = len(body) / 1024.0
    if kb < 2:
        return {'ok': False, 'why': '返回空壳（%.1f KB），正文可能在登录后' % kb, 'kb': round(kb, 1)}
    # 有正文但夹着“登录后查看”的也算半死
    t = body.decode('utf-8', 'ignore')
    if re.search(r'登录后查看|请先登录|VIP会员|开通会员', t) and kb < 8:
        return {'ok': False, 'why': '正文要登录/会员', 'kb': round(kb, 1)}
    return {'ok': True, 'why': '', 'kb': round(kb, 1)}


def main():
    D = json.load(open(os.path.join(ROOT, 'merged.json'), encoding='utf-8'))
    urls = []
    for r in D:
        u = (r.get('url') or '').strip()
        if u.startswith('http') and u not in urls:
            urls.append(u)
    # 同域名只抽 3 条做抽样：一个站的表现是一致的，全探没必要
    by_host, pick = {}, []
    for u in urls:
        h = re.sub(r'^https?://', '', u).split('/')[0].lower()
        if by_host.get(h, 0) >= 3:
            continue
        by_host[h] = by_host.get(h, 0) + 1
        pick.append(u)
    print('总链接 %d 条，按域名抽样 %d 条探测' % (len(urls), len(pick)))

    res = {}
    done = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        for u, r in zip(pick, ex.map(probe, pick)):
            res[u] = r
            done += 1
            if done % 20 == 0:
                print('  %d/%d' % (done, len(pick)), flush=True)
    # 抽样结果按域名扩散到全部链接
    host_st = {}
    for u, r in res.items():
        h = re.sub(r'^https?://', '', u).split('/')[0].lower()
        host_st[h] = r
    full = {}
    for u in urls:
        h = re.sub(r'^https?://', '', u).split('/')[0].lower()
        full[u] = host_st.get(h, {'ok': True, 'why': '', 'kb': -1})

    dead = [u for u, r in full.items() if not r['ok']]
    print('判死 %d / %d 条' % (len(dead), len(full)))
    from collections import Counter
    c = Counter(re.sub(r'^https?://', '', u).split('/')[0] for u in dead)
    for k, v in c.most_common(12):
        print('   %4d  %s' % (v, k))
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': full},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)


if __name__ == '__main__':
    main()
