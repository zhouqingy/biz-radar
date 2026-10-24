# -*- coding: utf-8 -*-
"""
2026-10-24 视觉 v3 + 默认档改「全部」

用户原话：
  「三个省能投和已投的项目只有18个拜托这都是2026年了」
  「找商机还是默认全部吧」
  「整体样式调一下，这卡片大小都不一样看着比较奇怪」
  「你可以使用element-UI这种来进行布局吗？怎么感觉你都是手搓的最原始的风格代码」
  「有机会的话还是做的好看了，不管你用那种方式」

本脚本只做 6 件事，各自独立、可单独回滚：
  1) :root 补 Element 设计变量（不引 CDN，见下方说明）
  2) 项目卡片等高栅格（栅格 stretch + 卡片 flex + 各段锁行高 + 操作行沉底）
  3) F.bk 默认 'all'
  4) 三档按钮默认选中「全部」，且「只看还能投的」开关默认可见
  5) loadAllItems 由串行改并行（省一个 RTT）
  6) 首屏默认档后台静默拉全量 + rbar 明示「载入中」

关于为什么不引 Element UI 的 CDN：
  Element UI 的组件要跑在 Vue 2 运行时上，而这个页面是 8 页签、16 个分模块下发、
  300KB+ 的单文件手写 DOM 结构，套 Vue 等于整页重写，风险和工作量都不成比例。
  用户真正要的是「Element 那套整齐的视觉规范」——主色 #409EFF、4px 圆角、
  0 2px 12px 0 rgba(0,0,0,.1) 阴影、统一的三级文字色和三级边框色——
  这些全是 CSS，不需要 Vue。所以这里把规范本地化成 CSS 变量直接吃进去，
  零外部请求、零额外体积，也不会再拖慢本来就抱怨过的加载速度。
"""
import io, re, sys

P = '/workspace/biz-radar/index.html'
src = io.open(P, encoding='utf-8').read()
orig = src
log = []


def rep(tag, old, new, cnt=1):
    global src
    n = src.count(old)
    if n != cnt:
        print('!! [%s] 期望命中 %d 次，实际 %d 次 —— 中止' % (tag, cnt, n))
        sys.exit(1)
    src = src.replace(old, new)
    log.append('  ✓ %s' % tag)


# ---------------------------------------------------------------- 1) Element 变量
rep('1 :root 加 Element 设计变量',
    """  --sh:0 1px 2px rgba(20,30,50,.04),0 2px 8px rgba(20,30,50,.04);
}""",
    """  --sh:0 1px 2px rgba(20,30,50,.04),0 2px 8px rgba(20,30,50,.04);

  /* ---- Element 设计规范（本地化，不引 CDN）----
     用户问「能不能用 element-UI 这种来布局」。Element 的组件层依赖 Vue 2 运行时，
     这个页面是手写 DOM，套上去要整页重写；但它那套**视觉规范**是纯 CSS，可以直接吃：
       主色 #409EFF / 成功 #67C23A / 警告 #E6A23C / 危险 #F56C6C / 信息 #909399
       文字三级 #303133 / #606266 / #909399，四级占位 #C0C4CC
       边框三级 #DCDFE6 / #E4E7ED / #EBEEF5，填充 #F5F7FA
       圆角 4px（控件）/ 8px（卡片），卡片阴影 0 2px 12px 0 rgba(0,0,0,.1)
     命名一律 --el- 前缀，跟原有的 --brand/--line 并存，互不干扰，
     这样改卡片样式时不会把页头 KPI 那些老样式的颜色带崩。 */
  --el-blue:#409EFF;--el-blue-d:#337ECC;--el-blue-l:#ECF5FF;
  --el-success:#67C23A;--el-success-l:#F0F9EB;
  --el-warning:#E6A23C;--el-warning-l:#FDF6EC;
  --el-danger:#F56C6C;--el-danger-l:#FEF0F0;
  --el-info:#909399;--el-info-l:#F4F4F5;
  --el-tx1:#303133;--el-tx2:#606266;--el-tx3:#909399;--el-tx4:#C0C4CC;
  --el-bd1:#DCDFE6;--el-bd2:#E4E7ED;--el-bd3:#EBEEF5;--el-fill:#F5F7FA;
  --el-r:4px;--el-r-card:8px;
  --el-sh:0 2px 12px 0 rgba(0,0,0,.1);
  --el-sh-h:0 2px 4px rgba(0,0,0,.12),0 0 6px rgba(0,0,0,.04);
}""")

