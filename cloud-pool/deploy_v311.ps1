# 一键部署v3.1.1到阿里云 + 商户配置
# 用法: .\deploy_v311.ps1

Write-Host "=== Deploy v3.1.1 ===" -ForegroundColor Cyan

# 1. SCP上传
Write-Host "[1/4] SCP上传..." -ForegroundColor Yellow
scp -o ConnectTimeout=20 "$PSScriptRoot\cloud_pool_server.py" aliyun:/opt/cloud_pool/cloud_pool_server.py
if ($LASTEXITCODE -ne 0) { Write-Host "SCP失败,SSH可能仍被限流" -ForegroundColor Red; exit 1 }

# 2. 重启服务
Write-Host "[2/4] 重启cloud-pool..." -ForegroundColor Yellow
ssh -o ConnectTimeout=15 aliyun "systemctl restart cloud-pool && sleep 3 && systemctl status cloud-pool --no-pager | head -5"

# 3. 配置商户收款信息
Write-Host "[3/4] 配置商户收款..." -ForegroundColor Yellow
scp -o ConnectTimeout=15 "$PSScriptRoot\_remote_setup.py" aliyun:/tmp/_remote_setup.py
ssh -o ConnectTimeout=15 aliyun "python3 /tmp/_remote_setup.py"

# 4. 验证
Write-Host "[4/4] 验证..." -ForegroundColor Yellow
ssh -o ConnectTimeout=15 aliyun "curl -s http://127.0.0.1:19880/api/health"

Write-Host "`n=== 部署完成 ===" -ForegroundColor Green
