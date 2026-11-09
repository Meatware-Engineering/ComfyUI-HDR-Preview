import logging
import os
from pathlib import Path
import re
import threading
import time
import uuid

import torch

import folder_paths
from comfy_extras.nodes_images import _save_avif


WEB_DIRECTORY = "./web"
_FILE_PATTERN = re.compile(r"hdr_preview_[0-9a-f]{32}\.avif")
_MAX_FILES = 64
_MAX_BYTES = 256 * 1024 * 1024
_MAX_AGE = 24 * 60 * 60
_FILE_LOCK = threading.Lock()
_COLOR_SPACES = {"HLG (BT.2020)": "HDR", "PQ (BT.2020)": "HDR PQ"}


def _cleanup(directory, keep):
    now = time.time()
    files = []
    for path in directory.iterdir():
        if not _FILE_PATTERN.fullmatch(path.name) or path.is_symlink():
            continue
        try:
            stat = path.stat()
            if path.is_file():
                files.append((path, stat.st_mtime, stat.st_size))
        except FileNotFoundError:
            continue
    files.sort(key=lambda item: item[1], reverse=True)
    count, size = 1, keep.stat().st_size
    for path, modified, length in files:
        if path == keep:
            continue
        if now - modified > _MAX_AGE or count >= _MAX_FILES or size + length > _MAX_BYTES:
            try:
                path.unlink()
            except OSError as error:
                logging.warning("Preview HDR: could not remove its expired preview %s: %s", path.name, error)
        else:
            count += 1
            size += length


class PreviewHDR:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "input_color_space": (list(_COLOR_SPACES), {
                    "default": "HLG (BT.2020)",
                    "tooltip": "The input must already be BT.2020 HLG or PQ, normalized to 0–1. Match RTX Video HDR: HDR = HLG, HDR PQ = PQ. This node does not convert SDR to HDR.",
                }),
                "batch_index": ("INT", {"default": 0, "min": 0, "max": 65535,
                    "tooltip": "Image to preview from the batch. The original full batch passes through unchanged."}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "preview"
    CATEGORY = "image/preview"
    OUTPUT_NODE = True
    DESCRIPTION = "Native inline HDR preview using a temporary 10-bit AVIF. No file is saved to output. Requires an HDR-capable browser/display; SDR systems may tone-map. Previews expire after 24 hours, 64 files, or 256 MiB. Save separately when wanted."

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # An expired temporary preview must regenerate even when its input is cached.
        return float("nan")

    def preview(self, images, input_color_space="HLG (BT.2020)", batch_index=0):
        if input_color_space not in _COLOR_SPACES:
            raise ValueError("Preview HDR: choose HLG (BT.2020) or PQ (BT.2020).")
        if images.ndim != 4 or images.shape[-1] != 3 or min(images.shape) < 1:
            raise ValueError("Preview HDR expects a nonempty IMAGE batch [B, H, W, 3]. Composite alpha before previewing.")
        if not 0 <= batch_index < images.shape[0]:
            raise ValueError(f"Preview HDR: batch_index {batch_index} is outside this {images.shape[0]}-image batch.")
        frame = images[batch_index:batch_index + 1].detach().to(device="cpu", dtype=torch.float32)
        if not torch.isfinite(frame).all().item():
            raise ValueError("Preview HDR: input contains NaN or infinity.")
        if frame.min().item() < 0 or frame.max().item() > 1:
            raise ValueError("Preview HDR expects HLG/PQ signal values in 0–1. Convert scene-linear HDR to HLG or PQ first.")

        directory = Path(folder_paths.get_temp_directory()) / "hdr-preview"
        if directory.is_symlink():
            raise ValueError("Preview HDR: its temporary directory must not be a symlink.")
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"hdr_preview_{uuid.uuid4().hex}.avif"
        target = directory / filename
        pending = directory / (filename + ".pending")
        try:
            _save_avif(frame, str(pending), "10-bit YUV420", _COLOR_SPACES[input_color_space], 18)
            with _FILE_LOCK:
                os.replace(pending, target)
                _cleanup(directory, target)
        finally:
            pending.unlink(missing_ok=True)

        return {
            "ui": {"hdr_preview": [{
                "filename": filename,
                "subfolder": "hdr-preview",
                "type": "temp",
                "width": images.shape[2],
                "height": images.shape[1],
                "input_color_space": input_color_space,
                "batch_index": batch_index,
            }]},
            "result": (images,),
        }


NODE_CLASS_MAPPINGS = {"PreviewHDR": PreviewHDR}
NODE_DISPLAY_NAME_MAPPINGS = {"PreviewHDR": "Preview HDR"}
