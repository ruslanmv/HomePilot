FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /ComfyUI

RUN apt-get update && apt-get install -y --no-install-recommends \
    git python3 python3-venv python3-pip libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/comfyanonymous/ComfyUI.git . \
 && python3 -m pip install --upgrade pip \
 && pip install -r requirements.txt

EXPOSE 8188
CMD ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188"]