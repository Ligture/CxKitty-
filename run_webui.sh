#!/bin/bash
# CxKitty Web UI 启动脚本

echo "================================"
echo "  CxKitty Web UI"
echo "  超星学习通答题姬 - 网页版"
echo "================================"
echo ""

# 检查Python版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python版本: $python_version"

# 检查依赖
echo "检查依赖..."
if ! python3 -c "import flask" 2>/dev/null; then
    echo "错误: Flask未安装"
    echo "请运行: pip install flask flask-socketio pillow"
    exit 1
fi

if ! python3 -c "import flask_socketio" 2>/dev/null; then
    echo "错误: Flask-SocketIO未安装"
    echo "请运行: pip install flask flask-socketio pillow"
    exit 1
fi

echo "依赖检查通过!"
echo ""
echo "启动 Web UI..."
echo "访问地址: http://127.0.0.1:5000"
echo ""

python3 webui.py
