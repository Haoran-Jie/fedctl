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
        task: str = "submit",
        stderr: bool = True,
        follow: bool = False,
    ) -> str:
        params = {
            "task": task,
            "stderr": "true" if stderr else "false",
            "follow": "true" if follow else "false",
        }
        return self._request(
            "GET",
            f"/v1/submissions/{submission_id}/logs",
            params=params,
            text_response=True,
        )

    def cancel_submission(self, submission_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/submissions/{submission_id}/cancel")

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
