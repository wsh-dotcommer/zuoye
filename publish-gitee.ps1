<#
推送到 Gitee（作为 GitHub 导入的中转），适用于本机连不上 github.com 的情况。

用法：
    .\publish-gitee.ps1                                  # 默认推送到 https://gitee.com/king-sh/zuoye.git
    .\publish-gitee.ps1 -Gitee "https://gitee.com/你的用户名/仓库名.git"

前置条件：先在 Gitee 上建好空仓库（不要勾选"初始化仓库"，不要生成 README）。

推完之后去 GitHub 做导入（浏览器操作，GitHub 服务器自己来拉取，不受你本地网络影响）：
    https://github.com/new/import
#>

param(
    [string]$Gitee = "https://gitee.com/king-sh/zuoye.git",
    [string]$Branch = "main",
    [string]$Message = "chore: 同步本地改动"
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Info($text) { Write-Host $text -ForegroundColor Cyan }
function Ok($text) { Write-Host $text -ForegroundColor Green }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath (Join-Path $root ".git"))) {
    Warn "[错误] 当前目录还不是 git 仓库。请先运行 .\publish.ps1 完成首次初始化与提交。"
    exit 1
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Warn "[错误] 未检测到 git。"
    exit 1
}

Info "[1/4] 提交本地未提交的改动"
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Ok "    没有待提交的改动"
} else {
    git commit -q -m $Message
    git log --oneline -1 | ForEach-Object { Write-Host "    $_" }
}

Info "[2/4] 绑定 Gitee 远端"
$remotes = git remote
if ($remotes -contains "gitee") {
    git remote set-url gitee $Gitee
} else {
    git remote add gitee $Gitee
}
git remote -v | Select-String -SimpleMatch "gitee" | ForEach-Object { Write-Host "    $_" }

Info "[3/4] 推送到 Gitee（首次会要求输入 Gitee 账号或私人令牌）"
git push -u gitee $Branch
if ($LASTEXITCODE -ne 0) {
    Warn "[失败] 推送到 Gitee 未成功。请检查："
    Warn "  1) Gitee 仓库是否已经建好（$Gitee）"
    Warn "  2) 建仓库时是否勾选了'初始化仓库'——勾了会导致历史冲突，删掉重建一个空仓库即可"
    Warn "  3) 账号密码/私人令牌是否正确"
    exit 1
}
Ok "    推送成功"

Info "[4/4] 下一步：在 GitHub 上导入（浏览器操作，只需做一次）"
Write-Host "    1) 打开 https://github.com/new/import"
Write-Host "    2) 'Your old repository's clone URL' 填：$Gitee"
Write-Host "    3) Repository name 填：zuoye（或你想要的任意名字）"
Write-Host "    4) 选 Public → Begin import → 等 1~2 分钟"
Write-Host "    5) 导入完成后开 Pages：Settings → Pages → Deploy from a branch → main + /docs"
Ok "完成后访问 https://wsh-dotcommer.github.io/zuoye/ 即可看到日报站点。"
