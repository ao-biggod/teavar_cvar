# -*- coding: utf-8 -*-
"""Lightweight TEAVAR routing-mode helpers — no Gurobi dependency."""
from typing import Optional, Tuple


def _hub(data) -> int:
    return int(getattr(data, "hub", 0))


def teavar_flow_anchors(data, i: Optional[int] = None) -> Tuple[int, int]:
    """Determine ingress/egress anchor nodes for P_cand lookups.

    - ``hub``: (hub, hub)
    - ``per_task_od`` + ``i``: (task_src[i], task_dst[i])
    - ``umcf_global``: (umcf_vs, umcf_vt)
    - ``umcf_per_task`` + ``i``: (umcf_task_src[i], umcf_task_dst[i])
    - ``hub`` + ``umcf_virtual_nodes``: same as umcf_global
    """
    mode = getattr(data, "routing_mode", "hub")

    if mode == "umcf_per_task":
        if i is None:
            raise ValueError(
                "routing_mode='umcf_per_task' requires task index i."
            )
        src_map = getattr(data, "umcf_task_src", None)
        dst_map = getattr(data, "umcf_task_dst", None)
        if not src_map or not dst_map:
            raise ValueError("umcf_per_task requires data.umcf_task_src / umcf_task_dst")
        if i not in src_map or i not in dst_map:
            raise ValueError(f"task index {i} missing in umcf_task_src/dst")
        return int(src_map[i]), int(dst_map[i])

    if mode == "umcf_global" or (
        mode == "hub" and getattr(data, "umcf_virtual_nodes", False)
    ):
        vs = getattr(data, "umcf_vs", None)
        vt = getattr(data, "umcf_vt", None)
        if vs is None or vt is None:
            raise ValueError("umcf_global missing data.umcf_vs / data.umcf_vt")
        return int(vs), int(vt)

    if mode in ("per_task_od", "umcf_per_task") and i is not None:
        task_src = getattr(data, "task_src", None)
        task_dst = getattr(data, "task_dst", None)
        if not task_src or not task_dst:
            raise ValueError("per_task_od requires data.task_src / task_dst")
        if i not in task_src or i not in task_dst:
            raise ValueError(f"task index {i} missing in task_src/dst")
        return int(task_src[i]), int(task_dst[i])

    h = _hub(data)
    return h, h
