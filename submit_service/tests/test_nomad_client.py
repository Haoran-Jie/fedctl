from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from submit_service.app.nomad_client import _decode_alloc_logs_response


def test_decode_alloc_logs_response_handles_json_string_payload() -> None:
    text = "INFO: decoded from nominal text/plain response\n"
    payload = {
        "Data": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "File": "alloc/logs/submit.stderr.0",
        "Offset": 123,
    }

    decoded = _decode_alloc_logs_response(json.dumps(payload))

    assert decoded == text


def test_decode_alloc_logs_response_preserves_plain_text() -> None:
    text = "plain stderr line\n"

    decoded = _decode_alloc_logs_response(text)

    assert decoded == text
