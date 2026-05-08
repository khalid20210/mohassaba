$ErrorActionPreference = 'Stop'

# يشغّل Redis عبر Docker على المنفذ 6379
# يتطلب Docker Desktop

$exists = docker ps -a --format "{{.Names}}" | Select-String -Pattern "^jenan-redis$" -Quiet

if ($exists) {
  $running = docker ps --format "{{.Names}}" | Select-String -Pattern "^jenan-redis$" -Quiet
  if ($running) {
    Write-Host "Redis already running: jenan-redis"
    exit 0
  }
  docker start jenan-redis | Out-Null
  Write-Host "Redis container started: jenan-redis"
  exit 0
}

docker run -d --name jenan-redis -p 6379:6379 redis:7-alpine | Out-Null
Write-Host "Redis container created and started: jenan-redis"
