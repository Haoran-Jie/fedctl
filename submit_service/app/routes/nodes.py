from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..config import SubmitConfig
from ..nomad_client import NomadError
from ..nomad_inventory import NomadInventory
from .submissions import authenticate, get_config

router = APIRouter()


@router.get("/v1/nodes")
def list_nodes(
    request: Request,
    include_allocs: bool = Query(True),
    status: str | None = Query(None),
    node_class: str | None = Query(None),
    device_type: str | None = Query(None),
    cfg: SubmitConfig = Depends(get_config),
) -> list[dict[str, object]]:
    authenticate(request, cfg)
    inventory: NomadInventory = request.app.state.inventory
    try:
        nodes = inventory.list_nodes(include_allocs=include_allocs)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NomadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    filtered = []
    for node in nodes:
        if status is not None and node.get("status") != status:
            continue
        if node_class is not None and node.get("node_class") != node_class:
            continue
        if device_type is not None and node.get("device_type") != device_type:
            continue
        filtered.append(node)
    return filtered
