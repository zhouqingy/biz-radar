# -*- coding: utf-8 -*-
"""开工前必读校验 · 防止 AI / 脚本在没搞清「我们是做什么的」之前碰数据

用户 2026-11-05 18:35 原话：
  「不管用哪个软件的 AI，开始做事之前都需要去了解我们是做什么的，就是那个文件，
    你给我设置成开始聊天必读的一个文件，必须把那个文件读完之后才能做数据识别、
    数据筛选，了解清楚嘛，不然你乱找的话只会污染数据库。」

做法：任何采集 / 构建 / 体检脚本启动时先调用 require_briefing()。
它会真的把 00-公司业务口径.md 读一遍、校验关键锚点、打印口径摘要；
文件缺失或关键章节被删 → 直接 SystemExit，禁止继续碰数据。

这不是形式主义：口径不清就跑筛选，会把不该留的标塞进①投放库（历史教训见 §5.1）。
"""
import os, sys

BRIEFING = '/workspace/00-公司业务口径.md'

# 关键锚点：文件里必须有，否则视为口径底稿不完整
ANCHORS = [
    ('主业定义', '能源清洁高效利用'),
    ('国内重点', '钢铁行业'),
    ('海外判据', '看业主是谁'),
    ('两个库', '投放 / 商机库'),
    ('过滤总纲', '5.1 总纲'),
    ('规则源', 'semantic_drop'),
    ('金额分层', 'AMT_FOCUS_MIN_YI'),
]

SUMMARY = """  · 主业：能源清洁高效利用（燃煤火电/煤气发电/余热发电/热电联产/光伏+储能+柴发）；交付 EPC / F+EPC / EPC+O / EP
  · 地域分工：国内主营钢铁 + 市政园区热电联产（江浙沪皖）；海外主线有色（看业主是谁，不看项目在哪个国家）
  · 两个库：①投放/商机库严格过滤（标的必须是能源设施本体）；②业绩/动向库按单位聚合，②反推①必须再过①过滤
  · 过滤唯一规则源：biz_rules.py 的 judge() + semantic_drop()；采集端 collect_v4.py、构建端 build_web.py 都调同一份
  · 关注档：金额 ≥1 亿 → w=1 重点关注；<1 亿 / 无金额 → w=0 留库不删（AMT_FOCUS_MIN_YI=1.0）
  · 删除规则：12 条启用（11 类词表 + N13 存量主设备改造），护栏 W / W2 / W3 / W4 先判"""


def find_briefing():
    """按「最近优先」找底稿，返回绝对路径或 None。

    为什么不再写死单一绝对路径（2026-11-08 §5.53）：
      collect_v4 / build_data / build_web / update_weekly 都 import 本模块，
      在 GitHub Actions 里工作目录是仓库根，底稿不可能在 /workspace/ 下。
      写死路径 → CI 每次开跑就 SystemExit(2) → 4 个 Action 全红。
      而「同步 tools/ 让 Action 能自动更新」正卡在这里。

    查找顺序（先近后远，谁先存在用谁）：
      ① 环境变量 BIZ_BRIEFING 指定的路径（排查/临时覆盖用）
      ② 本文件所在目录（也就是 tools/）下的 00-公司业务口径.md —— CI 主用
      ③ 上一级目录（本地 /workspace 布局：底稿与 tools/ 平级）
      ④ 历史写死路径 /workspace/00-公司业务口径.md（本地沙箱）
    四步都找不到才拦，拦的时候把试过的路径全打出来，别让人猜。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    cands = []
    env = os.environ.get('BIZ_BRIEFING')
    if env:
        cands.append(env)
    cands += [
        os.path.join(here, '00-公司业务口径.md'),          # tools/00-…（CI）
        os.path.join(os.path.dirname(here), '00-公司业务口径.md'),  # 仓库根/工作区根
        BRIEFING,                                          # /workspace/00-…
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c), cands
    return None, cands


def require_briefing(caller='unknown', quiet=False):
    """读底稿 → 校验锚点 → 打印摘要。失败直接退出，不允许后续数据操作。"""
    path, tried = find_briefing()
    if not path:
        sys.stderr.write('[开工拦截] 找不到业务口径底稿，禁止做数据识别/筛选/入库\n')
        for c in tried:
            sys.stderr.write('  试过：%s\n' % c)
        raise SystemExit(2)
    bp = path
    try:
        text = open(bp, encoding='utf-8').read()
    except Exception as e:
        sys.stderr.write('[开工拦截] 底稿读不了：%s\n' % e)
        raise SystemExit(2)
    missing = [name for name, kw in ANCHORS if kw not in text]
    if missing:
        sys.stderr.write('[开工拦截] 底稿缺关键章节 %s，口径不完整，禁止继续\n' % missing)
        raise SystemExit(2)
    if not quiet:
        sys.stdout.write('[开工必读] %s 已读《00-公司业务口径.md》（%d 字）\n' % (caller, len(text)))
        sys.stdout.write(SUMMARY + '\n')
    return {'path': bp, 'chars': len(text), 'anchors': len(ANCHORS), 'caller': caller}


if __name__ == '__main__':
    r = require_briefing('preflight 自检')
    print('\n校验通过：%d 个关键锚点齐全，口径可加载。' % r['anchors'])