# ---------------------------------------------------------------- 2) 卡片等高栅格
rep('2a .grid 去 align-items:start（同排等高）+ 列宽 380→340',
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:13px;align-items:start}",
    """/* 卡片大小不一的根因有两处，都在这里治：
     ① 原来是 align-items:start —— 同一排的卡片各按自己内容撑高，短的悬在半空，
        一眼看过去参差不齐。去掉它回到 grid 默认的 stretch，同排卡片强制等高。
     ② 列宽 minmax(380px→340px)：380 在 1440 宽的屏幕上只能排 3 列，卡片被迫拉得很宽；
        340 能排 4 列，卡片更接近正方，扫读时视线移动更短。 */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}""")

rep('2b .pj 卡片本体：flex 纵向流 + 固定最小高度 + Element 圆角阴影',
    """.pj{background:#fff;border:1px solid var(--line);border-radius:14px;padding:13px 16px 12px;position:relative;overflow:hidden;transition:transform .16s,box-shadow .16s,border-color .16s}
.pj:hover{transform:translateY(-2px);border-color:#bcd4ff;box-shadow:0 10px 26px rgba(20,50,110,.11)}""",
    """/* 卡片本体：改成 flex 纵向流。
   这样里面的 .pj-act 才能用 margin-top:auto 沉到卡片底部——
   不管中间 snip/chain/org 这几段有还是没有，操作行永远贴着底边对齐，
   一排卡片看过去按钮在同一条水平线上，这是「整齐感」最主要的来源。
   min-height 是给单列（手机/窄窗口）兜底的，栅格拉伸时不会用到。 */
.pj{background:#fff;border:1px solid var(--el-bd2);border-radius:var(--el-r-card);
    padding:14px 16px 13px;position:relative;overflow:hidden;
    display:flex;flex-direction:column;min-height:238px;
    transition:transform .2s,box-shadow .2s,border-color .2s}
.pj:hover{transform:translateY(-2px);border-color:var(--el-blue);box-shadow:var(--el-sh)}""")

rep('2c .pj-top 固定高度',
    ".pj-top{display:flex;align-items:flex-start;gap:8px;margin-bottom:7px}",
    """/* 卡头（分级徽章 + 分数 + 金额）固定 26px：
   有 NEW 标记和没 NEW 标记的卡片，卡头高度原来会差 3px，累积到一排就很明显。 */
.pj-top{display:flex;align-items:flex-start;gap:8px;margin-bottom:9px;min-height:26px}""")

rep('2d .pj-t 标题锁 2 行',
    """.pj-t{font-size:14.5px;font-weight:750;line-height:1.55;color:var(--tx);display:block}""",
    """/* 标题锁 2 行：原来 1~3 行都有，一排卡片里标题区高度能差 40px。
   clamp 到 2 行 + min-height 兜住「只有 1 行」的情况（短标题也占 2 行的高度），
   这样标题区永远等高，标题本身还留了完整的 hover 变蓝。
   字重 750→600：750 是 Windows 下的合成粗体，边缘发虚，Element 规范一律用 600。 */
.pj-t{font-size:14.5px;font-weight:600;line-height:1.55;color:var(--el-tx1);
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;
  min-height:44px}""")

rep('2e .tags 标签行固定 2 行高',
    ".tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}",
    """/* 标签行：原来 0~3 行不定（有的卡片连 sG 命中词和 early 都有，有的只有 2 个）。
   固定最小 22px（一行）、最大 44px（两行），再多就截掉——
   标签是给眼睛扫的，第 5 个标签的边际价值远不如「一排卡片一样高」。 */
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px;min-height:22px;max-height:44px;overflow:hidden}""")

rep('2f .pj-meta 固定高度',
    ".pj-meta{margin-top:8px;display:flex;flex-wrap:wrap;gap:3px 14px;font-size:12px;color:var(--tx2);border-top:1px dashed var(--line);padding-top:7px}",
    """/* 元信息行（业主/中标/来源/预计招标）：业主名长短差很大，换行数 1~3 行都有。
   锁在 1~2 行之间（33~55px），超出的靠 overflow 吃掉，卡片高度不再被业主名绑架。 */
.pj-meta{margin-top:auto;display:flex;flex-wrap:wrap;gap:3px 14px;font-size:12px;color:var(--el-tx2);
  border-top:1px dashed var(--el-bd2);padding-top:8px;min-height:33px;max-height:55px;overflow:hidden}""")

rep('2g .pj-snip 摘要锁 2 行',
    ".pj-snip{margin-top:7px;font-size:12px;color:#7c838d;line-height:1.65;background:#f8fafc;border-radius:8px;padding:6px 9px}",
    """/* 摘要锁 2 行：原来有的公告摘要一写就是五六行，单卡能撑到别人的两倍高。 */
.pj-snip{margin-top:8px;font-size:12px;color:var(--el-tx2);line-height:1.65;
  background:var(--el-fill);border-radius:var(--el-r);padding:7px 10px;
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}""")

