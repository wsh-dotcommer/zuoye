<#
本地演示辅助脚本：启动一次，之后每隔 N 秒自动重跑一次日报生成。
这样你只要在浏览器里按 F5，就能看到自己刚在 GitHub 上做的事。

用法：
    .\watch.ps1                                  # 默认 config.yaml，每 5 分钟跑一次
    .\watch.ps1 -IntervalSeconds 60              # 每分钟跑一次（建议配 GITHUB_TOKEN）
    .\watch.ps1 -Config config.demo.yaml         # 换配置
    .\watch.ps1 -MaxRuns 1                       # 只跑一次（自检用）

说明：这不是规范里的"常驻后台服务"（proposal.md 明确不做常驻服务），
      只是本地演示时省去反复敲命令的小工具；Ctrl+C 退出。

注意：匿名访问 GitHub 只有 60 次/小时，每次运行约消耗 4~8 次请求，
      所以默认间隔取 5 分钟。配置了 GITHUB_TOKEN 后可放宽到 60 秒。
#>

param(
    [string]$Config = "config.yaml",
    [int]$IntervalSeconds = 300,
    [int]$MaxRuns = 0
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$main = Join-Path $root "main.py"
$configPath = Join-Path $root $Config

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "[错误] 找不到 .venv，请先执行：" -ForegroundColor Red
    Write-Host '  python -m venv .venv'
    Write-Host '  .\.venv\Scripts\python.exe -m pip install -e ".[dev]"'
    exit 1
}
if (-not (Test-Path -LiteralPath $configPath)) {
    Write-Host "[错误] 找不到配置文件 $Config（可先 Copy-Item config.yaml.example config.yaml）" -ForegroundColor Red
    exit 1
}

if ($MaxRuns -eq 0) {
    Write-Host "[watch] 每 $IntervalSeconds 秒自动生成一次日报（$Config），Ctrl+C 退出。" -ForegroundColor Cyan
    Write-Host "[watch] 之后你只要在浏览器里刷新页面即可看到最新内容。" -ForegroundColor Cyan
} else {
    Write-Host "[watch] 只运行 $MaxRuns 次（自检模式）。" -ForegroundColor Cyan
}

$run = 0
while ($true) {
    $run++
    Write-Host ("[watch] 第 {0} 次执行 @ {1}" -f $run, (Get-Date -Format "HH:mm:ss")) -ForegroundColor Yellow
    & $python $main --config $Config --dry-run
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[watch] 本次返回码 $LASTEXITCODE（2 表示所有数据源都失败），继续等待下一次。" -ForegroundColor Red
    } else {
        Write-Host "[watch] 完成，刷新浏览器即可看到最新日报。" -ForegroundColor Green
    }

    if ($MaxRuns -gt 0 -and $run -ge $MaxRuns) {
        break
    }
    Start-Sleep -Seconds $IntervalSeconds
}

Write-Host "[watch] 已退出。" -ForegroundColor Cyan
