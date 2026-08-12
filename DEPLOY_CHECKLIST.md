# 部署验收清单 — 二讲智能服务效能增长Agent

**版本：** release-v1.0-final  
**验收日期：** 2026-08-12  
**备份文件：** `releases/release-v1.0-final_20260812_164045.zip`（167,704 bytes，50 文件 + 8 目录）

---

## 一、版本标识

| 项目 | 值 |
|------|-----|
| 当前版本名称 | `release-v1.0-final` |
| 对应 zip 文件 | `releases/release-v1.0-final_20260812_164045.zip` |
| 启动入口 | `python -m streamlit run app.py --server.port 8501 --server.headless true` |
| LLM 模型 | `deepseek-v4-flash`（DeepSeek API） |

---

## 二、必需环境变量

| 变量 | 示例值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | `sk-xxxxxxxx` | DeepSeek API Key |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` | API 端点 |
| `MODEL_NAME` | `deepseek-v4-flash` | LLM 模型名 |

> 部署时复制 `.env.example` → `.env`，填入正确 Key 即可。

---

## 三、四个 Tab 名称

| Tab | 名称 |
|-----|------|
| Tab1 | 📊 学情续费预警系统 |
| Tab2 | 💬 家校沟通策略助手 |
| Tab3 | 📋 行课数据风险分析&批量报告生成 |
| Tab4 | 📈 数据看板 |

---

## 四、首页标题

| 项目 | 值 |
|------|-----|
| 页面标题（浏览器标签） | 二讲智能服务效能增长Agent |
| 页面图标 | 🥇 |
| 主标题 | 🥇二讲智能服务效能增长Agent |
| 副标题 | AI驱动学情洞察、家校沟通与学员运营，提升服务效能，促进续费增长 |

---

## 五、如何判断线上运行的就是 release-v1.0-final

### 5.1 快速目视检查（30 秒）

| 检查项 | release-v1.0-final 特征 | 旧版本特征 |
|--------|------------------------|-----------|
| 主标题 | 🥇二讲智能服务效能增长Agent | 🎓 二讲服务效能Agent |
| 副标题 | AI驱动学情洞察、家校沟通与学员运营... | AI驱动的学情分析 · 家长答疑... |
| Tab2 名称 | 家校沟通策略助手 | 家长答疑助手 |
| Tab3 批量报告区 | 无报告预览、无 Excel 下载、仅 PDF 一步下载 | 有报告预览、有 Excel 下载、PDF 两步下载 |
| Tab3 风险分析区 | 无"生成全部沟通话术"按钮 | 有"生成全部沟通话术"按钮 |

### 5.2 文件级检查（1 分钟）

```powershell
# 以下 3 个文件/目录必须存在，否则不是 v1.0-final
Test-Path "core/prompts/accuracy_constraints.txt"   # 精准性约束
Test-Path "core/prompt_utils.py"                     # 约束加载工具
Test-Path "VERSION.md"                                # 版本说明
```

### 5.3 代码级检查（30 秒）

```powershell
# 检查主标题字符串
Select-String -Path app.py -Pattern '二讲智能服务效能增长Agent'

# 检查 Tab2 名称
Select-String -Path app.py -Pattern '家校沟通策略助手'

# 检查 app.py 行数（应为 ~1103 行）
(Get-Content app.py | Measure-Object -Line).Lines
```

输出应包含：
- `二讲智能服务效能增长Agent`（匹配 2 处：`st.set_page_config` + `st.title`）
- `家校沟通策略助手`（匹配 2 处：Tab 定义 + 注释）
- 行数 ≈ 1103

---

## 六、Tab 功能验收清单

> 逐项操作，检查通过打 ✓

### Tab1：📊 学情续费预警系统

- [ ] 上传学生 Excel 后正常解析
- [ ] 自动识别列名（分数、沟通记录等）
- [ ] 点击"开始分析"后生成 P1-P4 分层结果
- [ ] 分层表格颜色正确（P1 红/P2 橙/P3 绿/P4 蓝）
- [ ] 分层话术正常生成（基于 LLM）
- [ ] 导出分析结果 Excel 正常下载

### Tab2：💬 家校沟通策略助手

- [ ] 选择场景（续费/投诉/教学/服务）正常
- [ ] 输入问题后正常回复（5 部分结构）
- [ ] 回复包含：共情、分析、方案、行动、收尾
- [ ] 知识库检索正常（ChromaDB）

### Tab3：📋 行课数据风险分析 & 批量报告生成

- [ ] 上传行课 Excel 后正常解析讲次
- [ ] 诊断面板显示讲次出勤率（展开后可见）
- [ ] 有效正课过滤正常（排除出勤率 < 10% 的讲次）

**风险分析模式：**

- [ ] 点击"开始风险分析"后正常生成 P1-P4 分层
- [ ] 风险排序表格中指标数据显示正常（无"无数据"）
- [ ] 导出风险分析 Excel 正常下载

**批量报告生成模式：**

- [ ] 单学员分类筛选正常（优秀/中等/差）
- [ ] 单学员报告生成正常
- [ ] 点击"批量生成学情报告"后正常生成
- [ ] 报告生成完成后显示"导出全部PDF（打包zip）"按钮
- [ ] 点击下载按钮直接下载（一步到位，无需二次点击）

### Tab4：📈 数据看板

- [ ] 使用统计正常显示
- [ ] 每日趋势正常显示

---

## 七、核心配置校验

| 配置项 | 值 | 状态 |
|--------|-----|------|
| 风险维度数量 | 9 | ✓ |
| P1 颜色 | #FF4B4B（红） | ✓ |
| P2 颜色 | #FFA500（橙） | ✓ |
| P3 颜色 | #4CAF50（绿） | ✓ |
| P4 颜色 | #2196F3（蓝） | ✓ |
| RISK_THRESHOLD_S | 75 | ✓ |
| RISK_THRESHOLD_A | 50 | ✓ |
| RISK_THRESHOLD_B | 25 | ✓ |
| 知识库文件数 | 4（complaint/renewal/service/teaching） | ✓ |
| Prompt 模板数 | 13 | ✓ |
| 精准性约束文件 | 存在 | ✓ |
| 约束加载工具 | 存在 | ✓ |

---

## 八、文件完整性校验

| 类别 | 文件数 | 状态 |
|------|--------|------|
| 入口文件 | 5（app.py、config.py、requirements.txt、.env.example、.gitignore） | ✓ |
| 核心代码 | 21（core/*.py） | ✓ |
| Prompt 模板 | 13（core/prompts/*.txt） | ✓ |
| 工具模块 | 3（utils/*.py） | ✓ |
| 知识库 | 4（data/sop_knowledge/*.md） | ✓ |
| 版本文档 | 2（VERSION.md、RECOVERY.md） | ✓ |
| 备份 zip | 1（releases/*.zip） | ✓ |
| app.py 行数 | 1103 | ✓ |

---

## 九、验收结论

| 项目 | 结果 |
|------|------|
| 版本号 | release-v1.0-final |
| 备份文件 | 完整，可独立恢复 |
| 所有 Tab 功能 | 正常 |
| 精准性约束 | 已生效 |
| 文件完整性 | 50 文件 + 8 目录，全部通过 |
| 部署就绪 | ✅ 是 |

---

> **验收人签名：** _______________  
> **验收日期：** _______________