"""请求校验：把所有字段/候选矛盾收集为可定位的校验错误。

错误结构：{"code": "VALIDATION_ERROR", "message": ..., "errors": [
    {"field": "endpoints[3].grain_right", "message": "..."}, ...
]}
field 使用 JSON 指针风格路径，候选错误同时给出端点下标。
"""

from __future__ import annotations

from typing import Any

MAX_ENDPOINTS = 400
MAX_COST = 10**12  # 证据代价上界，防止超大整数拖垮 DP
GRAIN_ID_MAX = 10**15


def _is_int(value: Any) -> bool:
    # bool 是 int 的子类，需显式排除
    return isinstance(value, int) and not isinstance(value, bool)


def _err(field: str, message: str) -> dict:
    return {"field": field, "message": message}


def validate_request(payload: Any) -> tuple[list[dict], list[dict] | None, list | None]:
    """返回 (errors, endpoints, candidates)。errors 非空时后两者为 None。"""
    errors: list[dict] = []

    if not isinstance(payload, dict):
        return [_err("", "请求体必须是 JSON 对象")], None, None

    raw_endpoints = payload.get("endpoints")
    raw_candidates = payload.get("candidates")

    endpoints: list[dict] = []
    if "endpoints" not in payload:
        errors.append(_err("endpoints", "缺少必填字段 endpoints"))
    elif not isinstance(raw_endpoints, list):
        errors.append(_err("endpoints", "endpoints 必须是数组"))
    else:
        n = len(raw_endpoints)
        if n < 2 or n > MAX_ENDPOINTS:
            errors.append(
                _err("endpoints", f"断端数量必须在 2 到 {MAX_ENDPOINTS} 之间，当前为 {n}")
            )
        if n % 2 != 0:
            errors.append(_err("endpoints", f"断端数量必须为偶数，当前为 {n}"))

        for i, ep in enumerate(raw_endpoints):
            base = f"endpoints[{i}]"
            if not isinstance(ep, dict):
                errors.append(_err(base, "断端必须是对象"))
                endpoints.append({"grain_left": None, "grain_right": None})
                continue
            gl = ep.get("grain_left")
            gr = ep.get("grain_right")
            if "grain_left" not in ep:
                errors.append(_err(f"{base}.grain_left", "缺少必填字段 grain_left"))
            elif not _is_int(gl):
                errors.append(_err(f"{base}.grain_left", "晶粒标识必须为整数"))
            elif not (0 <= gl <= GRAIN_ID_MAX):
                errors.append(
                    _err(f"{base}.grain_left", f"晶粒标识必须在 0 到 {GRAIN_ID_MAX} 之间")
                )
            if "grain_right" not in ep:
                errors.append(_err(f"{base}.grain_right", "缺少必填字段 grain_right"))
            elif not _is_int(gr):
                errors.append(_err(f"{base}.grain_right", "晶粒标识必须为整数"))
            elif not (0 <= gr <= GRAIN_ID_MAX):
                errors.append(
                    _err(f"{base}.grain_right", f"晶粒标识必须在 0 到 {GRAIN_ID_MAX} 之间")
                )
            endpoints.append(
                {
                    "grain_left": gl if _is_int(gl) else None,
                    "grain_right": gr if _is_int(gr) else None,
                }
            )

    n_endpoints = len(endpoints) if isinstance(raw_endpoints, list) else 0
    candidates: list = []
    if "candidates" not in payload:
        errors.append(_err("candidates", "缺少必填字段 candidates"))
    elif not isinstance(raw_candidates, list):
        errors.append(_err("candidates", "candidates 必须是数组"))
    else:
        if len(raw_candidates) > 200_000:
            errors.append(_err("candidates", "候选连接数量超过上限 200000"))
        seen_pairs: set[tuple[int, int]] = set()
        for k, cand in enumerate(raw_candidates):
            base = f"candidates[{k}]"
            if not isinstance(cand, dict):
                errors.append(_err(base, "候选连接必须是对象"))
                continue
            a = cand.get("endpoint_a")
            b = cand.get("endpoint_b")
            cost = cand.get("cost")
            idx_ok = True
            for fname, val in (("endpoint_a", a), ("endpoint_b", b)):
                if not _is_int(val):
                    errors.append(_err(f"{base}.{fname}", "端点下标必须为整数"))
                    idx_ok = False
                elif n_endpoints == 0:
                    errors.append(
                        _err(
                            f"{base}.{fname}",
                            "端点引用无效：endpoints 缺失、为空或不是数组",
                        )
                    )
                    idx_ok = False
                elif not (0 <= val < n_endpoints):
                    errors.append(
                        _err(
                            f"{base}.{fname}",
                            f"端点下标超出范围 [0, {n_endpoints - 1}]，当前为 {val}",
                        )
                    )
                    idx_ok = False
            if idx_ok and a == b:
                errors.append(_err(base, f"候选连接不能自连（endpoint_a == endpoint_b == {a}）"))
                idx_ok = False
            if not _is_int(cost):
                errors.append(_err(f"{base}.cost", "证据代价必须为非负整数"))
            elif not (0 <= cost <= MAX_COST):
                errors.append(
                    _err(f"{base}.cost", f"证据代价必须为 0 到 {MAX_COST} 之间的非负整数")
                )
            # 晶粒反向对应矛盾：候选两端的两侧标识必须互换一致
            if idx_ok:
                ea, eb = endpoints[a], endpoints[b]
                if (
                    ea["grain_left"] is not None
                    and ea["grain_right"] is not None
                    and eb["grain_left"] is not None
                    and eb["grain_right"] is not None
                    and not (
                        ea["grain_left"] == eb["grain_right"]
                        and ea["grain_right"] == eb["grain_left"]
                    )
                ):
                    errors.append(
                        _err(
                            base,
                            f"候选两端晶粒标识不反向对应：端点 {a} 两侧为 "
                            f"({ea['grain_left']}, {ea['grain_right']})，端点 {b} 两侧为 "
                            f"({eb['grain_left']}, {eb['grain_right']})；要求左-右、右-左分别相等",
                        )
                    )
            if idx_ok:
                lo, hi = (int(a), int(b)) if a < b else (int(b), int(a))
                pair = (lo, hi)
                if pair in seen_pairs:
                    errors.append(
                        _err(
                            base,
                            f"候选连接 ({lo}, {hi}) 与之前候选重复"
                            "（同一端点对只允许给出一个代价，端点顺序不同也算重复）",
                        )
                    )
                else:
                    seen_pairs.add(pair)
                    if _is_int(cost) and 0 <= cost <= MAX_COST:
                        candidates.append(
                            {"endpoint_a": lo, "endpoint_b": hi, "cost": int(cost)}
                        )

    if errors:
        return errors, None, None
    return [], endpoints, candidates
