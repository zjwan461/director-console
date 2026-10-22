#!/usr/bin/env bash
# 导演台：缺失模型下载（Linux/macOS，curl 多文件并发，带进度）
#
#   ./download-models.sh                          # 默认 3 并发，源 hf-mirror.com
#   ./download-models.sh -p 5                     # 5 并发
#   ./download-models.sh -s hf                    # 走 huggingface.co 官网
#   ./download-models.sh -s hf -x http://127.0.0.1:7897
#   ./download-models.sh -d /root/ComfyUI         # 指定 ComfyUI 目录（默认 /root/ComfyUI）
#   ./download-models.sh -n                       # 只看计划（dry-run）
#
# 说明：
#   - 并发 = 多个文件同时下，每个文件单连接；单文件多连接用 aria2c（见文件末尾）
#   - 每条 curl 都带 -C -：中断后重跑会续传
#   - 失败的会在最后重试一轮
set -uo pipefail
export LC_ALL=C

SOURCE="mirror"
PARALLEL=3
PROXY=""
COMFY_DIR="/root/ComfyUI"
DRYRUN=0

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while getopts "s:p:x:d:nh" opt; do
  case "$opt" in
    s) SOURCE="$OPTARG" ;;
    p) PARALLEL="$OPTARG" ;;
    x) PROXY="$OPTARG" ;;
    d) COMFY_DIR="$OPTARG" ;;
    n) DRYRUN=1 ;;
    h) usage 0 ;;
    *) usage 1 ;;
  esac
done

case "$SOURCE" in
  mirror) BASE="https://hf-mirror.com" ;;
  hf)     BASE="https://huggingface.co" ;;
  http*)  BASE="${SOURCE%/}" ;;
  *) echo "未知来源：$SOURCE（可用 mirror / hf / http://镜像地址）"; exit 1 ;;
esac

command -v curl >/dev/null 2>&1 || { echo "需要 curl"; exit 1; }
[ -d "$COMFY_DIR" ] || echo "[warn] $COMFY_DIR 不存在，仍会按此路径下载（目录会自动创建）"

MODELS_DIR="$COMFY_DIR/models"
CURL_PROXY=()
[ -n "$PROXY" ] && CURL_PROXY=(-x "$PROXY")

# ---------------------------------------------------------------
# 任务表：<仓库内路径>\t<models 下的相对路径>
# ---------------------------------------------------------------
TASKS=$(cat <<'TASKS_EOF'
Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors	loras/minimax/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors	vae/minimax_h3_audio_vae_fp32.safetensors
Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors	vae/minimax_h3_video_vae_fp16.safetensors
Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors	text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
OzzyGT/taeh3/resolve/main/taeh3.safetensors	vae_approx/taeh3.safetensors
Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors	text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors
Kijai/MiniMax-H3-experimental/resolve/main/minimax_h3_video_vae_int8_convrot.safetensors	vae/minimax_h3_video_vae_int8_convrot.safetensors
t8star/Semantic-Bridge-Comfy/resolve/main/models/semantic_bridge/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors	loras/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors
JOKER141/MiniMax-H3-Combat-Base-V2/resolve/main/H3_Combat_V2.safetensors	loras/minimax/H3_Combat_V2.safetensors
RunningHubAI/rh-minimax-h3-fl2v-turbo-4step-v1.2-768p-comfyui-bf16.safetensors-lora/resolve/main/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors	loras/minimax/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors
RunningHubAI/rh-minimax-h3-turbo-4step-10erosmax-test4-pruned-curveproj1025-exp-v001-t8-lora/resolve/main/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors	loras/minimax/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors
t8star/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001/resolve/main/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors	loras/minimax/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors
kirk86413/cinema-h3/resolve/main/Minimax%20H3%E7%9C%9F%E5%AE%9E%E7%94%B5%E5%BD%B1%E8%B4%A8%E6%84%9FV0.1%EF%BC%88%E8%A7%A3%E5%86%B3%E5%BC%A0%E9%87%8F%E6%8A%A5%E9%94%99%EF%BC%89.safetensors	loras/minimax/MinimaxH3真实电影质感V0.1.safetensors
JOKER141/MiniMax-H3-General-Motion-Continuity-Repair/resolve/main/Motion_Repair.safetensors	loras/minimax/Motion_Repair.safetensors
Asirus/Minimax-H3-Latent-Upscaler-BF16-MAXQUALITY/resolve/main/minimax_h3_latent_upscaler_3d_fp16.safetensors	latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16.safetensors
Konteni2/Minimax_h3_latent_Upscaler/resolve/main/minimax_h3_latent_upscaler_3d_bf16.safetensors	latent_upscale_models/minimax_h3_latent_upscaler_3d_bf16.safetensors
Alissonerdx/Minimax-H3-ComfyUI/resolve/main/latent_upscaler/h3_upscaler_lms_v0.1.safetensors	upscale_models/h3_upscaler_lms_v0.1.safetensors
Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors	text_encoders/gemma4_e4b_it_fp8_scaled.safetensors
Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors	loras/minimax/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors
unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_M.gguf	LLM/Qwen3.8-27B-Q4_K_M.gguf
unsloth/Qwen3.8-27B-GGUF/resolve/main/mmproj-BF16.gguf	LLM/Qwen3.8-mmproj-BF16.gguf
TASKS_EOF
)

