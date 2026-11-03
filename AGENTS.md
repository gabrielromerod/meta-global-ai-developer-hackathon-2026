# Agent instructions

All agent instructions for this repository live in [`CLAUDE.md`](CLAUDE.md). Read it before
changing anything; it is the single source of truth (commands, layout, invariants, workflow).
The specification is [`docs/spec/vigil-spec.md`](docs/spec/vigil-spec.md).

The six rules that must never be broken:

1. **Code decides, models describe.** The verdict is the pure function in
   `vigil/reasoning/verdict.py`; only rules produce `needs_attention`; gap sentences are
   written by code; Wonder never sees pixels. Roles (`actor_role`) come from spatial origin in
   code, `unknown` fails closed, and Vigil never identifies anyone.
2. **Every Meta model call goes through `MetaClient`** (`vigil/meta/client.py`) with cache,
   budget guard and ledger. No live call without the owner's approval; never a
   `-contributor` model ID; never set `VIGIL_ALLOW_PAID` or the $25 judging cap.
3. **Privacy.** Never commit raw footage, `data/`, `.env`, credentials, GPS metadata, house
   numbers, street-facing frames or audio outside `config/audio_fixtures.json`. Run the
   privacy gate (`make scan`) before any export or `demo/` change.
4. **Test first.** Write the spec-named failing test (spec 12.1), then implement. Tests are
   offline and deterministic; `live`, `gpu`, `e2e` and `hardware` tests are marked.
5. **Respect integration boundaries.** Shared types come from `vigil/models.py`; do not edit
   integrator-owned files (`pyproject.toml`, `uv.lock`, `vigil/models.py`,
   `vigil/settings.py`, `vigil/cli.py`, `vigil/store/schema.sql`, `tests/conftest.py`,
   `Makefile`, `scripts/tasks.ps1`, `.github/**`) without saying so.
6. **Report honestly.** Run `uv run ruff check .`, `uv run ruff format --check .` and
   `uv run pytest`; report what actually happened. Never mark a requirement Verified
   without real-data acceptance.
