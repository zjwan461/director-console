#!/usr/bin/env bash
# 导演台：缺失模型下载（Linux/macOS，多文件并发 + sha256 校验）
#
#   ./download-models.sh                          # 默认 3 并发，源 hf-mirror.com
#   ./download-models.sh -p 5                     # 5 并发
#   ./download-models.sh -s hf                    # 走 huggingface.co 官网
#   ./download-models.sh -s hf -x http://127.0.0.1:7897
#   ./download-models.sh -d /root/ComfyUI         # 指定 ComfyUI 目录（默认 /root/ComfyUI）
#   ./download-models.sh -k                       # 跳过 sha256（默认校验）
#   ./download-models.sh -n                       # 只看计划（dry-run）
#
# 说明：
#   - 并发 = 多个文件同时下，每个文件单连接；单文件多连接用 aria2c（见文件末尾）
#   - 每条 curl 带 -C -：中断后重跑会续传
#   - 下完逐个校验：大小 + sha256（sha256 来自 HF 的 X-Linked-ETag）；不符会删掉重下
#   - 失败的会在最后重试一轮
set -uo pipefail
export LC_ALL=C

SOURCE="mirror"
PARALLEL=3
PROXY=""
COMFY_DIR="/root/ComfyUI"
DRYRUN=0
NOHASH=0

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while getopts "s:p:x:d:knh" opt; do
  case "$opt" in
    s) SOURCE="$OPTARG" ;;
    p) PARALLEL="$OPTARG" ;;
    x) PROXY="$OPTARG" ;;
    d) COMFY_DIR="$OPTARG" ;;
    k) NOHASH=1 ;;
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

# 单实例锁：两个下载器同时写同一个文件会互相覆盖（-C - 各自算偏移）
LOCK="$(cd "$(dirname "$0")" && pwd)/.download-models.lock"
if [ -e "$LOCK" ]; then
  OLD=$(cat "$LOCK" 2>/dev/null || echo "")
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    echo "另一个下载进程还在跑（PID $OLD），先停掉它：kill $OLD"
    exit 1
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
command -v sha256sum >/dev/null 2>&1 || NOHASH=1

MODELS_DIR="$COMFY_DIR/models"
CURL_PROXY=()
[ -n "$PROXY" ] && CURL_PROXY=(-x "$PROXY")

