# -*- coding: utf-8 -*-
"""Launch HwWatch elevated (UAC) without shell quoting games."""
import ctypes
import os
import sys

root = os.path.dirname(os.path.abspath(__file__))
python = sys.executable
pythonw = python.replace("python.exe", "pythonw.exe")
if not os.path.exists(pythonw):
    pythonw = python
run_py = os.path.join(root, "run.pyw")
params = '"%s"' % run_py
rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", pythonw, params, root, 1)
print("ShellExecuteW ->", rc)
