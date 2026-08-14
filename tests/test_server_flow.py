"""server.py 全流程集成测试：真实起 HTTP 服务，用模拟平台响应走完整链路。

覆盖：首页服务、参数校验、任务创建、SSE 日志流、证书事件、证书图片下载、
并发任务 409、停止任务、404 兜底。平台 API 全部 mock，不发真实网络请求。
"""
import base64
import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server
import xy_auto as xy

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
PNG_URI = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()

# 模拟平台响应
def fake_get_test(s, cfg, exam_type):
    return {"code": 200, "data": {
        "id": "exam-1", "name": "正式考试", "total": 10,
        "duration": 30, "pass": 80, "lastNum": 1, "lastRasitNum": 0,
    }}


def fake_run_courses(s, cfg, bank):
    print("共 1 门课程")
    print("=== 课程: 新生安全教育 (id=c1) [未完成] ===")
    print("  ▸ 文章[第一章]  id=a1")
    print("    [✓] 第 1 次提交通过（本次题库未命中 0 题）")
    print("通过 1  跳过课程 0  跳过文章 0  失败 0")
    return 1, 0, 0


def fake_do_exam(s, cfg, bank, exam_type, test_info=None):
    print("=== 考试: 正式考试 (examType=2, id=exam-1) ===")
    print("    [✓] 通过！得分 100  错题 0")
    cfg.certificate_id = "cert-123"
    cfg.certificate_image = PNG_URI
    return True


class ServerFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    # ---------- 工具方法 ----------
    def http(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, data=data, timeout=10) as r:
            return r.status, r.headers, r.read()

    def http_err(self, method, path, body=None):
        """返回 (status, body_bytes)，用于预期报错的请求。"""
        req = urllib.request.Request(self.base + path, method=method)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, data=data, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            e.close()
            return e.code, body

    def start_task(self, url="http://x.test/?userId=20250101&ah=abcdefgh"):
        status, _, body = self.http("POST", "/api/start", {"url": url})
        self.assertEqual(status, 200)
        return json.loads(body)["taskId"]

    def read_stream(self, tid):
        with urllib.request.urlopen(self.base + f"/api/stream/{tid}", timeout=15) as r:
            raw = r.read().decode("utf-8")
        events = []
        for block in raw.split("\n\n"):
            event = data = None
            for line in block.splitlines():
                if line.startswith("event: "):
                    event = line[len("event: "):]
                elif line.startswith("data: "):
                    data = line[len("data: "):]
            if event:
                events.append((event, data))
        return raw, events

    # ---------- 基础路由 ----------
    def test_index_served(self):
        status, headers, body = self.http("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("开始答题并获取证书".encode("utf-8"), body)

    def test_unknown_route_404(self):
        status, body = self.http_err("GET", "/nope")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not found")

    def test_start_without_token_400(self):
        status, body = self.http_err("POST", "/api/start", {})
        self.assertEqual(status, 400)
        self.assertIn("ah", json.loads(body)["error"])

    def test_start_with_invalid_retry_400(self):
        status, body = self.http_err("POST", "/api/start", {
            "url": "http://x.test/?userId=20250101&ah=abcdefgh", "maxRetry": "abc",
        })
        self.assertEqual(status, 400)
        self.assertIn("整数", json.loads(body)["error"])

    def test_oversized_body_413(self):
        status, body = self.http_err("POST", "/api/start", {"pad": "x" * 20 * 1024})
        self.assertEqual(status, 413)

    def test_stream_unknown_task_404(self):
        status, _ = self.http_err("GET", "/api/stream/deadbeef")
        self.assertEqual(status, 404)

    def test_certificate_unknown_task_404(self):
        status, _ = self.http_err("GET", "/api/certificate/deadbeef")
        self.assertEqual(status, 404)

    # ---------- 完整成功链路 ----------
    def test_full_flow_certificate(self):
        with mock.patch.object(xy, "api_test_get_test", fake_get_test), \
                mock.patch.object(xy, "run_courses", fake_run_courses), \
                mock.patch.object(xy, "do_exam", fake_do_exam):
            tid = self.start_task()

            raw, events = self.read_stream(tid)
            kinds = [e for e, _ in events]
            self.assertIn("certificate", kinds)
            self.assertEqual(events[-1], ("done", "done"))

            # 日志包含关键步骤与请求统计
            self.assertIn("题库已加载", raw)
            self.assertIn("步骤 1/3", raw)
            self.assertIn("步骤 2/3", raw)
            self.assertIn("一键答题结果: ✅ 已通过", raw)
            self.assertIn("请求统计", raw)

            cert = json.loads(next(d for e, d in events if e == "certificate"))
            self.assertIn("cert-123", cert["url"])
            self.assertIn(f"/api/certificate/{tid}", cert["imageUrl"])

            # 证书图片可下载且内容一致
            status, headers, body = self.http("GET", cert["imageUrl"])
            self.assertEqual(status, 200)
            self.assertIn("image/png", headers["Content-Type"])
            self.assertEqual(body, PNG_BYTES)

    # ---------- 并发 409 与停止 ----------
    def test_busy_then_stop(self):
        gate = threading.Event()

        def blocking_run_courses(s, cfg, bank):
            print("正在处理课程（模拟慢请求）")
            gate.wait(10)
            return 1, 0, 0

        with mock.patch.object(xy, "api_test_get_test", fake_get_test), \
                mock.patch.object(xy, "run_courses", blocking_run_courses), \
                mock.patch.object(xy, "do_exam", fake_do_exam):
            tid = self.start_task()
            try:
                # 任务运行中，第二个任务被拒绝
                status, body = self.http_err("POST", "/api/start", {
                    "url": "http://x.test/?userId=20250101&ah=abcdefgh",
                })
                self.assertEqual(status, 409)

                # 停止后释放阻塞，流以 stopped 结束
                status, _, _ = self.http("POST", f"/api/stop/{tid}")
                self.assertEqual(status, 200)
            finally:
                gate.set()  # 无论断言成败都放行后台任务，避免影响后续测试

            raw, events = self.read_stream(tid)
            self.assertIn("已请求停止", raw)
            self.assertEqual(events[-1], ("done", "stopped"))


if __name__ == "__main__":
    unittest.main()
