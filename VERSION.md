# 二讲智能服务效能增长Agent

## 版本信息

| 项目 | 详情 |
|------|------|
| **项目名称** | 二讲智能服务效能增长Agent |
| **当前版本** | `release-v1.0.1-final` |
| **版本日期** | 2026-08-12 |
| **版本说明** | Linux/Streamlit Cloud PDF 中文字体兼容修复 |
| **备份位置** | `releases/release-v1.0.1-final_20260812_180216.zip` |
| **LLM 后端** | DeepSeek API (`deepseek-v4-flash`) |
| **运行环境** | Python 3.x + Streamlit |

---

## 包含功能

### Tab1：📊 学情续费预警系统
- 上传学生数据 Excel
- 自动识别列名（语义匹配）
- 9 维度风险评分（续费状态、订金、沟通间隔、成绩趋势等）
- P1-P4 四级分层（颜色标记）
- 分层话术生成（基于 LLM）
- 续费风险分析报告
- 导出分析结果 Excel

### Tab2：💬 家校沟通策略助手
- 家长问题智能分类
- 基于 RAG（ChromaDB）+ SOP 知识库的回复生成
- 支持续费沟通、投诉处理、教学答疑、服务沟通四类场景
- 5 部分结构回复（共情、分析、方案、行动、收尾）

### Tab3：📋 行课数据风险分析 & 批量报告生成
- 上传行课 Excel 数据
- 自动解析讲次列（听课时长、答题正确率、练习提交、练习得分、有效听课）
- 全班出勤率统计
- 有效正课过滤（排除家长会/复习课，出勤率 < 10% 跳过）
- 学员分类筛选（优秀/中等/差）
- 单个学员报告生成
- 批量全部报告生成
- 导出全部 PDF（打包 zip，一步下载）
- 学员沟通优先级分析（P1-P4 分层 + 风险排序表格）
- 导出风险分析结果 Excel

### Tab4：📈 数据看板
- 使用统计（分析次数、答疑次数、报告生成次数）
- 每日使用趋势
- 操作日志记录

---

## 核心模块清单

### 前端代码
| 文件 | 大小 | 说明 |
|------|------|------|
| `app.py` | ~1100 行 | Streamlit 主应用，4 个 Tab 页面 |

### 后端核心代码
| 文件 | 说明 |
|------|------|
| `core/risk_llm_analyzer.py` | AI 风险分析引擎 |
| `core/renewal_risk_engine.py` | 续费风险评分引擎 |
| `core/report_generator_v3.py` | 学情报告批量生成（v3）+ PDF 导出（支持 Windows/Linux 双环境中文） |
| `core/script_generator.py` | 分层话术生成 |
| `core/semantic_column_recognizer.py` | 列名语义识别 |
| `core/lecture_risk_analyzer.py` | 行课风险分析 |
| `core/student_analyzer.py` | 学生画像分析 |
| `core/exam_analyzer.py` | 试卷智能分析 |
| `core/qa_responder.py` + `qa_responder_v2.py` | 家长答疑回复 |
| `core/prompt_utils.py` | 精准性约束加载 |

### 工具模块
| 文件 | 说明 |
|------|------|
| `utils/excel_parser.py` | Excel 解析 & 列名检测 |
| `utils/excel_exporter.py` | 分析结果导出 Excel |
| `utils/logger.py` | 事件日志埋点（JSONL） |

### 配置文件
| 文件 | 说明 |
|------|------|
| `config.py` | 全局配置（路径、阈值、风险维度） |
| `.env` | LLM API 密钥和模型配置 |
| `.env.example` | 环境变量模板 |
| `requirements.txt` | Python 依赖 |
| `packages.txt` | Streamlit Cloud 系统依赖（中文字体） |

### Prompt 模板（13 个）
| 文件 | 用途 |
|------|------|
| `accuracy_constraints.txt` | 精准性约束（5 条规则） |
| `batch_report.txt` / `v2` / `v3` | 学情报告模板 |
| `student_segmentation.txt` / `flexible` | 分层话术 |
| `qa_response.txt` / `v2` / `combined` | 答疑回复 |
| `qa_classification.txt` | 问题分类 |
| `lecture_risk_script.txt` | 行课风险沟通 |
| `renewal_risk_advisory.txt` | 续费预警话术 |
| `exam_analysis_script.txt` | 试卷分析 |

### 知识库
| 文件 | 说明 |
|------|------|
| `data/sop_knowledge/complaint_faq.md` | 投诉处理 FAQ |
| `data/sop_knowledge/renewal_faq.md` | 续费 FAQ |
| `data/sop_knowledge/service_faq.md` | 服务 FAQ |
| `data/sop_knowledge/teaching_faq.md` | 教学 FAQ |

---

## 版本历史

### release-v1.0.1-final（当前版本）
- **新增：** `packages.txt` — Streamlit Cloud 自动安装中文字体（fonts-noto-cjk）
- **修复：** `core/report_generator_v3.py` — `_register_chinese_font()` 增加 Linux 字体路径回退
  - Noto Sans CJK（fonts-noto-cjk）
  - DroidSansFallback（Debian 默认）
  - WenQuanYi Micro Hei（轻量回退）
- **效果：** PDF 导出在 Windows 本地和 Streamlit Cloud Linux 环境均可正常显示中文
- 其余所有功能与 release-v1.0-final 完全一致

### release-v1.0-final（历史基线）
- 完整 4 个 Tab 功能
- 9 维度风险评分引擎
- 行课数据解析 + 有效正课过滤
- 批量 PDF 报告生成（一步下载）
- 精准性约束（5 条规则）自动追加到所有 LLM 调用
- 家校沟通策略助手（RAG + SOP 知识库）
- 飞书/企业微信 Bot 接入
- 操作日志埋点
- 数据看板可视化

---

## 依赖环境

```
streamlit>=1.35.0
pandas>=2.2.0
openai>=1.30.0
langchain>=0.2.0
langchain-openai>=0.1.0
chromadb>=0.5.0
openpyxl>=3.1.0
xlsxwriter>=3.2.0
python-dotenv>=1.0.0
pytest>=8.0.0
plotly>=5.18.0
```

LLM 后端：DeepSeek API（`deepseek-v4-flash`），通过 OpenAI 兼容接口调用。