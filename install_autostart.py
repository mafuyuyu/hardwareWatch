# -*- coding: utf-8 -*-
"""Create a logon scheduled task that starts hardwareWatch with highest privileges."""
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
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, os.path.dirname(os.path.abspath(__file__)), 1
    )
    return rc


def main():
    if not is_admin():
        print("需要管理员权限，正在请求 UAC 授权…")
        elevate()
        return 0
    root = os.path.dirname(os.path.abspath(__file__))
    python = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(python):
        python = sys.executable
    run_py = os.path.join(root, "run.pyw")
    action = '"%s" "%s"' % (python, run_py)
    cmd = [
        "schtasks", "/Create", "/TN", TASK_NAME, "/TR", action,
        "/SC", "ONLOGON", "/RL", "HIGHEST", "/F",
    ]
    print("执行:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk", errors="replace")
    print(result.stdout.strip())
    print(result.stderr.strip())
    if result.returncode == 0:
        print("")
        print("已设置开机自启（登录时以管理员权限启动）。")
        print("如需取消，运行 uninstall_autostart.bat。")
    else:
        print("创建计划任务失败，请尝试右键以管理员身份运行。")
    input("按回车键关闭…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
