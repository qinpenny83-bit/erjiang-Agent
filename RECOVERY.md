# 恢复方案 — 二讲智能服务效能增长Agent

## 稳定版本备份

| 版本 | 备份文件 | 日期 |
|------|---------|------|
| **当前版本** | `release-v1.0.1-final` | `releases/release-v1.0.1-final_20260812_180216.zip` | 2026-08-12 |
| 历史基线 | `release-v1.0-final` | `releases/release-v1.0-final_20260812_173833.zip` | 2026-08-12 |

## 版本差异

| 项目 | v1.0-final | v1.0.1-final |
|------|-----------|-------------|
| PDF 中文字体 | 仅 Windows（msyh.ttc） | Windows + Linux 双环境兼容 |
| packages.txt | 无 | 新增（fonts-noto-cjk） |
| 其他功能 | — | 完全一致 |

---

## 情况 1：部署后回到旧版本

**症状：** 部署/更新后 Streamlit 页面显示的是旧版本功能。

**恢复步骤：**

1. 停止当前运行的应用
   ```
   taskkill /F /IM python.exe
   ```

2. 选择要恢复的版本：
   - 恢复最新版（含 PDF 修复）：`releases/release-v1.0.1-final_20260812_180216.zip`
   - 恢复基线版：`releases/release-v1.0-final_20260812_173833.zip`

3. 解压覆盖核心文件
   ```
   & 7z x releases/release-v1.0.1-final_20260812_180216.zip -o. -y
   ```

4. 清除 Python 字节码缓存
   ```
   Remove-Item -Recurse -Force core\__pycache__ 2>$null
   Remove-Item -Recurse -Force utils\__pycache__ 2>$null
   ```

5. 确认 .env 配置正确
   ```
   type .env
   ```

6. 重新启动应用
   ```
   python -m streamlit run app.py --server.port 8501 --server.headless true
   ```

---

## 情况 2：代码被覆盖

**恢复步骤：** 同情况 1。

---

## 情况 3：环境重新部署

**恢复步骤：**

1. 克隆或复制项目文件夹到目标机器
2. 从备份解压核心文件
   ```
   & 7z x releases/release-v1.0.1-final_20260812_180216.zip -o. -y
   ```
3. 创建 Python 虚拟环境（推荐）
   ```
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
4. 安装依赖
   ```
   pip install -r requirements.txt
   ```
5. 配置 .env 文件
   ```
   copy .env.example .env
   ```
   编辑 .env，填入正确的 API Key
6. 启动应用
   ```
   python -m streamlit run app.py --server.port 8501 --server.headless true
   ```

---

## 情况 4：找不到当前版本

**定位方法：**

1. 检查 VERSION.md 文件
   ```
   type VERSION.md
   ```

2. 检查 v1.0.1-final 独有特征
   ```
   Test-Path "packages.txt"  # 必须 True（v1.0.1-final 独有）
   Test-Path "core/prompts/accuracy_constraints.txt"  # 必须 True
   Test-Path "core/prompt_utils.py"  # 必须 True
   ```

**版本识别特征：**

| 特征 | v1.0.1-final | v1.0-final |
|------|-------------|-----------|
| packages.txt | 存在 | 不存在 |
| 主标题 | 🥇二讲智能服务效能增长Agent | 🥇二讲智能服务效能增长Agent |
| PDF 字体兼容 | Windows + Linux | 仅 Windows |
| accuracy_constraints.txt | 存在 | 存在 |

---

## 恢复后验证清单

- [ ] 标题显示"🥇二讲智能服务效能增长Agent"
- [ ] Tab1 学情续费预警系统：上传 Excel → 正常分析 → 导出 Excel
- [ ] Tab2 家校沟通策略助手：输入问题 → 正常回复
- [ ] Tab3 行课数据风险分析：上传行课 Excel → 风险分析 → P1-P4 分层正常
- [ ] Tab3 批量报告生成：生成报告 → 导出 PDF（一步下载）
- [ ] Tab4 数据看板：正常显示使用统计
- [ ] `packages.txt` 文件存在
- [ ] `core/prompts/accuracy_constraints.txt` 存在

---

## 后续开发流程

**禁止直接修改 release-v1.0.1-final！**

1. 当前开发始终在 `release-v1.0.1-final` 基础上进行
2. 如需修改功能，先创建版本分支标记：
   - 在 `releases/` 目录下创建新备份：`release-v1.1-dev_YYYYMMDD.zip`
3. 修改代码并测试
4. 测试通过后，创建新的正式版本备份：`release-v1.1-final_YYYYMMDD.zip`
5. 更新 `VERSION.md` 中的版本号和版本历史
6. `release-v1.0-final` 和 `release-v1.0.1-final` 备份文件**永不删除**，作为可回退的基线

**版本命名规范：**
- `release-vX.Y-final` — 正式稳定版本
- `release-vX.Y-dev` — 开发中版本
- 备份文件名后缀 `_YYYYMMDD_HHmmss` — 时间戳确保唯一性