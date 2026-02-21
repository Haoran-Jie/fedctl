from __future__ import annotations

from typing import Any, Dict

import httpx
import base64

from fedctl.config.schema import EffectiveConfig
from .errors import NomadConnectionError, NomadHTTPError, NomadTLSError


class NomadClient:
    def __init__(self, cfg: EffectiveConfig):
        self.cfg = cfg

        headers: Dict[str, str] = {}
        if cfg.nomad_token:
            headers["X-Nomad-Token"] = cfg.nomad_token
        if cfg.namespace:
            headers["X-Nomad-Namespace"] = cfg.namespace

        self._client = httpx.Client(
            base_url=cfg.endpoint.rstrip("/"),
            headers=headers,
            verify=True,
            timeout=10.0,
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        json_payload: Any | None = None,
        params: Dict[str, str] | None = None,
    ) -> Any:
        try:
            r = self._client.request(method, path, json=json_payload, params=params)
        except httpx.ConnectError as e:
            raise NomadConnectionError(str(e)) from e
        except httpx.ReadTimeout as e:
            raise NomadConnectionError(f"Timeout: {e}") from e
        except httpx.TransportError as e:
            msg = str(e)
            if "CERTIFICATE_VERIFY_FAILED" in msg or "certificate" in msg.lower():
                raise NomadTLSError(msg) from e
            raise NomadConnectionError(msg) from e

        if r.status_code >= 400:
            text = r.text.strip()
            raise NomadHTTPError(r.status_code, text[:500])

        ct = r.headers.get("content-type", "")
        if "application/json" in ct:
            return r.json()
        return r.text

    def _get(self, path: str, params: Dict[str, str] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, payload: Any) -> Any:
        return self._request("POST", path, json_payload=payload)

    def _request_raw(self, path: str, params: Dict[str, str] | None = None) -> bytes:
        try:
            r = self._client.request("GET", path, params=params)
        except httpx.ConnectError as e:
            raise NomadConnectionError(str(e)) from e
        except httpx.ReadTimeout as e:
            raise NomadConnectionError(f"Timeout: {e}") from e
        except httpx.TransportError as e:
            msg = str(e)
            if "CERTIFICATE_VERIFY_FAILED" in msg or "certificate" in msg.lower():
                raise NomadTLSError(msg) from e
            raise NomadConnectionError(msg) from e

        if r.status_code >= 400:
            text = r.text.strip()
            raise NomadHTTPError(r.status_code, text[:500])
        return r.content

    def status_leader(self) -> str:
        data = self._get("/v1/status/leader")
        if isinstance(data, str):
            return data.strip().strip('"')
        return str(data)

    def agent_self(self) -> Dict[str, Any]:
        data = self._get("/v1/agent/self")
        if not isinstance(data, dict):
            raise NomadHTTPError(500, "Unexpected response for agent self")
        return data

    def nodes(self) -> Any:
        return self._get("/v1/nodes")

    def submit_job(self, job: Dict[str, Any]) -> Any:
        return self._post("/v1/jobs", job)

    def job_allocations(self, job_name: str) -> Any:
        return self._get(f"/v1/job/{job_name}/allocations")

    def job(self, job_name: str) -> Any:
        return self._get(f"/v1/job/{job_name}")

    def alloc_logs(
        self,
        alloc_id: str,
        task: str,
        *,
        stderr: bool = True,
        follow: bool = False,
    ) -> str:
        params = {
            "task": task,
            "type": "stderr" if stderr else "stdout",
            "follow": "true" if follow else "false",
        }
        data = self._get(f"/v1/client/fs/logs/{alloc_id}", params=params)
        if isinstance(data, dict):
            raw = data.get("Data")
            if isinstance(raw, str):
                try:
                    return base64.b64decode(raw).decode("utf-8", errors="replace")
                except (ValueError, OSError):
                    return raw
            return str(data)
        return data if isinstance(data, str) else str(data)

    def alloc_fs_ls(self, alloc_id: str, path: str) -> Any:
        return self._get(f"/v1/client/fs/ls/{alloc_id}", params={"path": path})

    def alloc_fs_cat(self, alloc_id: str, path: str) -> bytes:
        return self._request_raw(f"/v1/client/fs/cat/{alloc_id}", params={"path": path})

    def allocation(self, alloc_id: str) -> Any:
        return self._get(f"/v1/allocation/{alloc_id}")

    def jobs(self) -> Any:
        return self._get("/v1/jobs")

    def stop_job(self, job_name: str, *, purge: bool = False) -> Any:
        suffix = "?purge=true" if purge else ""
        return self._request("DELETE", f"/v1/job/{job_name}{suffix}")

    def acl_enabled(self) -> bool:
        try:
            data = self.agent_self()
        except NomadHTTPError as exc:
            if exc.status_code == 403:
                return True
            raise
        cfg = data.get("Config", {}) if isinstance(data, dict) else {}
        acl = cfg.get("ACL", {}) if isinstance(cfg, dict) else {}
        enabled = acl.get("Enabled")
        return bool(enabled)

    def create_namespace(self, name: str) -> Any:
        return self._post("/v1/namespace", {"Name": name})

    def namespace(self, name: str) -> Any:
        return self._get(f"/v1/namespace/{name}")

    def delete_namespace(self, name: str) -> Any:
        return self._request("DELETE", f"/v1/namespace/{name}")

    def create_acl_policy(self, name: str, rules: str) -> Any:
        payload = {"Name": name, "Rules": rules}
        return self._post(f"/v1/acl/policy/{name}", payload)

    def delete_acl_policy(self, name: str) -> Any:
        return self._request("DELETE", f"/v1/acl/policy/{name}")

    def create_acl_token(
        self,
        name: str,
        policies: list[str],
        *,
        ttl: str | None = None,
    ) -> Any:
        payload: Dict[str, Any] = {"Name": name, "Policies": policies, "Type": "client"}
        if ttl:
            payload["ExpirationTTL"] = ttl
        return self._post("/v1/acl/token", payload)

    def acl_token_self(self) -> Any:
        return self._get("/v1/acl/token/self")

    def delete_acl_token(self, accessor_id: str) -> Any:
        return self._request("DELETE", f"/v1/acl/token/{accessor_id}")
