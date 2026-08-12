# Streamlit Cloud 部署操作指南

**版本：** release-v1.0.1-final  
**目标平台：** GitHub + Streamlit Cloud

---

## 部署前确认

已在本地确认以下全部就绪：

| 检查项 | 状态 |
|--------|------|
| app.py | ✅ |
| requirements.txt | ✅ |
| packages.txt（中文字体） | ✅ |
| VERSION 文件 | ✅ |
| .streamlit/config.toml | ✅ |
| .gitignore（排除 .env / releases / 测试文件） | ✅ |
| 版本号 | release-v1.0.1-final |

---

## 第一步：创建 GitHub 仓库

1. 打开 https://github.com/new
2. 填写：
   - Repository name: `erjiang-agent`（建议）
   - Description: `二讲智能服务效能增长Agent`
   - **选择 Public**（Streamlit Cloud 免费版要求 Public）
   - 不要勾选 "Add a README file"
   - 不要勾选 ".gitignore"
   - 不要勾选 "Choose a license"
3. 点击 "Create repository"
4. 复制仓库 URL：`https://github.com/你的用户名/erjiang-agent.git`

---

## 第二步：推送代码到 GitHub

在项目根目录打开终端，执行：

```bash
cd c:\Users\qinpei\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a6050685ca1edf6e77755b6\erjiang-agent

# 配置 git 用户信息
git config user.name "你的名字"
git config user.email "你的邮箱"

# 添加 GitHub 远程仓库（替换为你的仓库 URL）
git remote add github https://github.com/你的用户名/erjiang-agent.git

# 添加所有文件
git add .

# 提交
git commit -m "release-v1.0.1-final: Linux/Streamlit Cloud PDF 中文字体兼容修复"

# 推送到 GitHub
git push github main
```

> 如果 main 分支不存在，先用 `git branch -M main` 重命名。

---

## 第三步：连接 Streamlit Cloud

1. 打开 https://share.streamlit.io/
2. 点击 "Sign in with GitHub"
3. 授权 Streamlit 访问你的 GitHub
4. 点击 "New app"
5. 选择：
   - Repository: `你的用户名/erjiang-agent`
   - Branch: `main`
   - Main file path: `app.py`
6. 点击 "Deploy!"

---

## 第四步：配置 Secrets

部署完成后，进入 App Settings → Secrets：

1. 点击 "⋮" → "Settings" → "Secrets"
2. 添加以下 Secrets：

| Name | Value |
|------|-------|
| `OPENAI_API_KEY` | `sk-xxxxxxxx`（你的 DeepSeek Key） |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` |
| `MODEL_NAME` | `deepseek-v4-flash` |

3. 点击 "Save"
4. 应用会自动重启（Reboot）

---

## 第五步：验证部署

1. 打开 Streamlit Cloud 给你的链接（格式：`https://你的用户名-erjiang-agent.streamlit.app`）
2. 检查：
   - [ ] 首页标题显示 `🥇二讲智能服务效能增长Agent`
   - [ ] Tab2 显示 `💬 家校沟通策略助手`
   - [ ] Tab1 上传 Excel → 正常分析
   - [ ] Tab2 输入问题 → 正常回复
   - [ ] Tab3 上传行课 Excel → 风险分析 → 导出 PDF

---

## 部署后验证 VERSION

在 Streamlit Cloud 的 App 页面，点击右下角 "⋮" → "Settings" → 查看 "App controls" 中的 "Reboot app" 确认已部署。

本地通过以下命令验证线上版本：

```bash
# 检查 GitHub 仓库中的 VERSION 文件
curl -s https://raw.githubusercontent.com/你的用户名/erjiang-agent/main/VERSION
```

输出应显示：
```
release-v1.0.1-final
2026-08-12
Linux/Streamlit Cloud PDF 中文字体兼容修复
基于 release-v1.0-final 升级
```

---

## 公网访问链接

部署成功后，你的固定链接为：

```
https://你的用户名-erjiang-agent.streamlit.app
```

---

## 后续更新流程

1. 本地修改代码并测试通过
2. 创建新版本备份
   ```
   & 7z a releases/release-v1.1-final_YYYYMMDD_HHmmss.zip app.py config.py core/ utils/ data/sop_knowledge/ requirements.txt packages.txt VERSION .streamlit/
   ```
3. 提交并推送
   ```
   git add .
   git commit -m "release-v1.1-final: 更新说明"
   git push github main
   ```
4. Streamlit Cloud 自动检测到 GitHub 更新，自动重新部署
5. **公网链接不变**，用户刷新即可看到新版本

---

## 紧急回退

```bash
# 回退到 release-v1.0.1-final
git reset --hard <v1.0.1-final的commit>
git push github main --force

# 或从本地备份恢复
双击 restore.bat
git add . && git commit -m "回退到 release-v1.0.1-final" && git push github main --force
```