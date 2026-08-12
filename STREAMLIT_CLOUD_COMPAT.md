# Streamlit Community Cloud 部署兼容性报告

**版本：** release-v1.0-final  
**检查日期：** 2026-08-12  
**目标平台：** Streamlit Community Cloud（免费）

---

## 一、兼容性检查总览

| 检查项 | 结果 | 风险等级 |
|--------|------|----------|
| Streamlit 入口 | ✅ 兼容 | 无 |
| requirements.txt | ✅ 兼容 | 无 |
| 环境变量 (Secrets) | ✅ 兼容 | 无 |
| 文件上传 (st.file_uploader) | ✅ 兼容 | 无 |
| 文件下载 (st.download_button) | ✅ 兼容 | 无 |
| Excel 导出 | ✅ 兼容 | 无 |
| ChromaDB 知识库 | ⚠️ 部分兼容 | 中 |
| PDF 中文字体 | ❌ 不兼容 | **高（阻断）** |
| 硬编码 Windows 路径 | ❌ 不兼容 | **高（阻断）** |

---

## 二、详细检查

### 2.1 ✅ Streamlit 入口 — 兼容

`app.py` 第 16 行使用标准 `st.set_page_config()` + `st.title()`，第 20 行使用 `st.tabs()`，符合 Streamlit Cloud 规范。无需修改。

### 2.2 ✅ requirements.txt — 兼容

11 个依赖均为纯 Python 包，Streamlit Cloud 自动 `pip install -r requirements.txt`。无需修改。

### 2.3 ✅ 环境变量 (Secrets) — 兼容

`config.py` 第 3-10 行使用 `os.getenv()` 读取环境变量。Streamlit Cloud 支持在 Dashboard → Settings → Secrets 中配置：

```toml
OPENAI_API_KEY = "sk-xxxxxxxx"
OPENAI_BASE_URL = "https://api.deepseek.com/v1"
MODEL_NAME = "deepseek-v4-flash"
```

`load_dotenv()` 在 `.env` 文件不存在时会静默跳过，`os.getenv()` 从系统环境变量获取 Secrets 配置的值。无需修改。

### 2.4 ✅ 文件上传 — 兼容

`st.file_uploader()` 返回 `BytesIO` 对象，`parse_uploaded_excel()` 直接读取内存中的字节流，不依赖本地文件系统。无需修改。

### 2.5 ✅ 文件下载 — 兼容

`st.download_button()` 的 `data` 参数接受文件对象，Streamlit Cloud 会将其作为临时文件提供给浏览器下载。虽然当前代码先写入 `OUTPUT_DIR` 再读取，但 Streamlit Cloud 的临时文件系统在会话期间可用。无需修改。

### 2.6 ⚠️ ChromaDB 知识库 — 部分兼容

**当前行为：**
- `rag_engine.py` 第 15 行：`chromadb.PersistentClient(path=CHROMA_DIR)`，数据写入 `data/chroma_db/`
- 第 19 行：`if collection.count() == 0` 自动从 `data/sop_knowledge/` 重新导入

**Streamlit Cloud 行为：**
- 文件系统是临时的（ephemeral），每次重启/重新部署后 `data/chroma_db/` 被清空
- `.gitignore` 已排除 `data/chroma_db/`，所以不会随代码部署

**影响：** 每次应用重启后，ChromaDB 需要重新构建（从 SOP markdown 文件导入）。构建过程很快（4 个 markdown 文件，约 30 条文档），不影响功能。

**结论：** 功能可用，但每次重启后首次调用 Tab2 会有 1-2 秒初始化延迟。

### 2.7 ❌ PDF 中文字体 — 阻断性不兼容

**问题位置：** `core/report_generator_v3.py` 第 24-42 行

```python
font_paths = [
    (r"C:\Windows\Fonts\msyh.ttc", "MSYH"),       # ← 仅 Windows 存在
    (r"C:\Windows\Fonts\msyhbd.ttc", "MSYHBD"),    # ← 仅 Windows 存在
    (r"C:\Windows\Fonts\simsun.ttc", "SimSun"),     # ← 仅 Windows 存在
    (r"C:\Windows\Fonts\simhei.ttf", "SimHei"),     # ← 仅 Windows 存在
]
```

