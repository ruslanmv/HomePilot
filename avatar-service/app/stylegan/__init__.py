# StyleGAN inference module — optional GPU-accelerated face generation.
#
# When STYLEGAN_ENABLED=true and model weights are present, provides
# real StyleGAN2 inference. Otherwise, the service gracefully falls
# back to placeholder PNG generation (existing behavior preserved).