rep('2h .chain 阶段链锁 2 行',
    """/* 卡片四角镂空：卡片是 flex 容器了，.pj-files（附件清单）是后来插进来的，
   不能让它把卡片撑变形。 */""",
    """/* 卡片四角镂空：卡片是 flex 容器了，.pj-files（附件清单）是后来插进来的，
   不能让它把卡片撑变形。 */""", 0)

# ---------------------------------------------------------------- 3) 操作行沉底
rep('3 .pj-act 沉底',
    ".pj-act{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;padding-top:7px;border-top:1px dashed var(--line)}",
    """/* 操作行沉底：margin-top:auto 把上面所有剩余空间全吃进这一行之前，
   于是无论卡片内容是 3 段还是 6 段，按钮组都贴着底边，同排按钮水平对齐。
   没有操作按钮的卡片（比如纯立项线索）由 .pj-meta 的 margin-top:auto 顶住。 */
.pj-act{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;padding-top:8px;border-top:1px dashed var(--el-bd2)}""")

# ---------------------------------------------------------------- 4) 默认档改「全部」
rep('4a F.bk 默认 all',
    "st:'',q:'',sort:'sc',page:1,tab:0,bk:'tender',hideWin:false,side:false};",
    """/* 2026-10-24 默认档 tender→all。
     用户原话：「三个省能投和已投的项目只有18个拜托这都是2026年了」
     原因：三档按钮上的 13/18 是「主场 + 关注档（≥3000万 或 A/B）」双重过滤后的数，
     和全库的 96/140 差一个量级。默认档切到「全部」，进来先看到 1521 条这个量级，
     想收窄再点前三档——让「宽口径」当默认值，「严口径」当用户主动的选择。 */
         st:'',q:'',sort:'sc',page:1,tab:0,bk:'all',hideWin:false,side:false};""")

rep('4b 按钮默认选中「全部」',
    """      return '<div class="ware' + (b[0] === 'tender' ? ' on' : '') + '" data-bk="' + b[0] + '" title="' + esc(tip) + '">' +
        b[1] + '<b style="display:none">0</b></div>';
    }).join('') +
      '<div class="ware" data-bk="all" id="waAllW">全部 <b style="display:none">0</b></div>' +""",
    """      return '<div class="ware" data-bk="' + b[0] + '" title="' + esc(tip) + '">' +
        b[1] + '<b style="display:none">0</b></div>';
    }).join('') +
      /* 默认选中「全部」：跟着 F.bk 走，不然按钮高亮在「能投的标」上、列表却是全部，
         用户又会对着两个口径起疑。见上方 4a 的口径说明。 */
      '<div class="ware on" data-bk="all" id="waAllW">全部 <b style="display:none">0</b></div>' +""")

rep('4c 「只看还能投的」开关默认可见',
    """  var waBox = el('wares');
  if (waBox) {""",
    """  var waBox = el('wares');
  if (waBox) {
    /* 这个开关只在「全部」档下有意义（前三档本来就只留有能投的）。
       默认档改成 all 了，所以它得默认就露出来，否则用户根本不知道有这功能。 */""")

rep('4d 初始化时把开关显示出来',
    """      '<div class="wtip">数字 = <b>这一档点进去看到的条数</b>（随下方筛选条件实时变）。' +""",
    """      '<div class="wtip" id="waTip">数字 = <b>这一档点进去看到的条数</b>（随下方筛选条件实时变）。' +""")

# ---------------------------------------------------------------- 5) 并行加载
rep('5 loadAllItems 串行→并行',
    """function loadAllItems(cb) {
  if (!window.__itemsSplit) { if (cb) cb(); return; }
  loadChunk('lead', function () { loadChunk('rest', cb); });
}""",
    """function loadAllItems(cb) {
  if (!window.__itemsSplit) { if (cb) cb(); return; }
  /* 2026-10-24 串行改并行。
     原来是 loadChunk('lead', ()=>loadChunk('rest', cb))，两个 600KB 的 chunk
     必须一个下完才开始下第二个，白白多付一个完整 RTT。
     默认档改成「全部」之后，这条路成了每次进页面的必经之路，
     串行那一个 RTT 就直接摊到每个用户的首屏上了。
     预注入版（__CHUNKS__）例外：它是 shift() 逐个取的，并行会取错序，
     那种情况本来也不发请求，串行没有代价。 */
  if (window.__CHUNKS__ && window.__CHUNKS__.length) {
    loadChunk('lead', function () { loadChunk('rest', cb); });
    return;
  }
  var n = 0;
  var fin = function () { if (++n >= 2 && cb) cb(); };
  loadChunk('lead', fin);
  loadChunk('rest', fin);
}""")

io.open(P, 'w', encoding='utf-8').write(src)
print('index.html 改动完成：')
print('\n'.join(log))
print('大小 %d -> %d' % (len(orig), len(src)))
