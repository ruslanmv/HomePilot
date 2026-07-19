# Base image published by .github/workflows/container.yml to GHCR.
# Docker Hub (docker.io/ruslanmv/homepilot) is only pushed on a release, so its
# :latest tag may not exist; GHCR always has :latest on the default branch.
ARG BASE_IMAGE=ghcr.io/ruslanmv/homepilot:latest
FROM ${BASE_IMAGE}

USER root

COPY notifications/content-notice.css /home/user/app/static/homepilot-content-notice.css
COPY notifications/content-notice.js /home/user/app/static/homepilot-content-notice.js
COPY oracle/inject-notifications.py /tmp/inject-notifications.py

RUN python /tmp/inject-notifications.py /home/user/app/static/index.html \
    && rm /tmp/inject-notifications.py \
    && chown user:user \
       /home/user/app/static/index.html \
       /home/user/app/static/homepilot-content-notice.css \
       /home/user/app/static/homepilot-content-notice.js

# Oracle's Always Free shapes are CPU-only with little RAM, and this deployment
# targets an external LLM API — the bundled ComfyUI diffusion engine can't do
# useful work here and its CPU-torch startup saturates the single OCPU and risks
# OOM-killing the backend, which then never becomes healthy. Disable ComfyUI's
# autostart so only nginx + the backend run. (Guarded so the build still
# succeeds if the base image ever relocates the supervisord config.)
RUN SV=/etc/supervisor/conf.d/supervisord.conf; \
    if [ -f "$SV" ]; then \
      awk '/^\[program:comfyui\]/{b=1} /^\[program:/ && $0 !~ /comfyui/{b=0} b && /^autostart=/{print "autostart=false"; next} {print}' "$SV" > "$SV.tmp" \
      && mv "$SV.tmp" "$SV" \
      && sed -i 's/--workers[[:space:]]\+[0-9]\+/--workers 1/' "$SV" \
      && echo "Oracle image: ComfyUI autostart disabled; backend workers=1."; \
    else \
      echo "supervisord.conf not found at $SV — leaving base image untouched."; \
    fi

USER user
