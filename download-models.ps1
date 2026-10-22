<# 导演台：缺失模型并行下载（curl.exe，带进度 + sha256 校验）
  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1 -Parallel 4
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1 -Proxy http://127.0.0.1:7897
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1 -NoHash      # 跳过 sha256（快，但不保险）
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1 -DryRun
  说明：- 并行是多个文件同时下，每个文件单连接；单文件多连接用 aria2c（见文件末尾）
        - 每条 -C -，中断重跑会续传；下完逐个校验「大小 + sha256」，不符会删掉重下
        - sha256 来自 HF 的 X-Linked-ETag（生成脚本时已取好，不用联网核对）
#>
param([int]$Parallel = 3, [string]$Proxy = "", [switch]$NoHash, [switch]$DryRun)

$ErrorActionPreference = "Continue"
function Fmt($bytes) {
  if ($bytes -ge 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
  if ($bytes -ge 1MB) { return "{0:N0} MB" -f ($bytes / 1MB) }
  return "{0:N0} KB" -f ($bytes / 1KB)
}

$tasks = @(
  [pscustomobject]@{ url = "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"; size = 1956193000; sha = "2339acdf19bfe123f46b971ea35d367a84adb85de43627e1eceafa5a5b2b111e" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors"; out = "D:/ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors"; size = 605254808; sha = "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors"; out = "D:/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors"; size = 5207808496; sha = "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"; out = "D:/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"; size = 15687142551; sha = "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6" }
  [pscustomobject]@{ url = "https://hf-mirror.com/OzzyGT/taeh3/resolve/main/taeh3.safetensors"; out = "D:/ComfyUI/models/vae_approx/taeh3.safetensors"; size = 22709752; sha = "4fd022bfcab08772fe0536b17ea1a3bbb5625be11e397868d1c5d891863d4c13" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors"; out = "D:/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors"; size = 27141342152; sha = "bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Kijai/MiniMax-H3-experimental/resolve/main/minimax_h3_video_vae_int8_convrot.safetensors"; out = "D:/ComfyUI/models/vae/minimax_h3_video_vae_int8_convrot.safetensors"; size = 3171670912; sha = "9bb2d96f218c76babd85e0611b85ca8fb330a90546c01a0005e8a58a59593410" }
  [pscustomobject]@{ url = "https://hf-mirror.com/t8star/Semantic-Bridge-Comfy/resolve/main/models/semantic_bridge/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors"; out = "D:/ComfyUI/models/loras/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors"; size = 11024432; sha = "896829a178e89e23f35799d403971b19b10bbacb2da00454c576770b2f58a9b1" }
  [pscustomobject]@{ url = "https://hf-mirror.com/JOKER141/MiniMax-H3-Combat-Base-V2/resolve/main/H3_Combat_V2.safetensors"; out = "D:/ComfyUI/models/loras/minimax/H3_Combat_V2.safetensors"; size = 155110280; sha = "5b3edb09e9d6029439badf9bc9db4ba4a355ae679b0810888de82c4793c0bac8" }
  [pscustomobject]@{ url = "https://hf-mirror.com/RunningHubAI/rh-minimax-h3-fl2v-turbo-4step-v1.2-768p-comfyui-bf16.safetensors-lora/resolve/main/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors"; size = 1956193000; sha = "c8168ebc17bbacc4296103dda2fec1ba85b24392fa08cf2bfbcef0cff0dc3cc8" }
  [pscustomobject]@{ url = "https://hf-mirror.com/RunningHubAI/rh-minimax-h3-turbo-4step-10erosmax-test4-pruned-curveproj1025-exp-v001-t8-lora/resolve/main/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors"; size = 794888696; sha = "6c2f38d45dfa3fc282a48de3171b6946a5e6d46e13f832c43b93734f6d12edf5" }
  [pscustomobject]@{ url = "https://hf-mirror.com/t8star/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001/resolve/main/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors"; size = 794888704; sha = "a117f18682a22a0381cadd9832da0afe9912f604305b3e44310b5aa1919734cc" }
  [pscustomobject]@{ url = "https://hf-mirror.com/kirk86413/cinema-h3/resolve/main/Minimax%20H3%E7%9C%9F%E5%AE%9E%E7%94%B5%E5%BD%B1%E8%B4%A8%E6%84%9FV0.1%EF%BC%88%E8%A7%A3%E5%86%B3%E5%BC%A0%E9%87%8F%E6%8A%A5%E9%94%99%EF%BC%89.safetensors"; out = "D:/ComfyUI/models/loras/minimax/MinimaxH3真实电影质感V0.1.safetensors"; size = 155110448; sha = "cd9ef1ebb1ab9221492dc09f069de364fff1454fdcae76902754d07db6e58dcd" }
  [pscustomobject]@{ url = "https://hf-mirror.com/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair/resolve/main/Motion_Repair.safetensors"; out = "D:/ComfyUI/models/loras/minimax/Motion_Repair.safetensors"; size = 155110272; sha = "a678a3657cefd5c2c2712f892da2f71be53c3f252e335557e918854f8abc579f" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Asirus/Minimax-H3-Latent-Upscaler-BF16-MAXQUALITY/resolve/main/minimax_h3_latent_upscaler_3d_fp16.safetensors"; out = "D:/ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16.safetensors"; size = 690592672; sha = "043e5a48e161610ef6c3ea974645220354d06fa618abca15f76d084812eb55c2" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Konteni2/Minimax_h3_latent_Upscaler/resolve/main/minimax_h3_latent_upscaler_3d_bf16.safetensors"; out = "D:/ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_bf16.safetensors"; size = 690592992; sha = "4f57821f5837f32f7142b67d815606dbd7550f194e5c769f7d6c3f83b146a5e6" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Alissonerdx/Minimax-H3-ComfyUI/resolve/main/latent_upscaler/h3_upscaler_lms_v0.1.safetensors"; out = "D:/ComfyUI/models/upscale_models/h3_upscaler_lms_v0.1.safetensors"; size = 690593048; sha = "40d4228227146245ef2b65480b647c50222465ca125de5880f192e3259e40d59" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors"; out = "D:/ComfyUI/models/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors"; size = 9057782194; sha = "bf0b4fa2e41a25684dc9e9b256cd505564f02fed09be3da95ce024e653e2c52b" }
  [pscustomobject]@{ url = "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"; size = 1956192992; sha = "c396a9a06f58399e9df9754b18299818d84a2ddd371724ba48fe4a41221437dc" }
  [pscustomobject]@{ url = "https://hf-mirror.com/unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_M.gguf"; out = "D:/ComfyUI/models/LLM/Qwen3.8-27B-Q4_K_M.gguf"; size = 16464440224; sha = "322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482" }
  [pscustomobject]@{ url = "https://hf-mirror.com/unsloth/Qwen3.8-27B-GGUF/resolve/main/mmproj-BF16.gguf"; out = "D:/ComfyUI/models/LLM/Qwen3.8-mmproj-BF16.gguf"; size = 931146432; sha = "83ee4f4f205fa514161778c41df1ea14144faa0f713510893b63c2395f5c2d53" }
)

if ($Proxy) { $env:HTTPS_PROXY = $Proxy; $env:HTTP_PROXY = $Proxy; "代理: $Proxy" }

# 单实例锁：两个下载器同时写同一批文件会互相覆盖（curl -C - 各自算偏移）
$lockFile = Join-Path $PSScriptRoot ".download-models.lock"
if (Test-Path $lockFile) {
  $oldPid = 0
  [void][int]::TryParse((Get-Content $lockFile -Raw -ErrorAction SilentlyContinue), [ref]$oldPid)
  if ($oldPid -gt 0 -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
    "另一个下载进程还在跑（PID $oldPid），先停掉它：Stop-Process -Id $oldPid -Force"
    exit 1
  }
  Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}
Set-Content -Path $lockFile -Value $PID -Encoding ascii
try {
$totalAll = ($tasks | Measure-Object -Property size -Sum).Sum
"任务 {0} 个，合计约 {1}" -f $tasks.Count, (Fmt $totalAll)
if ($NoHash) { "校验：只比大小（-NoHash）" } else { "校验：大小 + sha256" }

if ($DryRun) {
  "计划（并发 $Parallel）："
  foreach ($t in $tasks) { "  {0,10}  {1}" -f (Fmt $t.size), $t.out }
  exit 0
}

function Verify-One($t) {
  $sz = if (Test-Path $t.out) { (Get-Item $t.out).Length } else { 0 }
  if ($t.size -gt 0 -and $sz -ne $t.size) {
    Write-Host ("    大小不符：{0} / {1}" -f (Fmt $sz), (Fmt $t.size))
    return $false
  }
  if (-not $NoHash -and $t.sha) {
    $h = (Get-FileHash -Path $t.out -Algorithm SHA256).Hash.ToLower()
    if ($h -ne $t.sha) {
      Write-Host ("    sha256 不符，删掉重下：{0}" -f $h)
      Remove-Item $t.out -Force -ErrorAction SilentlyContinue
      return $false
    }
    Write-Host "    sha256 OK"
  }
  return $true
}

function Start-One($t) {
  $a = @("-L", "-C", "-", "--create-dirs", "-sS", "--retry", "2", "--retry-delay", "5", $t.url, "-o", $t.out)
  Start-Process -FilePath "curl.exe" -ArgumentList $a -PassThru -NoNewWindow
}

"预检：跳过已经完整的文件"
$todo = @()
foreach ($t in $tasks) {
  $sz = if (Test-Path $t.out) { (Get-Item $t.out).Length } else { -1 }
  if ($sz -eq $t.size) {
    if (Verify-One $t) { "[skip] 已完整  {0}" -f (Split-Path $t.out -Leaf); continue }
    Remove-Item $t.out -Force -ErrorAction SilentlyContinue
  }
  $todo += $t
}
"待下载 {0} 个" -f $todo.Count

$queue = [System.Collections.Queue]::new()
$todo | ForEach-Object { $queue.Enqueue($_) }
$running = @(); $failed = @()
$sw = [Diagnostics.Stopwatch]::StartNew()
$lastTick = 0.0

while ($queue.Count -gt 0 -or $running.Count -gt 0) {
  while ($queue.Count -gt 0 -and $running.Count -lt $Parallel) {
    $t = $queue.Dequeue()
    $base = if (Test-Path $t.out) { (Get-Item $t.out).Length } else { 0 }
    $p = Start-One $t
    $running += [pscustomobject]@{ Process = $p; Task = $t; LastSize = $base; LastTime = [double]$sw.Elapsed.TotalSeconds }
    "[{0}] 开始  {1}  ({2})" -f (Get-Date -Format "HH:mm:ss"), (Split-Path $t.out -Leaf), (Fmt $t.size)
  }

  Start-Sleep -Milliseconds 1000

  if ($sw.Elapsed.TotalSeconds - $lastTick -ge 5) {
    $lastTick = $sw.Elapsed.TotalSeconds
    foreach ($r in $running) {
      if ($r.Process.HasExited) { continue }
      $size = if (Test-Path $r.Task.out) { (Get-Item $r.Task.out).Length } else { 0 }
      $now = [double]$sw.Elapsed.TotalSeconds
      $dt = [math]::Max($now - $r.LastTime, 0.001)
      $speed = ($size - $r.LastSize) / $dt
      $r.LastSize = $size; $r.LastTime = $now
      $pct = if ($r.Task.size -gt 0) { [math]::Round(100.0 * $size / $r.Task.size, 1) } else { 0 }
      "[{0}] {1,-46} {2,8} / {3,-8} {4,5}%  {5}/s" -f (Get-Date -Format "HH:mm:ss"),
        (Split-Path $r.Task.out -Leaf), (Fmt $size), (Fmt $r.Task.size), $pct, (Fmt ([int64]$speed))
    }
  }

  foreach ($r in @($running)) {
    if (-not $r.Process.HasExited) { continue }
    $code = $r.Process.ExitCode
    $size = if (Test-Path $r.Task.out) { (Get-Item $r.Task.out).Length } else { 0 }
    if (Verify-One $r.Task) {
      "[{0}] 完成  {1}  ({2})" -f (Get-Date -Format "HH:mm:ss"), (Split-Path $r.Task.out -Leaf), (Fmt $size)
    } else {
      "[{0}] 未完成 {1}  (exit={2}, {3} / {4})" -f (Get-Date -Format "HH:mm:ss"), (Split-Path $r.Task.out -Leaf), $code, (Fmt $size), (Fmt $r.Task.size)
      $failed += $r.Task
    }
    $running = @($running | Where-Object { $_.Process.Id -ne $r.Process.Id })
  }
}

if ($failed.Count -gt 0) {
  "---- 重试 {0} 个（续传）----" -f $failed.Count
  foreach ($t in $failed) {
    "[{0}] 重试  {1}" -f (Get-Date -Format "HH:mm:ss"), (Split-Path $t.out -Leaf)
    $p = Start-One $t; $p.WaitForExit()
    $size = if (Test-Path $t.out) { (Get-Item $t.out).Length } else { 0 }
    if (Verify-One $t) { "    完成 {0}" -f (Fmt $size) }
    else { "    仍然失败：$($t.out)" }
  }
}

"全部结束，用时 {0:N1} 分钟" -f $sw.Elapsed.TotalMinutes
"目录：D:\ComfyUI\models"
<# 单文件多连接（更快，需 aria2；清单里已带 checksum=sha-256）：
   winget install aria2.aria2
   aria2c -i download-models-aria2.txt -c -x16 -s16 -k1M -j3 --dir="D:\ComfyUI\models"
#>
} finally { Remove-Item $lockFile -Force -ErrorAction SilentlyContinue }
