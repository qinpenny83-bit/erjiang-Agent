# 公网部署方案 — 二讲智能服务效能增长Agent

**版本：** release-v1.0-final  
**日期：** 2026-08-12  

---

## 一、部署架构设计

### 推荐方案：Hugging Face Spaces（Docker SDK）

| 评估维度 | 详情 |
|----------|------|
| **费用** | 完全免费（CPU Basic） |
| **资源** | 2 vCPU / 16GB RAM / 50GB 临时盘 |
| **公网链接** | `https://huggingface.co/spaces/你的用户名/erjiang-agent` |
| **HTTPS** | 默认支持 |
| **休眠** | 48 小时无活动后暂停（可通过定时 ping 保持活跃） |
| **ChromaDB** | 通过 Docker SDK 完全控制环境，无 sqlite3 版本问题 |

**选型原因：**

1. 免费资源最充裕（16GB RAM），足以支撑 ChromaDB + Streamlit 同时运行
2. Docker SDK 完全控制 Python 环境，无 sqlite3 版本兼容问题
3. 预构建 ChromaDB 数据可打包进 Docker 镜像，零成本解决持久化
4. 固定 URL，支持 HTTPS，比赛展示友好
5. 社区已有多个 Streamlit + ChromaDB 成功案例

**为何不选其他平台：**
- Streamlit Community Cloud：文件系统完全临时，ChromaDB 数据每次部署丢失，社区大量反馈此问题
- Render：15 分钟休眠，冷启动 ~1 分钟体验差；512MB RAM 偏紧
- Railway：2026 年已无真正免费方案（仅 30 天试用）

---

## 二、部署前检查结果

### ✅ 已通过

| 检查项 | 结果 | 说明 |
|--------|------|------|
| app.py 是否为正确入口 | ✅ | 行 16-18 设 `st.set_page_config` + `st.title`，标准 Streamlit 入口 |
| requirements.txt 是否完整 | ✅ | 11 个依赖，覆盖 streamlit / pandas / openai / chromadb / openpyxl / plotly |
| 环境变量配置 | ✅ | 仅需 3 个：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL_NAME`，均在 .env 中 |
| 本地路径依赖 | ✅ | `config.py` 第 15 行用 `os.path.dirname(__file__)` 相对定位，无硬编码绝对路径 |
| ChromaDB 云端运行 | ✅ | `rag_engine.py` 第 15 行用 `PersistentClient(path=CHROMA_DIR)`，Docker 镜像内可正常工作 |

### ⚠️ 风险与解决方案

| 风险 | 影响 | 解决方案 |
|------|------|----------|
| ChromaDB 数据在重启后丢失 | Tab2 知识库检索首次需重建 | Docker 构建时将 SOP 知识库预导入 ChromaDB，镜像自带数据 |
| `data/output/` 写入文件 | 生成的报告文件重启后丢失 | 所有下载功能已使用 `st.download_button` 的 `data` 参数（内存 bytes），不依赖文件持久化。但 `report_generator_v3.py` 中 `generate_pdf_report` 会先写本地文件再读取，需改为内存方案 |
| 默认端口 8501 | HF Spaces 固定端口 7860 | 在 Dockerfile 中指定 `--server.port 7860` |

---

## 三、部署文件准备

### 3.1 新增文件：`Dockerfile`

```dockerfile
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

# 预构建 ChromaDB 知识库（在 Docker 构建阶段完成）
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
```

### 3.2 新增文件：`.dockerignore`

```
__pycache__/
*.pyc
.env
.git/
data/logs/
data/output/
data/chroma_db/
.pytest_cache/
releases/
docs/
tests/
test_*.py
check_*.py
```

### 3.3 新增文件：`packages.txt`（HF Spaces 系统依赖）

```
build-essential
```

---

## 四、第一次部署完整步骤

### 步骤 1：准备 GitHub 仓库

```bash
# 在项目根目录执行
git init
git add .
git commit -m "release-v1.0-final: 二讲智能服务效能增长Agent"
git remote add origin https://github.com/你的用户名/erjiang-agent.git
git push -u origin main
```

### 步骤 2：创建 Hugging Face Space

1. 打开 https://huggingface.co/new-space
2. 填写：
   - **Space Name**: `erjiang-agent`（或自定义）
   - **License**: MIT
   - **SDK**: Docker
   - **Docker Template**: Blank
   - **Hardware**: CPU Basic（免费）
3. 点击 "Create Space"

### 步骤 3：配置 Secrets

在 Space Settings → Repository Secrets 中添加：

| Name | Value |
|------|-------|
| `OPENAI_API_KEY` | `sk-xxxxxxxx`（你的 DeepSeek Key） |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` |
| `MODEL_NAME` | `deepseek-v4-flash` |

### 步骤 4：推送代码 & 自动构建

```bash
# 添加 HF 远程仓库
git remote add hf https://huggingface.co/spaces/你的用户名/erjiang-agent

# 推送（触发自动构建和部署）
git push hf main
```

### 步骤 5：验证部署

1. 等待构建完成（约 5-10 分钟，首次需安装依赖）
2. 打开 `https://huggingface.co/spaces/你的用户名/erjiang-agent`
3. 确认页面显示：`🥇二讲智能服务效能增长Agent`
4. 依次测试 4 个 Tab 功能

### 步骤 6：保持 24x7 在线（可选）

