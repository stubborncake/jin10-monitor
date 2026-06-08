# 金十监听 — Docker 镜像
# 树莓派/ARM 设备构建：docker build -t jin10-monitor .
# x86 交叉编译：docker buildx build --platform linux/arm64 -t jin10-monitor .

FROM python:3.12-slim

WORKDIR /app

# 安装依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝代码
COPY *.py .

# 静默模式运行
CMD ["python", "main.py", "--quiet"]
