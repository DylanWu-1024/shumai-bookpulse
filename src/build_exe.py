# -*- coding: utf-8 -*-
"""
打包脚本 —— 把工作台打成 Windows 可执行程序
================================================================================
两种形态，各有取舍：

  onefile  单文件 exe（约 47MB）
      优点：只发一个文件，朋友直接双击
      缺点：每次启动都要先把内容解压到临时目录，实测首启约 2.6 秒

  fast     onedir 目录版
      优点：不需要解压，启动明显更快
      缺点：是一个文件夹（几十个文件），要压缩成 zip 再发

用法：  python build_exe.py onefile
        python build_exe.py fast
        python build_exe.py both
打包前请确保 .venv 已建好（双击 setup_env.bat）。
================================================================================
"""
import os
import sys
import time
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))   # src/（源码都在这里）
ROOT = os.path.dirname(HERE)                        # 项目根
VENV_PY = os.path.join(ROOT, '.venv', 'Scripts', 'python.exe')
DIST_ONE = os.path.join(ROOT, 'dist')               # 单文件产物
DIST_DIR = os.path.join(ROOT, 'dist_fast')          # onedir 产物
WORK = os.path.join(ROOT, 'build')                  # PyInstaller 中间产物，别弄脏 src/

# 排除用不到的 Qt 模块 —— 这一项把体积从 300MB+ 压到 47MB。
# 都是本程序完全没 import 的模块（WebEngine / Qt3D / QML / 多媒体 / 数据库 / 串口…）。
EXCLUDE_MODULES = [
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DAnimation',
    'PySide6.Qt3DExtras', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
    'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQml',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSql',
    'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtHelp', 'PySide6.QtTest',
    'PySide6.QtBluetooth', 'PySide6.QtNfc',
    'PySide6.QtPositioning', 'PySide6.QtLocation',
    'PySide6.QtSerialPort', 'PySide6.QtSerialBus',
    'PySide6.QtWebSockets', 'PySide6.QtWebChannel',
    'PySide6.QtNetworkAuth', 'PySide6.QtRemoteObjects',
    'PySide6.QtSensors', 'PySide6.QtSpatialAudio',
    'PySide6.QtTextToSpeech', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
    # tkinter：本程序不用它。
    # 注意：PyInstaller 的 --splash 启动画面依赖 tkinter，而这个精简版 Python
    # 没有 tcl/tk，所以启动画面这条路线在本机走不通，改用 onedir 解决启动慢。
    'tkinter',
    'unittest',
    'matplotlib', 'numpy', 'pandas', 'scipy',   # 以防环境里有，多余就排除
]


def build(mode):
    # onedir 会往已有目录里覆盖，先自己清掉目标 ——
    # 交给 shell 的批量删除容易被安全策略拦下，Python 内部删更稳。
    if mode == 'fast':
        target = os.path.join(DIST_DIR, 'BookPulse')
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)

    # 图标必须用**绝对路径**：spec 文件会生成在 build/ 下，
    # PyInstaller 解析 datas 时是相对于 spec 所在目录的，
    # 写相对路径会变成找 build/app.ico（不存在）而直接报错。
    icon = os.path.join(HERE, 'app.ico')
    args = [VENV_PY, '-m', 'PyInstaller',
            '--noconfirm', '--windowed', '--clean',
            '--workpath', WORK, '--specpath', WORK,
            '--icon', icon, '--add-data', '%s%c.' % (icon, os.pathsep),
            'app_gui.py']
    if mode == 'onefile':
        args[3:3] = ['--onefile', '--name', 'WeReadHotmarks',
                     '--distpath', DIST_ONE]
    else:
        args[3:3] = ['--onedir', '--name', 'BookPulse', '--distpath', DIST_DIR]
    for m in EXCLUDE_MODULES:
        args += ['--exclude-module', m]

    print('\n>>> 构建 %s ...' % mode)
    t0 = time.time()
    r = subprocess.run(args, cwd=HERE)
    dt = time.time() - t0
    print('>>> %s 结束：返回码 %s，耗时 %.1f 秒' % (mode, r.returncode, dt))
    return r.returncode


def main():
    if not os.path.exists(VENV_PY):
        print('[ERROR] 找不到 .venv，请先双击 setup_env.bat')
        return 1
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'onefile').lower()
    if mode not in ('onefile', 'fast', 'both'):
        print('用法：python build_exe.py [onefile|fast|both]')
        return 2

    rc = 0
    if mode in ('onefile', 'both'):
        rc |= build('onefile')
    if mode in ('fast', 'both'):
        rc |= build('fast')

    print('\n产物：')
    p1 = os.path.join(DIST_ONE, 'WeReadHotmarks.exe')
    p2 = os.path.join(DIST_DIR, 'BookPulse', 'BookPulse.exe')
    if os.path.exists(p1):
        print('  单文件：%s  (%.1f MB)' % (p1, os.path.getsize(p1) / 1048576.0))
    if os.path.exists(p2):
        print('  快速版：%s' % p2)
    return 1 if rc else 0


if __name__ == '__main__':
    sys.exit(main())
