#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""江浙沪皖市级公共资源交易平台批量探测器 · probe_city.py

为什么写这个：
  用户 2026-10-23 指出「为什么只找省的，各个市一级的平台不也有信息吗」——
  这条站得住脚，而且脚本里早就写明了：

    > 市级站就是「最原始发布平台」，公告和附件都在这里，
    > 省级平台上的同名公告往往只是转发。

  省级是转发源，市级才是首发源：公告更早、附件更全。之前实测也印证——
  浙江省级平台很少挂附件（2/135），附件都挂在市级平台的原页上。

  但江浙沪皖一共 41 个地级市，现在只接了 3 个（合肥、常州、苏州且 502）。
  所以先把它们挨个探一遍：域名通不通、接口是不是同一套 ES、每站 rn 上限多少。

探测分两步，先快后慢：
  ① DNS：解析域名，不通的直接淘汰（毫秒级）
  ② 接口：POST /inteligentsearch/rest/esinteligentsearch/getFullTextDataNew，
     试 rn=20 / 50，记录每站真实上限——浙江站 rn 上限 20 的坑不能再踩第二次

⚠ 沙箱网络限制：本沙箱对部分政府域名不通（如江苏 jsggzy 直接 rc=7）。
  探测结果里的「不通」有两种可能：域名/接口真的变了，或者沙箱出口拦了。
  GitHub Actions 在美国，可能能连通——所以不通的站先记下，不要直接判死。
