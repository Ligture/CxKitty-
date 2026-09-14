#!/usr/bin/env python3
"""CxKitty 统一启动器"""

import os
import subprocess
import sys


def main():
    print("=" * 50)
    print("  CxKitty - 超星学习通答题姬")
    print("=" * 50)
    print("  1. WebUI 开发模式 (前后端热重载)")
    print("  2. WebUI 生产模式 (构建并启动)")
    print("  3. TUI  终端模式 (命令行交互)")
    print("=" * 50)

    choice = input("请选择 [1/2/3]: ").strip()

    if choice == "1":
        print("\n[INFO] 启动开发环境...")
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/k", "poetry run python -m server.main"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            subprocess.Popen(
                ["cmd", "/k", "cd web && npm run dev"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            subprocess.Popen(["poetry", "run", "python", "-m", "server.main"])
            subprocess.Popen(["npm", "run", "dev"], cwd="web")
        print("[OK] 前后端已在独立窗口中启动")

    elif choice == "2":
        print("\n[INFO] 构建前端...")
        subprocess.run(["npm", "run", "build"], cwd="web", check=True)
        print("[INFO] 启动服务端...")
        subprocess.run(["poetry", "run", "python", "-m", "server.main"])

    elif choice == "3":
        print("\n[INFO] 启动 TUI 终端模式...")
        subprocess.run(["poetry", "run", "python", "main.py"])

    else:
        print("无效选项")


if __name__ == "__main__":
    main()