**问题：** Streamlit Cloud 运行在 Linux 上，这些 Windows 字体路径全部不存在。`_register_chinese_font()` 会静默失败（try/except），但后续 PDF 生成时 `ParagraphStyle` 引用 `fontName='MSYH'` 等字体名，会导致 PDF 中中文全部显示为方块（tofu）。

**影响范围：** Tab3 批量报告生成的 PDF 下载功能完全不可用。

### 2.8 ❌ 其他硬编码路径 — 已通过

`config.py` 第 15 行使用 `os.path.dirname(__file__)` 相对定位，`OUTPUT_DIR`、`CHROMA_DIR`、`LOG_DIR` 均基于 `BASE_DIR` 计算，不存在硬编码绝对路径。✅

---

## 三、风险汇总

| # | 风险 | 严重程度 | 影响功能 |
|---|------|----------|----------|
| 1 | PDF 中文字体硬编码 Windows 路径 | **阻断** | Tab3 PDF 下载全部不可用 |
| 2 | ChromaDB 每次重启需重建 | 低 | Tab2 首次调用延迟 1-2 秒 |
| 3 | `data/output/` 文件累积 | 低 | 长期运行可能占用磁盘 |

---

## 四、解决方案

### 方案 1：修复 PDF 字体（推荐，改动最小）

**修改 `core/report_generator_v3.py` 第 24-42 行**，增加 Linux 字体回退：

```python
def _register_chinese_font():
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    font_paths = [
        # Windows
        (r"C:\Windows\Fonts\msyh.ttc", "MSYH"),
        (r"C:\Windows\Fonts\msyhbd.ttc", "MSYHBD"),
        (r"C:\Windows\Fonts\simsun.ttc", "SimSun"),
        (r"C:\Windows\Fonts\simhei.ttf", "SimHei"),
        # Linux (Streamlit Cloud / Docker)
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "MSYH"),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", "MSYHBD"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "MSYH"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "MSYHBD"),
        # 通用回退：DroidSansFallbackFull（Debian/Ubuntu 默认中文字体）
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", "MSYH"),
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", "MSYHBD"),
    ]
    for path, name in font_paths:
        try:
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
        except:
            pass
    _FONT_REGISTERED = True
```

同时在 `packages.txt` 中添加中文字体依赖：

```
fonts-noto-cjk
```

### 方案 2：切换到 Hugging Face Spaces + Docker（推荐，功能最完整）

使用 Docker 部署，可以在 Dockerfile 中安装中文字体并预构建 ChromaDB，完全避免上述问题。详见 `DEPLOY_GUIDE.md`。

---

## 五、结论

| 结论 | 说明 |
|------|------|
| **Streamlit Cloud 可行吗？** | 可以，但需要修复 PDF 字体问题（1 处改动） |
| **修复后能否稳定运行？** | 可以，文件上传、Excel 导出、ChromaDB 均兼容 |
| **比赛演示可用吗？** | 修复 PDF 字体后即可 |
| **推荐方案** | Hugging Face Spaces + Docker（零改动，功能最完整） |

---

## 六、推荐部署方案对比

| 维度 | Streamlit Cloud | Hugging Face Spaces |
|------|----------------|---------------------|
| 费用 | 免费 | 免费 |
| 资源 | 1GB RAM | 16GB RAM |
| 需改代码 | 1 处（PDF 字体） | 0 处 |
| ChromaDB | 每次重启重建 | Docker 镜像预构建 |
| PDF 中文 | 需安装中文字体 | Dockerfile 安装 |
| 休眠 | 无明确休眠 | 48小时（可 ping 保持） |
| 部署难度 | 低（GitHub push） | 中（Dockerfile） |

**最终建议：** 如果时间紧迫，修复 PDF 字体后使用 Streamlit Cloud。如果追求稳定性和功能完整性，使用 Hugging Face Spaces + Docker。