fmt() { awk -v b="$1" 'BEGIN{ if (b>=1073741824) printf "%.2f GB", b/1073741824; else if (b>=1048576) printf "%.0f MB", b/1048576; else printf "%.0f KB", b/1024 }'; }

# 读任务到数组
T_PATH=(); T_REL=()
while IFS=$'\t' read -r p r; do
  [ -z "$p" ] && continue
  T_PATH+=("$p"); T_REL+=("$r")
done <<< "$TASKS"
N=${#T_REL[@]}

echo "来源：$BASE"
echo "目标：$MODELS_DIR"
echo "任务：$N 个文件"

# ---- 并发查远端大小（算百分比要用）----
T_TOT=()
declare -A _SZPID=()
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT
i=0
while [ $i -lt $N ]; do
  ( curl -sIL --max-time 30 "${CURL_PROXY[@]}" "$BASE/${T_PATH[$i]}" > "$tmpdir/$i.h" 2>/dev/null ) &
  _SZPID[$i]=$!
  i=$((i+1))
  if [ $((i % 8)) -eq 0 ]; then wait; fi
done
wait
i=0; total_all=0
while [ $i -lt $N ]; do
  sz=$(grep -i '^content-length:' "$tmpdir/$i.h" 2>/dev/null | tail -n1 | tr -d '\r' | awk '{print $2}')
  case "$sz" in ''|*[!0-9]*) sz=0 ;; esac
  T_TOT+=("$sz")
  total_all=$((total_all + sz))
  i=$((i+1))
done
echo "合计约 $(fmt "$total_all")"

if [ "$DRYRUN" -eq 1 ]; then
  echo "计划（并发 $PARALLEL）："
  i=0
  while [ $i -lt $N ]; do
    printf '  %10s  %s\n' "$(fmt "${T_TOT[$i]}")" "$MODELS_DIR/${T_REL[$i]}"
    i=$((i+1))
  done
  exit 0
fi

# ---------------------------------------------------------------
# 下载（并发 + 每 5 秒一行进度）
# ---------------------------------------------------------------
declare -A RUN_PID=() RUN_LAST=() RUN_TIME=()
next=0; failed=(); start_ts=$(date +%s); last_tick=0

