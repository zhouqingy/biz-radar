# -*- coding: utf-8 -*-
"""原子写 + 安全读（2026-11-13）

为什么需要这个文件：
  2026-11-13 收尾时发现 raw/award_index.json 只有 2,969,384 B，json.load 直接报
  「unexpected end of data」，而远端完整版本是 4,755,508 B / 9,281 条。

  查下来根因很朴素：scan_awards.py / mine_bjx.py 都是

      json.dump(obj, open(OUT, 'w', encoding='utf-8'))

  这个写法第一步就把原文件截断成 0 字节，然后才开始写。CI 有 6 小时上限、
  网络也可能中途断，只要进程在写完之前死掉，磁盘上就永久留下一个半截 JSON——
  而且没有任何一处会报错，下一轮 read 时才炸，或者更糟：被 except 吞掉，悄悄少一批数据。

  所以两件事一起改：
    1) atomic_dump：先写 .tmp，fsync，再 os.replace 原子替换。中途死，原文件毫发无损。
    2) safe_load：读坏了不抛异常给上层瞎吞，直接返回 None 并打醒目的日志，
       让调用方决定「保留旧数据」还是「退出」。
"""
import json
import os
import time


def atomic_dump(obj, path, indent=None, ensure_ascii=False):
    """原子写入：写临时文件 → fsync → os.replace

    比 json.dump(obj, open(path,'w')) 多做三件事：
      - 原文件在整个写入过程中保持完整（不会被截断成 0 字节）
      - fsync 保证数据真的落到磁盘，而不是停在页缓存里
      - 失败时清理临时文件，不留垃圾
    """
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def safe_load(path, default=None, label=''):
    """读 JSON；坏了返回 default，并把原因打清楚（不静默）

    返回 (obj, ok)。ok=False 表示文件存在但读不出来，调用方不要拿 default 当真数据用。
    """
    if not os.path.exists(path):
        return default, True          # 不存在不算坏，是首次运行
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f), True
    except Exception as e:
        size = os.path.getsize(path)
        print('[FATAL] %s 读取失败：%s' % (label or os.path.basename(path), e))
        print('        文件 %s，%d 字节（%s）' % (path, size, _human(size)))
        print('        这个文件被写坏了 —— 上一轮多半是在写一半时被杀。'
              '本轮请勿把它当空数据继续用，保留旧文件并触发修复。')
        return default, False


def _human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return '%.1f %s' % (n, u)
        n /= 1024.0
    return '%.1f TB' % n


def stamp(path):
    """文件最后修改时间（字符串），给日志用"""
    if not os.path.exists(path):
        return '不存在'
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))
