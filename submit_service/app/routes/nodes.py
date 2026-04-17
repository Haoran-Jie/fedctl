from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..config import SubmitConfig
from ..nomad_client import NomadError
from ..nomad_inventory import NomadInventory
from .submissions import authenticate, get_config

router = APIRouter()


@router.get("/v1/nodes/debug-raw")
def debug_nodes_raw(
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
) -> dict:
    """Debug endpoint to see raw Nomad response"""
    authenticate(request, cfg)
    if not cfg.nomad_endpoint:
        return {"error": "Nomad endpoint not configured"}

    from ..nomad_client import NomadClient, NomadError
    client = NomadClient(
        cfg.nomad_endpoint,
        token=cfg.nomad_token,
        namespace=cfg.nomad_namespace,
        tls_ca=cfg.nomad_tls_ca,
        tls_skip_verify=cfg.nomad_tls_skip_verify,
    )
    try:
        nodes_list = client.nodes()
        if not nodes_list:
            return {"error": "No nodes returned", "nodes": []}

        first_node = nodes_list[0] if isinstance(nodes_list, list) else None
        if not first_node:
            return {"error": "First node is not a dict", "first_node_type": str(type(first_node))}

        node_id = first_node.get("ID")
        if not node_id:
            return {"error": "Node has no ID", "first_node": first_node}

        detail = client.node(node_id)
        return {
            "node_id": node_id,
            "node_name": first_node.get("Name"),
            "detail_structure": {
                "has_Node": "Node" in detail if isinstance(detail, dict) else False,
                "detail_keys": list(detail.keys()) if isinstance(detail, dict) else str(type(detail)),
                "node_keys": list(detail.get("Node", {}).keys()) if isinstance(detail.get("Node"), dict) else "N/A",
            },
            "Resources": detail.get("Node", {}).get("Resources") if isinstance(detail, dict) else None,
            "NodeResources": detail.get("Node", {}).get("NodeResources") if isinstance(detail, dict) else None,
            "full_detail": detail,
        }
    except NomadError as exc:
        return {"error": str(exc)}
    finally:
        client.close()


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
