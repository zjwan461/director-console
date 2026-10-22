<# 导演台：缺失模型并行下载（curl.exe，带进度）——HuggingFace 官网版
  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1 -Parallel 4
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1 -Proxy http://localhost:11081
    powershell -NoProfile -ExecutionPolicy Bypass -File download-models.ps1 -DryRun
  说明：- 源是 https://huggingface.co（官网，国内一般需要代理：-Proxy http://localhost:11081）
        - 并行是多个文件同时下，每个文件单连接；单文件多连接用 aria2c（见文件末尾）
        - 每条 -C -，中断重跑会续传；失败最后重试一轮
#>
param([int]$Parallel = 3, [string]$Proxy = "", [switch]$DryRun)

$ErrorActionPreference = "Continue"
function Fmt($bytes) {
  if ($bytes -ge 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
  if ($bytes -ge 1MB) { return "{0:N0} MB" -f ($bytes / 1MB) }
  return "{0:N0} KB" -f ($bytes / 1KB)
}

$tasks = @(
  [pscustomobject]@{ url = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors"; out = "D:/ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors"; out = "D:/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"; out = "D:/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/OzzyGT/taeh3/resolve/main/taeh3.safetensors"; out = "D:/ComfyUI/models/vae_approx/taeh3.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors"; out = "D:/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Kijai/MiniMax-H3-experimental/resolve/main/minimax_h3_video_vae_int8_convrot.safetensors"; out = "D:/ComfyUI/models/vae/minimax_h3_video_vae_int8_convrot.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/t8star/Semantic-Bridge-Comfy/resolve/main/models/semantic_bridge/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors"; out = "D:/ComfyUI/models/loras/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/JOKER141/MiniMax-H3-Combat-Base-V2/resolve/main/H3_Combat_V2.safetensors"; out = "D:/ComfyUI/models/loras/minimax/H3_Combat_V2.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/RunningHubAI/rh-minimax-h3-fl2v-turbo-4step-v1.2-768p-comfyui-bf16.safetensors-lora/resolve/main/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/RunningHubAI/rh-minimax-h3-turbo-4step-10erosmax-test4-pruned-curveproj1025-exp-v001-t8-lora/resolve/main/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/t8star/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001/resolve/main/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/kirk86413/cinema-h3/resolve/main/Minimax%20H3%E7%9C%9F%E5%AE%9E%E7%94%B5%E5%BD%B1%E8%B4%A8%E6%84%9FV0.1%EF%BC%88%E8%A7%A3%E5%86%B3%E5%BC%A0%E9%87%8F%E6%8A%A5%E9%94%99%EF%BC%89.safetensors"; out = "D:/ComfyUI/models/loras/minimax/MinimaxH3真实电影质感V0.1.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair/resolve/main/Motion_Repair.safetensors"; out = "D:/ComfyUI/models/loras/minimax/Motion_Repair.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Asirus/Minimax-H3-Latent-Upscaler-BF16-MAXQUALITY/resolve/main/minimax_h3_latent_upscaler_3d_fp16.safetensors"; out = "D:/ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Konteni2/Minimax_h3_latent_Upscaler/resolve/main/minimax_h3_latent_upscaler_3d_bf16.safetensors"; out = "D:/ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_bf16.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI/resolve/main/latent_upscaler/h3_upscaler_lms_v0.1.safetensors"; out = "D:/ComfyUI/models/upscale_models/h3_upscaler_lms_v0.1.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors"; out = "D:/ComfyUI/models/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"; out = "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors" }
  [pscustomobject]@{ url = "https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_M.gguf"; out = "D:/ComfyUI/models/LLM/Qwen3.8-27B-Q4_K_M.gguf" }
  [pscustomobject]@{ url = "https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/mmproj-BF16.gguf"; out = "D:/ComfyUI/models/LLM/Qwen3.8-mmproj-BF16.gguf" }
)

if ($Proxy) { $env:HTTPS_PROXY = $Proxy; $env:HTTP_PROXY = $Proxy; "代理: $Proxy" }

function Get-RemoteSize($url) {
  try {
    $head = & curl.exe -sIL --max-time 30 $url 2>$null
    $line = $head | Select-String -Pattern '^content-length:' | Select-Object -Last 1
    if ($line) { return [int64]($line.Line.Split(':')[1].Trim()) }
  } catch { }
  return 0
}

"查远端大小（{0} 个一起查，约 10 秒）..." -f $tasks.Count
$swSize = [Diagnostics.Stopwatch]::StartNew()
$slots = @()
foreach ($t in $tasks) {
  $tmp = [System.IO.Path]::GetTempFileName()
  $pr = Start-Process -FilePath "curl.exe" -ArgumentList @("-sIL", "--max-time", "30", $t.url) -PassThru -NoNewWindow -RedirectStandardOutput $tmp -RedirectStandardError "$tmp.err"
  $slots += [pscustomobject]@{ Task = $t; Proc = $pr; File = $tmp }
}
$totalAll = 0
foreach ($s in $slots) {
  $s.Proc.WaitForExit()
  $size = 0
  try {
    $line = Get-Content $s.File -ErrorAction SilentlyContinue | Select-String -Pattern '^content-length:' | Select-Object -Last 1
    if ($line) { $size = [int64]($line.Line.Split(':')[1].Trim()) }
  } catch { }
  Remove-Item $s.File, "$($s.File).err" -Force -ErrorAction SilentlyContinue
  $s.Task | Add-Member -NotePropertyName total -NotePropertyValue $size -Force
  $totalAll += $size
}
"合计约 {0}（用时 {1:N1}s）" -f (Fmt $totalAll), $swSize.Elapsed.TotalSeconds

if ($DryRun) {
  "计划（并发 $Parallel）："
  foreach ($t in $tasks) { "  {0,10}  {1}" -f (Fmt $t.total), $t.out }
  exit 0
}

function Start-One($t) {
  $a = @("-L", "-C", "-", "--create-dirs", "-sS", "--retry", "2", "--retry-delay", "5", $t.url, "-o", $t.out)
  Start-Process -FilePath "curl.exe" -ArgumentList $a -PassThru -NoNewWindow
}

$queue = [System.Collections.Queue]::new()
$tasks | ForEach-Object { $queue.Enqueue($_) }
$running = @(); $failed = @()
$sw = [Diagnostics.Stopwatch]::StartNew()
$lastTick = 0.0

while ($queue.Count -gt 0 -or $running.Count -gt 0) {
  while ($queue.Count -gt 0 -and $running.Count -lt $Parallel) {
    $t = $queue.Dequeue()
    $base = if (Test-Path $t.out) { (Get-Item $t.out).Length } else { 0 }
    $p = Start-One $t
    $running += [pscustomobject]@{
      Process = $p; Task = $t; Base = $base
      LastSize = $base; LastTime = [double]$sw.Elapsed.TotalSeconds
    }
    "[{0}] 开始  {1}  ({2})" -f (Get-Date -Format "HH:mm:ss"), (Split-Path $t.out -Leaf), (Fmt $t.total)
  }

  Start-Sleep -Milliseconds 1000

  # 每 5 秒打一行进度
  if ($sw.Elapsed.TotalSeconds - $lastTick -ge 5) {
    $lastTick = $sw.Elapsed.TotalSeconds
    foreach ($r in $running) {
      if ($r.Process.HasExited) { continue }
      $size = if (Test-Path $r.Task.out) { (Get-Item $r.Task.out).Length } else { 0 }
      $now = [double]$sw.Elapsed.TotalSeconds
      $dt = [math]::Max($now - $r.LastTime, 0.001)
      $speed = ($size - $r.LastSize) / $dt
      $r.LastSize = $size; $r.LastTime = $now
      $pct = if ($r.Task.total -gt 0) { [math]::Round(100.0 * $size / $r.Task.total, 1) } else { 0 }
      "[{0}] {1,-46} {2,8} / {3,-8} {4,5}%  {5}/s" -f (Get-Date -Format "HH:mm:ss"),
        (Split-Path $r.Task.out -Leaf), (Fmt $size), (Fmt $r.Task.total), $pct, (Fmt ([int64]$speed))
    }
  }

  foreach ($r in @($running)) {
    if (-not $r.Process.HasExited) { continue }
    $code = $r.Process.ExitCode
    $size = if (Test-Path $r.Task.out) { (Get-Item $r.Task.out).Length } else { 0 }
    if ($code -eq 0 -and ($r.Task.total -le 0 -or $size -ge $r.Task.total)) {
      "[{0}] 完成  {1}  ({2})" -f (Get-Date -Format "HH:mm:ss"), (Split-Path $r.Task.out -Leaf), (Fmt $size)
    } else {
      "[{0}] 未完成 {1}  (exit={2}, {3} / {4})" -f (Get-Date -Format "HH:mm:ss"), (Split-Path $r.Task.out -Leaf), $code, (Fmt $size), (Fmt $r.Task.total)
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
    if ($p.ExitCode -ne 0) { "  仍然失败：$($t.out)" } else { "  完成 {0}" -f (Fmt $size) }
  }
}

"全部结束，用时 {0:N1} 分钟" -f $sw.Elapsed.TotalMinutes
"目录：D:\ComfyUI\models"
<# 单文件多连接（更快，需 aria2）：
   winget install aria2.aria2
   aria2c -i download-models-aria2.txt -c -x16 -s16 -k1M -j3 --dir="D:\ComfyUI\models"
#>