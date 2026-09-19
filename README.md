# grain-stitch — 金相断端缝合分析服务（纯后端）

沿抛光缺口边缘，断端按顺时针排列。服务在凸多边形弦模型上求**总证据代价最小、
弦互不相交、覆盖每个断端恰好一次**的完美缝合，并对每个候选连接标注其在
最优解集合中的归属。纯 Python 标准库实现，无前端、无任何在线服务依赖。

## 运行

```bash
# 宿主机端口可用环境变量配置（默认 8080）
API_HOST_PORT=9090 docker compose up --build
```

或直接本地运行：

```bash
APP_PORT=8000 python -m app.server
```

健康检查：`GET /health` → `{"status":"healthy",...}`（Dockerfile 与 Compose 均内置 healthcheck）。

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `API_HOST_PORT` | `8080` | 宿主机映射端口（docker-compose） |
| `APP_HOST` | `0.0.0.0` | 容器内监听地址 |
| `APP_PORT` | `8000` | 容器内监听端口 |

## API

### `POST /analyze`

请求：

```json
{
  "endpoints": [
    {"grain_left": 1, "grain_right": 2},
    {"grain_left": 2, "grain_right": 1}
  ],
  "candidates": [
    {"endpoint_a": 0, "endpoint_b": 1, "cost": 3}
  ]
}
```

- `endpoints`：2~400 个断端，**数量必须为偶数**，按顺时针排列；下标即位置。
- 每个断端给出缺口两侧的晶粒标识（非负整数）。
- `candidates`：候选连接，代价为非负整数；**只有两侧标识反向对应**
  （端点 A 的左/右标识分别等于端点 B 的右/左标识）的候选才允许采用，
  矛盾的候选返回 400 校验错误。

成功响应（200）关键字段：

- `total_cost`：最低总代价；
- `canonical_stitching`：规范缝合，按 `[a,b]`（a<b）升序的端点对数组；
  并列最优时取排序端点对序列字典序最小者；
- `optimal_solution_count`：最优解总数（十进制字符串，可能极大）；
- `connections_in_all_optima` / `connections_in_some_optima`：
  存在于**全部** / 仅**部分**最优解中的候选连接；
- `candidate_classification`：逐候选 `all` / `some` / `none` 分类，
  以及包含该连接的最优解数（大整数十进制字符串）。

错误：

- `400 VALIDATION_ERROR`：字段或候选矛盾，`errors[].field` 为可定位路径
  （如 `candidates[3].cost`、`endpoints[5].grain_left`）；
- `400 INVALID_JSON` / `413 PAYLOAD_TOO_LARGE`；
- `422 NO_SOLUTION`：合法请求但不存在完整非交叉缝合。

**确定性**：响应是请求内容的纯函数（规范化 JSON、无时间戳、输出排序），
合法请求重复提交（含跨实例）返回字节等价的代价、规范缝合与歧义分类；
候选的提交顺序不影响结果。

## 算法

圆周偶数点非交叉完美匹配。在倍长链 `0..2n-1`（位置 p 即断端 p mod n）上
做配对首点的区间 DP，O(n²) 个区间、总计 O(n³) 时间，O(n²) 内存，
同时用大整数累计每个区间的最优方案数。一条弦 `(a,b)` 把剩余断端分成
内外两个独立区间，故包含它的最优解数 = 两区间最优方案数之积，
与全局总数比较即可完成 all/some/none 分类。

## 测试

```bash
python tests/test_analyzer.py   # 或 pytest tests/
```

测试用 Catalan 递归暴力枚举（n≤12）对随机实例逐一核对最小代价、
最优解数、规范解与每条候选的分类；另含校验、HTTP 端到端、
跨实例字节等价与 n=400 性能测试。
