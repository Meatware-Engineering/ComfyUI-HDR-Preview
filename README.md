# ComfyUI HDR Preview

**Experimental custom node.** Native browser preview for already encoded HDR images; not an SDR-to-HDR converter.

A standalone ComfyUI output node that previews an already HDR-encoded `IMAGE` without saving to `output`. It uses ComfyUI's existing AVIF encoder and a native browser `<img>` DOM widget, including Nodes 2.0. It adds no Python dependencies and changes no core files.

Connect `RTX Video HDR → hdr_images` to **Preview HDR**, under `image/preview`.

- NVIDIA `HDR` output: select **HLG (BT.2020)**.
- NVIDIA `HDR PQ` output: select **PQ (BT.2020)**.
- Other sources must already contain normalized 0–1 BT.2020 HLG/PQ signal values. This node does not expand SDR or interpret scene-linear/LogC data as HLG/PQ. Use core color conversion before it when appropriate.
- `batch_index` selects one image to preview. The complete original IMAGE batch passes through unchanged. Connect a separate save node only when you want permanent output.

After a preview appears, **Открыть** opens the current original HDR AVIF in a new browser tab. **Сохранить** downloads that same file using the browser, without running the workflow again or writing to ComfyUI `output`. The buttons are disabled until the preview loads. No technical caption or start instruction is shown; errors remain visible.

`example_workflows/preview_hdr_pq.json` contains `Load Image → RTX Video HDR → Preview HDR` with matching PQ settings and no Save node. Choose your source image after importing it. The example was checked for loading and wiring, not executed on the GPU.

The temporary preview is a 10-bit YUV420 AVIF with BT.2020 primaries and HLG/PQ transfer metadata. The original is requested through `/view` without `preview=` or channel conversion. No canvas, SDR thumbnail, or tone mapping is inserted by this extension. AVIF compression is lossy (CRF 18).

HDR appearance requires a browser, OS, display, and display settings that actually support HDR images. A successful AVIF decode, screenshot, or `(dynamic-range: high)` result does not prove physical HDR luminance. The browser may tone-map on SDR systems.

Temporary files live only in ComfyUI's `temp/hdr-preview/`. On successful runs the node expires its own UUID-named AVIFs after 24 hours and retains at most 64 previews / 256 MiB (the current preview is always retained). It never removes other files, symlinks, or files in `output`. Previous workflow-history previews may expire; re-run to regenerate them. Failed encodes remove only their own pending file.

## Install

From your ComfyUI installation directory:

```sh
git clone https://github.com/Meatware-Engineering/ComfyUI-HDR-Preview.git custom_nodes/ComfyUI-HDR-Preview
```

Restart ComfyUI after any running jobs finish, then refresh the browser. Add **Preview HDR** from `image/preview`.

No extra pip installation is required beyond ComfyUI's working AVIF encoder and existing PyTorch/PyAV dependencies. The extension imports the private `comfy_extras.nodes_images._save_avif` helper; older cores without it cannot load the node, and future API changes may require an update. Do not replace ComfyUI's dependencies blindly if an encoder is unavailable.

## Example workflow

Import [preview_hdr_pq.json](example_workflows/preview_hdr_pq.json), select a source image and match its color-space settings. This example additionally requires the [ComfyUI NVIDIA VFX nodes](https://github.com/Comfy-Org/ComfyUI_Nvidia_VFX_Nodes) and their supported hardware/software. NVIDIA is not required by this preview extension itself when an already encoded HDR image is supplied by another source.

## Compatibility and validation

The original development checks used ComfyUI `72fc2631f` and frontend `1.55.17`. This is a historical tested configuration, not a guarantee for every current version. The frontend uses a DOM image widget, including Nodes 2.0. Button labels are currently Russian: **Открыть** (Open) and **Сохранить** (Save).

The integration suite checks the real AVIF encoder, 10-bit format, HLG/PQ metadata, dimensions, invalid input, concurrent runs, failed encodes and bounded cleanup. Run it using the Python environment of a compatible ComfyUI checkout:

```sh
# Run from your ComfyUI installation directory.
PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" python custom_nodes/ComfyUI-HDR-Preview/test_preview.py
```

The test uses temporary files and synthetic tensors; it does not need model weights or GPU inference. Passing these checks does not establish visible HDR brightness on a physical display. The example workflow was checked for wiring, not run on the GPU.

## Privacy

Only the selected image is encoded into the temporary AVIF. The node does not intentionally embed prompts or workflow metadata. Opening or saving retrieves that original file from your own ComfyUI server; there is no external upload service.

## License

MIT. See [LICENSE](LICENSE). ComfyUI and other dependencies remain subject to their own licenses.
