from pathlib import Path

import numpy as np
import torch
from facenet_pytorch import InceptionResnetV1

from vision.recognition import normalize

MODEL_VERSION = "facenet-vggface2-mp-align-v1"


class Embedder:
    def __init__(self, asset_dir: Path, device="cpu"):
        if device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS is unavailable; set ATTENDANCE_DEVICE=cpu")
        weight_path = asset_dir / "20180402-114759-vggface2.pt"
        if not weight_path.is_file():
            raise RuntimeError("FaceNet weights are missing. Run: attendance download-models")
        torch.set_num_threads(2)
        self.device = torch.device(device)
        self.model = InceptionResnetV1(classify=True, num_classes=8631).eval()
        # Only the bundled asset downloader supplies weights. Never deserialize uploaded models.
        state = torch.load(weight_path, map_location="cpu", weights_only=True)
        self.model.load_state_dict(state)
        self.model.classify = False
        self.model.to(self.device)

    def extract(self, rgb_crops):
        if not rgb_crops:
            return np.empty((0, 512), np.float32)
        if any(crop.shape != (160, 160, 3) for crop in rgb_crops):
            raise ValueError("FaceNet requires 160×160 RGB crops")
        batch = np.stack(rgb_crops).astype(np.float32)
        tensor = torch.from_numpy(batch).permute(0, 3, 1, 2).to(self.device)
        tensor = (tensor - 127.5) / 128.0
        with torch.inference_mode():
            result = self.model(tensor).cpu().numpy()
        return normalize(result)
