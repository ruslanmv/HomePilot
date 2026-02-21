FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /ComfyUI

RUN apt-get update && apt-get install -y --no-install-recommends \
    git python3 python3-venv python3-pip libgl1 libglib2.0-0 unzip \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/comfyanonymous/ComfyUI.git . \
 && python3 -m pip install --upgrade pip \
 && pip install -r requirements.txt

# Face restoration dependencies (required for GFPGAN/CodeFormer nodes)
RUN pip install facexlib gfpgan

# ComfyUI-Impact-Pack — provides FaceRestoreModelLoader / FaceRestoreWithModel nodes
RUN git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git custom_nodes/ComfyUI-Impact-Pack \
 && if [ -f custom_nodes/ComfyUI-Impact-Pack/requirements.txt ]; then \
      pip install -r custom_nodes/ComfyUI-Impact-Pack/requirements.txt; \
    fi

# ComfyUI-InstantID — provides InstantIDFaceAnalysis / InstantIDModelLoader / ApplyInstantID nodes
RUN git clone https://github.com/cubiq/ComfyUI_InstantID.git custom_nodes/ComfyUI-InstantID \
 && if [ -f custom_nodes/ComfyUI-InstantID/requirements.txt ]; then \
      pip install -r custom_nodes/ComfyUI-InstantID/requirements.txt; \
    fi

# InsightFace + ONNX Runtime (required by InstantID for face detection/embedding)
RUN pip install insightface onnxruntime

EXPOSE 8188
CMD ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
