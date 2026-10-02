# -*- coding: utf-8 -*-
"""
生成打包用的启动画面（splash.png）
================================================================================
为什么需要它：单文件 exe 每次启动都要先把 150MB 内容解压到临时目录，
这段空窗期用户盯着的是一个「双击了没反应」的桌面 —— 体验很差。

PyInstaller 的 splash 由 bootloader（C 层）直接显示，**不需要等 Python 解压完成**，
是目前唯一能在解压阶段就给出反馈的方案。它依赖 Tk，所以打包时不能排除 tkinter。

纯代码绘制，零图片依赖，和 app.ico / LogoMark 同一套视觉。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def main():
    from PySide6.QtGui import QGuiApplication, QColor, QImage, QLinearGradient, QPainter, QFont
    from PySide6.QtCore import Qt
    import make_icon

    app = QGuiApplication(sys.argv)   # noqa: F841  QPainter 需要有 GUI 应用实例

    W, H = 560, 320
    img = QImage(W, H, QImage.Format_ARGB32)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0.0, QColor('#4F46E5'))
    g.setColorAt(0.55, QColor('#7C3AED'))
    g.setColorAt(1.0, QColor('#DB2777'))
    p.fillRect(0, 0, W, H, g)

    # 品牌标记（与侧栏同一个自绘 Logo）
    p.save()
    p.translate(int(W / 2 - 46), 70)
    make_icon.draw_logo(p, 92)
    p.restore()

    p.setPen(QColor(255, 255, 255))
    f = QFont('Microsoft YaHei UI')
    f.setPixelSize(36)
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 184, W, 48, Qt.AlignHCenter, '书脉')

    f2 = QFont('Microsoft YaHei UI')
    f2.setPixelSize(15)
    p.setFont(f2)
    p.setPen(QColor(255, 255, 255, 235))
    p.drawText(0, 234, W, 24, Qt.AlignHCenter, 'BookPulse · 热门划线工作台')

    f3 = QFont('Microsoft YaHei UI')
    f3.setPixelSize(13)
    p.setFont(f3)
    p.setPen(QColor(255, 255, 255, 185))
    p.drawText(0, 274, W, 22, Qt.AlignHCenter, '正在启动，请稍候…')

    # 底部一条细进度感装饰
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 60))
    p.drawRoundedRect(int(W / 2 - 90), 302, 180, 4, 2, 2)
    p.setBrush(QColor(255, 255, 255, 230))
    p.drawRoundedRect(int(W / 2 - 90), 302, 74, 4, 2, 2)

    p.end()
    img.save(os.path.join(HERE, 'splash.png'))
    print('已生成 splash.png  %dx%d' % (W, H))


if __name__ == '__main__':
    main()
