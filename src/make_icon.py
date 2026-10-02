# -*- coding: utf-8 -*-
"""
生成应用图标 app.ico（多尺寸）
================================================================================
设计：**脉冲书** —— 书形轮廓 + 心电图式折线，对应「书脉 BookPulse」。

用法：
    <项目>/.venv/Scripts/python.exe make_icon.py

输出：
    app.ico   含 16 / 24 / 32 / 48 / 64 / 128 / 256 七种尺寸

要点：
  · 纯代码绘制，零外部素材，换设计只改本文件
  · 小尺寸（≤32px）自动**加粗笔画并简化折线** —— 否则 16px 下会糊成一团
  · ICO 用 PNG 内嵌格式（Vista+ 支持），比传统 BMP 体积小且支持透明
"""
import os
import sys
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PySide6.QtCore import Qt, QBuffer, QIODevice
from PySide6.QtGui import (
    QGuiApplication, QImage, QPainter, QColor, QPen, QLinearGradient, QPainterPath,
)

SIZES = [16, 24, 32, 48, 64, 128, 256]
OUT = os.path.join(HERE, 'app.ico')

C1 = '#6366F1'      # 主色（蓝紫）
C2 = '#8B5CF6'      # 渐变末端（紫）


def draw_logo(p, size):
    """在 size×size 画布上绘制「脉冲书」。内部用 100×100 设计坐标。"""
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 100.0, size / 100.0)

    # ---- 圆角方底 + 渐变 ----
    g = QLinearGradient(0, 0, 100, 100)
    g.setColorAt(0.0, QColor(C1))
    g.setColorAt(1.0, QColor(C2))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, 100, 100, 30, 30)

    small = size <= 32

    # ---- 书形轮廓（开口向上的槽）----
    pen = QPen(QColor('#FFFFFF'), 9.0 if small else 6.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    book = QPainterPath()
    if small:
        book.moveTo(29, 35)
        book.lineTo(29, 69)
        book.lineTo(71, 69)
        book.lineTo(71, 35)
    else:
        book.moveTo(28, 33)
        book.lineTo(28, 70)
        book.lineTo(72, 70)
        book.lineTo(72, 33)
    p.drawPath(book)

    # ---- 脉冲线（小尺寸少一次转折，避免糊掉）----
    pen2 = QPen(QColor('#FFFFFF'), 8.5 if small else 5.0)
    pen2.setCapStyle(Qt.RoundCap)
    pen2.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen2)
    pulse = QPainterPath()
    if small:
        pulse.moveTo(34, 52)
        pulse.lineTo(44, 52)
        pulse.lineTo(52, 39)
        pulse.lineTo(60, 63)
        pulse.lineTo(66, 52)
    else:
        pulse.moveTo(33, 52)
        pulse.lineTo(43, 52)
        pulse.lineTo(48, 40)
        pulse.lineTo(55, 64)
        pulse.lineTo(60, 52)
        pulse.lineTo(67, 52)
    p.drawPath(pulse)


def png_bytes(size):
    """渲染成 PNG 字节。"""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_logo(p, size)
    p.end()

    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, 'PNG')
    data = bytes(buf.data())
    buf.close()
    return data


def build_ico(sizes, out_path):
    """把若干尺寸的 PNG 组装成一个 .ico 文件。"""
    blobs = [(s, png_bytes(s)) for s in sizes]
    n = len(blobs)
    header = struct.pack('<HHH', 0, 1, n)          # reserved, type=icon, count
    offset = 6 + 16 * n
    entries, payload = b'', b''
    for s, blob in blobs:
        w = 0 if s >= 256 else s                    # 256 在 ICO 里记为 0
        h = 0 if s >= 256 else s
        entries += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        payload += blob
    with open(out_path, 'wb') as f:
        f.write(header + entries + payload)
    return out_path


def main():
    app = QGuiApplication(sys.argv)          # QImage/QPainter 需要 GUI 应用实例
    build_ico(SIZES, OUT)
    print('已生成：%s' % OUT)
    print('  尺寸：%s' % ' / '.join('%dpx' % s for s in SIZES))
    print('  大小：%.1f KB' % (os.path.getsize(OUT) / 1024.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
