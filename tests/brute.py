"""暴力枚举参考实现：枚举凸 n 边形上全部非交叉完美匹配。"""

from functools import lru_cache


def brute_force(n: int, weight: dict[tuple[int, int], int]):
    """返回 (min_cost, list[frozenset(pairs)] 全部最优匹配, 最优解数)。

    weight 键为归一化端点对 (a,b), a<b。无解时返回 (None, [], 0)。
    """

    @lru_cache(maxsize=None)
    def enum(vertices: tuple[int, ...]):
        if not vertices:
            return {(0, frozenset())}
        l = vertices[0]
        rest = vertices[1:]
        out = set()
        for j, k in enumerate(rest):
            if j % 2 != 0:  # 两配对点间的顶点数 j 必须为偶数
                continue
            edge = (l, k) if l < k else (k, l)
            if edge not in weight:
                continue
            inside = tuple(rest[:j])
            outside = tuple(rest[j + 1 :])
            for c1, s1 in enum(inside):
                for c2, s2 in enum(outside):
                    out.add((weight[edge] + c1 + c2, s1 | s2 | {edge}))
        return out

    all_matches = enum(tuple(range(n)))
    if not all_matches:
        return None, [], 0
    best = min(c for c, _ in all_matches)
    opt = [s for c, s in all_matches if c == best]
    return best, opt, len(opt)
