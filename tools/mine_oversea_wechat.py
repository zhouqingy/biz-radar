#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出海速览：微信公众号每日抓取（2026-11-04）

用户的需求：
    「新闻我觉得是不是每天搜一下微信公众号上，它不是有一些关于出海的有色的、
      然后去什么建厂了、然后巴淡岛那个数据中心吧，数据中心不也用电嘛，
      就这些类似的跟我们业务相关的抓一下，做一个速览新闻之类的东西」

技术选型（实测过才写的）
------------------------
用搜狗微信搜索（vendor/search_wechat.js，零依赖、只要 node、不用 API Key）。
另一条路是红狐数据的公众号 API，要 REDFOX_API_KEY，沙箱里没有，放弃。

实测出来的三个硬事实，决定了下面这份关键词表怎么排：

  ① **关键词必须贴公众号的实际写法，不能按行业术语写**
     「镍冶炼」→ 0 条，「印尼 镍」→ 0 条
     但「电解铝 印尼」→ 6 条、「数据中心 巴淡」→ 满屏硬货
     公众号写的是「镍铁」「高冰镍」「镍矿」，不写「镍冶炼」。

  ② **覆盖不保证**。热门话题（巴淡岛数据中心）几天几十篇，
     冷门方向（垃圾焚烧出海）一篇没有。所以速览只能当「补充视角」，
     不能当「完整信息源」—— 真正的项目线索还是靠备案 + 公告。

  ③ **一半结果是服务商广告**。实测抓「中资出海 建厂」，前 8 条里有
     4 条是「环保合规指引」「LMS 培训」「FastPass 一站式落地」这类
     卖服务给中国企业的软文，必须过掉。

用法
----
    python3 mine_oversea_wechat.py            # 抓最近 10 天
    python3 mine_oversea_wechat.py --days 3   # 只抓 3 天
    python3 mine_oversea_wechat.py --dry      # 只看不落盘
"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(ROOT, 'vendor', 'search_wechat.js')
OUT = os.path.join(ROOT, 'raw', 'oversea_flash.json')

# ── 关键词表 ────────────────────────────────────────────────────────────
# 分三组，按「命中率 × 业务贴合度」排。每组的每词单独一跑，结果合并去重。
# 注意：多词之间用空格，搜狗按 AND 处理；词越多越窄，所以最多两个词。
# ── 关键词分三组轮换 ────────────────────────────────────────────────────
# 为什么不一次性全跑：实测 2026-11-04 三次结果对比 ——
#   跑 14 个词 → 有效 15 条
#   再跑 14 个词 → 有效 8 条
#   一口气跑 31 个词 → 有效 1 条，之后连「数据中心 巴淡」都返回 0，等了 75 秒还没恢复
# 搜狗是按请求次数累计限流的，不是按频率。硬跑 30 个词会把 IP 打进冷宫几十分钟。
# 所以分 3 组、每天只跑一组（约 10 个词），三天轮一遍。要加新词就加进当天这组。
KW_GROUPS = {
    # A 组：东南亚的用电用热 —— 目标最集中，命中率最高
    'A': ['数据中心 巴淡', '印尼 数据中心', '印尼 电厂', '越南 电厂', '马来 电厂',
          '自备电厂 印尼', '印尼 用电', '电解铝 印尼', '印尼 镍矿', '印尼 冶炼'],
    # B 组：固废、水、非洲 —— 伟明/旺能那条线，还有几内亚铝土那些
    'B': ['垃圾焚烧 出海', '垃圾焚烧 印尼', '垃圾焚烧 非洲', '海水淡化 印尼',
          '工业污水 海外', '非洲 电厂', '非洲 建厂', '非洲 冶炼',
          '几内亚 铝土', '沙特 建厂'],
    # C 组：其余地区 + 泛出海兜底
    'C': ['中资出海 建厂', '海外 电站', '沙特 电站', '哈萨克 建厂', '乌兹别克 建厂',
          '马来 建厂', '越南 建厂', '水泥 海外', '钢铁 海外', '中资 印尼',
          '出海 园区'],
}


def today_group():
    """按日期取模轮换。用「年内第几天 % 3」，保证每天换一组、三天一轮。"""
    import datetime
    return 'ABC'[datetime.date.today().timetuple().tm_yday % 3]


KW = KW_GROUPS[today_group()]

# ── 噪声：卖服务给中国企业的软文，不是项目情报 ──────────────────────────
# 实测抓下来，噪声主要三类，都被下面这套词盖住：
#   劳务派遣（「印尼火电厂土建项目」其实是招工广告）
#   律所/会计所（「算力出海(七)——项目开发与融资的法律衔接」）
#   设备商/工程分包（「烟气处理设备怎么出海」）
AD_W = ('培训', 'LMS', '合规指引', '一站式', 'FastPass', '代办', '咨询服务',
        '注册公司', '财税', '签证', '招聘', '猎头', '物流专线', '货代',
        '选型', '怎么选', '哪家', '推荐', '攻略', '指南', '避坑', '必看',
        '课程', '直播', '报名', '峰会报名', '白皮书', '下载',
        '劳务', '招工', '出国打工', '薪资', '月薪', '包吃住',
        '律师事务所', '律师', '法律服务', '法律顾问', '大成研究', '锦天城',
        '如何', '怎么做', '解析', '实务', '问答', '解读',
        '直招', '岗位', '职位', '招聘信息', '求职',
        '解决方案', '提供商', '集成商', '供应商', '厂家')
# 国内新闻：讲的是国内项目，跟出海无关
DOMESTIC_W = ('国内首个', '我国首个', '全省首个', '全市首个', '本项目位于',
              '招标公告', '中标结果', '环评受理', '竣工验收')

