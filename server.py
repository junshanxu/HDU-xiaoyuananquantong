#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园安全通 Web 后台 - 本地 HTTP 服务（零依赖，纯标准库）

运行: python3 server.py
浏览器打开: http://localhost:8090
粘贴平台链接即可一键答题。
"""
import json
import html
import os
import queue
import re
import sys
import threading
import uuid
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, urlencode

# 同目录 import xy_auto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xy_auto as xy

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8090"))
WEB_DIR = os.path.dirname(os.path.abspath(__file__))

# 全局任务存储: {taskId: {queue, status, mode}}
tasks = {}
tasks_lock = threading.Lock()
VALID_MODES = {"certificate", "chapter", "learn_all", "exam_mock", "exam_official"}
CERTIFICATE_PAGE = "http://wap.xiaoyuananquantong.com/guns-vip-main/wap/certificate"


class Cfg:
    """模拟 argparse 的 cfg 对象，供 xy_auto 函数使用"""
    def __init__(self, **kw):
        defaults = dict(
            user_id="", college_id="", ah="", course_type="1", exam_class="10",
            course_id=None, force=False, dry_run=False, delay=0.5,
            max_retry=10, retry_exam=False, max_exam_retry=30,
            cancel_event=None,
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


def certificate_url(certificate_id, user_id):
    """构建平台证书页链接；证书页只需要证书 ID 与用户 ID。"""
    return f"{CERTIFICATE_PAGE}?{urlencode({'id': certificate_id, 'userId': user_id})}"


def certificate_image_bytes(image):
    """验证平台 data URI，返回安全的图片 MIME 类型和二进制内容。"""
    match = re.fullmatch(r"data:(image/(?:jpeg|jpg|png));base64,([A-Za-z0-9+/=]+)", image or "")
    if not match:
        return None
    try:
        body = base64.b64decode(match.group(2), validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    if not body or len(body) > 5 * 1024 * 1024:
        return None
    return ("image/jpeg" if match.group(1) == "image/jpg" else match.group(1), body)


def set_certificate_result(task_id, task, cfg):
    certificate_id = getattr(cfg, "certificate_id", "")
    certificate_image = getattr(cfg, "certificate_image", "")
    if not certificate_id and not certificate_image:
        return
    task["certificate"] = {
        "url": certificate_url(certificate_id, cfg.user_id) if certificate_id else "",
        "imageUrl": f"/api/certificate/{task_id}" if certificate_image else "",
    }
    task["certificate_image"] = certificate_image


def existing_certificate_status(s, cfg):
    """正式考试机会用尽时，优先判断已有证书，避免再扫描课程。"""
    info = xy.api_test_get_test(s, cfg, "2")
    if info.get("code") != 200:
        # 平台耗尽次数时并不总是返回 lastNum=0；有时直接以错误文本返回。
        if "考试次数已使用完毕" in str(info.get("message") or ""):
            return xy.load_certificate_image(s, cfg)
        return None
    data = info.get("data") or {}
    try:
        last_num = int(data.get("lastNum", 0) or 0)
    except (TypeError, ValueError):
        return None
    if last_num > 0:
        return None
    return xy.load_certificate_image(s, cfg)


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
        if mode == "certificate":
            existing_certificate = existing_certificate_status(s, cfg)
            if existing_certificate:
                set_certificate_result(task_id, t, cfg)
                q.put("[✓] 考试次数已用完，已直接查询到合格证书")
                q.put("证书已生成，可在页面中打开或保存")
            elif existing_certificate is False:
                q.put("[!] 考试次数已用完，且未查询到合格证书")
                t["status"] = "failed"
            else:
                q.put("步骤 1/3：完成未完成的课程章节")
                _, _, failed = xy.run_courses(s, cfg, bank)
                if failed:
                    q.put("[!] 存在未完成的章节，已停止后续考试")
                    t["status"] = "failed"
                elif not cfg.cancel_event.is_set():
                    q.put("步骤 2/3：加载杭电内置题库")
                    if t["status"] == "running" and not cfg.cancel_event.is_set():
                        q.put("步骤 3/3：参加正式考试并获取证书")
                        ok = xy.do_exam(s, cfg, bank, "2")
                        q.put(f"一键答题结果: {'✅ 已通过' if ok else '❌ 未通过'}")
                        if ok:
                            set_certificate_result(task_id, t, cfg)
                            if t["certificate"]:
                                q.put("证书已生成，可在页面中打开或保存")
                        if not ok:
                            t["status"] = "failed"
        elif mode == "chapter":
            _, _, failed = xy.run_courses(s, cfg, bank)
            if failed:
                t["status"] = "failed"
        elif mode == "learn_all":
            if not xy.do_learn_all(s, cfg, bank, "1"):
                t["status"] = "failed"
        elif mode == "exam_mock":
            ok = xy.do_exam(s, cfg, bank, "1")
            q.put(f"模拟考结果: {'✅ 通过' if ok else '❌ 未通过'}")
            if not ok:
                t["status"] = "failed"
        elif mode == "exam_official":
            ok = xy.do_exam(s, cfg, bank, "2")
            q.put(f"正式考结果: {'✅ 通过' if ok else '❌ 未通过'}")
            if not ok:
                t["status"] = "failed"
        if cfg.cancel_event.is_set():
            t["status"] = "stopped"
        elif t["status"] == "running":
            t["status"] = "done"
    except Exception as e:
        t["status"] = "error"
        q.put(f"[错误] {e}")
    finally:
        sys.stdout = old
        q.put(None)  # 结束信号


def parse_params(url):
    """从完整 URL、残缺 URL 或聊天文本中尽可能提取登录参数。"""
    text = html.unescape(str(url or "").strip())
    # 微信/聊天软件有时会把整段 query 再编码一层。
    for _ in range(2):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded

    parsed = urlparse(text)
    chunks = [parsed.query]
    if parsed.fragment:
        chunks.append(parsed.fragment.split("?", 1)[-1])
    q = {}
    for chunk in chunks:
        for key, values in parse_qs(chunk, keep_blank_values=True).items():
            q.setdefault(key.lower(), values)

    result = {
        "userId": q.get("userid", [""])[0],
        "collegeId": q.get("collegeid", [""])[0],
        "ah": q.get("ah", [""])[0],
    }
    if not re.fullmatch(r"[0-9]{6,}", result["userId"]):
        result["userId"] = ""
    if not re.fullmatch(r"[0-9]{6,}", result["collegeId"]):
        result["collegeId"] = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,}", result["ah"]):
        result["ah"] = ""

    # query 被截断、分隔符写成 ?/空格，或用户粘贴的是整段聊天文字时兜底。
    patterns = {
        "userId": r"userid\s*[=:]\s*([0-9]{6,})",
        "collegeId": r"collegeid\s*[=:]\s*([0-9]{6,})",
        "ah": r"ah\s*[=:]\s*([A-Za-z0-9_-]{8,})",
    }
    for key, pattern in patterns.items():
        if not result[key]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result[key] = match.group(1)
    # 本项目只服务杭州电子科技大学，学校参数固定，不要求链接携带。
    result["collegeId"] = xy.DEFAULT_COLLEGE_ID
    return result


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
        elif p.startswith("/api/certificate/"):
            self._certificate_image(p.rsplit("/", 1)[-1])
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
            url = str(body.get("url") or "").strip()
            if not url:
                return self._send_json(400, {"error": "缺少 url"})
            params = parse_params(url)
            missing = [k for k, v in params.items() if not v]
            if not params["ah"]:
                return self._send_json(400, {"error": "没有找到 ah= 后面的登录 token", "params": params})
            return self._send_json(200, {**params, "missing": missing})
        if p == "/api/start":
            return self._start(body)
        if p.startswith("/api/stop/"):
            tid = p.rsplit("/", 1)[-1]
            t = tasks.get(tid)
            if t and t["status"] in ("pending", "running"):
                t["cancel_event"].set()
                t["queue"].put("[已请求停止，当前请求结束后将不再提交]")
            return self._send_json(200, {"ok": True})
        self._send_json(404, {"error": "not found"})

    def _start(self, body):
        params = parse_params(str(body.get("url", ""))) if body.get("url") else {}
        ah = str(params.get("ah") or body.get("ah") or "").strip()
        user_id = str(params.get("userId") or body.get("userId") or "").strip()
        college_id = xy.DEFAULT_COLLEGE_ID
        mode = body.get("mode", "certificate")
        if not ah:
            return self._send_json(400, {
                "error": "没有找到 ah= 后面的登录 token",
                "params": {"userId": user_id, "collegeId": college_id, "ah": ""},
            })
        missing_identity = [name for name, value in (("userId", user_id), ("collegeId", college_id)) if not value]
        if missing_identity:
            return self._send_json(400, {
                "error": "token 已提取；首次使用还需要带 " + " / ".join(missing_identity) + " 的完整链接",
                "params": {"userId": user_id, "collegeId": college_id, "ah": ah},
            })
        if mode not in VALID_MODES:
            return self._send_json(400, {"error": "无效答题模式"})
        try:
            max_retry = max(1, min(int(body.get("maxRetry", 10)), 50))
            max_exam_retry = max(1, min(int(body.get("maxExamRetry", 30)), 100))
        except (TypeError, ValueError):
            return self._send_json(400, {"error": "重试次数必须是整数"})
        cancel_event = threading.Event()
        cfg = Cfg(
            user_id=user_id, college_id=college_id, ah=ah,
            force=False,
            retry_exam=True,
            max_retry=max_retry,
            max_exam_retry=max_exam_retry,
            cancel_event=cancel_event,
        )
        tid = uuid.uuid4().hex[:12]
        with tasks_lock:
            if any(t["status"] in ("pending", "running") for t in tasks.values()):
                return self._send_json(409, {"error": "已有答题任务运行中，请等待完成或先停止"})
            tasks[tid] = {
                "queue": queue.Queue(), "status": "pending", "mode": mode,
                "cancel_event": cancel_event, "certificate": None,
                "certificate_image": None,
            }
        threading.Thread(target=run_task, args=(tid, cfg, mode), daemon=True).start()
        self._send_json(200, {
            "taskId": tid,
            "params": {"userId": user_id, "collegeId": college_id, "ah": ah},
        })

    def _certificate_image(self, tid):
        task = tasks.get(tid)
        image = certificate_image_bytes(task.get("certificate_image")) if task else None
        if not image:
            return self._send_json(404, {"error": "证书图片不存在"})
        content_type, body = image
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
                    certificate = t.get("certificate")
                    if certificate:
                        data = json.dumps(certificate, ensure_ascii=False)
                        self.wfile.write(f"event: certificate\ndata: {data}\n\n".encode("utf-8"))
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
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    main()
