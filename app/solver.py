"""最小代价非交叉完美匹配求解器。

模型
----
断端按顺时针编号 0..n-1（n 为偶数），候选连接是凸多边形弦。
要求：完美匹配（每端恰好一次）、弦互不相交、仅采用晶粒标识反向对应的候选，
总证据代价最小。

算法
----
在倍长链 0..2n-1（位置 p 表示断端 p mod n）上做区间 DP：

    F[l][r] = 区间 [l,r]（顶点数为偶数、<= n）的最小匹配代价
    C[l][r] = 取得 F[l][r] 的匹配方案数（精确大整数）

    F[l][r] = min  over k: l 与 k 配对, (k-l) 为奇数, 边 (l,k) 存在
               w(l,k) + F[l+1][k-1] + F[k+1][r]

倍长链使得一条弦 (a,b) 的「内侧」[a+1,b-1] 与「外侧」[b+1,a+n-1]
都是普通线性区间，可在 O(1) 时间判定该边属于多少个全局最优解：

    含 (a,b) 的最优解数 = C[a+1][b-1] * C[b+1][a+n-1]
    （仅当 w + 两侧最优代价之和 == 全局最优代价）

与全局最优解总数比较即可分类：全部最优解包含 / 仅部分包含 / 不包含。

规范解：从最小未配端点开始贪心选择能达到区间最优的最小搭档，
等价于「排序后的端点对序列」字典序最小的全局最优解。

结果只依赖请求内容，不含任何随机性或进程状态，重复请求字节等价。
"""

from __future__ import annotations

from typing import Any

INF = 10**30  # 最大可能总代价 <= 200 * 10**12，INF 远大于之


def grains_reverse_match(endpoints: list[dict], a: int, b: int) -> bool:
    """候选 (a,b) 两侧晶粒标识是否反向对应。"""
    ea, eb = endpoints[a], endpoints[b]
    return ea["grain_left"] == eb["grain_right"] and ea["grain_right"] == eb["grain_left"]


def solve(endpoints: list[dict], candidates: list[dict]) -> dict[str, Any]:
    """计算最优缝合与歧义分类。输入已经过 validation 校验。"""
    n = len(endpoints)

    # 原始边权（键为归一化端点对），反向对应是校验阶段已保证的前提；
    # 这里再过滤一次，使求解器可独立使用。
    weight: dict[tuple[int, int], int] = {}
    adj: list[list[int]] = [[] for _ in range(n)]
    for cand in candidates:
        a, b, cost = cand["endpoint_a"], cand["endpoint_b"], cand["cost"]
        if a > b:
            a, b = b, a
        if not grains_reverse_match(endpoints, a, b):
            continue
        weight[(a, b)] = cost
        adj[a].append(b)
        adj[b].append(a)
    for lst in adj:
        lst.sort()

    # 倍长链邻接：位置 l 的搭档 k 取满足 l < k < l+n 且距离为奇数的副本。
    size = 2 * n
    adj2: list[list[int]] = [[] for _ in range(size)]
    for l in range(size):
        orig = l % n
        partners: list[int] = []
        for v in adj[orig]:
            k = v
            while k <= l:
                k += n
            if k < l + n and (k - l) % 2 == 1 and k < size:
                partners.append(k)
        partners.sort()
        adj2[l] = partners

    def w2(l: int, k: int) -> int:
        a, b = l % n, k % n
        return weight[(a, b)] if a < b else weight[(b, a)]

    # F[l][r] / C[l][r]：仅偶数顶点区间；空区间代价 0、方案数 1。
    F = [[INF] * size for _ in range(size)]
    C = [[0] * size for _ in range(size)]

    def inner_val(l: int, k: int) -> tuple[int, int]:
        # [l+1, k-1]
        return (0, 1) if k == l + 1 else (F[l + 1][k - 1], C[l + 1][k - 1])

    def outer_val(k: int, r: int) -> tuple[int, int]:
        # [k+1, r]
        return (0, 1) if k == r else (F[k + 1][r], C[k + 1][r])

    for m in range(2, n + 1, 2):  # 区间顶点数
        for l in range(0, size - m + 1):
            r = l + m - 1
            best = INF
            ways = 0
            for k in adj2[l]:
                if k > r:
                    break
                if k > l + 1 and F[l + 1][k - 1] >= INF:
                    continue
                if k < r and F[k + 1][r] >= INF:
                    continue
                ic, iw = inner_val(l, k)
                oc, ow = outer_val(k, r)
                val = w2(l, k) + ic + oc
                if val < best:
                    best = val
                    ways = iw * ow
                elif val == best:
                    ways += iw * ow
            F[l][r] = best
            C[l][r] = ways

    global_cost = F[0][n - 1]
    if global_cost >= INF:
        return {
            "status": "no_solution",
            "message": "不存在覆盖所有断端且弦互不相交的合法缝合（候选不足或晶粒标识无法反向对应）",
            "endpoint_count": n,
        }

    total_ways = C[0][n - 1]

    # 规范解恢复：每个区间选能达到最优的最小搭档，得到排序端点对的字典序最小序列。
    stack: list[tuple[int, int]] = [(0, n - 1)]
    canonical_pairs: list[tuple[int, int]] = []
    while stack:
        l, r = stack.pop()
        if l > r:
            continue
        chosen = None
        target = F[l][r]
        for k in adj2[l]:
            if k > r:
                break
            ic, _ = inner_val(l, k)
            oc, _ = outer_val(k, r)
            if w2(l, k) + ic + oc == target:
                chosen = k
                break
        # F 有限则必然存在搭档
        assert chosen is not None
        canonical_pairs.append((l, chosen))
        stack.append((chosen + 1, r))
        stack.append((l + 1, chosen - 1))
    canonical_pairs.sort()

    # 候选边的歧义分类。
    def interval_fc(l: int, r: int) -> tuple[int, int]:
        if l > r:
            return 0, 1
        return F[l][r], C[l][r]

    classification: list[dict[str, Any]] = []
    all_set: list[list[int]] = []
    some_set: list[list[int]] = []
    # 按归一化端点对排序输出，使响应不依赖候选的提交顺序
    for (a, b), cost in sorted(weight.items()):
        label = "none"
        ways_with = 0
        if (b - a) % 2 == 1:
            in_c, in_w = interval_fc(a + 1, b - 1)
            out_c, out_w = interval_fc(b + 1, a + n - 1)
            if in_c < INF and out_c < INF and weight[(a, b)] + in_c + out_c == global_cost:
                ways_with = in_w * out_w
                if ways_with == total_ways:
                    label = "all"
                elif ways_with > 0:
                    label = "some"
        entry = {
            "connection": [a, b],
            "cost": cost,
            "classification": label,
            "optimal_solutions_containing_it": str(ways_with),
        }
        classification.append(entry)
        if label == "all":
            all_set.append([a, b])
        elif label == "some":
            some_set.append([a, b])

    return {
        "status": "optimal",
        "endpoint_count": n,
        "total_cost": global_cost,
        "canonical_stitching": [[a, b] for a, b in canonical_pairs],
        "optimal_solution_count": str(total_ways),
        "has_multiple_optima": total_ways > 1,
        "connections_in_all_optima": all_set,
        "connections_in_some_optima": some_set,
        "candidate_classification": classification,
    }
