from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class SubmitServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmitServiceClient:
    endpoint: str
    token: str | None = None
    user: str | None = None
    timeout: float = 15.0

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.user:
            headers["X-Submit-User"] = self.user
        return headers

    def create_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/submissions", json_payload=payload)

    def list_submissions(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/submissions", params={"limit": str(limit)})

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/submissions/{submission_id}")

    def get_logs(
        self,
        submission_id: str,
        *,
        job: str = "submit",
        task: str | None = None,
        stderr: bool = True,
        follow: bool = False,
        index: int = 1,
    ) -> str:
        params = {
            "job": job,
            "index": str(index),
            "stderr": "true" if stderr else "false",
            "follow": "true" if follow else "false",
        }
        if task:
            params["task"] = task
        return self._request(
            "GET",
            f"/v1/submissions/{submission_id}/logs",
            params=params,
            text_response=True,
        )

    def cancel_submission(self, submission_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/submissions/{submission_id}/cancel")

    def purge_submissions(self) -> dict[str, Any]:
        return self._request("POST", "/v1/submissions/purge")

    def update_results(
        self,
        submission_id: str,
        *,
        result_location: str | None = None,
        artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if result_location:
            payload["result_location"] = result_location
        if artifacts is not None:
            payload["artifacts"] = artifacts
        return self._request("POST", f"/v1/submissions/{submission_id}/results", json_payload=payload)

    def list_nodes(
        self,
        *,
        include_allocs: bool = False,
        status: str | None = None,
        node_class: str | None = None,
        device_type: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "include_allocs": "true" if include_allocs else "false",
        }
        if status:
            params["status"] = status
        if node_class:
            params["node_class"] = node_class
        if device_type:
            params["device_type"] = device_type
        return self._request("GET", "/v1/nodes", params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: Any | None = None,
        params: dict[str, str] | None = None,
        text_response: bool = False,
    ) -> Any:
        url = self.endpoint.rstrip("/") + path
        try:
            response = httpx.request(
                method,
                url,
                json=json_payload,
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise SubmitServiceError(str(exc)) from exc
        if response.status_code >= 400:
            raise SubmitServiceError(
                f"Submit service error {response.status_code}: {response.text[:200]}"
            )
        if text_response:
            return response.text
        return response.json()
