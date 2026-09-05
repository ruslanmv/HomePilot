// GENERATED FILE — DO NOT EDIT.
//
// Written by scripts/generate-model-catalog.mjs from backend/app/model_catalog_data.json,
// which is the single source of truth for HomePilot's model catalog (batch V7).
//
// To change what appears here, edit the backend JSON and run:
//     node scripts/generate-model-catalog.mjs
//
// `modelCatalog.generated.test.ts` fails if this file and the JSON have drifted apart. That
// test is what stops the two lists separating again, which is what happened to the hand-written
// copy this file replaced.
//
// Catalog version: "1.0.0"   Entries: 135

export type GeneratedCatalogEntry = {
    id: string;
    label?: string;
    description?: string;
    recommended?: boolean;
    recommended_nsfw?: boolean;
    recommended_expert?: boolean;
    expert_hint?: string;
    protected?: boolean;
    nsfw?: boolean;
    size_gb?: number;
    resolution?: string;
    frames?: number;
    civitai_url?: string;
    civitai_version_id?: string;
    install?: Record<string, unknown>;
    provides_nodes?: string[];
    requires?: unknown;
    /** What this vision model can take. Populated only where it has been measured (V8). */
    vision_input?: {
        max_long_edge?: number;
        max_megapixels?: number;
        preferred_mime?: string;
        supports_multiple_images?: boolean;
        strategy?: string;
    };
};

export const GENERATED_CATALOG_VERSION = "1.0.0";

