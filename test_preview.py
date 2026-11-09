import importlib.util
from pathlib import Path
import os
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import comfy.cli_args
comfy.cli_args.args.cpu = True

import av
import torch


spec = importlib.util.spec_from_file_location("hdr_preview_extension", Path(__file__).with_name("__init__.py"))
extension = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extension)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hdr-preview-test-")
        self.root = Path(self.temp.name)
        self.patch = patch.object(extension.folder_paths, "get_temp_directory", return_value=str(self.root))
        self.patch.start()
        self.node = extension.PreviewHDR()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def encode(self, height=64, width=64, color="HLG (BT.2020)", batch_index=0):
        image = torch.linspace(0, 1, width).reshape(1, 1, width, 1).expand(2, height, width, 3)
        result = self.node.preview(image, color, batch_index)
        self.assertIs(result["result"][0], image)
        self.assertNotIn("images", result["ui"])
        info = result["ui"]["hdr_preview"][0]
        self.assertEqual(info["type"], "temp")
        return self.root / info["subfolder"] / info["filename"]

    def test_real_codec_hdr_metadata_and_dimensions(self):
        for color, transfer in [("HLG (BT.2020)", 18), ("PQ (BT.2020)", 16)]:
            for height, width in [(64, 64), (65, 67), (19, 17)]:
                with self.subTest(color=color, size=(width, height)):
                    path = self.encode(height, width, color, batch_index=1)
                    data = path.read_bytes()
                    offset = data.index(b"nclx") + 4
                    self.assertEqual(struct.unpack(">HHH", data[offset:offset + 6]), (9, transfer, 9))
                    with av.open(str(path)) as container:
                        frame = next(container.decode(video=0))
                        self.assertEqual((frame.width, frame.height), (width, height))
                        self.assertEqual(frame.format.name, "yuv420p10le")
                        self.assertEqual((frame.color_primaries, frame.color_trc, frame.colorspace), (9, transfer, 9))

    def test_repeated_and_concurrent_runs_use_distinct_files(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            paths = list(pool.map(lambda _: self.encode(), range(2)))
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertFalse(list((self.root / "hdr-preview").glob("*.pending")))

    def test_bad_input_is_not_silently_clipped_or_retagged(self):
        valid = torch.full((1, 16, 16, 3), 0.5)
        cases = [
            (valid, "sRGB", 0),
            (valid, "HLG (BT.2020)", 1),
            (torch.ones(1, 16, 16, 4), "HLG (BT.2020)", 0),
            (torch.ones(0, 16, 16, 3), "HLG (BT.2020)", 0),
            (valid * float("nan"), "HLG (BT.2020)", 0),
            (valid * 3, "HLG (BT.2020)", 0),
        ]
        for image, color, index in cases:
            with self.subTest(color=color, index=index, shape=image.shape):
                with self.assertRaises(ValueError):
                    self.node.preview(image, color, index)
        self.assertFalse((self.root / "hdr-preview").exists())

    def test_failed_encode_leaves_no_partial_or_finished_preview(self):
        def fail(images, path, *args):
            Path(path).write_bytes(b"partial encoder output")
            raise RuntimeError("codec unavailable")
        with patch.object(extension, "_save_avif", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "codec unavailable"):
                self.encode()
        self.assertEqual(list((self.root / "hdr-preview").iterdir()), [])

    def test_cleanup_never_removes_unrelated_files_or_symlinks(self):
        directory = self.root / "hdr-preview"
        directory.mkdir()
        outside = self.root / "user-image.avif"
        outside.write_bytes(b"user image")
        unrelated = directory / "keep-my-image.avif"
        unrelated.write_bytes(b"unrelated")
        link = directory / ("hdr_preview_" + "a" * 32 + ".avif")
        link.symlink_to(outside)
        stale = directory / ("hdr_preview_" + "b" * 32 + ".avif")
        stale.write_bytes(b"old preview")
        os.utime(stale, (1, 1))
        kept = directory / ("hdr_preview_" + "c" * 32 + ".avif")
        kept.write_bytes(b"current preview")
        extension._cleanup(directory, kept)
        self.assertFalse(stale.exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_bytes(), b"user image")
        self.assertTrue(unrelated.exists())
        self.assertTrue(kept.exists())

    def test_retention_is_bounded_and_current_preview_is_kept(self):
        directory = self.root / "hdr-preview"
        directory.mkdir()
        files = []
        for index in range(5):
            path = directory / f"hdr_preview_{index:032x}.avif"
            path.write_bytes(b"12345678")
            files.append(path)
        with patch.object(extension, "_MAX_FILES", 2):
            extension._cleanup(directory, files[0])
        self.assertTrue(files[0].exists())
        self.assertEqual(len(list(directory.iterdir())), 2)
        with patch.object(extension, "_MAX_BYTES", 8):
            extension._cleanup(directory, files[0])
        self.assertEqual(list(directory.iterdir()), [files[0]])

    def test_symlinked_preview_directory_is_rejected(self):
        outside = self.root / "unrelated"
        outside.mkdir()
        (self.root / "hdr-preview").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.encode()


if __name__ == "__main__":
    unittest.main(verbosity=2)
