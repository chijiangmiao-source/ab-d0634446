"""纯标准库 HTTP 服务：POST /analyze 缝合分析，GET /health 健康检查。

环境变量：
  APP_HOST         容器内监听地址，默认 0.0.0.0
  APP_PORT         容器内监听端口，默认 8000
  API_HOST_PORT    宿主机映射端口（在 docker-compose.yml 中使用），默认 8080

所有响应使用规范化 JSON（sort_keys、紧凑分隔符），且不含时间戳等
进程相关内容：同一合法请求重复提交，响应体字节完全一致。
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .solver import solve
from .validation import validate_request

MAX_BODY_BYTES = 16 * 1024 * 1024


def canonical_dumps(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "GrainStitch/1.0"

    def _send(self, status: int, payload: dict) -> None:
        body = canonical_dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # 保持容器日志简洁
        pass

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "healthy", "service": "grain-stitch"})
            return
        if self.path == "/":
            self._send(
                200,
                {
                    "service": "grain-stitch",
                    "endpoints": {"health": "/health", "analyze": "POST /analyze"},
                },
            )
            return
        self._send(404, {"code": "NOT_FOUND", "message": f"未知路径: {self.path}"})

    def do_POST(self):
        if self.path != "/analyze":
            self._send(404, {"code": "NOT_FOUND", "message": f"未知路径: {self.path}"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(
                400,
                {
                    "code": "INVALID_JSON",
                    "message": "Content-Length 非法",
                    "errors": [{"field": "", "message": "Content-Length 头必须为整数"}],
                },
            )
            return
        if length <= 0:
            self._send(
                400,
                {
                    "code": "INVALID_JSON",
                    "message": "请求体为空",
                    "errors": [{"field": "", "message": "期望 UTF-8 编码的 JSON 对象"}],
                },
            )
            return
        if length > MAX_BODY_BYTES:
            self._send(
                413,
                {"code": "PAYLOAD_TOO_LARGE", "message": f"请求体超过 {MAX_BODY_BYTES} 字节上限"},
            )
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            self._send(
                400,
                {
                    "code": "INVALID_JSON",
                    "message": "请求体不是合法 UTF-8",
                    "errors": [{"field": "", "message": "请求体必须为 UTF-8 编码"}],
                },
            )
            return
        except json.JSONDecodeError as exc:
            self._send(
                400,
                {
                    "code": "INVALID_JSON",
                    "message": f"JSON 解析失败: {exc.msg}",
                    "errors": [
                        {
                            "field": "",
                            "message": f"第 {exc.lineno} 行第 {exc.colno} 列附近语法错误",
                        }
                    ],
                },
            )
            return

        errors, endpoints, candidates = validate_request(payload)
        if errors:
            self._send(
                400,
                {
                    "code": "VALIDATION_ERROR",
                    "message": f"请求存在 {len(errors)} 个校验错误",
                    "errors": errors,
                },
            )
            return

        result = solve(endpoints, candidates)
        if result["status"] == "no_solution":
            self._send(422, {"code": "NO_SOLUTION", **result})
        else:
            self._send(200, {"code": "OK", **result})


def main() -> None:
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"grain-stitch listening on {host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
