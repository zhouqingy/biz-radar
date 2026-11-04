# -*- coding: utf-8 -*-
"""金属行情历史 · 生成 data.metalhist.js

为什么要这份文件（2026-10-30 用户提的）：
  页面原来只有一条「当日行情」——13 个品种每天一个价格 + 涨跌幅，看不出趋势。
  用户原话：「这个加历史价格曲线图加了吗」。
  做投标决策真正要看的是「现在的价格处在什么位置」「这三个月是涨还是跌」，
  单点价格给不了这个信息。

数据从哪来：
  新浪财经的期货日 K 接口（InnerFuturesNewService.getDailyKLine）。
  ⚠ 这条路是 2026-10-28 就验证过的（见 verify_metal_history.py 的注释）：
     不用自己按日存档攒历史，接口直接给全历史 ——
     沪铜能追到 2005-01-04、5300 多条，氧化铝上市晚（2023-06）只有 800 多条。
     所以「历史曲线」不依赖我们跑多久，第一天上线就有 20 年。
  ⚠ 浏览器直连这条路走不通（新浪校验 Referer、东财不支持跨域、腾讯无国内期货），
     只能在服务端抓、生成静态文件 —— 和 metals 当日行情同一条链路。

产出格式（体积优先）：
  每个品种只存「日期(MMDD) + 收盘价」，价格取整（元/吨精确到小数没意义，
  沪铜 108660.0 存成 108660）。近 5 年全量 + 更早的按月采样，
  两段各自够画「近 30/90 天」和「近 5 年」两条线。
"""
import json, os, re, subprocess, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.environ.get('BIZ_OUT') or os.path.join(ROOT, '..'), 'data.metalhist.js')
RAW = os.path.join(ROOT, 'raw', 'metal_hist_raw.json')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'
API = ('https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20_{s}=/'
       'InnerFuturesNewService.getDailyKLine?symbol={s}')

# (页面 code, 新浪代码, 中文名, 单位) —— code 与 data.core.js 的 metals.items 对齐
SYMS = [
    ('CU', 'CU0', '沪铜', '元/吨'),
    ('AL', 'AL0', '沪铝', '元/吨'),
    ('ZN', 'ZN0', '沪锌', '元/吨'),
    ('PB', 'PB0', '沪铅', '元/吨'),
    ('NI', 'NI0', '沪镍', '元/吨'),
    ('SN', 'SN0', '沪锡', '元/吨'),
    ('AO', 'AO0', '氧化铝', '元/吨'),
    ('SS', 'SS0', '不锈钢', '元/吨'),
    ('LC', 'LC0', '碳酸锂', '元/吨'),
    ('RB', 'RB0', '螺纹钢', '元/吨'),
    ('HC', 'HC0', '热轧卷板', '元/吨'),
    ('I',  'I0',  '铁矿石', '元/吨'),
    ('JM', 'JM0', '焦煤', '元/吨'),
]

RECENT_DAYS = 1260      # 近 5 年（约 252×5 交易日）保留逐日
# 更早的部分**全部**按月采样（每个月只留一个点）。
# ⚠ 2026-10-30 修：原来写的是 12*12=144，意思是"只留最近 12 年"，
#   但 144 是**采样点个数**，沪铜从 2005 年到近 5 年之前有 16 年多 = 190 多个月，
#   于是被截掉最前面 4 年 —— 页面标着 start=2005-01-04，曲线却从 2009-09-30 起，
#   「全部」区间看了个假开头。按月采样本身就把 190 个点压到很小，没必要再截。
MONTH_KEEP = None       # None = 不截断


def fetch(sym):
    url = API.format(s=sym)
    r = subprocess.run(['curl', '-s', '-m', '40', '-A', UA,
                        '-H', 'Referer: https://finance.sina.com.cn/', url],
                       capture_output=True)
    txt = r.stdout.decode('utf-8', 'ignore')
    m = re.search(r'var _\w+=\((\[.*\])\)', txt, re.S)
    if not m:
        return None
    try:
        raw = json.loads(m.group(1))
    except Exception:
        return None
    out = []
    for x in raw:
        try:
            out.append((x['d'], round(float(x['c']), 1)))
        except Exception:
            continue
    return out


