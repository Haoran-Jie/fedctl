"""msgbench: message-size benchmark ClientApp."""

import time

from flwr.app import ConfigRecord, Context, Message, RecordDict
from flwr.clientapp import ClientApp

app = ClientApp()


@app.query()
def query(msg: Message, context: Context) -> Message:  # pylint: disable=unused-argument
    started = time.perf_counter()
    config = msg.content["msgbench_config"]
    if not isinstance(config, ConfigRecord):
        reply = ConfigRecord({"error": "missing msgbench_config"})
        return Message(RecordDict({"msgbench_result": reply}), reply_to=msg)

    request_payload = config.get("request_payload")
    request_bytes = len(request_payload) if isinstance(request_payload, bytes) else 0
    reply_bytes_raw = config.get("reply_bytes")
    reply_bytes = int(reply_bytes_raw) if isinstance(reply_bytes_raw, int) else 0
    reply_bytes = max(reply_bytes, 0)
    response_payload = b"y" * reply_bytes

    elapsed_s = time.perf_counter() - started
    result = ConfigRecord(
        {
            "request_bytes_seen": request_bytes,
            "response_payload": response_payload,
            "response_bytes": len(response_payload),
            "client_elapsed_s": elapsed_s,
        }
    )
    return Message(RecordDict({"msgbench_result": result}), reply_to=msg)

