# Base image published by .github/workflows/container.yml to GHCR.
# Docker Hub (docker.io/ruslanmv/homepilot) is only pushed on a release, so its
# :latest tag may not exist; GHCR tags each default-branch build with the
# 7-character commit id (for example ghcr.io/ruslanmv/homepilot:b317a51).
ARG BASE_IMAGE=ghcr.io/ruslanmv/homepilot:latest
FROM ${BASE_IMAGE}

USER root

# Redeclared after FROM. The workflow sets these to the commit of the app
# image being wrapped, which is the same commit the Hugging Face Space builds.
ARG HOMEPILOT_BUILD_SHA=unknown
ARG HOMEPILOT_BUILT_AT=unknown
ARG HOMEPILOT_BUILD_REF=master
ENV HOMEPILOT_BUILD_SHA=${HOMEPILOT_BUILD_SHA} \
    HOMEPILOT_BUILT_AT=${HOMEPILOT_BUILT_AT} \
    HOMEPILOT_BUILD_REF=${HOMEPILOT_BUILD_REF}

# Older published app images do not contain Expert, the persona samples, or
# the download script. Copy them from this commit so a wrapper around :latest
# still serves the same chat path as the Space. A base image that already has
# them is overwritten with this commit's copies.
COPY expert/backend/app/expert /home/user/app/expert
COPY community/sample /home/user/app/community/sample
COPY scripts/download.py /home/user/app/scripts/download.py

# GET /version reads build-info.json next to the package (/home/user/app).
RUN python -c 'import json,os; from pathlib import Path; Path("/home/user/app/build-info.json").write_text(json.dumps({"sha":os.environ["HOMEPILOT_BUILD_SHA"],"built_at":os.environ["HOMEPILOT_BUILT_AT"],"ref":os.environ["HOMEPILOT_BUILD_REF"]}))' \
    && chown -R user:user \
       /home/user/app/expert \
       /home/user/app/community \
       /home/user/app/scripts \
       /home/user/app/build-info.json

COPY notifications/content-notice.css /home/user/app/static/homepilot-content-notice.css
COPY notifications/content-notice.js /home/user/app/static/homepilot-content-notice.js
COPY oracle/inject-notifications.py /tmp/inject-notifications.py

RUN python /tmp/inject-notifications.py /home/user/app/static/index.html \
    && rm /tmp/inject-notifications.py \
    && chown user:user \
       /home/user/app/static/index.html \
       /home/user/app/static/homepilot-content-notice.css \
       /home/user/app/static/homepilot-content-notice.js

USER user
