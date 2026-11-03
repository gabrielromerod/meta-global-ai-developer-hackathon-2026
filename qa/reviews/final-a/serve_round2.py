"""Isolated review server; assert constructed settings before opening a listener."""

import json
import sys
from pathlib import Path

import uvicorn

from vigil.api.app import create_app
from vigil.settings import Settings

port = int(sys.argv[1])
settings = Settings(_env_file=None)
suffix = sys.argv[2] if len(sys.argv) > 2 else ("qa-final-a" if port == 8118 else "qa-final-a-edge")
expected = (Path.cwd() / "data" / suffix).resolve()
assert settings.meta_cache_only is True
assert settings.meta_base_url == "http://127.0.0.1:9/v1"
assert settings.cache_dir.resolve() == expected / "cache"
assert settings.db_path.resolve() == expected / "vigil.db"
assert settings.ledger_path.resolve() == expected / "ledger.db"
assert settings.model_api_key.get_secret_value() == "invalid"
record = {
    "port": port,
    "mode": settings.mode,
    "meta_cache_only": settings.meta_cache_only,
    "closed_loopback_model_base": settings.meta_base_url,
    "cache_dir": str(settings.cache_dir.relative_to(Path.cwd())),
    "db_path": str(settings.db_path.relative_to(Path.cwd())),
    "ledger_path": str(settings.ledger_path.relative_to(Path.cwd())),
    "invalid_key_verified": True,
}
Path(f"qa/reviews/final-a/settings-round2-{port}.json").write_text(
    json.dumps(record, indent=2), encoding="utf-8"
)
print(json.dumps(record), flush=True)
uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
