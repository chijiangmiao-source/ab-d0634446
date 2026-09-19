"""交叉验证与端到端测试。可直接 `python tests/test_analyzer.py` 运行，也兼容 pytest。"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import solve
from app.validation import validate_request
from app.server import Handler, canonical_dumps
from brute import brute_force


def make_endpoints(n, rng):
    """每个断端随机两侧晶粒标识。"""
    return [
        {"grain_left": rng.randrange(0, 5), "grain_right": rng.randrange(0, 5)}
        for _ in range(n)
    ]


def compatible(endpoints, a, b):
    ea, eb = endpoints[a], endpoints[b]
    return ea["grain_left"] == eb["grain_right"] and ea["grain_right"] == eb["grain_left"]


def build_random_case(n, rng, edge_prob=0.7, extra_incompatible=False):
    endpoints = make_endpoints(n, rng)
    candidates = []
    for a in range(n):
        for b in range(a + 1, n):
            if compatible(endpoints, a, b) and rng.random() < edge_prob:
                candidates.append(
                    {"endpoint_a": a, "endpoint_b": b, "cost": rng.randrange(0, 5)}
                )
    return {"endpoints": endpoints, "candidates": candidates}


def run_solver(payload):
    errors, endpoints, candidates = validate_request(payload)
    assert not errors, errors
    return solve(endpoints, candidates)


def cross_check_case(n, rng, edge_prob):
    payload = build_random_case(n, rng, edge_prob)
    result = run_solver(payload)
    weight = {(c["endpoint_a"], c["endpoint_b"]): c["cost"] for c in payload["candidates"]}
    best, opt_matches, count = brute_force(n, weight)

    if best is None:
        assert result["status"] == "no_solution", result
        return

    assert result["status"] == "optimal"
    assert result["total_cost"] == best, (result["total_cost"], best)
    assert int(result["optimal_solution_count"]) == count, (
        result["optimal_solution_count"],
        count,
    )

    # 规范缝合 = 排序端点对序列的字典序最小最优解
    expected_canon = min(sorted(sorted(p) for p in m) for m in opt_matches)
    assert result["canonical_stitching"] == expected_canon, (
        result["canonical_stitching"],
        expected_canon,
    )
    # 规范缝合本身确实是最优解
    got_pairs = {tuple(p) for p in result["canonical_stitching"]}
    assert got_pairs in opt_matches

    # 歧义分类逐一核对
    by_pair = {tuple(e["connection"]): e for e in result["candidate_classification"]}
    assert len(by_pair) == len(payload["candidates"])
    for (a, b), w in weight.items():
        contained = sum(1 for m in opt_matches if (a, b) in m)
        entry = by_pair[(a, b)]
        assert int(entry["optimal_solutions_containing_it"]) == contained, (
            (a, b),
            entry,
            contained,
        )
        label = "all" if contained == count else ("some" if contained > 0 else "none")
        assert entry["classification"] == label, ((a, b), entry, label)
        assert entry["cost"] == w

    common = frozenset.intersection(*opt_matches)
    union = frozenset.union(*opt_matches)
    assert result["connections_in_all_optima"] == sorted(list(p) for p in common)
    assert result["connections_in_some_optima"] == sorted(
        list(p) for p in union - common
    )


def test_random_cross_check():
    rng = random.Random(20260919)
    for n in (2, 4, 6, 8, 10, 12):
        for _ in range(40):
            cross_check_case(n, rng, rng.choice([0.3, 0.6, 1.0]))


def test_explicit_ties():
    # 4 个端点，两种非交叉最优：{(0,1),(2,3)} 与 {(0,3),(1,2)} 代价相同
    # 晶粒标识：0/1 配对，2/3 配对，且 (0,3)/(1,2) 也反向对应
    # 端点两侧：(A,B)(B,A) 配；让 0=(1,2),1=(2,1),2=(3,4),3=(4,3)
    # 再加 0<->3 需 (1,2)==(3的右,3的左) 不同，改为构造全部可配：
    endpoints = [
        {"grain_left": 1, "grain_right": 2},  # 0
        {"grain_left": 2, "grain_right": 1},  # 1
        {"grain_left": 1, "grain_right": 2},  # 2
        {"grain_left": 2, "grain_right": 1},  # 3
    ]
    candidates = [
        {"endpoint_a": 0, "endpoint_b": 1, "cost": 1},
        {"endpoint_a": 1, "endpoint_b": 2, "cost": 1},
        {"endpoint_a": 2, "endpoint_b": 3, "cost": 1},
        {"endpoint_a": 0, "endpoint_b": 3, "cost": 1},
    ]
    result = run_solver({"endpoints": endpoints, "candidates": candidates})
    assert result["status"] == "optimal"
    assert result["total_cost"] == 2
    assert int(result["optimal_solution_count"]) == 2
    assert result["has_multiple_optima"] is True
    # 排序端点对：[[0,1],[2,3]] 与 [[0,3],[1,2]]，字典序前者更小
    assert result["canonical_stitching"] == [[0, 1], [2, 3]]
    labels = {tuple(e["connection"]): e["classification"] for e in result["candidate_classification"]}
    assert labels[(0, 1)] == "some"
    assert labels[(2, 3)] == "some"
    assert labels[(0, 3)] == "some"
    assert labels[(1, 2)] == "some"
    assert result["connections_in_all_optima"] == []


def test_unique_optimum_marks_all():
    endpoints = [
        {"grain_left": 1, "grain_right": 2},
        {"grain_left": 2, "grain_right": 1},
        {"grain_left": 1, "grain_right": 2},
        {"grain_left": 2, "grain_right": 1},
    ]
    candidates = [
        {"endpoint_a": 0, "endpoint_b": 1, "cost": 1},
        {"endpoint_a": 2, "endpoint_b": 3, "cost": 1},
        {"endpoint_a": 0, "endpoint_b": 3, "cost": 5},
        {"endpoint_a": 1, "endpoint_b": 2, "cost": 5},
    ]
    result = run_solver({"endpoints": endpoints, "candidates": candidates})
    assert result["total_cost"] == 2
    assert int(result["optimal_solution_count"]) == 1
    assert result["connections_in_all_optima"] == [[0, 1], [2, 3]]
    labels = {tuple(e["connection"]): e["classification"] for e in result["candidate_classification"]}
    assert labels[(0, 1)] == "all" and labels[(2, 3)] == "all"
    assert labels[(0, 3)] == "none" and labels[(1, 2)] == "none"


def test_no_solution():
    endpoints = [
        {"grain_left": 1, "grain_right": 2},
        {"grain_left": 2, "grain_right": 1},
        {"grain_left": 1, "grain_right": 2},
        {"grain_left": 2, "grain_right": 1},
    ]
    # 候选合法但无法覆盖所有端点（2、3 缺少奇数距搭档）
    candidates = [
        {"endpoint_a": 0, "endpoint_b": 1, "cost": 1},
        {"endpoint_a": 0, "endpoint_b": 3, "cost": 1},
    ]
    result = run_solver({"endpoints": endpoints, "candidates": candidates})
    assert result["status"] == "no_solution"


def test_validation_errors_locatable():
    # 奇数个端点
    payload = {
        "endpoints": [{"grain_left": 1, "grain_right": 2}] * 3,
        "candidates": [],
    }
    errors, _, _ = validate_request(payload)
    assert any("偶数" in e["message"] and e["field"] == "endpoints" for e in errors)

    # 越界、负代价、自连、布尔值
    payload = {
        "endpoints": [
            {"grain_left": 1, "grain_right": 2},
            {"grain_left": 2, "grain_right": 1},
            {"grain_left": 3, "grain_right": 4},
            {"grain_left": 4, "grain_right": 3},
        ],
        "candidates": [
            {"endpoint_a": 0, "endpoint_b": 4, "cost": 1},
            {"endpoint_a": 1, "endpoint_b": 1, "cost": 0},
            {"endpoint_a": 2, "endpoint_b": 3, "cost": -1},
            {"endpoint_a": 2, "endpoint_b": 3, "cost": True},
        ],
    }
    errors, _, _ = validate_request(payload)
    fields = {e["field"] for e in errors}
    assert "candidates[0].endpoint_b" in fields
    assert "candidates[1]" in fields
    assert "candidates[2].cost" in fields
    assert "candidates[3].cost" in fields

    # 反向重复候选对
    payload = {
        "endpoints": [
            {"grain_left": 1, "grain_right": 2},
            {"grain_left": 2, "grain_right": 1},
        ],
        "candidates": [
            {"endpoint_a": 0, "endpoint_b": 1, "cost": 3},
            {"endpoint_a": 1, "endpoint_b": 0, "cost": 4},
        ],
    }
    errors, _, _ = validate_request(payload)
    assert any("重复" in e["message"] and e["field"] == "candidates[1]" for e in errors)

    # 晶粒标识不反向对应
    payload = {
        "endpoints": [
            {"grain_left": 1, "grain_right": 2},
            {"grain_left": 9, "grain_right": 8},
        ],
        "candidates": [{"endpoint_a": 0, "endpoint_b": 1, "cost": 0}],
    }
    errors, _, _ = validate_request(payload)
    assert any("反向对应" in e["message"] and e["field"] == "candidates[0]" for e in errors)

    # 缺字段 / 类型错
    payload = {"endpoints": [{"grain_left": 1}], "candidates": "x"}
    errors, _, _ = validate_request(payload)
    fields = {e["field"] for e in errors}
    assert "endpoints[0].grain_right" in fields
    assert "candidates" in fields


def test_performance_400():
    rng = random.Random(7)
    # 端点取向左右交替：任意奇距端点对都反向对应（稠密可行）
    endpoints = [
        ({"grain_left": 1, "grain_right": 2} if i % 2 == 0 else {"grain_left": 2, "grain_right": 1})
        for i in range(400)
    ]
    candidates = []
    for a in range(400):
        for b in range(a + 1, 400):
            if (b - a) % 2 == 1:
                candidates.append(
                    {"endpoint_a": a, "endpoint_b": b, "cost": rng.randrange(0, 1_000_000)}
                )
    t0 = time.time()
    result = run_solver({"endpoints": endpoints, "candidates": candidates})
    elapsed = time.time() - t0
    assert result["status"] == "optimal"
    assert len(result["canonical_stitching"]) == 200
    assert elapsed < 60, f"400 点稠密 DP 耗时 {elapsed:.1f}s"
    print(f"\n[perf] n=400 稠密候选({len(candidates)}) 耗时 {elapsed:.2f}s")


# ---------------------- HTTP 端到端 ----------------------


class ServerHarness:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def request(self, method, path, body=None, raw=False):
        data = body if raw else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method
        )
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


def test_http_end_to_end():
    srv = ServerHarness()
    try:
        status, body = srv.request("GET", "/health")
        assert status == 200
        assert json.loads(body)["status"] == "healthy"

        payload = {
            "endpoints": [
                {"grain_left": 1, "grain_right": 2},
                {"grain_left": 2, "grain_right": 1},
                {"grain_left": 1, "grain_right": 2},
                {"grain_left": 2, "grain_right": 1},
            ],
            "candidates": [
                {"endpoint_a": 0, "endpoint_b": 1, "cost": 1},
                {"endpoint_a": 1, "endpoint_b": 2, "cost": 1},
                {"endpoint_a": 2, "endpoint_b": 3, "cost": 1},
                {"endpoint_a": 0, "endpoint_b": 3, "cost": 1},
            ],
        }
        # 同请求重复提交 -> 字节等价
        _, b1 = srv.request("POST", "/analyze", payload)
        _, b2 = srv.request("POST", "/analyze", payload)
        assert b1 == b2, "重复提交响应不一致"

        # 改变字段/候选提交顺序：响应是请求内容的纯函数，仍字节等价
        shuffled = {
            "candidates": list(reversed(payload["candidates"])),
            "endpoints": payload["endpoints"],
        }
        _, b3 = srv.request("POST", "/analyze", shuffled)
        assert b1 == b3, "候选顺序不应影响响应字节"
        r1 = json.loads(b1)

        # 校验错误
        status, body = srv.request(
            "POST", "/analyze", {"endpoints": [], "candidates": []}
        )
        assert status == 400
        err = json.loads(body)
        assert err["code"] == "VALIDATION_ERROR" and err["errors"][0]["field"] == "endpoints"

        # 非法 JSON
        status, body = srv.request("POST", "/analyze", b"{not json", raw=True)
        assert status == 400 and json.loads(body)["code"] == "INVALID_JSON"

        # 无解
        no_sol = {
            "endpoints": [
                {"grain_left": 1, "grain_right": 2},
                {"grain_left": 2, "grain_right": 1},
                {"grain_left": 3, "grain_right": 4},
                {"grain_left": 4, "grain_right": 3},
            ],
            "candidates": [{"endpoint_a": 0, "endpoint_b": 1, "cost": 1}],
        }
        status, body = srv.request("POST", "/analyze", no_sol)
        assert status == 422 and json.loads(body)["code"] == "NO_SOLUTION"

        # 404
        status, _ = srv.request("GET", "/nope")
        assert status == 404
    finally:
        srv.stop()


def test_byte_equivalence_across_instances():
    """两个独立服务实例（无共享状态）对同一请求给出字节相同响应。"""
    a, b = ServerHarness(), ServerHarness()
    try:
        rng = random.Random(99)
        payload = build_random_case(16, rng, 0.8)
        _, ba = a.request("POST", "/analyze", payload)
        _, bb = b.request("POST", "/analyze", payload)
        assert ba == bb
        # 规范化 JSON 本身确定性
        assert canonical_dumps({"x": 1, "y": [1, 2]}) == canonical_dumps(
            {"y": [1, 2], "x": 1}
        )
    finally:
        a.stop()
        b.stop()


if __name__ == "__main__":
    fns = [
        test_random_cross_check,
        test_explicit_ties,
        test_unique_optimum_marks_all,
        test_no_solution,
        test_validation_errors_locatable,
        test_http_end_to_end,
        test_byte_equivalence_across_instances,
        test_performance_400,
    ]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("ALL TESTS PASSED")
