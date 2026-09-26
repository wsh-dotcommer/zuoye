<#
一键发布到 GitHub Pages（首次运行会弹出 GitHub 登录窗口）

用法：
    .\publish.ps1
    .\publish.ps1 -Message "docs: 更新日报站点"

它做什么：
    1. 检查站点产物 docs/index.html 是否存在
    2. 若尚未初始化，则初始化 git 仓库并绑定 origin
    3. 以远端 main 为基线，把本项目文件提交为一个新 commit（普通快进提交，不强推、不覆盖远端历史）
    4. push 到 https://github.com/wsh-dotcommer/zuoye.git
    5. 打印 GitHub Pages 的开启步骤

不会推送的内容（见 .gitignore）：.venv/、各类缓存、config*.yaml 本地配置、
output/、logs/、data/、demo/ 等本地产物，以及 87MB 的扫描件 PDF。
#>

param(
    [string]$Remote = "https://github.com/wsh-dotcommer/zuoye.git",
    [string]$Branch = "main",
    [string]$Message = "feat: SDD 复现智能日报生成器 v1.1（含工时统计与静态日报站）"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Info($text) { Write-Host $text -ForegroundColor Cyan }
function Ok($text) { Write-Host $text -ForegroundColor Green }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Warn "[错误] 未检测到 git，请先安装 Git for Windows。"
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $root "docs\index.html"))) {
    Warn "[错误] 找不到 docs\index.html。请先跑一次日报生成："
    Warn '  .\.venv\Scripts\python.exe main.py --config config.yaml --dry-run'
    exit 1
}

# 提交身份：只对本仓库生效（local），不会动你的全局配置
git config user.name "wsh-dotcommer" | Out-Null
git config user.email "wsh-dotcommer@users.noreply.github.com" | Out-Null

$initialized = Test-Path -LiteralPath (Join-Path $root ".git")
if (-not $initialized) {
    Info "[1/5] 初始化本地仓库并绑定远端"
    git init -q -b $Branch
    git remote add origin $Remote
    git fetch origin $Branch
    if ($LASTEXITCODE -eq 0) {
        # 以远端 main 为基线：既保留远端已有历史，又不覆盖本地工作区
        git branch -f $Branch "origin/$Branch" | Out-Null
        git symbolic-ref HEAD "refs/heads/$Branch"
        git reset --mixed "origin/$Branch" | Out-Null
        Ok "    已基于远端 $Branch 建立基线（远端历史保留）"
    } else {
        Warn "    远端没有 $Branch 分支，将创建新分支"
    }
} else {
    Info "[1/5] 检测到已初始化的仓库，直接增量提交"
    if (-not (git remote | Select-String -SimpleMatch "origin")) {
        git remote add origin $Remote
    } else {
        git remote set-url origin $Remote
    }
    git fetch origin $Branch 2>$null | Out-Null
}

Info "[2/5] 扫描变更（.gitignore 已排除虚拟环境、缓存与本地产物）"
git add -A
$status = git status --short
if ($status) {
    $status | ForEach-Object { Write-Host "    $_" }
    $deleted = $status | Where-Object { $_ -match "^D" }
    if ($deleted) {
        Warn "    注意：以上 D 开头的是本次会从远端删除的文件（例如本地不存在的产物）。"
    }
} else {
    Ok "    没有需要提交的变更"
}

Info "[3/5] 提交"
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Ok "    没有变更需要提交，跳过"
} else {
    git commit -q -m $Message
    git log --oneline -1 | ForEach-Object { Write-Host "    $_" }
}

Info "[4/5] 推送到 $Remote（首次会弹出 GitHub 登录）"
git push -u origin $Branch
if ($LASTEXITCODE -ne 0) {
    Warn "[失败] 推送未成功。请按报错内容对照下面两类原因："
    Warn "  A. 报错含 'Could not connect' / 'Failed to connect' —— 网络连不上 github.com"
    Warn "     判断：浏览器能打开 GitHub 就说明是 git 没走代理（git 不读系统代理）"
    Warn "     办法1：给 git 配代理（端口换成你代理软件的 HTTP 端口）"
    Warn "       git config --global http.proxy http://127.0.0.1:7890"
    Warn "       git config --global https.proxy http://127.0.0.1:7890"
    Warn "     办法2：改用 GitHub Desktop / VS Code 推送（它们走系统代理）"
    Warn "     办法3：换网络（手机热点常可直接连通）"
    Warn "  B. 报错含 'Authentication failed' / '403' / 'Permission denied' —— 账号或权限问题"
    Warn "     用 wsh-dotcommer 账号登录后重跑 .\publish.ps1 即可"
    Warn "  提示：本地提交已经完成，修好网络后重跑本脚本不会重复提交。"
    exit 1
}
Ok "    推送成功"

Info "[5/5] 下一步：在 GitHub 上开启 Pages（只需做一次）"
Write-Host "    1) 打开 https://github.com/wsh-dotcommer/zuoye/settings/pages"
Write-Host "    2) Source 选 'Deploy from a branch'"
Write-Host "    3) 分支选 main，目录选 /docs，点 Save"
Write-Host "    4) 等 30~60 秒后访问 https://wsh-dotcommer.github.io/zuoye/"
Ok "完成。以后每次更新只要再跑一次 .\publish.ps1，站点会自动刷新。"
