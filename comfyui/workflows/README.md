
# ComfyUI Workflows (templates)

Backend expects these files (JSON):

* txt2img.json
* edit.json
* img2vid.json

How to make them real:

1. Open ComfyUI
2. Build your workflow (FLUX txt2img, FLUX inpaint, SVD img2vid, etc.)
3. Export workflow JSON
4. Replace user prompt fields inside the JSON with placeholders:

   * {{prompt}}        for txt2img
   * {{image_url}}     for edit/img2vid
   * {{instruction}}   for edit
   * {{seconds}}       for img2vid
   * {{motion}}        for img2vid (optional)

Backend replaces placeholders recursively across the whole graph, then:

* POSTs to /prompt
* polls /history/<prompt_id>
* extracts image/video filenames and returns /view URLs.

Tip:
Use ComfyUI "Load Image" nodes that can fetch http URLs, or implement a workflow that reads images from /files URLs.
