"""Vendor only the approved, pinned UI runtime and open icons; no Node build step."""

import base64
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "web" / "vendor"
PACKAGES = [
    (
        "preact",
        "10.27.2",
        "MIT",
        "5SYSgFKSyhCbk6SrXyMpqjb5+MQBgfvEKE/OC+PujcY34sOpqtr+0AZQtPYx5IA6VxynQ7rUPCtKzyovpj9Bpg==",
        {
            "dist/preact.module.js": "preact.module.js",
            "hooks/dist/hooks.module.js": "hooks.module.js",
            "LICENSE": "preact.LICENSE",
        },
    ),
    (
        "htm",
        "3.1.1",
        "Apache-2.0",
        "983Vyg8NwUE7JkZ6NmOqpCZ+sh1bKv2iYTlUkzlWmA5JD2acKoxd4KVxbMmxX/85mtfdnDmTFoNKcg5DGAvxNQ==",
        {
            "dist/htm.module.js": "htm.module.js",
            "LICENSE": "htm.LICENSE",
        },
    ),
    (
        "lucide-static",
        "0.468.0",
        "ISC",
        "JvpWui2umxRyEVMoETfMzb+qKqibV/sdoqJbKmW1JLdkuhXluJKoO6NqCbvCK/vAbUuH5bTEFD4T6uECsrNcnA==",
        {
            "icon-nodes.json": "lucide-nodes.json",
            "LICENSE": "lucide.LICENSE",
        },
    ),
]


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {"packages": [], "files": {}}
    for name, version, license_id, integrity, paths in PACKAGES:
        url = f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz"
        with urllib.request.urlopen(url, timeout=30) as response:
            archive = response.read()
        actual = base64.b64encode(hashlib.sha512(archive).digest()).decode()
        if actual != integrity:
            raise ValueError(f"Integrity mismatch: {name}")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            for source, destination in paths.items():
                member = package.extractfile(f"package/{source}")
                if member is None:
                    raise ValueError(f"Missing package file: {source}")
                content = member.read()
                if destination == "lucide-nodes.json":
                    all_icons = json.loads(content)
                    names = [
                        "house",
                        "shield-alert",
                        "clapperboard",
                        "folder-open",
                        "messages-square",
                        "sliders-horizontal",
                        "chart-no-axes-combined",
                        "settings",
                        "bell",
                        "menu",
                        "x",
                        "chevron-down",
                        "chevron-right",
                        "search",
                        "check",
                        "circle-help",
                        "triangle-alert",
                        "clock",
                        "camera",
                        "video",
                        "package",
                        "car",
                        "person-standing",
                        "arrow-right",
                        "play",
                        "pause",
                        "sun",
                        "moon",
                        "send",
                        "paperclip",
                        "image",
                        "scan-line",
                        "plus",
                        "trash-2",
                        "map-pin",
                        "eye",
                        "eye-off",
                        "filter",
                        "maximize-2",
                        "minimize-2",
                        "tree-pine",
                    ]
                    content = (
                        json.dumps({n: all_icons[n] for n in names}, indent=2) + "\n"
                    ).encode()
                (ROOT / destination).write_bytes(content)
                manifest["files"][destination] = hashlib.sha256(content).hexdigest()
                if destination == "lucide-nodes.json":
                    module = b"export const icons = " + content.rstrip() + b";\n"
                    (ROOT / "lucide.js").write_bytes(module)
                    manifest["files"]["lucide.js"] = hashlib.sha256(module).hexdigest()
        manifest["packages"].append(
            {
                "name": name,
                "version": version,
                "license": license_id,
                "source": url,
                "integrity": f"sha512-{integrity}",
            }
        )
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