注册 https://cron-job.org（免费），创建定时任务：
- URL: `https://huggingface.co/spaces/你的用户名/erjiang-agent`
- 频率: 每 30 分钟
- 作用: 防止 48 小时休眠

---

## 五、版本关联

### 线上版本标识

线上部署后，通过以下方式确认运行的是 release-v1.0-final：

```
1. 打开公网链接，查看页面标题是否为 "🥇二讲智能服务效能增长Agent"
2. Tab2 名称是否为 "家校沟通策略助手"
3. 在浏览器控制台执行：检查页面源码中是否包含 "accuracy_constraints"
```

### 禁止行为

- ❌ 不要在 GitHub 仓库中保留多个版本的 app.py（如 app_v2.py、app_old.py）
- ❌ 不要使用 `pip install` 安装非固定版本的依赖
- ❌ 不要修改 `.dockerignore` 排除 `core/prompts/accuracy_constraints.txt`

---

## 六、后续更新机制

### 更新流程

```
release-v1.0-final（线上稳定版）
        │
        │ 本地开发新功能（不推送）
        │
        ▼
release-v1.1-dev（本地测试）
        │
        │ 测试通过
        │
        ▼
release-v1.1-final（打包备份 + 推送）
        │
        │ git push hf main
        │
        ▼
Hugging Face Spaces 自动重建
        │
        │ 公网链接不变
        │
        ▼
用户访问同一链接看到新版本
```

### 每次更新操作

```bash
# 1. 本地开发并测试通过
# 2. 创建备份
& 7z a releases/release-v1.1-final_YYYYMMDD_HHmmss.zip app.py config.py core/ utils/ data/sop_knowledge/ requirements.txt Dockerfile .dockerignore

# 3. 提交并推送
git add .
git commit -m "release-v1.1-final: 更新说明"
git push hf main

# 4. 等待 HF Spaces 自动构建完成（约 5-10 分钟）

# 5. 如果出问题，回退到 v1.0-final
git reset --hard <v1.0-final的commit哈希>
git push hf main --force
```

---

## 七、出现版本错误如何恢复

### 方案 A：通过 GitHub 回退

```bash
git log --oneline  # 找到 v1.0-final 的 commit hash
git reset --hard <commit_hash>
git push hf main --force
```

### 方案 B：通过 restore.bat 恢复本地 + 重新推送

```bash
# 双击运行 restore.bat（恢复本地文件到 release-v1.0-final）
# 然后重新推送
git add .
git commit -m "回退到 release-v1.0-final"
git push hf main --force
```

### 方案 C：从备份 zip 恢复（最可靠）

```bash
# 1. 解压 releases/release-v1.0-final_20260812_164045.zip
# 2. 覆盖所有项目文件
# 3. 重新推送
git push hf main --force
```

---

## 八、如何确认线上就是最终版本

| 检查项 | 方法 | 预期结果 |
|--------|------|----------|
| 首页标题 | 打开公网链接 | `🥇二讲智能服务效能增长Agent` |
| 副标题 | 查看标题下方 | `AI驱动学情洞察、家校沟通与学员运营...` |
| Tab2 名称 | 查看 Tab 栏 | `💬 家校沟通策略助手` |
| v1.0 特征文件 | 查看 HF Space Logs | 构建日志中显示 "ChromaDB 知识库预构建完成" |
| 精准性约束 | 功能验证 | Tab3 风险分析结果稳定，不出现全部 P1 的异常 |

---

## 九、部署架构图

```
┌─────────────────────────────────────────────┐
│           Hugging Face Spaces                │
│          (免费 CPU Basic)                     │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │         Docker Container              │   │
│  │                                       │   │
│  │  ┌─────────┐  ┌──────────────────┐   │   │
│  │  │Streamlit │  │    ChromaDB      │   │   │
│  │  │  :7860  │  │  (预构建数据)     │   │   │
│  │  └────┬────┘  └────────┬─────────┘   │   │
│  │       │                │              │   │
│  │       ▼                ▼              │   │
│  │  ┌──────────────────────────────┐    │   │
│  │  │    core/prompts/ (13模板)     │    │   │
│  │  │    data/sop_knowledge/ (4 FAQ)│    │   │
│  │  └──────────────────────────────┘    │   │
│  │                                       │   │
│  └───────────────────────────────────────┘   │
│                    │                          │
└────────────────────┼──────────────────────────┘
                     │
                     ▼
         ┌─────────────────────┐
         │   DeepSeek API      │
         │  (deepseek-v4-flash) │
         └─────────────────────┘
                     │
                     ▼
         ┌─────────────────────┐
         │   用户浏览器         │
         │  公网固定链接        │
         └─────────────────────┘
```

---

## 十、快速参考卡片

| 你想做什么 | 命令/操作 |
|-----------|----------|
| 首次部署 | 创建 HF Space → 推送代码 → 等待构建 |
| 查看线上版本 | 打开 `https://huggingface.co/spaces/你的用户名/erjiang-agent` |
| 更新功能 | 本地改代码 → `git push hf main` → 自动重建 |
| 回退到 v1.0-final | `git reset --hard <v1.0-commit> && git push hf main --force` |
| 本地恢复 | 双击 `restore.bat` |
| 紧急修复 | 编辑 HF Space → Settings → Factory Rebuild |

---

**公网链接（部署后）：**
```
https://huggingface.co/spaces/你的用户名/erjiang-agent
```