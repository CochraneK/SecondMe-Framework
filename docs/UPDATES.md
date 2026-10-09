# SecondMe Updater｜不覆盖个人资料的框架更新

**版本：v0.2 · 面向通过模板创建的私人 SecondMe 仓库。**

## 一句话原理

你只需要创建一次私人仓库。之后当公开 SecondMe-Framework 发布新版，私人仓库可以**定期检查**，并提出一个待你人工审核的 Pull Request（PR）。

**Updater 不是自动合并器。** 只有在你查看变更并亲自合并之后，新方法才会进入个人仓库。

## 受保护的边界

| 内容 | 默认更新行为 |
| --- | --- |
| `framework/**/*.md` | 官方文件未被修改时才升级 |
| `prompts/**/*.md` | 官方文件未被修改时才升级 |
| `templates/**/*.md` | 可增加新空模板；已填写或修改的模板不会被覆盖 |
| `my/`、`custom/` | 不读取、不更新、不暂存 |
| `personal/`、`private/`、`raw/` | 不读取、不更新、不暂存 |
| `examples/` | 不同步，以免影响个人建模的上下文 |
| `scripts/`、`.github/`、`docs/` | **不会通过自动升级执行或替换代码、Actions、图形文件** |
| `.secondme/framework-lock.json` | 仅记录已安装的官方文件指纹；无个人数据 |
| `.secondme/UPDATE_NOTICE.md` | 更新提示与冲突路径名称，无文件正文 |

**特别注意：** 上游 Markdown 内容虽需满足 Git 指纹校验，仍是**需要人审查的外部内容**，可能改变 AI 的行为。请在合并 PR 前阅读差异。

## 朋友第一次使用（推荐）

1. 在公开仓库选择 **Use this template → Create a new repository**，将新仓库设为 **Private**。必须先由维护者开启 Template repository。
2. 在私人副本中选 **Actions** 并启用工作流（如果 GitHub 有提示）。
3. 进入私人仓库 **Settings → Actions → General → Workflow permissions**，允许合适的 `GITHUB_TOKEN` 权限；如果界面提供 **Allow GitHub Actions to create and approve pull requests**，也需要允许创建 PR。
4. 在 Actions 中找到 **SecondMe · 安全检查框架更新**，点击 **Run workflow** 进行首次手动检测。
5. 以后默认每周一 03:17 UTC 检查一次。如发现上游版本变化，它会在*你的私人仓库内部*创建一个待审核 PR。
6. 合并前查看 PR 的差异，确认新内容适合自己；你也可以拒绝更新或继续使用旧版。

> **如果 GitHub 阻止 Actions 创建 PR**：工作流不会直接合并；若已推送更新分支，可手动从该分支创建 PR。查看 Actions 日志即可找到分支名。

## 三方隔离

- **官方框架：** `framework/`、`prompts/`、`templates/` 的初始文件。
- **本人资料：** 建议在私有副本中使用 `my/`，按需版本控制，不上传到公开框架。
- **个人定制：** 建议放在 `custom/`；不要在官方 prompt 原件里直接修改，便于长期更新。

如果确实修改了官方文件，更新器会比较其当前 Git Blob SHA 与已安装官方版本的指纹：

- 与旧官方版本**一致**：允许用新版本更新；
- 已与新官方版本**一致**：更新版本指纹；
- **本地自行修改**：报告冲突，不覆盖；
- 上游**新增**而本地不存在：添加；
- 上游**移除**：保留本地文件并提示人工评估；
- 文件或路径存在符号链接、路径穿越等风险：停止。

## 只更新规则，不替你重新分析人生

新版理论或提示词**不会自动修改你的自我认识**。个人事实、记忆、关系资料和已作出的决定没有被自动重跑、覆盖或重新解释。

## 本地手动检查

需要 Python 3.10+ 和联网读取公开 GitHub 原始文件：

```bash
python3 scripts/secondme_updater.py
```

只会展示计划，不会修改文件。

要在私人副本里实际应用允许的文件更新（建议先新建 Git 分支）：

```bash
python3 scripts/secondme_updater.py --apply
```

注意：`--apply` 仅对允许同步的官方文件生效；它**不会替你创建 PR**，也不会覆盖冲突文件。

## 维护者如何发布新版本

在**公开上游仓库**修改官方 Markdown 文件之后：

```bash
git add framework/ prompts/ templates/
python3 scripts/build_manifest.py 0.3.0
git add .secondme/framework-manifest.json .secondme/framework-lock.json
python3 -m unittest discover -s tests -v
git diff --cached --check
```

确认文件无真实私人内容，检查差异，然后正常提交推送。`0.3.0` 仅为例子，应按实际版本递增。**修改任何受管理文件必须提升版本并更新清单**；否则校验失败并安全停止。

特别要确认：
- 正在发布的是从零公开编写的通用框架，不是私人 SecondMe 的原始文件或历史。
- `framework-manifest.json` 中全部 SHA 匹配实际发布的文件。
- `scripts/` 与 `.github/` 的更新不会自动推给已有的私人仓库；涉及新可执行功能需额外的、显式同意的升级路径。
- 用户的 Private 仓库仍然可能面临 GitHub 账号权限、设备、备份、Actions 运行环境等常规云端风险，不是端到端加密仓库。

## 更新状态说明

- 当前公开仓库自带 v0.2.0 的基础清单，可供今后新的私人模板副本使用。
- 现在不需要假装已有 v0.3 可供升级。
- 基于更老 v0.1 模板建立的仓库，需要先**手动**添加 Updater 文件和基础指纹清单，才能获得后续更新；旧仓库不能自动得知这套新能力。
- GitHub 定时任务可能延迟、因配置问题失败或因长期无活动而停用；用户仍可以手动运行。

**核心承诺：自动发现，人工批准；更新方法，不覆盖生活。**