# ── 业务相关度打分 ──────────────────────────────────────────────────────
# 高：工程本体就是我们的活
S_W = ('热电', '供热', '余热', '脱硫', '脱硝', '超低排放', '污水', '废水',
       '中水', '零排放', '海水淡化', '淡化厂', '垃圾焚烧', '固废', '飞灰',
       '自备电厂', '能源站', '锅炉', '汽轮', '发电', '电力', '用电',
       '缺水', '缺电', '电网', '装机')
# 中：客户行业建厂，厂里要配套
A_W = ('镍', '钴', '锂', '铜', '铝', '锌', '锰', '不锈钢', '钢铁', '冶炼',
       '化工', '化纤', '水泥', '造纸', '玻璃', '数据中心', '算力', 'IDC',
       '纺织', '印染', '化肥', '矿业', '矿山')


def score(title, summary):
    t = (title or '') + ' ' + (summary or '')
    s = sum(1 for w in S_W if w in t)
    a = sum(1 for w in A_W if w in t)
    return s * 3 + a


def is_ad(title, summary, source=''):
    """判断是不是服务商软文。

    来源公众号名也要查 —— 实测漏过一条「[红包]印尼火电厂土建项目」，
    标题摘要都看不出问题，但发它的号叫「佳点海外劳务」，是劳务派遣号。
    """
    t = (title or '') + ' ' + (summary or '') + ' ' + (source or '')
    return any(w in t for w in AD_W)


def is_domestic(title):
    return any(w in (title or '') for w in DOMESTIC_W)


def run_one(kw, days=10, num=8, retry=1):
    """调一次搜狗微信搜索。返回文章列表（可能为空）。

    为什么要重试：实测同一个关键词连跑三次，返回 7 → 0 → 7 条。
    不是被持续封，是**间歇性反爬**（随机吐空页）。所以空结果重试一次就能救回来，
    重试间隔 3 秒。这个坑不重试的话，日更会莫名其妙丢一半数据。
    """
    for attempt in range(retry + 1):
        arts = _run_once(kw, days, num)
        if arts:
            return arts
        if attempt < retry:
            time.sleep(3.0)
    return []


def _run_once(kw, days=10, num=8):
    try:
        p = subprocess.run(
            ['node', JS, kw, '-n', str(num), '-d', str(days)],
            capture_output=True, text=True, timeout=120, cwd=ROOT)
        out = p.stdout or ''
    except subprocess.TimeoutExpired:
        return []
    # 脚本前面有进度行，JSON 从第一个 { 开始
    i = out.find('{')
    if i < 0:
        return []
    try:
        d = json.loads(out[i:])
    except Exception:
        return []
    return d.get('articles') or []


def main():
    days = 10
    dry = '--dry' in sys.argv
    for i, a in enumerate(sys.argv):
        if a == '--days' and i + 1 < len(sys.argv):
            days = int(sys.argv[i + 1])

    seen = {}
    stat = []
    # 同一条新闻常被多个号转发，标题几乎一样但 url 不同 —— 只按 url 去重会重复显示。
    # 这里再按「标题前 24 字」压一道（实测「数据中心日报|11.04 印尼20GW用电缺口」
    # 在两个号上同时出现，标题一字不差）。
    seen_title = set()
    for kw in KW:
        arts = run_one(kw, days)
        n_new = 0
        for x in arts:
            u = x.get('url') or ''
            ti = (x.get('title') or '').strip()
            if not ti or u in seen:
                continue
            key = re.sub(r'[\s\|｜:：,，。.\-—\[\]【】()（）]', '', ti)[:24]
            if key in seen_title:
                continue
            if is_ad(ti, x.get('summary'), x.get('source')):
                continue
            if is_domestic(ti):
                continue
            sc = score(ti, x.get('summary'))
            if sc < 3:          # 不沾业务的直接丢，速览不是资讯大全
                continue
            seen_title.add(key)
            seen[u] = {
                'title': ti,
                'url': u,
                'summary': (x.get('summary') or '')[:220],
                'date': (x.get('datetime') or '')[:10],
                'datetime': x.get('datetime') or '',
                'src': x.get('source') or '',
                'kw': kw,
                'sc': sc,
            }
            n_new += 1
        stat.append((kw, len(arts), n_new))
        print('%-16s 抓到 %2d 条 → 有效 %d' % (kw, len(arts), n_new))
        time.sleep(4.5)     # 搜狗反爬比较敏感，间隔别低于 4 秒

    print('\n本次跑的是 %s 组，共 %d 个词' % (today_group(), len(KW)))
    items = sorted(seen.values(), key=lambda x: (x['datetime'] or '', -x['sc']), reverse=True)
    print('\n合计 %d 条' % len(items))
    if dry:
        for x in items[:20]:
            print('  [%d] %s | %s | %s' % (x['sc'], x['date'], x['src'][:12], x['title'][:56]))
        return
    old = {}
    if os.path.exists(OUT):
        try:
            for x in json.load(open(OUT, encoding='utf-8')).get('items', []):
                old[x['url']] = x
        except Exception:
            pass
    for x in items:
        old.setdefault(x['url'], x)
    merged = sorted(old.values(), key=lambda x: (x.get('datetime') or '', -x.get('sc', 0)), reverse=True)
    # 只留 60 天内的，防止无限膨胀
    cut = time.strftime('%Y-%m-%d', time.localtime(time.time() - 60 * 86400))
    merged = [x for x in merged if (x.get('date') or '') >= cut]
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(merged),
               'items': merged}, open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('写入 %s（含历史累计 %d 条）' % (OUT, len(merged)))


if __name__ == '__main__':
    main()
