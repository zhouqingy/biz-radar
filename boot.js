/* ==================== 启动器 ====================
   加载顺序（三个都在 body 末尾，按序执行）：
     1. index.html 内联的主脚本  —— 定义 packItems / render / 各面板渲染函数，
                                   同时算出 D / items / meta
     2. data.core.js + data.items.js（defer）—— 把 DATA_CORE / DATA_ITEMS 挂到 window
     3. 本文件（defer）—— 数据到位后才真正渲染

   为什么主脚本必须排在数据脚本前面：main 脚本执行时就要读 window.DATA_CORE
   来算 D 和 items，如果它排在数据后面，只能拿到 undefined。
   也不能用「数据在前、主脚本包成 function 等 DOMContentLoaded 再调」的写法——
   那样里面的 function 全是函数作用域，外部（含错误兜底）都看不见。
   所以：主脚本在前定义一切 → 数据在后挂载 → 本文件最后点火。 */

(function () {
  var T0 = Date.now();

  function fail(msg) {
    var g = document.getElementById('grid');
    if (g) g.innerHTML = '<div class="empty">' + msg + '</div>';
  }

  /* 把数据挂载后的全局状态同步给主脚本用到的变量。
     主脚本里 var D / items / meta 是在数据挂载之前算的（那时是空），
     这里重新赋值——它们都在同一个全局作用域，直接覆盖即可。 */
  function sync() {
    if (window.DATA_CORE) D = window.DATA_CORE;
    else if (window.DATA) D = window.DATA;
    meta = D.meta || {};

    if (window.DATA_ITEMS) items = packItems(window.DATA_ITEMS);
    else if (window.DATA) items = packItems(window.DATA);
    else items = [];
  }

  function start() {
    if (!window.DATA_CORE && !window.DATA) {
      fail('数据文件未能加载，请强制刷新（Ctrl+F5）再试');
      return;
    }
    if (!window.DATA_ITEMS && !window.DATA) {
      fail('商机明细（data.items.js）未能加载，请强制刷新（Ctrl+F5）再试');
      return;
    }
    try {
      sync();
      boot_main();
      /* 首屏耗时打到控制台，方便以后判断是卡在网络上还是卡在渲染上 */
      try {
        console.log('[boot] 首屏完成 ' + (Date.now() - T0) + 'ms · ' +
          items.length + ' 条明细 · ' + document.querySelectorAll('#grid .pj').length + ' 张卡片');
      } catch (e) { }
    } catch (e) {
      console.error('[boot] 渲染失败', e);
      fail('页面渲染出错：' + e.message + '（请强制刷新 Ctrl+F5）');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
