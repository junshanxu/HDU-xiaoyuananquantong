#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园安全通 Web 后台 - 本地 HTTP 服务（零依赖，纯标准库）

运行: python3 server.py
浏览器打开: http://localhost:8080
粘贴平台链接即可一键答题。
"""
import json
import os
import queue
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 同目录 import xy_auto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xy_auto as xy

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8090"))
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

# 全局任务存储: {taskId: {queue, status, mode}}
tasks = {}


class Cfg:
    """模拟 argparse 的 cfg 对象，供 xy_auto 函数使用"""
    def __init__(self, **kw):
        defaults = dict(
            user_id="", college_id="", ah="", course_type="1", exam_class="10",
            course_id=None, force=False, dry_run=False, delay=0.5,
            max_retry=10, retry_exam=False, max_exam_retry=30,
        )
        defaults.update(kw)
        self.__dict__.update(defaults)


class QueueWriter:
    """把 print 输出按行写入 queue，供 SSE 推送给前端"""
    def __init__(self, q):
        self.q = q
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.q.put(line)

    def flush(self):
        if self.buf.strip():
            self.q.put(self.buf)
            self.buf = ""


def run_task(task_id, cfg, mode):
    """后台线程：重定向 stdout 到 queue，调用 xy_auto 答题函数"""
    t = tasks[task_id]
    q = t["queue"]
    writer = QueueWriter(q)
    s = xy.Session()
    bank = xy.load_bank()
    t["status"] = "running"
    old = sys.stdout
    sys.stdout = writer
    try:
        q.put(f"题库已加载 {len(bank)} 题")
        if mode == "chapter":
            xy.run_courses(s, cfg, bank)
        elif mode == "learn_all":
            xy.do_learn_all(s, cfg, bank, "1")
        elif mode == "exam_mock":
            ok = xy.do_exam(s, cfg, bank, "1")
            q.put(f"模拟考结果: {'✅ 通过' if ok else '❌ 未通过'}")
        elif mode == "exam_official":
            ok = xy.do_exam(s, cfg, bank, "2")
            q.put(f"正式考结果: {'✅ 通过' if ok else '❌ 未通过'}")
        else:
            q.put(f"[!] 未知模式: {mode}")
        t["status"] = "done"
    except Exception as e:
        t["status"] = "error"
        q.put(f"[错误] {e}")
    finally:
        sys.stdout = old
        q.put(None)  # 结束信号


def parse_params(url):
    q = parse_qs(urlparse(url).query)
    return {
        "userId": q.get("userId", [""])[0],
        "collegeId": q.get("collegeId", [""])[0],
        "ah": q.get("ah", [""])[0],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 静默默认日志

    def _send_json(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def _serve_file(self, name, ctype):
        path = os.path.join(WEB_DIR, name)
        if not os.path.exists(path):
            return self._send_json(404, {"error": f"{name} 不存在"})
        body = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif p == "/api/schools":
            self._serve_file("xy_schools.json", "application/json; charset=utf-8")
        elif p.startswith("/api/stream/"):
            self._stream(p.rsplit("/", 1)[-1])
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            body = self._read_body()
        except Exception:
            return self._send_json(400, {"error": "无效 JSON"})
        if p == "/api/parse":
            url = body.get("url", "").strip()
            if not url:
                return self._send_json(400, {"error": "缺少 url"})
            return self._send_json(200, parse_params(url))
        if p == "/api/start":
            return self._start(body)
        if p.startswith("/api/stop/"):
            tid = p.rsplit("/", 1)[-1]
            t = tasks.get(tid)
            if t:
                t["status"] = "stopped"
                t["queue"].put("[已请求停止]")
                t["queue"].put(None)
            return self._send_json(200, {"ok": True})
        self._send_json(404, {"error": "not found"})

    def _start(self, body):
        ah = body.get("ah", "").strip()
        user_id = body.get("userId", "").strip()
        college_id = body.get("collegeId", "").strip()
        mode = body.get("mode", "chapter")
        if not ah or not user_id or not college_id:
            return self._send_json(400, {"error": "参数不全：需要 userId / collegeId / ah"})
        cfg = Cfg(
            user_id=user_id, college_id=college_id, ah=ah,
            force=bool(body.get("force")),
            retry_exam=bool(body.get("retryExam")),
            max_retry=int(body.get("maxRetry", 10)),
            max_exam_retry=int(body.get("maxExamRetry", 30)),
        )
        tid = uuid.uuid4().hex[:12]
        tasks[tid] = {"queue": queue.Queue(), "status": "pending", "mode": mode}
        threading.Thread(target=run_task, args=(tid, cfg, mode), daemon=True).start()
        self._send_json(200, {"taskId": tid})

    def _stream(self, tid):
        t = tasks.get(tid)
        if not t:
            return self._send_json(404, {"error": "任务不存在"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = t["queue"]
        try:
            while True:
                try:
                    line = q.get(timeout=25)
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                if line is None:
                    self.wfile.write(f"event: done\ndata: {t['status']}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    break
                self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    print(f"校园安全通答题服务已启动: http://localhost:{PORT}")
    print("浏览器打开上面网址，粘贴平台链接即可一键答题。Ctrl+C 停止。")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