"""
import json
import os
import socket
import subprocess
import time

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
API_PATH = '/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew'

# 城市 → 候选域名。各地命名不统一，一个城市可能要试好几个。
# 规律：多数是 ggzy.{城市拼音}.gov.cn；少数用简称或加省码。
CITIES = {
    '江苏': {
        '南京': ['ggzy.nanjing.gov.cn', 'njggzy.nanjing.gov.cn'],
        '苏州': ['ggzy.suzhou.gov.cn'],
        '无锡': ['ggzy.wuxi.gov.cn', 'wxggzy.wuxi.gov.cn'],
        '常州': ['ggzy.changzhou.gov.cn'],
        '镇江': ['ggzy.zhenjiang.gov.cn'],
        '南通': ['ggzy.nantong.gov.cn', 'ntggzy.nantong.gov.cn'],
        '扬州': ['ggzy.yangzhou.gov.cn'],
        '泰州': ['ggzy.taizhou.gov.cn', 'tzggzy.taizhou.gov.cn'],
        '盐城': ['ggzy.yancheng.gov.cn'],
        '淮安': ['ggzy.huaian.gov.cn', 'haggzy.huaian.gov.cn'],
        '连云港': ['ggzy.lyg.gov.cn', 'ggzy.lyg.gov.cn'],
        '徐州': ['ggzy.xz.gov.cn', 'xzggzy.xz.gov.cn'],
        '宿迁': ['ggzy.suqian.gov.cn'],
    },
    '浙江': {
        '杭州': ['ggzy.hangzhou.gov.cn', 'hzggzy.hangzhou.gov.cn'],
        '宁波': ['ggzy.ningbo.gov.cn', 'nbggzy.ningbo.gov.cn'],
        '温州': ['ggzy.wenzhou.gov.cn'],
        '绍兴': ['ggzy.sx.gov.cn', 'ggzy.shaoxing.gov.cn'],
        '湖州': ['ggzy.huzhou.gov.cn'],
        '嘉兴': ['ggzy.jiaxing.gov.cn'],
        '金华': ['ggzy.jinhua.gov.cn'],
        '衢州': ['ggzy.qz.gov.cn', 'ggzy.quzhou.gov.cn'],
        '台州': ['ggzy.tz.gov.cn', 'ggzy.taizhou.gov.cn'],
        '丽水': ['ggzy.lishui.gov.cn'],
        '舟山': ['ggzy.zhoushan.gov.cn'],
    },
    '安徽': {
        '合肥': ['ggzy.hefei.gov.cn'],
        '芜湖': ['ggzy.wuhu.gov.cn'],
        '马鞍山': ['ggzy.mas.gov.cn', 'ggzy.mamshan.gov.cn'],
        '铜陵': ['ggzy.tl.gov.cn', 'ggzy.tongling.gov.cn'],
        '安庆': ['ggzy.anqing.gov.cn'],
        '滁州': ['ggzy.chuzhou.gov.cn'],
        '阜阳': ['ggzy.fy.gov.cn', 'ggzy.fuyang.gov.cn'],
        '蚌埠': ['ggzy.bengbu.gov.cn'],
        '淮南': ['ggzy.huainan.gov.cn'],
        '淮北': ['ggzy.huaibei.gov.cn'],
        '六安': ['ggzy.luan.gov.cn', 'ggzy.luan.gov.cn'],
        '宿州': ['ggzy.ahsz.gov.cn', 'ggzy.suzhou.gov.cn'],
        '宣城': ['ggzy.xuancheng.gov.cn'],
        '黄山': ['ggzy.huangshan.gov.cn'],
        '池州': ['ggzy.chizhou.gov.cn'],
        '亳州': ['ggzy.bozhou.gov.cn'],
    },
    '上海': {
        '上海': ['www.shggzy.com', 'ggzy.sh.gov.cn'],
    },
}

# 已知可用的（对照用，验证探测脚本本身没坏）
KNOWN_OK = ['ggzy.hefei.gov.cn', 'ggzy.changzhou.gov.cn', 'ggzy.zj.gov.cn']


def dns_ok(host):
    try:
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


def mk_payload(rn, wd='热电'):
    return {
        'token': '', 'pn': 0, 'rn': str(rn), 'sdt': '2026-10-16', 'edt': '2026-10-23',
        'wd': wd, 'inc_wd': '', 'exc_wd': '', 'fields': 'title', 'cnum': '001',
        'sort': '{"webdate":"0"}', 'ssort': 'title', 'cl': 200, 'terminal': '',
        'condition': None, 'time': None, 'highlights': 'title', 'statistics': None,
        'unionCondition': None, 'opCondition': None, 'opType': 0, 'accuracy': '',
        'noParticiple': '', 'searchRange': None, 'isBusiness': '1',
    }


def try_api(host, rn=20, timeout=15, https=True):
    """返回 (状态, 详情)。状态：OK / ERR / FAIL / TIMEOUT"""
    proto = 'https' if https else 'http'
    url = proto + '://' + host + API_PATH
    body = json.dumps(mk_payload(rn), ensure_ascii=False)
    try:
        p = subprocess.run(
            ['curl', '-s', '-m', str(timeout), '-X', 'POST', url,
             '-H', 'Content-Type: application/json;charset=utf-8',
             '-H', 'User-Agent: ' + UA, '-d', body],
            capture_output=True, text=True)
    except Exception as e:
        return 'FAIL', str(e)[:60]
    raw = (p.stdout or '').strip()
    if p.returncode != 0:
        return 'FAIL', 'curl rc=%s' % p.returncode
    if not raw:
        return 'FAIL', '空响应'
    if raw.lstrip().startswith('<') or 'Bad Gateway' in raw[:200]:
        return 'ERR', re.sub(r'\s+', ' ', raw[:60])
    try:
        o = json.loads(raw)
        if isinstance(o.get('content'), str):
            o = json.loads(o['content'])
        if 'result' in o:
            tot = o['result'].get('totalcount')
            return 'OK', 'total=%s' % tot
        return 'ERR', re.sub(r'\s+', ' ', raw[:70])
    except Exception:
        return 'ERR', re.sub(r'\s+', ' ', raw[:70])


import re


def probe_rn(host, https=True):
    """探每站 rn 上限。浙江站上限 20，别的站可能 50/100，逐个试出来。"""
    for rn in (20, 50, 100):
        st, info = try_api(host, rn, https=https)
        if st == 'OK':
            return rn, info
        if 'rn' in info and '超过最大允许值' in info:
            continue
        break
    return 20, '未探明'


def main():
    print('[probe_city] 江浙沪皖市级平台探测\n')
    print('先验证探测脚本本身（已知可用的站）：')
    for h in KNOWN_OK:
        st, info = try_api(h)
        print('   %-28s %s  %s' % (h, st, info[:40]))
    print()

    out = []
    for prov, cities in CITIES.items():
        print('── %s ──' % prov)
        for city, hosts in cities.items():
            got = None
            for h in hosts:
                if not dns_ok(h):
                    print('   %-6s %-30s DNS 不通' % (city, h))
                    continue
                for https in (True, False):
                    st, info = try_api(h, 20, https=https)
                    if st == 'OK':
                        rnmax, _ = probe_rn(h, https)
                        got = {'prov': prov, 'city': city, 'host': h,
                               'proto': 'https' if https else 'http',
                               'rnMax': rnmax, 'note': info}
                        print('   %-6s %-30s ✅ %s rn上限=%s  %s'
                              % (city, h, 'https' if https else 'http', rnmax, info))
                        break
                    else:
                        print('   %-6s %-30s %s %s' % (city, h, st, info[:40]))
                        if not https:
                            break
                if got:
                    break
                time.sleep(0.2)
            if got:
                out.append(got)
            else:
                out.append({'prov': prov, 'city': city, 'host': '',
                            'proto': '', 'rnMax': 0, 'note': '全部候选不通'})
            time.sleep(0.2)
        print()

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'raw', 'probe_city.json')
    json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    ok = [x for x in out if x['host']]
    print('[probe_city] 可用 %d / %d → %s' % (len(ok), len(out), path))
    for x in ok:
        print('   %s %-6s %-28s rn<=%s' % (x['prov'], x['city'], x['host'], x['rnMax']))


if __name__ == '__main__':
    main()
