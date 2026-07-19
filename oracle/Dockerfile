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

USER user
