---
description: how to publish this (or a) project to GitHub — audit, clean, open-source essentials, push
---

# 把项目开源到 GitHub

按顺序执行。标记 `// turbo` 的步骤为只读审计，可自动运行。

## 1. 盘点仓库现状

// turbo
```bash
git status --short | head -40
git log --oneline -5
git ls-files | wc -l
git remote -v
git branch -a
```

确认：当前分支、与 main 的领先/落后关系、有没有 remote、有没有未提交改动。

## 2. 敏感信息与垃圾审计（最重要，漏了密钥就泄露）

// turbo
```bash
# .env 类文件是否被忽略
for f in .env .env.bak *.env*; do git check-ignore "$f" >/dev/null 2>&1 && echo "$f IGNORED" || echo "$f NOT-IGNORED"; done

# 已跟踪文件里的硬编码密钥扫描
git grep -nE "sk-[a-zA-Z0-9]{20}|ghp_[a-zA-Z0-9]{20}|hf_[a-zA-Z0-9]{20}|api[_-]?key.{0,5}=.{0,3}['\"][a-zA-Z0-9_-]{16}" || echo "clean"

# 待提交的新文件同样扫
git status --porcelain | awk '$1=="??"{print $2}' | xargs grep -lnE "sk-[a-zA-Z0-9]{20}|ghp_[a-zA-Z0-9]{20}" 2>/dev/null || echo "new files clean"

# 大文件（单文件 >1MB 的在 GitHub 上拖慢 clone）
git ls-files -z | xargs -0 du -b 2>/dev/null | sort -rn | head -10
du -sh .git
```

凡含真实密钥的文件（`.env.bak` 之类）→ 加进 `.gitignore`，**永远不要 commit**。密钥类只留 `.env.example` 模板。

## 3. 补齐开源必备文件

- **`.gitignore`** 追加：密钥备份、运行产物（`reports/`、日志、cache)、无关 side-project、编辑器锁文件、scratch 测试脚本
- **`README.md`** 重写公开版：一句话定位 → 徽章行 → Demo 图/GIF → Highlights → 架构图/目录表 → Quickstart → License。语言建议英文（中文项目可加中文段）
- **`LICENSE`** — MIT（默认）或其它，版权人写 git user.name
- **`requirements.txt`** — `git ls-files "*.py" | xargs grep -h "^import\|^from "` 扫三方包，排除 stdlib 和不可安装的运行时（如 isaacsim），分层注释
- **`.github/workflows/ci.yml`** — checkout → setup-python → `pip install -r requirements.txt` → `pytest tests/ -q`
- 可选：`CONTRIBUTING.md`、issue 模板、demo GIF(`ffmpeg` 从录制视频 `setpts=0.05*PTS,fps=8,scale=640` + palettegen 两趟出 ~7MB GIF)

## 4. 先跑测试再提交

```bash
python3 -m pytest tests/ -q
```

有失败先修——别把红的仓库推上去。环境依赖类失败（如测试偷偷连活体服务）在 fixture 里桩掉。

## 5. 提交并合到 main

```bash
git add -A
# gitignore 挡不住的已跟踪杂文件：git rm -r --cached <path>
git config user.name 2>/dev/null || git config user.name "$(git log -1 --format='%an')"
git config user.email 2>/dev/null || git config user.email "$(git log -1 --format='%ae')"
git commit -m "..."
git checkout main && git merge <当前分支> --ff-only
```

身份未配置时从历史提交取作者。merge 用 `--ff-only`；不能快进就先处理分歧。

## 6. 推送

```bash
git remote add origin <https-url>        # 若已有 remote 跳过
GIT_TERMINAL_PROMPT=0 git push -u origin main
git tag -a v0.1.0 -m "..." && git push origin v0.1.0
```

- `GIT_TERMINAL_PROMPT=0` 防止卡在密码框；失败说明无凭证 → 提示用户：装 `gh` 走 `gh auth login`，或网页建仓后提供 Personal Access Token
- 仓库需先在 GitHub 创建（**不勾** README/License/gitignore 初始化项，避免冲突）；或用 `gh repo create <name> --public --source=. --push` 一步完成

## 7. 推送后

// turbo
```bash
git status -sb   # 确认 main...origin/main 无 ahead/behind
```

提醒用户手动完成（API/git 推不上去的）：仓库页 ⚙ About → Description + Topics。

## 常见坑

- `.gitignore` 只对**未跟踪**文件生效；已入库的要 `git rm --cached`
- `.git` 体积远大于工作区 → 历史里有二进制；新仓库刚推时可用 `git lfs migrate`/删历史瘦身，之后需 force push，**有 fork/star 后不要再重写历史**
- mp4 在 README 里只是链接不自动播；首屏动图用 GIF
- 无 SSH key/无 gh CLI 时 HTTPS push 靠已存凭证；凭证不存在就必须用户介入，不要硬编码 token 进命令行
