# -*- coding: utf-8 -*-
"""Remove the hardwareWatch logon task."""
import ctypes
import os
import subprocess
import sys

TASK_NAME = "hardwareWatch Hardware Monitor"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    params = '"%s"' % os.path.abspath(__file__)
    return ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params,
        os.path.dirname(os.path.abspath(__file__)), 1,
    )


def main():
    if not is_admin():
        print("需要管理员权限，正在请求 UAC 授权…")
        elevate()
        return 0
    cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk", errors="replace")
    print(result.stdout.strip())
    print(result.stderr.strip())
    input("按回车键关闭…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
