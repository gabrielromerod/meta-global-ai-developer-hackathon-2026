# Consumer round coordination

Lead owns integration. Append requests/readiness below; do not edit another worker's
owned paths. Frozen contracts: docs/contracts/api.md, web/design/tokens.css,
web/design/README.md and web/fixtures/*.json. Only lead changes frozen files.

| Worker | Branch | Owned paths | State |
| --- | --- | --- | --- |
| A | ws/a-shell | web/design except tokens.css and README.md; web/shell; web/vendor | pending freeze |
| B | ws/b-pages | web/pages | pending freeze |
| C | ws/c-twin | web/twin | pending freeze |
| D | ws/d-chat | web/chat | queued until a background slot opens (owner approved) |

Requests must name requester, needed contract/component/token, fixture workaround,
and whether it blocks final integration. Keep working on independent fixture work.
Lead answers after each completed backend item; no mid-item interruptions required.

## Requests and readiness

- Lead: normalized /api/ui/state/search/chat endpoints are MISSING until Phase 2.
  Fixtures define their contract; no worker should add backend routes or shared hooks.