# ---------------------------------------------------------------
# 任务表：<仓库内路径>\t<models 下相对路径>\t<字节数>\t<sha256>
# ---------------------------------------------------------------
TASKS=$(cat <<'TASKS_EOF'
Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors	loras/minimax/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors	1956193000	2339acdf19bfe123f46b971ea35d367a84adb85de43627e1eceafa5a5b2b111e
Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors	vae/minimax_h3_audio_vae_fp32.safetensors	605254808	8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48
Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors	vae/minimax_h3_video_vae_fp16.safetensors	5207808496	7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522
Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors	text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors	15687142551	35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6
OzzyGT/taeh3/resolve/main/taeh3.safetensors	vae_approx/taeh3.safetensors	22709752	4fd022bfcab08772fe0536b17ea1a3bbb5625be11e397868d1c5d891863d4c13
Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors	text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors	27141342152	bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923
Kijai/MiniMax-H3-experimental/resolve/main/minimax_h3_video_vae_int8_convrot.safetensors	vae/minimax_h3_video_vae_int8_convrot.safetensors	3171670912	9bb2d96f218c76babd85e0611b85ca8fb330a90546c01a0005e8a58a59593410
t8star/Semantic-Bridge-Comfy/resolve/main/models/semantic_bridge/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors	loras/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors	11024432	896829a178e89e23f35799d403971b19b10bbacb2da00454c576770b2f58a9b1
JOKER141/MiniMax-H3-Combat-Base-V2/resolve/main/H3_Combat_V2.safetensors	loras/minimax/H3_Combat_V2.safetensors	155110280	5b3edb09e9d6029439badf9bc9db4ba4a355ae679b0810888de82c4793c0bac8
RunningHubAI/rh-minimax-h3-fl2v-turbo-4step-v1.2-768p-comfyui-bf16.safetensors-lora/resolve/main/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors	loras/minimax/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors	1956193000	c8168ebc17bbacc4296103dda2fec1ba85b24392fa08cf2bfbcef0cff0dc3cc8
RunningHubAI/rh-minimax-h3-turbo-4step-10erosmax-test4-pruned-curveproj1025-exp-v001-t8-lora/resolve/main/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors	loras/minimax/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors	794888696	6c2f38d45dfa3fc282a48de3171b6946a5e6d46e13f832c43b93734f6d12edf5
t8star/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001/resolve/main/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors	loras/minimax/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors	794888704	a117f18682a22a0381cadd9832da0afe9912f604305b3e44310b5aa1919734cc
kirk86413/cinema-h3/resolve/main/Minimax%20H3%E7%9C%9F%E5%AE%9E%E7%94%B5%E5%BD%B1%E8%B4%A8%E6%84%9FV0.1%EF%BC%88%E8%A7%A3%E5%86%B3%E5%BC%A0%E9%87%8F%E6%8A%A5%E9%94%99%EF%BC%89.safetensors	loras/minimax/MinimaxH3真实电影质感V0.1.safetensors	155110448	cd9ef1ebb1ab9221492dc09f069de364fff1454fdcae76902754d07db6e58dcd
JOKER141/MiniMax-H3-General-Motion-Continuity-Repair/resolve/main/Motion_Repair.safetensors	loras/minimax/Motion_Repair.safetensors	155110272	a678a3657cefd5c2c2712f892da2f71be53c3f252e335557e918854f8abc579f
Asirus/Minimax-H3-Latent-Upscaler-BF16-MAXQUALITY/resolve/main/minimax_h3_latent_upscaler_3d_fp16.safetensors	latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16.safetensors	690592672	043e5a48e161610ef6c3ea974645220354d06fa618abca15f76d084812eb55c2
Konteni2/Minimax_h3_latent_Upscaler/resolve/main/minimax_h3_latent_upscaler_3d_bf16.safetensors	latent_upscale_models/minimax_h3_latent_upscaler_3d_bf16.safetensors	690592992	4f57821f5837f32f7142b67d815606dbd7550f194e5c769f7d6c3f83b146a5e6
Alissonerdx/Minimax-H3-ComfyUI/resolve/main/latent_upscaler/h3_upscaler_lms_v0.1.safetensors	upscale_models/h3_upscaler_lms_v0.1.safetensors	690593048	40d4228227146245ef2b65480b647c50222465ca125de5880f192e3259e40d59
Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors	text_encoders/gemma4_e4b_it_fp8_scaled.safetensors	9057782194	bf0b4fa2e41a25684dc9e9b256cd505564f02fed09be3da95ce024e653e2c52b
Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors	loras/minimax/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors	1956192992	c396a9a06f58399e9df9754b18299818d84a2ddd371724ba48fe4a41221437dc
unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_M.gguf	LLM/Qwen3.8-27B-Q4_K_M.gguf	16464440224	322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482
unsloth/Qwen3.8-27B-GGUF/resolve/main/mmproj-BF16.gguf	LLM/Qwen3.8-mmproj-BF16.gguf	931146432	83ee4f4f205fa514161778c41df1ea14144faa0f713510893b63c2395f5c2d53
TASKS_EOF
)

fmt() { awk -v b="$1" 'BEGIN{ if (b>=1073741824) printf "%.2f GB", b/1073741824; else if (b>=1048576) printf "%.0f MB", b/1048576; else printf "%.0f KB", b/1024 }'; }

T_PATH=(); T_REL=(); T_TOT=(); T_SHA=()
while IFS=$'\t' read -r p r sz sh; do
  [ -z "$p" ] && continue
  T_PATH+=("$p"); T_REL+=("$r"); T_TOT+=("${sz:-0}"); T_SHA+=("${sh:-}")
