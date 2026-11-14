# Native local ComfyUI workflows

`qwen.json` edits from up to three composed reference boards; character identity comes first. `qwen_text.json` is Qwen-Image 2512 prompt-only generation. `h3.json` generates H.264 MP4 with native AAC audio from a preceding keyframe.

J Director uploads inputs, validates installed nodes/models, queues `/prompt`, receives real `/ws` progress, polls the matching history, and fetches the matching output. Hosted generation nodes are rejected.

Omnichar creates immutable, content-versioned `.char` snapshots from selected character references. These archives do not invent trained LoRA weights. The installed FL2VA H3 workflow uses the approved keyframe; direct `.char` multi-reference H3 conditioning requires a compatible Ref2VA workflow/model and is not claimed by this I2V graph.

The old WanGP adapter is removed. Shared H3 weights, project assets and completed output files stay in their original locations. Qwen uses ComfyUI-compatible Q4_K_M GGUF models; quality must be checked against references, not inferred from the job status.