start_one() {
  local idx=$1
  local out="$MODELS_DIR/${T_REL[$idx]}"
  mkdir -p "$(dirname "$out")"
  curl -L -C - --create-dirs -sS --retry 2 --retry-delay 5 "${CURL_PROXY[@]}" \
       "$BASE/${T_PATH[$idx]}" -o "$out" &
  RUN_PID[$idx]=$!
  RUN_LAST[$idx]=$(stat -c%s "$out" 2>/dev/null || echo 0)
  RUN_TIME[$idx]=$(date +%s)
  echo "[$(date +%H:%M:%S)] 开始  ${T_REL[$idx]##*/}  ($(fmt "${T_TOT[$idx]}"))"
}

while :; do
  while [ "${#RUN_PID[@]}" -lt "$PARALLEL" ] && [ $next -lt $N ]; do
    start_one $next
    next=$((next+1))
  done

  now=$(date +%s)
  if [ $((now - last_tick)) -ge 5 ]; then
    last_tick=$now
    for idx in "${!RUN_PID[@]}"; do
      out="$MODELS_DIR/${T_REL[$idx]}"
      sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
      dt=$(( now - ${RUN_TIME[$idx]} ))
      [ $dt -le 0 ] && dt=1
      spd=$(( (sz - ${RUN_LAST[$idx]}) / dt ))
      RUN_LAST[$idx]=$sz; RUN_TIME[$idx]=$now
      tot=${T_TOT[$idx]}
      pct=$(awk -v s="$sz" -v t="$tot" 'BEGIN{ if (t>0) printf "%.1f", 100*s/t; else printf "?" }')
      printf '[%s] %-46s %8s / %-8s %6s%%  %s/s\n' \
        "$(date +%H:%M:%S)" "${T_REL[$idx]##*/}" "$(fmt "$sz")" "$(fmt "$tot")" "$pct" "$(fmt "$spd")"
    done
  fi

  done_count=0
  for idx in "${!RUN_PID[@]}"; do
    if kill -0 "${RUN_PID[$idx]}" 2>/dev/null; then
      done_count=$((done_count+1))
      continue
    fi
    wait "${RUN_PID[$idx]}" 2>/dev/null; code=$?
    out="$MODELS_DIR/${T_REL[$idx]}"
    sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
    tot=${T_TOT[$idx]}
    if [ "$code" -eq 0 ] && { [ "$tot" -le 0 ] || [ "$sz" -ge "$tot" ]; }; then
      echo "[$(date +%H:%M:%S)] 完成  ${T_REL[$idx]##*/}  ($(fmt "$sz"))"
    else
      echo "[$(date +%H:%M:%S)] 未完成 ${T_REL[$idx]##*/}  (exit=$code, $(fmt "$sz") / $(fmt "$tot"))"
      failed+=("$idx")
    fi
    unset "RUN_PID[$idx]" "RUN_LAST[$idx]" "RUN_TIME[$idx]"
  done

  if [ "${#RUN_PID[@]}" -eq 0 ] && [ $next -ge $N ]; then break; fi
  sleep 1
done

if [ ${#failed[@]} -gt 0 ]; then
  echo "---- 重试 ${#failed[@]} 个（续传）----"
  for idx in "${failed[@]}"; do
    out="$MODELS_DIR/${T_REL[$idx]}"
    echo "[$(date +%H:%M:%S)] 重试  ${T_REL[$idx]##*/}"
    curl -L -C - --create-dirs -sS --retry 2 "${CURL_PROXY[@]}" "$BASE/${T_PATH[$idx]}" -o "$out" &
    wait $!
    code=$?
    sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
    if [ "$code" -ne 0 ]; then echo "  仍然失败：$out"; else echo "  完成 $(fmt "$sz")"; fi
  done
fi

echo "全部结束，用时 $(( ($(date +%s) - start_ts) / 60 )) 分钟"
echo "目录：$MODELS_DIR"

# 单文件多连接（更快，需 aria2c）：
#   aria2c -c -x16 -s16 -k1M -j3 --dir="$MODELS_DIR" -i download-models-aria2.txt