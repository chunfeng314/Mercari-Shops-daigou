param(
    [string]$ShopId,
    [switch]$ConnectToWorkbench
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$profileRoot = Join-Path $projectRoot 'data\browser_profiles\japan\shop-login'
$chromePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not $ShopId) {
    $shopProfilePath = Join-Path $projectRoot 'data\shop-profile.json'
    if (-not (Test-Path -LiteralPath $shopProfilePath)) {
        throw 'Shop ID is required. Pass -ShopId or configure data/shop-profile.json locally.'
    }
    $shopProfile = Get-Content -LiteralPath $shopProfilePath -Raw | ConvertFrom-Json
    $ShopId = [string]$shopProfile.shop_id
}
if (-not $ShopId) {
    throw 'Shop ID is missing. Pass -ShopId or configure data/shop-profile.json locally.'
}
$shopUrl = "https://mercari-shops.com/seller/shops/$ShopId/products"

if (-not (Test-Path -LiteralPath $chromePath)) {
    throw "Chrome was not found at $chromePath"
}

# Use the same local Japanese route as the workbench, over HTTP. This Mihomo
# listener accepts HTTP proxy traffic on the same local port as SOCKS5.
$proxySetting = Get-Content -LiteralPath (Join-Path $projectRoot '.env') |
    Where-Object { $_ -match '^JAPAN_BROWSER_PROXY=' } |
    Select-Object -First 1
$proxyServer = 'http://127.0.0.1:10090'
if ($proxySetting) {
    $rawProxy = ($proxySetting -split '=', 2)[1].Trim()
    if ($rawProxy -match '^socks5?://([^:/]+):(\d+)$') {
        $proxyServer = "http://$($Matches[1]):$($Matches[2])"
    } elseif ($rawProxy -match '^https?://([^:/]+):(\d+)$') {
        $proxyServer = $rawProxy
    }
}
$proxyUri = [Uri]$proxyServer
$tcp = [System.Net.Sockets.TcpClient]::new()
try {
    $connect = $tcp.BeginConnect($proxyUri.Host, $proxyUri.Port, $null, $null)
    if (-not $connect.AsyncWaitHandle.WaitOne(2500)) { throw "VPN proxy is not reachable at $($proxyUri.Host):$($proxyUri.Port)" }
    $tcp.EndConnect($connect)
} finally {
    $tcp.Dispose()
}

$alreadyOpen = Get-CimInstance Win32_Process -Filter "name='chrome.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileRoot) }
if ($alreadyOpen) {
    throw 'The dedicated Mercari Chrome profile is already open. Close that window before switching its connection mode.'
}

New-Item -ItemType Directory -Path $profileRoot -Force | Out-Null
$arguments = @(
    "--user-data-dir=`"$profileRoot`"",
    "--proxy-server=$proxyServer",
    '--no-first-run',
    '--new-window'
)
if ($ConnectToWorkbench) {
    $arguments += '--remote-debugging-address=127.0.0.1'
    $arguments += '--remote-debugging-port=0'
}
$arguments += $shopUrl

Start-Process -FilePath $chromePath -ArgumentList $arguments | Out-Null
if ($ConnectToWorkbench) {
    $activePortFile = Join-Path $profileRoot 'DevToolsActivePort'
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline -and -not (Test-Path -LiteralPath $activePortFile)) {
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-Path -LiteralPath $activePortFile)) {
        throw 'Chrome opened, but did not expose its local workbench connection. Close it and try again.'
    }
}

Write-Host 'Mercari Chrome opened with the dedicated profile and Japanese proxy.'
if ($ConnectToWorkbench) {
    Write-Host 'Workbench connection is enabled for this launch.'
} else {
    Write-Host 'This login test uses ordinary Chrome without remote debugging. After login, close Chrome and reopen with -ConnectToWorkbench.'
}
