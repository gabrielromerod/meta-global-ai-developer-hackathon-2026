"""Generic public diagram, independent of private imported scans and textures."""

import json

from vigil.models import Config
from vigil.settings import REPO_ROOT


def public_twin(config: Config) -> dict:
    template = json.loads((REPO_ROOT / "config/public_massing.json").read_text(encoding="utf-8"))
    return {
        "generic_massing": True,
        "glb_url": None,
        "note": template["note"],
        "ground": template["ground"],
        "site_plan": template["site_plan"],
        "cameras": [
            {
                "id": c.id,
                "name": c.name,
                "width": c.width,
                "height": c.height,
                **template["camera_layout"].get(c.id, {}),
                "placement_measured": False,
            }
            for c in config.cameras
        ],
        "blind_regions": [r.model_dump() for r in config.blind_regions],
        "coverage": [],
    }