def thin(rows):
    """近 5 年逐日；更早的按月采样（每月最后一个交易日）。
    返回 (dates[], prices[], start, end, daily_from_idx)"""
    n = len(rows)
    if n <= RECENT_DAYS:
        keep = rows
        daily_from = 0
    else:
        older = rows[:n - RECENT_DAYS]
        recent = rows[n - RECENT_DAYS:]
        # 老段按月末采样
        bym = {}
        for d, c in older:
            bym[d[:7]] = (d, c)
        keys = sorted(bym.keys())
        if MONTH_KEEP:
            keys = keys[-MONTH_KEEP:]
        old_keep = [bym[k] for k in keys]
        keep = old_keep + recent
        daily_from = len(old_keep)
    return keep, daily_from


def main():
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    raw_all, series = {}, {}
    ok = 0
    for code, sym, name, unit in SYMS:
        rows = fetch(sym)
        if not rows:
            print(f'  ✗ {name}({sym}) 抓取失败，跳过')
            continue
        raw_all[sym] = rows
        keep, daily_from = thin(rows)
        # 日期编码分两段：
        #   老段（按月采样）→ 存完整 'YYYY-MM-DD'，反正只有 100~200 个点，省不了几个字节，
        #                     但省掉了前端「按月份倒推年份」的猜测，跨年不会错。
        #   新段（近 5 年逐日）→ 存 'MMDD'，一年内不会撞车，前端靠 end 年份往前推。
        ds, ps = [], []
        for i, (d, c) in enumerate(keep):
            ds.append(d if i < daily_from else d[5:].replace('-', ''))
            ps.append(c)
        series[code] = {
            'n': name, 'u': unit, 'sym': sym,
            # ⚠ start 要写**实际输出曲线的首点**，不是原始数据的首日 ——
            #   老段按月采样，首点是当月最后一个交易日（沪铜 2005-01-04 → 2005-01-31），
            #   写原始首日会让页头标 2005-01-04 而曲线从 1 月底起，对不上。
            'start': keep[0][0], 'end': keep[-1][0],
            'cnt': len(rows), 'df': daily_from,   # df=逐日数据从第几位开始
            'd': ds, 'p': ps,
        }
        ok += 1
        print(f'  ✓ {name:6s} 原始{len(rows):5d}条 → 输出{len(keep):5d}点  '
              f'{rows[0][0]} ~ {rows[-1][0]}  最新 {ps[-1]}')

    if ok == 0:
        print('!! 全部失败，不覆盖线上文件')
        return 1

    json.dump(raw_all, open(RAW, 'w'), ensure_ascii=False)

    payload = {
        'updated': datetime.now().strftime('%Y-%m-%d'),
        'src': '新浪财经期货日K · InnerFuturesNewService.getDailyKLine',
        'note': 'df 之后是逐日（MMDD，年份由 end 倒推）；df 之前是月末采样（YYYY-MM-DD）',
        's': series,
    }
    js = ('/* 金属行情历史 · 近5年逐日 + 更早按月采样\n'
          '   生成：tools/gen_metal_hist.py   数据源：新浪财经期货日K\n'
          f'   数据日：{payload["updated"]}   品种：{ok} 个\n'
          '   ⚠ 这份文件是按需加载的（约 300KB），不进首屏。 */\n'
          'window.DATA_METALHIST=' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + ';\n')
    open(OUT, 'w', encoding='utf-8').write(js)
    print(f'\n写到 {OUT}  {os.path.getsize(OUT)/1024:.0f} KB  {ok} 个品种')
    return 0


if __name__ == '__main__':
    sys.exit(main())
