FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建必要目录
RUN mkdir -p data/output data/logs data/chroma_db

# 预构建 ChromaDB 知识库（在 Docker 构建阶段完成，镜像自带数据）
RUN python -c "
import os, sys
sys.path.insert(0, '/app')
from core.rag_engine import init_chroma
init_chroma()
print('ChromaDB 知识库预构建完成')
"

# HF Spaces 固定端口
ENV STREAMLIT_SERVER_PORT=7860
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

EXPOSE 7860

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]