# 应用镜像：包含 FastAPI 后端、静态前端和 Playwright 降级引擎。
FROM python:3.13-slim

WORKDIR /app

# 先复制依赖清单，充分利用 Docker 层缓存。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Chromium；CloakBrowser 远程 CDP 可用时这里仅作为降级引擎。
RUN playwright install --with-deps chromium

COPY . .

# 提前创建运行时目录，避免容器以只读项目目录启动时失败。
RUN mkdir -p data logs browser_profiles

# 容器内 API 与前端统一暴露 8000；宿主机端口由 compose 映射。
EXPOSE 8000

# 容器内必须监听 0.0.0.0，宿主机访问才可通过端口映射进入。
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