done <<< "$TASKS"
N=${#T_REL[@]}

total_all=0
for v in "${T_TOT[@]}"; do total_all=$((total_all + v)); done

echo "来源：$BASE"
echo "目标：$MODELS_DIR"
echo "任务：$N 个文件，合计约 $(fmt "$total_all")"
[ "$NOHASH" -eq 0 ] && echo "校验：大小 + sha256" || echo "校验：只比大小（-k 或没有 sha256sum）"

if [ "$DRYRUN" -eq 1 ]; then
  echo "计划（并发 $PARALLEL）："
  i=0
  while [ $i -lt $N ]; do
    printf '  %10s  %s\n' "$(fmt "${T_TOT[$i]}")" "$MODELS_DIR/${T_REL[$i]}"
    i=$((i+1))
  done
  exit 0
fi

# 校验一个文件；成功返回 0。内容坏了会删掉，让重试从头下
verify_one() {
  local idx=$1
  local out="$MODELS_DIR/${T_REL[$idx]}" tot="${T_TOT[$idx]}" want="${T_SHA[$idx]}"
  local sz; sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
  if [ "$tot" -gt 0 ] && [ "$sz" -ne "$tot" ]; then
    echo "    大小不符：$(fmt "$sz") / $(fmt "$tot")"
    return 1
  fi
  if [ "$NOHASH" -eq 0 ] && [ -n "$want" ]; then
    local got; got=$(sha256sum "$out" | awk '{print $1}')
    if [ "$got" != "$want" ]; then
      echo "    sha256 不符，删掉重下"
      echo "      got  $got"
      echo "      want $want"
      rm -f "$out"
      return 1
    fi
    echo "    sha256 OK"
  fi
  return 0
}

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
      dt=$(( now - ${RUN_TIME[$idx]} )) ; [ $dt -le 0 ] && dt=1
      spd=$(( (sz - ${RUN_LAST[$idx]}) / dt ))
      RUN_LAST[$idx]=$sz; RUN_TIME[$idx]=$now
      tot=${T_TOT[$idx]}
      pct=$(awk -v s="$sz" -v t="$tot" 'BEGIN{ if (t>0) printf "%.1f", 100*s/t; else printf "?" }')
      printf '[%s] %-46s %8s / %-8s %6s%%  %s/s\n' \
        "$(date +%H:%M:%S)" "${T_REL[$idx]##*/}" "$(fmt "$sz")" "$(fmt "$tot")" "$pct" "$(fmt "$spd")"
    done
  fi

  for idx in "${!RUN_PID[@]}"; do
    if kill -0 "${RUN_PID[$idx]}" 2>/dev/null; then continue; fi
    wait "${RUN_PID[$idx]}" 2>/dev/null; code=$?
    out="$MODELS_DIR/${T_REL[$idx]}"
    sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
    if [ "$code" -eq 0 ] && verify_one "$idx"; then
      echo "[$(date +%H:%M:%S)] 完成  ${T_REL[$idx]##*/}  ($(fmt "$sz"))"
    else
      echo "[$(date +%H:%M:%S)] 未完成 ${T_REL[$idx]##*/}  (exit=$code, $(fmt "$sz") / $(fmt "${T_TOT[$idx]}"))"
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
    curl -L -C - --create-dirs -sS --retry 2 "${CURL_PROXY[@]}" "$BASE/${T_PATH[$idx]}" -o "$out"
    if [ $? -eq 0 ] && verify_one "$idx"; then
      echo "    完成 $(fmt "$(stat -c%s "$out" 2>/dev/null || echo 0)")"
    else
      echo "    仍然失败：$out"
    fi
  done
fi

echo "全部结束，用时 $(( ($(date +%s) - start_ts) / 60 )) 分钟"
echo "目录：$MODELS_DIR"

# 单文件多连接（更快，需 aria2c；清单里已带 checksum）：
#   aria2c -c -x16 -s16 -k1M -j3 --dir="$MODELS_DIR" -i download-models-aria2.txt