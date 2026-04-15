from __future__ import annotations

import base64
import json
from typing import Any, Dict

import httpx


class NomadError(RuntimeError):
    pass


class NomadClient:
    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        namespace: str | None = None,
        tls_ca: str | None = None,
        tls_skip_verify: bool = False,
        timeout: float = 15.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._headers: dict[str, str] = {}
        if token:
            self._headers["X-Nomad-Token"] = token
        if namespace:
            self._headers["X-Nomad-Namespace"] = namespace
        verify: bool | str = True
        if tls_ca:
            verify = tls_ca
        if tls_skip_verify:
            verify = False
        self._client = httpx.Client(base_url=self._endpoint, headers=self._headers, verify=verify, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def submit_job(self, job: dict[str, Any]) -> Any:
        return self._post("/v1/jobs", job)

    def stop_job(self, job_id: str, *, purge: bool = False) -> Any:
        suffix = "?purge=true" if purge else ""
        return self._delete(f"/v1/job/{job_id}{suffix}")

    def job(self, job_id: str) -> Any:
        return self._get(f"/v1/job/{job_id}")

    def job_allocations(self, job_id: str) -> Any:
        return self._get(f"/v1/job/{job_id}/allocations")

    def nodes(self) -> Any:
        return self._get("/v1/nodes")

    def node(self, node_id: str) -> Any:
        return self._get(f"/v1/node/{node_id}")

    def node_allocations(self, node_id: str) -> Any:
        return self._get(f"/v1/node/{node_id}/allocations")

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
        return _decode_alloc_logs_response(data)

    def _get(self, path: str, params: Dict[str, str] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, payload: Any) -> Any:
        return self._request("POST", path, json_payload=payload)

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: Any | None = None,
        params: Dict[str, str] | None = None,
    ) -> Any:
        try:
            resp = self._client.request(method, path, json=json_payload, params=params)
        except httpx.HTTPError as exc:
            raise NomadError(str(exc)) from exc
        if resp.status_code >= 400:
            raise NomadError(f"Nomad error {resp.status_code}: {resp.text[:200]}")
        if "application/json" in resp.headers.get("content-type", ""):
            try:
                return resp.json()
            except ValueError:
                return resp.text
        return resp.text


def _decode_alloc_logs_response(data: Any) -> str:
    payload = data
    if isinstance(data, str):
        payload = _coalesce_alloc_log_payload(data)
        if isinstance(payload, str):
            return payload
    if isinstance(payload, dict):
        raw = payload.get("Data")
        if isinstance(raw, str):
            try:
                return base64.b64decode(raw).decode("utf-8", errors="replace")
            except (ValueError, OSError):
                return raw
        return str(payload)
    return payload if isinstance(payload, str) else str(payload)


def _coalesce_alloc_log_payload(data: str) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        decoder = json.JSONDecoder()
        chunks: list[dict[str, Any]] = []
        idx = 0
        while idx < len(data):
            while idx < len(data) and data[idx].isspace():
                idx += 1
            if idx >= len(data):
                break
            try:
                payload, idx = decoder.raw_decode(data, idx)
            except ValueError:
                return data
            if not isinstance(payload, dict):
                return data
            chunks.append(payload)
        if not chunks:
            return data
        if len(chunks) == 1:
            return chunks[0]
        merged = dict(chunks[-1])
        encoded_parts = []
        for chunk in chunks:
            raw = chunk.get("Data")
            if not isinstance(raw, str):
                return data
            encoded_parts.append(raw)
        merged["Data"] = "".join(encoded_parts)
        return merged
