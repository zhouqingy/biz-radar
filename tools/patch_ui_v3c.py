# -*- coding: utf-8 -*-
"""第三批补丁 v2：把「命中 602 / 全库 1521」的差值在统计条上说清楚。

上一版把 onclick 直接内联在字符串里，Python 的 \' 转义把 JS 字符串的引号吃了，
落进 HTML 变成 var c=el('f-side')... —— 外层本来就是单引号字符串，直接 SyntaxError。
这一版改成事件委托：a.rside 不带任何内联 JS，只挂 data-act，点击统一走 document 级监听。
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


rep('1a rbar 生成兼营提示（无内联 JS）',
    """  var _loadTip = _loading
    ? '<span class="rload"><i></i>全库共 <b>' + (meta.total || 0) + '</b> 条，正在载入…（当前已到位 ' + a.length + ' 条）</span>'
    : '';""",
    """  /* 「全部」档下默认还叠着「只看主场业务」这道过滤（602 vs 1521），
     不写明的话用户看到 602 就当成了全库——上一轮「三个省才这么几个项目」
     的质疑就是这么来的。这里把差值、原因和出口一并给出。
     ⚠ 别在字符串里拼 onclick=...el('f-side')...：这段本身就在 JS 单引号字符串里，
       内联引号一转义就 SyntaxError（2026-10-24 踩过），统一走 data-act 委托。 */
  var _sideTip = (F.bk === 'all' && !F.side && window.items && items.length > a.length)
    ? '<a href="javascript:void(0)" class="rside" data-act="sideAll">' +
      '另有 ' + (items.length - a.length) + ' 条兼营业务被隐藏，点这里一起看</a>'
    : '';
  var _loadTip = _loading
    ? '<span class="rload"><i></i>全库共 <b>' + (meta.total || 0) + '</b> 条，正在载入…（当前已到位 ' + a.length + ' 条）</span>'
    : '';""")

rep('1b rbar 拼进 _sideTip',
    "'顶部「已公示金额 '+meta.amtSum.toFixed(0)+' 亿」是全库 '+meta.withAmt+' 条带金额项目的总和，与本页筛选无关'+",
    "'顶部「已公示金额 '+meta.amtSum.toFixed(0)+' 亿」是全库 '+meta.withAmt+' 条带金额项目的总和，与本页筛选无关'+_sideTip+")

rep('1c .rside 样式',
    "@keyframes rspin{to{transform:rotate(360deg)}}",
    """@keyframes rspin{to{transform:rotate(360deg)}}
.rside{font-size:12px;color:var(--el-blue-d);font-weight:600;text-decoration:underline;
  text-underline-offset:3px;cursor:pointer}
.rside:hover{color:var(--el-blue)}""")

rep('2 data-act=sideAll 委托（放 render 后只绑一次）',
    """function toggleFiles(id){""",
    """/* 兼营一键放开：render 每次都重建 rbar 的 innerHTML，监听不能绑在 rbar 上，
   绑 document 上用 closest 找，委托一次管到页面销毁。 */
document.addEventListener('click', function (e) {
  var t = e.target.closest('[data-act="sideAll"]'); if (!t) return;
  F.side = true; F.page = 1;
  var c = el('f-side'); if (c) { var q = c.querySelector('.chip'); if (q) q.classList.add('on'); }
  render();
});

function toggleFiles(id){""")

io.open(P, 'w', encoding='utf-8').write(src)
print('index.html 改动完成：')
print('\n'.join(log))
print('大小 %d -> %d' % (len(orig), len(src)))
