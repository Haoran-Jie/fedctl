# Nomad API usage (current codebase)

*Updated: 2026-01-20*

This doc lists the endpoints used by fedctl today.

---

## Common headers
- `X-Nomad-Token: <token>` (required if ACLs enabled)
- `X-Nomad-Namespace: <namespace>` (required by fedctl)

TLS options:

---

## Connectivity
- `GET /v1/status/leader`
- `GET /v1/agent/self`

---

## Nodes / discovery
- `GET /v1/nodes`

---

## Jobs / allocations
- `POST /v1/jobs` (submit rendered JSON jobs)
- `GET /v1/jobs` (list jobs)
- `GET /v1/job/<job>/allocations`
- `GET /v1/allocation/<alloc_id>`
- `DELETE /v1/job/<job>?purge=true|false`

---

## Address resolution (SuperLink)
- Uses allocation **IP + control port** from `/v1/allocation/<alloc_id>`
- No node lookup; no host-only ports

---

## ACL / namespace (register)
- `POST /v1/namespace`
- `GET /v1/namespace/<name>`
- `DELETE /v1/namespace/<name>`

- `POST /v1/acl/policy`
- `DELETE /v1/acl/policy/<name>`

- `POST /v1/acl/token`
- `GET /v1/acl/token/self`
- `DELETE /v1/acl/token/<accessor_id>`

---

## ACL-enabled check
- `GET /v1/agent/self` and `Config.ACL.Enabled`
- If a 403 is returned, ACLs are treated as enabled
