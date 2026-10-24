# -*- coding: utf-8 -*-
"""patch_ui_v3 的第二半：操作行沉底、开关默认显形、首屏后台拉全量、页签数字口径。

分成两个脚本是因为这些改动依赖 v3 已经落地的结构（.pj 已经是 flex 容器、
F.bk 已经默认是 all），合在一起写会互相打架，也方便单独回滚。
"""
import io, sys

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


# ---- 1) 弹性占位：把卡片上部内容顶上去，底部区（原始发布/附件/操作行）沉底 ----
rep('1 卡片插弹性占位',
    """    (x.snip?'<div class="pj-snip">'+esc(x.snip)+'</div>':'')+chain+
    originLine(x)+fileList(x)+acts+'</div>';""",
    """    (x.snip?'<div class="pj-snip">'+esc(x.snip)+'</div>':'')+chain+
    /* 弹性占位：把上面「卡头/标题/标签/元信息/摘要/阶段链」整块顶到卡片上端，
       下面「原始发布/附件/操作按钮」整块吸到卡片下端。
       没有它，卡片内容少的那些（比如纯立项线索没有附件也没有操作按钮）会整块悬在上半截，
       底部空一大块，一排卡片看着就是「有的满有的空」。
       有了它，不管中间几段内容，操作按钮永远在同一条水平线上。 */
    '<i class="pj-sp"></i>'+originLine(x)+fileList(x)+acts+'</div>';""")

rep('1b .pj-sp 样式',
    """.pj-snip{margin-top:8px;font-size:12px;color:var(--el-tx2);line-height:1.65;""",
    """/* 卡片内的弹性占位：撑开上下两区之间的空白，自己不显示任何东西。
   min-height 保证内容超满的卡片也不会把两区挤成零间距。 */
.pj-sp{flex:1 1 auto;min-height:6px}
.pj-snip{margin-top:8px;font-size:12px;color:var(--el-tx2);line-height:1.65;""")

rep('1c .pj-meta 去掉 auto（沉底交给 spacer）',
    ".pj-meta{margin-top:auto;display:flex;flex-wrap:wrap;gap:3px 14px;font-size:12px;color:var(--el-tx2);",
    ".pj-meta{margin-top:9px;display:flex;flex-wrap:wrap;gap:3px 14px;font-size:12px;color:var(--el-tx2);")

# ---- 2) 「只看还能投的」开关默认显形（v3 只加了注释，这里补实际动作）----
rep('2 开关默认显形',
    """      var d = e.target.closest('.ware'); if (!d) return;
      pick(d.dataset.bk);
    };
  }""",
    """      var d = e.target.closest('.ware'); if (!d) return;
      pick(d.dataset.bk);
    };
    /* 默认档是「全部」，所以这个开关进来就得是显形的。
       原来它常驻 display:none，只有用户手点「全部」才出现——
       默认档改了之后，不补这一句用户永远看不到它。 */
    var _h0 = el('waHide');
    if (_h0) _h0.style.display = 'inline-block';
  }""")

# ---- 3) 页签「找商机」的数字口径跟着默认档走 ----
rep('3 页签数字 → 全部口径',
    "  _setTab('p-items',   (_W.tenderAll||0)+(_W.winAll||0)+(_W.lead||0));",
    """  /* 默认档是「全部」，页签上的数字就得是「全部」的条数，
     否则用户点进去看到 1521 条、页签却写着 490，又要怀疑一次。
     取不到 all 就退回三档相加（老口径），别显示 0。 */
  _setTab('p-items',   (_W.all||0) || ((_W.tenderAll||0)+(_W.winAll||0)+(_W.lead||0)));""")

# ---- 4) 首屏后台拉全量（不阻塞首屏）----
rep('4 首屏后台拉全量',
    """  buildFilters();  // 筛选器 + 三档关注库
  buildRivalFilter();
  render();        // 商机库第一页""",
    """  buildFilters();  // 筛选器 + 三档关注库
  buildRivalFilter();
  render();        // 商机库第一页
  /* 默认档是「全部」，可首屏只有 42 条切片——名义 1521、实际 42，又是数字对不上。
     这里在后台把 lead + rest 两块并行拉下来，拉完自动重渲，数字自然涨上去。
     刻意**不阻塞首屏**：卡片先出来让用户有事干，也比盯着白屏等 10 秒强。
     ⚠ 不要改成先 loadAllItems 再 render：那样首屏时间 = 两块 600KB 的下载时间，
       而用户已经抱怨过「上传这么慢」了。 */
  if ((F.bk || 'all') === 'all' && window.__itemsSplit) {
    loadAllItems(function () { render(); refreshFilterCounts(); });
  }""")

# ---- 5) 载入中提示：让人知道数字还会涨 ----
rep('5a rbar 载入中提示',
    """  var nAmt=a.filter(function(x){return num(x.amt)>0}).length;
  var nNo=a.length-nAmt;
  el('rbar').innerHTML='<span>命中 <b>'+a.length+'</b> 条 · 其中 <b>'+nAmt+'</b> 条有金额 · 这 '+nAmt+' 条合计 <b>'+sum.toFixed(1)+' 亿</b></span>'+""",
    """  var nAmt=a.filter(function(x){return num(x.amt)>0}).length;
  var nNo=a.length-nAmt;
  /* 分块还没拉完时，这里的 a.length 只是当前已到位的条数，不是全库。
     不写明的话用户看到「命中 42 条」就当成了全库只有 42 条——
     这是他上一轮质疑「三个省只有这么几个项目」的直接来源。
     所以加载中就明说：现在 42 条，全库 1521 条，正在载入。 */
  var _loading = window.__itemsSplit &&
    !((_chunkState['lead'] === 'done' || _chunkState['lead'] === 'err') &&
      (_chunkState['rest'] === 'done' || _chunkState['rest'] === 'err'));
  var _loadTip = _loading
    ? '<span class="rload"><i></i>全库共 <b>' + (meta.total || 0) + '</b> 条，正在载入…（当前已到位 ' + a.length + ' 条）</span>'
    : '';
  el('rbar').innerHTML='<span>命中 <b>'+a.length+'</b> 条 · 其中 <b>'+nAmt+'</b> 条有金额 · 这 '+nAmt+' 条合计 <b>'+sum.toFixed(1)+' 亿</b></span>'+_loadTip+""")

rep('5b .rload 样式 + 旋转点',
    """.rbar .rhint{margin-left:auto;display:flex;gap:8px;align-items:center}""",
    """.rbar .rhint{margin-left:auto;display:flex;gap:8px;align-items:center}
/* 载入中提示：一个转圈的点 + 一句话。
   用它而不是 progress 条，是因为这是后台静默加载，
   页面完全可用，没必要拿个进度条挡在最显眼的位置。 */
.rload{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--el-tx3);
  background:var(--el-blue-l);border:1px solid #d9ecff;border-radius:20px;padding:2px 12px}
.rload b{color:var(--el-blue-d);font-size:12px;font-weight:700}
.rload i{width:6px;height:6px;border-radius:50%;background:var(--el-blue);flex:none;
  animation:rspin 1s linear infinite}
.rload i::after{content:'';display:block;width:6px;height:6px;border-radius:50%;
  box-shadow:0 -9px 0 -2px var(--el-blue)}
@keyframes rspin{to{transform:rotate(360deg)}}""")

io.open(P, 'w', encoding='utf-8').write(src)
print('index.html 改动完成：')
print('\n'.join(log))
print('大小 %d -> %d' % (len(orig), len(src)))