export const GENERATED_CATALOGS: Record<string, Record<string, GeneratedCatalogEntry[]>> =
{
    "ollama": {
        "chat": [
            {
                "id": "llama3:8b",
                "label": "Llama 3 8B",
                "description": "Fast, efficient 8B parameter model. Great for general-purpose tasks.",
                "recommended": true,
                "protected": true,
                "size_gb": 4.7
            },
            {
                "id": "llama3:70b",
                "label": "Llama 3 70B",
                "description": "High-quality 70B parameter model. Excellent reasoning and coding.",
                "size_gb": 40
            },
            {
                "id": "llama3.1",
                "label": "Llama 3.1 (8B)",
                "description": "Fast general-purpose chat model. Standard smart assistant baseline.",
                "recommended": true,
                "size_gb": 4.7
            },
            {
                "id": "llama3.1:70b",
                "label": "Llama 3.1 70B",
                "description": "Latest 70B model with 128K context window.",
                "size_gb": 40
            },
            {
                "id": "llama3.2",
                "label": "Llama 3.2 (3B)",
                "description": "Very fast, lightweight model for low-latency voice.",
                "recommended": true,
                "recommended_expert": true,
                "expert_hint": "Ultra-fast 3B for Expert 'Fast' mode. Runs on almost any GPU.",
                "size_gb": 2
            },
            {
                "id": "mistral:7b",
                "label": "Mistral 7B",
                "description": "Efficient 7B model from Mistral AI.",
                "size_gb": 4.1
            },
            {
                "id": "mistral-nemo",
                "label": "Mistral Nemo (12B)",
                "description": "Balanced quality; good instruction following. Best 'Smart' model for 12GB.",
                "recommended": true,
                "recommended_expert": true,
                "expert_hint": "Balanced 12B; Expert 'Heavy' mode fits 12 GB VRAM at Q4.",
                "size_gb": 7
            },
            {
                "id": "mixtral:8x7b",
                "label": "Mixtral 8x7B",
                "description": "Mixture of Experts model with excellent performance.",
                "size_gb": 26
            },
            {
                "id": "qwen2.5",
                "label": "Qwen 2.5 (7B)",
                "description": "Fast and capable general model with strong multilingual support.",
                "recommended": true,
                "recommended_expert": true,
                "expert_hint": "Fast capable 7B. Solid Expert Fast/Expert default; ~4.7 GB VRAM.",
                "size_gb": 4
            },
            {
                "id": "gemma2",
                "label": "Gemma 2 (9B)",
                "description": "Strong for writing, creative prose and tone.",
                "size_gb": 5.5
            },
            {
                "id": "phi3:3.8b",
                "label": "Phi-3 3.8B",
                "description": "Microsoft's compact model with strong reasoning.",
                "size_gb": 2.3
            },
            {
                "id": "phi4",
                "label": "Phi-4 (14B)",
                "description": "Logic-heavy model from Microsoft; may be slower in voice.",
                "recommended_expert": true,
                "expert_hint": "14B logic-heavy reasoning from Microsoft. Great for Expert 'Think'.",
                "size_gb": 8
            },
            {
                "id": "deepseek-r1:latest",
                "label": "DeepSeek R1 (7B)",
                "description": "Thinking model with chain-of-thought reasoning. Needs 300 tokens for voice.",
                "recommended_expert": true,
                "expert_hint": "7B chain-of-thought reasoning — ideal Expert 'Think' model at 12 GB.",
                "size_gb": 4.7
            },
            {
                "id": "deepseek-r1:32b",
                "label": "DeepSeek R1 (32B)",
                "description": "Top-tier chain-of-thought reasoning. Best Expert 'Think'/'Heavy' quality when VRAM allows.",
                "recommended_expert": true,
                "expert_hint": "32B top-tier reasoning. Needs ~20 GB VRAM — save for cloud / large-GPU deploys.",
                "size_gb": 20
            },
            {
                "id": "dolphin3",
                "label": "Dolphin 3.0 (8B)",
                "description": "Latest Dolphin on Llama 3.1. Uncensored, coding, math, function calling.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "dolphin-llama3",
                "label": "Dolphin Llama 3 (8B)",
                "description": "Dolphin 2.9 based on Llama 3. Uncensored chat & coding.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "dolphin-mistral",
                "label": "Dolphin Mistral (7B)",
                "description": "Fast uncensored Dolphin on Mistral 2.8. Reliable for voice.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.1
            },
            {
                "id": "dolphin-mixtral:8x7b",
                "label": "Dolphin Mixtral (8x7B MoE)",
                "description": "Powerful MoE for coding. Needs ~26GB RAM but fits 12GB VRAM.",
                "nsfw": true,
                "size_gb": 26
            },
            {
                "id": "hermes3",
                "label": "Hermes 3 (8B)",
                "description": "Best for roleplay & creative writing. Coherent long-form outputs.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "solar",
                "label": "Solar (10.7B)",
                "description": "Good mid-sized uncensored chat model. Test latency for voice.",
                "nsfw": true,
                "size_gb": 6.5
            },
            {
                "id": "wizardlm2",
                "label": "WizardLM2 (7B)",
                "description": "Solid uncensored chat model. Validate voice pacing.",
                "nsfw": true,
                "size_gb": 4
            },
            {
                "id": "llama2-uncensored",
                "label": "Llama 2 Uncensored (7B)",
                "description": "Original uncensored Llama 2. Lightweight & fast.",
                "nsfw": true,
                "size_gb": 3.8
            },
            {
                "id": "wizardlm-uncensored",
                "label": "WizardLM Uncensored (13B)",
                "description": "Eric Hartford's WizardLM uncensored. Good for chat.",
                "nsfw": true,
                "size_gb": 7.4
            },
            {
                "id": "wizard-vicuna-uncensored",
                "label": "Wizard Vicuna Uncensored (7B)",
                "description": "Hartford classic. Great for natural conversations.",
                "nsfw": true,
                "size_gb": 3.8
            },
            {
                "id": "mannix/llama3.1-8b-abliterated",
                "label": "Llama 3.1 Abliterated (8B)",
                "description": "Llama 3.1 with safety brakes removed via abliteration.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "mannix/dolphin-2.9-llama3-8b",
                "label": "Dolphin 2.9 Llama 3 (8B)",
                "description": "Dolphin 2.9 on Llama 3 by Mannix.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/qwen3-abliterated",
                "label": "Qwen3 Abliterated",
                "description": "Qwen3 abliterated. Highly recommended for uncensored use.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/qwen3-abliterated:8b",
                "label": "Qwen3 Abliterated (8B)",
                "description": "8B version. Best balance of speed and quality.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/qwen3-abliterated:4b",
                "label": "Qwen3 Abliterated (4B)",
                "description": "4B version. Super fast for voice applications.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 2.5
            },
            {
                "id": "huihui_ai/qwen3-coder-abliterated",
                "label": "Qwen3 Coder Abliterated",
                "description": "Best uncensored coder. Abliterated Qwen3 for code.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/qwen3-next-abliterated",
                "label": "Qwen3-Next Abliterated",
                "description": "Latest Qwen3-Next with abliteration.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/dolphin3-abliterated",
                "label": "Dolphin 3 Abliterated (8B)",
                "description": "Dolphin 3.0 + abliteration = Maximum compliance.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/huihui-moe-abliterated",
                "label": "Huihui MoE Abliterated",
                "description": "MoE architecture for efficient inference. Abliterated.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/gpt-oss-abliterated",
                "label": "GPT-OSS Abliterated",
                "description": "OpenAI's GPT-OSS abliterated (experimental).",
                "nsfw": true,
                "size_gb": 12
            },
            {
                "id": "goekdenizguelmez/JOSIEFIED-Qwen3",
                "label": "JOSIEFIED Qwen3",
                "description": "BEST OVERALL. 10/10 UGI Adherence. Abliterated + fine-tuned.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "goekdenizguelmez/JOSIEFIED-Qwen3:8b",
                "label": "JOSIEFIED Qwen3 (8B)",
                "description": "#1 Pick. Best coherence + uncensored for 12GB VRAM.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "goekdenizguelmez/JOSIEFIED-Qwen2.5",
                "label": "JOSIEFIED Qwen2.5",
                "description": "Qwen2.5 JOSIEFIED. Abliterated + fine-tuned for coherence.",
                "nsfw": true,
                "size_gb": 4
            },
            {
                "id": "goekdenizguelmez/JOSIEFIED-Qwen2.5:7b",
                "label": "JOSIEFIED Qwen2.5 (7B)",
                "description": "Fast 7B uncensored. Great for voice latency.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4
            },
            {
                "id": "goekdenizguelmez/JOSIEFIED-Qwen2.5:14b",
                "label": "JOSIEFIED Qwen2.5 (14B)",
                "description": "Best quality 14B. Fits 12GB with Q4 quantization.",
                "nsfw": true,
                "size_gb": 8
            },
            {
                "id": "goekdenizguelmez/JOSIEFIED-Qwen2.5:3b",
                "label": "JOSIEFIED Qwen2.5 (3B)",
                "description": "Ultra fast 3B. Minimal VRAM, great for voice.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 1.8
            },
            {
                "id": "huihui_ai/qwen3-vl-abliterated:8b-instruct",
                "label": "Qwen3 Vision Abliterated (8B)",
                "description": "Vision-Language abliterated. Analyzes any image without restrictions.",
                "nsfw": true,
                "size_gb": 5
            },
            {
                "id": "yarn-mistral",
                "label": "Yarn Mistral (7B)",
                "description": "Extended context uncensored Mistral variant.",
                "nsfw": true,
                "size_gb": 4.1
            },
            {
                "id": "openhermes",
                "label": "OpenHermes (7B)",
                "description": "Uncensored Hermes variant. Good general chat.",
                "nsfw": true,
                "size_gb": 4.1
            },
            {
                "id": "neural-chat",
                "label": "Neural Chat (7B)",
                "description": "Intel's uncensored chat model. Good conversational flow.",
                "nsfw": true,
                "size_gb": 4.1
            },
            {
                "id": "huihui_ai/llama3.2-abliterate:3b",
                "label": "Llama 3.2 Abliterated (3B)",
                "description": "Fast 3B Llama abliterated. Ultra-lightweight for voice.",
                "nsfw": true,
                "size_gb": 2
            },
            {
                "id": "huihui_ai/gemma3-abliterated",
                "label": "Gemma 3 Abliterated",
                "description": "Google Gemma 3 with abliteration. Good writing quality.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/deepseek-r1-abliterated:8b",
                "label": "DeepSeek R1 Abliterated (8B)",
                "description": "DeepSeek R1 thinking + uncensored. Chain-of-thought without filters.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "huihui_ai/deepseek-r1-abliterated:14b",
                "label": "DeepSeek R1 Abliterated (14B)",
                "description": "Larger DeepSeek R1 abliterated. Better reasoning, needs more VRAM.",
                "recommended_expert": true,
                "expert_hint": "14B uncensored reasoning. Tightest on 12 GB but the best quality.",
                "nsfw": true,
                "size_gb": 8
            },
            {
                "id": "huihui_ai/deepseek-r1-abliterated:1.5b",
                "label": "DeepSeek R1 Abliterated (1.5B)",
                "description": "Tiny fast DeepSeek R1 abliterated. Minimal VRAM.",
                "nsfw": true,
                "size_gb": 1
            },
            {
                "id": "dolphincoder",
                "label": "Dolphin Coder (7B)",
                "description": "Uncensored coding model based on CodeLlama. No content filters on code.",
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "goekdenizguelmez/JOSIEFIED-Llama",
                "label": "JOSIEFIED Llama",
                "description": "JOSIEFIED Llama series. Abliterated + fine-tuned for coherence.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.7
            },
            {
                "id": "samantha-mistral",
                "label": "Samantha Mistral (7B)",
                "description": "Uncensored companion model. Warm, conversational personality.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4.1
            }
        ],
        "multimodal": [
            {
                "id": "moondream",
                "label": "Moondream",
                "description": "Ultra-light vision captioning + OCR. Instant responses, minimal RAM.",
                "recommended": true,
                "size_gb": 1.6
            },
            {
                "id": "gemma3:4b",
                "label": "Gemma 3 Vision (4B)",
                "description": "Best overall edge multimodal model. Fast, accurate image understanding.",
                "recommended": true,
                "size_gb": 3
            },
            {
                "id": "llava:7b",
                "label": "LLaVA 1.6 (7B)",
                "description": "Strong general-purpose vision model. Good balance of quality and speed.",
                "recommended": true,
                "size_gb": 4.7
            },
            {
                "id": "minicpm-v:latest",
                "label": "MiniCPM-V 2.6",
                "description": "Strong multi-image reasoning. Good for documents and charts.",
                "size_gb": 5
            },
            {
                "id": "llama3.2-vision:11b",
                "label": "Llama 3.2 Vision (11B)",
                "description": "Best reasoning near the RAM limit. High-quality image understanding.",
                "size_gb": 7
            },
            {
                "id": "huihui_ai/qwen3-vl-abliterated:8b-instruct",
                "label": "Qwen3-VL Abliterated (8B)",
                "description": "Vision-Language abliterated. Unfiltered image descriptions without restrictions.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 5
            },
            {
                "id": "qwen2.5vl:7b",
                "label": "Qwen2.5-VL (7B)",
                "description": "Flagship vision-language model with strong OCR and chart understanding.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 6
            },
            {
                "id": "bakllava:latest",
                "label": "BakLLaVA (7B)",
                "description": "Lightweight multimodal fallback model for broad compatibility.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 4
            },
            {
                "id": "internvl3:8b",
                "label": "InternVL3 (8B)",
                "description": "Detailed scene analysis.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 7
            },
            {
                "id": "smolvlm2:latest",
                "label": "SmolVLM2 (2.2B)",
                "description": "Fast unrestricted captioning.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 2
            }
        ]
    },
    "comfyui": {
        "image": [
            {
                "id": "sd_xl_base_1.0.safetensors",
                "label": "SDXL Base 1.0",
                "description": "Stable Diffusion XL base model. Best balance of quality and speed.",
                "recommended": true,
                "protected": true,
                "nsfw": false,
                "size_gb": 6.94,
                "resolution": "1024x1024"
            },
            {
                "id": "flux1-schnell.safetensors",
                "label": "Flux.1 Schnell",
                "description": "Fast Flux model optimized for speed. 4-step generation. Note: Requires additional files (CLIP, VAE).",
                "protected": true,
                "nsfw": false,
                "size_gb": 23.8,
                "resolution": "1024x1024"
            },
            {
                "id": "flux1-dev.safetensors",
                "label": "Flux.1 Dev",
                "description": "High-quality Flux model for detailed generations. Note: Requires additional files (CLIP, VAE).",
                "nsfw": false,
                "size_gb": 23.8,
                "resolution": "1024x1024"
            },
            {
                "id": "ponyDiffusionV6XL.safetensors",
                "label": "Pony Diffusion v6 XL",
                "description": "SDXL-based model fine-tuned for anime/illustration. Uncensored, supports NSFW content.",
                "nsfw": true,
                "size_gb": 6.46,
                "resolution": "1024x1024"
            },
            {
                "id": "sd15.safetensors",
                "label": "Stable Diffusion 1.5",
                "description": "Classic SD 1.5 model. Fast, lightweight.",
                "nsfw": false,
                "size_gb": 4.27,
                "resolution": "512x512"
            },
            {
                "id": "realisticVisionV51.safetensors",
                "label": "Realistic Vision v5.1",
                "description": "Photorealistic SD 1.5 model.",
                "nsfw": false,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "dreamshaper_8.safetensors",
                "label": "DreamShaper 8",
                "description": "Versatile model for artistic and realistic styles. Uncensored, excellent for NSFW content.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "deliberate_v3.safetensors",
                "label": "Deliberate v3",
                "description": "High-quality photorealistic model. Uncensored, great for adult content generation.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "epicrealism_pureEvolution.safetensors",
                "label": "epiCRealism Pure Evolution",
                "description": "Ultra-realistic model for photorealistic generations. Fully uncensored for adult content.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "cyberrealistic_v42.safetensors",
                "label": "CyberRealistic v4.2",
                "description": "Photorealistic model optimized for portraits and figures. Uncensored NSFW support.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "absolutereality_v181.safetensors",
                "label": "AbsoluteReality v1.8.1",
                "description": "Highly realistic model for lifelike images. Full NSFW capability.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "aZovyaRPGArtist_v5.safetensors",
                "label": "aZovya RPG Artist v5",
                "description": "Fantasy/RPG style artwork model. Supports uncensored adult content.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "unstableDiffusion.safetensors",
                "label": "Unstable Diffusion",
                "description": "Community model trained without content restrictions. Designed for adult content.",
                "nsfw": true,
                "size_gb": 4.27,
                "resolution": "512x512"
            },
            {
                "id": "majicmixRealistic_v7.safetensors",
                "label": "MajicMix Realistic v7",
                "description": "Asian-focused photorealistic model. Uncensored for NSFW generations.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "bbmix_v4.safetensors",
                "label": "BBMix v4",
                "description": "Versatile model for realistic and semi-realistic styles. Full NSFW support.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "realisian_v50.safetensors",
                "label": "Realisian v5.0",
                "description": "Photorealistic model with excellent skin textures. Uncensored adult content support.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512"
            },
            {
                "id": "abyssOrangeMix3_aom3a1b.safetensors",
                "label": "AbyssOrangeMix3 (AOM3)",
                "description": "Japanese aesthetic anime model. Painterly style with realistic textures. Beautiful linework. SD 1.5 based, ~4GB VRAM.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x768",
                "civitai_version_id": "17233"
            },
            {
                "id": "counterfeit_v30.safetensors",
                "label": "Counterfeit V3.0",
                "description": "High-quality anime model with vibrant colors. Great for detailed character art and fan service illustrations.",
                "nsfw": true,
                "size_gb": 2.13,
                "resolution": "512x512",
                "civitai_version_id": "57618"
            },
            {
                "id": "anything_v5PrtRE.safetensors",
                "label": "Anything V5 (Prt-RE)",
                "description": "Classic anime model with vivid colors. Prt-RE is the recommended trimmed+repaired version. Great LoRA compatibility.",
                "nsfw": true,
                "size_gb": 2,
                "resolution": "512x768",
                "civitai_version_id": "90854"
            },
            {
                "id": "ponyDiffusionV6XL_v6.safetensors",
                "label": "Pony Diffusion V6 XL",
                "description": "Best overall anime NSFW model. SDXL finetune trained on 2.6M Danbooru/e621 images. Massive LoRA ecosystem. Use score_9, score_8_up quality tags. Clip Skip 2 required.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 6.46,
                "resolution": "1024x1024",
                "civitai_version_id": "290640"
            },
            {
                "id": "noobaiXL_epsPred11.safetensors",
                "label": "NoobAI-XL (EPS v1.1)",
                "description": "Newest & best prompt adherence. 13M+ Danbooru/e621 images. Knows thousands of anime characters/artists by name. Use 'very awa, masterpiece, best quality' tags. EPS-prediction version (standard, easy to use).",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 7,
                "resolution": "1024x1024",
                "civitai_version_id": "1022833"
            },
            {
                "id": "noobaiXL_vPred10.safetensors",
                "label": "NoobAI-XL (V-Pred v1.0)",
                "description": "V-Prediction variant of NoobAI-XL. Better color accuracy and quality than EPS version but requires v-pred compatible UI (ComfyUI, Forge, reForge). NOT compatible with standard A1111.",
                "nsfw": true,
                "size_gb": 7.11,
                "resolution": "1024x1024",
                "civitai_version_id": "1093948"
            },
            {
                "id": "meinamix_meinaV12Final.safetensors",
                "label": "MeinaMix V12 (Final)",
                "description": "Best SD1.5 anime model. Stunning results with minimal prompting. Ultra-fast on any GPU. Final version. Balanced between realistic textures and anime style.",
                "recommended_nsfw": true,
                "nsfw": true,
                "size_gb": 2,
                "resolution": "512x768",
                "civitai_version_id": "948574"
            }
        ],
        "video": [
            {
                "id": "svd_xt_1_1.safetensors",
                "label": "Stable Video Diffusion XT 1.1",
                "description": "Latest SVD model with 25 frames, 1024x576 resolution.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 9.56,
                "resolution": "1024x576",
                "frames": 25
            },
            {
                "id": "svd_xt.safetensors",
                "label": "Stable Video Diffusion XT",
                "description": "Extended temporal model with 25 frames.",
                "nsfw": false,
                "size_gb": 9.56,
                "resolution": "1024x576",
                "frames": 25
            },
            {
                "id": "svd.safetensors",
                "label": "Stable Video Diffusion",
                "description": "Base SVD model with 14 frames.",
                "nsfw": false,
                "size_gb": 9.56,
                "resolution": "1024x576",
                "frames": 14
            },
            {
                "id": "ltx-video-2b-v0.9.1.safetensors",
                "label": "LTX-Video 2B v0.9.1 (I2V/T2V)",
                "description": "Lightricks LTX-Video checkpoint + T5 text encoder. Fast, lightweight - best for RTX 4080.",
                "recommended": true,
                "protected": true,
                "nsfw": false,
                "size_gb": 10.5,
                "resolution": "varies",
                "frames": 80,
                "install": {
                    "type": "hf_files",
                    "requires_custom_nodes": [
                        "ComfyUI-LTXVideo"
                    ],
                    "hint": "After install: use LTX workflows/nodes in ComfyUI to load the checkpoint.",
                    "files": [
                        {
                            "repo_id": "Lightricks/LTX-Video",
                            "filename": "ltx-video-2b-v0.9.1.safetensors",
                            "dest": "checkpoints/ltx-video-2b-v0.9.1.safetensors"
                        },
                        {
                            "repo_id": "comfyanonymous/flux_text_encoders",
                            "filename": "t5xxl_fp16.safetensors",
                            "dest": "clip/t5xxl_fp16.safetensors"
                        }
                    ]
                }
            },
            {
                "id": "hunyuanvideo_t2v_720p_gguf_q4_k_m_pack",
                "label": "HunyuanVideo T2V 720p GGUF Q4_K_M Pack",
                "description": "GGUF UNet + required encoders + VAE. Optimized for RTX 4080 (16GB). Requires ComfyUI-GGUF nodes.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 9.5,
                "resolution": "720p",
                "frames": 80,
                "install": {
                    "type": "hf_files",
                    "requires_custom_nodes": [
                        "ComfyUI-GGUF"
                    ],
                    "hint": "After install: install ComfyUI-GGUF via ComfyUI Manager, restart ComfyUI, then load HunyuanVideo GGUF workflows.",
                    "files": [
                        {
                            "repo_id": "city96/HunyuanVideo-gguf",
                            "filename": "hunyuan-video-t2v-720p-Q4_K_M.gguf",
                            "dest": "unet/hunyuan-video-t2v-720p-Q4_K_M.gguf"
                        },
                        {
                            "repo_id": "Comfy-Org/HunyuanVideo_repackaged",
                            "filename": "split_files/text_encoders/clip_l.safetensors",
                            "dest": "text_encoders/clip_l.safetensors"
                        },
                        {
                            "repo_id": "Comfy-Org/HunyuanVideo_repackaged",
                            "filename": "split_files/text_encoders/llava_llama3_fp8_scaled.safetensors",
                            "dest": "text_encoders/llava_llama3_fp8_scaled.safetensors"
                        },
                        {
                            "repo_id": "Comfy-Org/HunyuanVideo_repackaged",
                            "filename": "split_files/vae/hunyuan_video_vae_bf16.safetensors",
                            "dest": "vae/hunyuan_video_vae_bf16.safetensors"
                        }
                    ]
                }
            },
            {
                "id": "wan2.2_5b_fp16_pack",
                "label": "Wan 2.2 5B FP16 Pack",
                "description": "Official Comfy-Org repack. Strong motion + modern open video. Good for RTX 4080.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 21.5,
                "resolution": "varies",
                "frames": 80,
                "install": {
                    "type": "hf_files",
                    "hint": "After install: use ComfyUI Wan2.2 workflows (Load Diffusion Model = wan2.2_ti2v_5B_fp16).",
                    "files": [
                        {
                            "repo_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                            "filename": "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
                            "dest": "diffusion_models/wan2.2_ti2v_5B_fp16.safetensors"
                        },
                        {
                            "repo_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                            "filename": "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                            "dest": "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
                        },
                        {
                            "repo_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                            "filename": "split_files/vae/wan2.2_vae.safetensors",
                            "dest": "vae/wan2.2_vae.safetensors"
                        }
                    ]
                }
            },
            {
                "id": "mochi_preview_fp8_pack",
                "label": "Mochi 1 Preview FP8 Pack",
                "description": "Mochi diffusion FP8 + T5XXL FP8 + Mochi VAE. Heavier model - may push 16GB VRAM limits.",
                "recommended": false,
                "nsfw": false,
                "size_gb": 28,
                "resolution": "480p",
                "frames": 80,
                "install": {
                    "type": "hf_files",
                    "hint": "After install: update ComfyUI and use Mochi workflows. May require lowering settings on 16GB cards.",
                    "files": [
                        {
                            "repo_id": "Comfy-Org/mochi_preview_repackaged",
                            "filename": "split_files/diffusion_models/mochi_preview_fp8_scaled.safetensors",
                            "dest": "diffusion_models/mochi_preview_fp8_scaled.safetensors"
                        },
                        {
                            "repo_id": "Comfy-Org/mochi_preview_repackaged",
                            "filename": "split_files/text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors",
                            "dest": "text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors"
                        },
                        {
                            "repo_id": "Comfy-Org/mochi_preview_repackaged",
                            "filename": "split_files/vae/mochi_vae.safetensors",
                            "dest": "vae/mochi_vae.safetensors"
                        }
                    ]
                }
            },
            {
                "id": "cogvideox1.5_5b_i2v_snapshot",
                "label": "CogVideoX 1.5 5B I2V (Diffusers)",
                "description": "Downloads entire Diffusers-style repo. Requires ComfyUI CogVideoX wrapper. May need tuning on 16GB.",
                "recommended": false,
                "nsfw": false,
                "size_gb": 20,
                "resolution": "varies",
                "frames": 80,
                "install": {
                    "type": "hf_snapshot",
                    "repo_id": "THUDM/CogVideoX1.5-5B-I2V",
                    "dest_dir": "diffusers/CogVideoX1.5-5B-I2V",
                    "requires_custom_nodes": [
                        "ComfyUI-CogVideoXWrapper"
                    ],
                    "hint": "After install: configure your CogVideoX ComfyUI wrapper to point to this diffusers folder."
                }
            }
        ],
        "edit": [
            {
                "id": "sd_xl_base_1.0_inpainting_0.1.safetensors",
                "label": "SDXL Inpainting 0.1 (Checkpoint)",
                "description": "High-quality inpainting backbone for natural edits (object removal, region replace) at 1024px.",
                "recommended": true,
                "protected": true,
                "nsfw": false,
                "size_gb": 5.14,
                "resolution": "1024x1024"
            },
            {
                "id": "sd-v1-5-inpainting.ckpt",
                "label": "SD 1.5 Inpainting (Fast fallback)",
                "description": "Fast and stable 512px inpainting fallback. Great for low-VRAM servers.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 4.27,
                "resolution": "512x512"
            },
            {
                "id": "control_v11p_sd15_inpaint.safetensors",
                "label": "ControlNet SD1.5 Inpaint (Guidance)",
                "description": "ControlNet inpaint guidance to preserve structure and blend edits naturally (SD1.5).",
                "recommended": true,
                "nsfw": false,
                "size_gb": 1.45
            },
            {
                "id": "sam_vit_h_4b8939.pth",
                "label": "Segment Anything (SAM ViT-H)",
                "description": "Optional auto-mask helper (Segment Anything Model). Useful for background removal / object selection.",
                "recommended": false,
                "nsfw": false,
                "size_gb": 2.56
            },
            {
                "id": "u2net.onnx",
                "label": "Background Remove (U2Net ONNX)",
                "description": "Optional background removal helper used by rembg-style workflows.",
                "recommended": false,
                "nsfw": false,
                "size_gb": 0.17
            }
        ],
        "enhance": [
            {
                "id": "4x-UltraSharp.pth",
                "label": "4x UltraSharp (Upscale)",
                "description": "Sharp, clean 4x upscaler for general photos.",
                "recommended": true,
                "protected": true,
                "nsfw": false,
                "size_gb": 0.08
            },
            {
                "id": "RealESRGAN_x4plus.pth",
                "label": "RealESRGAN x4+ (Photo)",
                "description": "Excellent photo upscaling with natural texture recovery.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 0.064
            },
            {
                "id": "realesr-general-x4v3.pth",
                "label": "Real-ESRGAN General x4v3",
                "description": "General-purpose Real-ESRGAN model, good for mixed content.",
                "recommended": false,
                "nsfw": false,
                "size_gb": 0.064
            },
            {
                "id": "SwinIR_4x.pth",
                "label": "SwinIR 4x (Restore)",
                "description": "Restoration upscaler for compression and mild blur cleanup.",
                "recommended": false,
                "nsfw": false,
                "size_gb": 0.12
            },
            {
                "id": "GFPGANv1.4.pth",
                "label": "GFPGAN v1.4 (Face Restore)",
                "description": "Optional face restoration after heavy edits or upscaling.",
                "recommended": false,
                "protected": true,
                "nsfw": false,
                "size_gb": 0.35
            }
        ],
        "addons": [
            {
                "id": "ComfyUI-VideoHelperSuite",
                "label": "Video Helper Suite (VHS)",
                "description": "Essential video tools: MP4/WebM export, video loading, frame manipulation. Enables proper video output instead of animated WEBP.",
                "recommended": true,
                "protected": true,
                "install": {
                    "type": "git_repo",
                    "repo_url": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite",
                    "dest_dir": "custom_nodes/ComfyUI-VideoHelperSuite",
                    "hint": "Restart ComfyUI after install. Requires ffmpeg in PATH for video encoding."
                },
                "provides_nodes": [
                    "VHS_VideoCombine",
                    "VHS_LoadVideo",
                    "VHS_SplitVideo"
                ]
            },
            {
                "id": "ComfyUI-LTXVideo",
                "label": "LTX-Video Nodes",
                "description": "Native LTX-Video nodes for optimal performance with LTX-Video checkpoints.",
                "recommended": true,
                "protected": true,
                "install": {
                    "type": "git_repo",
                    "repo_url": "https://github.com/Lightricks/ComfyUI-LTXVideo",
                    "dest_dir": "custom_nodes/ComfyUI-LTXVideo",
                    "hint": "Restart ComfyUI after install."
                },
                "provides_nodes": [
                    "LTXVLoader",
                    "LTXVSampler",
                    "LTXVConditioning"
                ]
            },
            {
                "id": "ComfyUI-GGUF",
                "label": "GGUF Model Loader",
                "description": "Load GGUF quantized models. Required for HunyuanVideo GGUF and other quantized models.",
                "recommended": true,
                "install": {
                    "type": "git_repo",
                    "repo_url": "https://github.com/city96/ComfyUI-GGUF",
                    "dest_dir": "custom_nodes/ComfyUI-GGUF",
                    "hint": "Restart ComfyUI after install."
                },
                "provides_nodes": [
                    "UnetLoaderGGUF",
                    "DualCLIPLoaderGGUF"
                ]
            },
            {
                "id": "ComfyUI-CogVideoXWrapper",
                "label": "CogVideoX Wrapper",
                "description": "Nodes to run CogVideoX Diffusers pipelines in ComfyUI.",
                "recommended": false,
                "install": {
                    "type": "git_repo",
                    "repo_url": "https://github.com/kijai/ComfyUI-CogVideoXWrapper",
                    "dest_dir": "custom_nodes/ComfyUI-CogVideoXWrapper",
                    "hint": "Restart ComfyUI after install."
                },
                "provides_nodes": [
                    "CogVideoXDiffusersLoader",
                    "CogVideoXSampler",
                    "CogVideoXDecode"
                ]
            },
            {
                "id": "ComfyUI-Impact-Pack",
                "label": "Impact Pack",
                "description": "Essential nodes for segmentation, face detection, and advanced image workflows.",
                "recommended": true,
                "protected": true,
                "install": {
                    "type": "git_repo",
                    "repo_url": "https://github.com/ltdrdata/ComfyUI-Impact-Pack",
                    "dest_dir": "custom_nodes/ComfyUI-Impact-Pack",
                    "hint": "Restart ComfyUI after install. Some features require additional model downloads."
                },
                "provides_nodes": [
                    "SAMLoader",
                    "FaceDetailer",
                    "BboxDetectorSEGS"
                ]
            },
            {
                "id": "t5xxl_fp8_e4m3fn.safetensors",
                "label": "T5-XXL FP8 Text Encoder",
                "description": "For 12-16GB VRAM (RTX 4080, 3080). Uses ~5GB vs ~10GB for FP16. Required for LTX-Video on limited VRAM.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 5,
                "install": {
                    "type": "hf_files",
                    "files": [
                        {
                            "repo_id": "comfyanonymous/flux_text_encoders",
                            "filename": "t5xxl_fp8_e4m3fn.safetensors",
                            "dest": "models/clip/t5xxl_fp8_e4m3fn.safetensors"
                        }
                    ],
                    "hint": "Download to ComfyUI/models/clip folder"
                }
            },
            {
                "id": "t5xxl_fp16.safetensors",
                "label": "T5-XXL FP16 Text Encoder",
                "description": "For 24GB+ VRAM (RTX 4090, A5000). Full precision for best quality. Baseline ~20GB + sampling ~6-10GB peak.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 10,
                "install": {
                    "type": "hf_files",
                    "files": [
                        {
                            "repo_id": "comfyanonymous/flux_text_encoders",
                            "filename": "t5xxl_fp16.safetensors",
                            "dest": "models/clip/t5xxl_fp16.safetensors"
                        }
                    ],
                    "hint": "Download to ComfyUI/models/clip folder"
                }
            },
            {
                "id": "mochi_vae.safetensors",
                "label": "Mochi VAE",
                "description": "Required VAE for Mochi video model.",
                "nsfw": false,
                "size_gb": 0.4,
                "install": {
                    "type": "hf_files",
                    "files": [
                        {
                            "repo_id": "Comfy-Org/mochi_preview_repackaged",
                            "filename": "split_files/vae/mochi_vae.safetensors",
                            "dest": "models/vae/mochi_vae.safetensors"
                        }
                    ],
                    "hint": "Download to ComfyUI/models/vae folder"
                }
            },
            {
                "id": "clip_l.safetensors",
                "label": "CLIP-L Text Encoder",
                "description": "CLIP-L text encoder for SDXL and video models.",
                "nsfw": false,
                "size_gb": 0.25,
                "install": {
                    "type": "hf_files",
                    "files": [
                        {
                            "repo_id": "comfyanonymous/flux_text_encoders",
                            "filename": "clip_l.safetensors",
                            "dest": "models/clip/clip_l.safetensors"
                        }
                    ],
                    "hint": "Download to ComfyUI/models/clip folder"
                }
            }
        ]
    },
    "civitai": {
        "image": [
            {
                "id": "pony_diffusion_v6_xl",
                "label": "Pony Diffusion V6 XL",
                "description": "The base model for character consistency and prompt adherence. Best for anime/illustration.",
                "recommended": true,
                "nsfw": true,
                "size_gb": 6.46,
                "resolution": "1024x1024",
                "civitai_url": "https://civitai.com/models/257749/pony-diffusion-v6-xl",
                "civitai_version_id": "290640"
            },
            {
                "id": "cyberrealistic_pony",
                "label": "CyberRealistic Pony",
                "description": "Best blend of Pony's prompt understanding with photorealism. Excellent for realistic NSFW.",
                "recommended": true,
                "nsfw": true,
                "size_gb": 6.46,
                "resolution": "1024x1024",
                "civitai_url": "https://civitai.com/models/443821/cyberrealistic-pony",
                "civitai_version_id": "544666"
            },
            {
                "id": "realvisxl_v50",
                "label": "RealVisXL V5.0",
                "description": "The gold standard for photorealistic skin texture and lighting. SDXL-based.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 6.94,
                "resolution": "1024x1024",
                "civitai_url": "https://civitai.com/models/139562/realvisxl-v50",
                "civitai_version_id": "361593"
            },
            {
                "id": "juggernaut_xl",
                "label": "Juggernaut XL",
                "description": "Cinematic and moody photorealism. Excellent for dramatic lighting and scenes.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 6.94,
                "resolution": "1024x1024",
                "civitai_url": "https://civitai.com/models/133005/juggernaut-xl",
                "civitai_version_id": "471120"
            },
            {
                "id": "flux1_checkpoint",
                "label": "Flux.1 Checkpoint (Easy to Use)",
                "description": "High-quality Flux checkpoint packaged for easy use with ComfyUI or Forge.",
                "nsfw": false,
                "size_gb": 23.8,
                "resolution": "1024x1024",
                "civitai_url": "https://civitai.com/models/628682/flux-1-checkpoint-easy-to-use",
                "civitai_version_id": "704954"
            },
            {
                "id": "adetailer_face",
                "label": "ADetailer Face Models",
                "description": "Face detection and enhancement models for better face quality in generations.",
                "nsfw": false,
                "size_gb": 0.5,
                "civitai_url": "https://civitai.com/models/195550",
                "civitai_version_id": "219687"
            }
        ],
        "video": [
            {
                "id": "ltx_video_workflow",
                "label": "LTX Video (Image to Video)",
                "description": "Fast, lightweight video generation workflow. Best for local RTX cards (8GB+ VRAM).",
                "recommended": true,
                "nsfw": false,
                "size_gb": 5,
                "resolution": "768x512",
                "frames": 24,
                "civitai_url": "https://civitai.com/models/995093/ltx-image-to-video-with-stg-caption-and-clip-extend-workflow",
                "civitai_version_id": "1119428"
            },
            {
                "id": "mochi_1_pack",
                "label": "Mochi 1 Video Pack",
                "description": "High motion fidelity video model. Excellent for smooth animations and motion.",
                "recommended": true,
                "nsfw": false,
                "size_gb": 10,
                "resolution": "848x480",
                "frames": 30,
                "civitai_url": "https://civitai.com/models/886896/donut-mochi-pack-video-generation",
                "civitai_version_id": "992820"
            },
            {
                "id": "animatediff_sdxl",
                "label": "AnimateDiff SDXL (Odinson)",
                "description": "Workflow to animate SDXL images using AnimateDiff. Turn still images into videos.",
                "nsfw": false,
                "size_gb": 2.5,
                "resolution": "1024x1024",
                "frames": 16,
                "civitai_url": "https://civitai.com/models/331700/odinson-sdxl-animatediff",
                "civitai_version_id": "373089"
            },
            {
                "id": "animatediff_lightning",
                "label": "AnimateDiff Lightning",
                "description": "Fast AnimateDiff model with 4-step generation. Good for quick video previews.",
                "nsfw": false,
                "size_gb": 1.5,
                "resolution": "512x512",
                "frames": 16,
                "civitai_url": "https://civitai.com/models/500187/animatediff-lightning",
                "civitai_version_id": "554533"
            }
        ]
    },
    "openai_compat": {
        "chat": [
            {
                "id": "local-model",
                "label": "Local Model (auto-detect)",
                "description": "Automatically detect and use the first available model from your vLLM/TGI server.",
                "recommended": true
            }
        ]
    },
    "openai": {
        "chat": [
            {
                "id": "gpt-4o",
                "label": "GPT-4o",
                "description": "Latest GPT-4 optimized model with vision capabilities.",
                "recommended": true
            },
            {
                "id": "gpt-4o-mini",
                "label": "GPT-4o Mini",
                "description": "Smaller, faster GPT-4 variant."
            },
            {
                "id": "gpt-4-turbo",
                "label": "GPT-4 Turbo",
                "description": "GPT-4 Turbo with vision support."
            },
            {
                "id": "gpt-3.5-turbo",
                "label": "GPT-3.5 Turbo",
                "description": "Fast and cost-effective GPT-3.5 model."
            }
        ]
    },
    "claude": {
        "chat": [
            {
                "id": "claude-opus-4-5-20251101",
                "label": "Claude Opus 4.5",
                "description": "Most capable Claude model with advanced reasoning.",
                "recommended": true
            },
            {
                "id": "claude-sonnet-4-5-20250929",
                "label": "Claude Sonnet 4.5",
                "description": "Balanced performance and speed."
            },
            {
                "id": "claude-sonnet-3-5-20241022",
                "label": "Claude Sonnet 3.5",
                "description": "Previous generation Sonnet model."
            },
            {
                "id": "claude-haiku-3-5-20241022",
                "label": "Claude Haiku 3.5",
                "description": "Fast and efficient Claude model."
            }
        ]
    },
    "watsonx": {
        "chat": [
            {
                "id": "meta-llama/llama-3-1-70b-instruct",
                "label": "Llama 3.1 70B Instruct",
                "description": "IBM-hosted Llama 3.1 70B model.",
                "recommended": true
            },
            {
                "id": "meta-llama/llama-3-1-8b-instruct",
                "label": "Llama 3.1 8B Instruct",
                "description": "Smaller, faster Llama 3.1 variant."
            },
            {
                "id": "ibm/granite-13b-chat-v2",
                "label": "IBM Granite 13B Chat v2",
                "description": "IBM's Granite model optimized for chat."
            },
            {
                "id": "mistralai/mixtral-8x7b-instruct-v01",
                "label": "Mixtral 8x7B Instruct",
                "description": "Mistral's Mixture of Experts model."
            }
        ]
    }
};

export default GENERATED_CATALOGS;
