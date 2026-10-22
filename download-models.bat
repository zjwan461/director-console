@echo off
chcp 65001 >nul
rem ============================================================
rem 导演台：21 个缺失模型（55 处引用）的顺序下载
rem 源：https://hf-mirror.com    支持断点续传，可反复执行
rem 想并行/走代理，用 download-models.ps1
rem ============================================================

rem ---- loras (9) ----
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors" -o "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/t8star/Semantic-Bridge-Comfy/resolve/main/models/semantic_bridge/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors" -o "D:/ComfyUI/models/loras/t8_compat/MiniMaxH3_SemanticBridge_v1_T8_Compat.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/JOKER141/MiniMax-H3-Combat-Base-V2/resolve/main/H3_Combat_V2.safetensors" -o "D:/ComfyUI/models/loras/minimax/H3_Combat_V2.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/RunningHubAI/rh-minimax-h3-fl2v-turbo-4step-v1.2-768p-comfyui-bf16.safetensors-lora/resolve/main/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors" -o "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/RunningHubAI/rh-minimax-h3-turbo-4step-10erosmax-test4-pruned-curveproj1025-exp-v001-t8-lora/resolve/main/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors" -o "D:/ComfyUI/models/loras/minimax/minimax_h3_turbo_4step_10ErosMax_test4_pruned_curveproj1025_exp_v001-T8.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/t8star/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001/resolve/main/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors" -o "D:/ComfyUI/models/loras/minimax/minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/kirk86413/cinema-h3/resolve/main/Minimax%20H3%E7%9C%9F%E5%AE%9E%E7%94%B5%E5%BD%B1%E8%B4%A8%E6%84%9FV0.1%EF%BC%88%E8%A7%A3%E5%86%B3%E5%BC%A0%E9%87%8F%E6%8A%A5%E9%94%99%EF%BC%89.safetensors" -o "D:/ComfyUI/models/loras/minimax/MinimaxH3真实电影质感V0.1.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair/resolve/main/Motion_Repair.safetensors" -o "D:/ComfyUI/models/loras/minimax/Motion_Repair.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors" -o "D:/ComfyUI/models/loras/minimax/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"

rem ---- text_encoders (3) ----
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" -o "D:/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors" -o "D:/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors" -o "D:/ComfyUI/models/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors"

rem ---- vae (3) ----
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors" -o "D:/ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors" -o "D:/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Kijai/MiniMax-H3-experimental/resolve/main/minimax_h3_video_vae_int8_convrot.safetensors" -o "D:/ComfyUI/models/vae/minimax_h3_video_vae_int8_convrot.safetensors"

rem ---- vae_approx () ----
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/OzzyGT/taeh3/resolve/main/taeh3.safetensors" -o "D:/ComfyUI/models/vae_approx/taeh3.safetensors"

rem ---- latent_upscale_models (2) ----
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Asirus/Minimax-H3-Latent-Upscaler-BF16-MAXQUALITY/resolve/main/minimax_h3_latent_upscaler_3d_fp16.safetensors" -o "D:/ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16.safetensors"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Konteni2/Minimax_h3_latent_Upscaler/resolve/main/minimax_h3_latent_upscaler_3d_bf16.safetensors" -o "D:/ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_bf16.safetensors"

rem ---- upscale_models () ----
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/Alissonerdx/Minimax-H3-ComfyUI/resolve/main/latent_upscaler/h3_upscaler_lms_v0.1.safetensors" -o "D:/ComfyUI/models/upscale_models/h3_upscaler_lms_v0.1.safetensors"

rem ---- LLM (2) ----
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_M.gguf" -o "D:/ComfyUI/models/LLM/Qwen3.8-27B-Q4_K_M.gguf"
curl.exe -L -C - --create-dirs -sS --retry 2 "https://hf-mirror.com/unsloth/Qwen3.8-27B-GGUF/resolve/main/mmproj-BF16.gguf" -o "D:/ComfyUI/models/LLM/Qwen3.8-mmproj-BF16.gguf"

echo.
echo 下载结束。
pause