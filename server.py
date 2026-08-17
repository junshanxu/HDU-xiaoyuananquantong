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
import time
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

# 全局任务存储: 仅保留正在运行任务和最近完成任务。
tasks = {}
tasks_lock = threading.Lock()
CERTIFICATE_PAGE = "http://wap.xiaoyuananquantong.com/guns-vip-main/wap/certificate"
MAX_JSON_BODY_BYTES = 16 * 1024
TASK_RETENTION_SECONDS = 10 * 60


class RequestBodyTooLarge(ValueError):
    """请求体超过本地 API 可接受的上限；length 为声明的未读字节数。"""

    def __init__(self, length):
        super().__init__("request body too large")
        self.length = length


def cleanup_task(task_id, expected_task):
    """任务结束一段时间后释放日志、证书图片等仅存在于内存的数据。"""
    with tasks_lock:
        if tasks.get(task_id) is expected_task and expected_task["status"] not in ("pending", "running"):
            tasks.pop(task_id, None)


def schedule_task_cleanup(task_id, task):
    timer = threading.Timer(TASK_RETENTION_SECONDS, cleanup_task, args=(task_id, task))
    timer.daemon = True
    timer.start()


class Cfg:
    """xy_auto 的配置对象，供后台任务使用"""
    def __init__(self, **kw):
        defaults = dict(
            user_id="", college_id="", ah="", course_type="1", exam_class="10",
            delay=0.5, max_retry=10, retry_exam=False, max_exam_retry=30,
            cancel_event=None,
        )
        defaults.update(kw)
        self.__dict__.update(defaults)


class QueueWriter:
    """把 print 输出按行写入 queue，供 SSE 推送给前端"""
    def __init__(self, q):
        self.q = q
        self.buf = ""
        self._lock = threading.Lock()

    def write(self, s):
        with self._lock:
            self.buf += s
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                if line.strip():
                    self.q.put(line)

    def flush(self):
        with self._lock:
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


def set_failure(task, kind, message):
    task["outcome"] = {"type": kind, "message": message}


def existing_certificate_status(s, cfg):
    """读取正式考试状态，并返回响应供后续考试流程复用。"""
    info = xy.api_test_get_test(s, cfg, "2")
    if info.get("code") != 200:
        message = str(info.get("message") or "平台暂时无法读取考试状态")
        # 平台耗尽次数时并不总是返回 lastNum=0；有时直接以错误文本返回。
        if "考试次数已使用完毕" in message:
            if xy.load_certificate_image(s, cfg):
                return "certificate", "", None
            return "exhausted", "考试次数已用完，且未查询到合格证书", None
        if "303" in message or "登录" in message or "token" in message.lower():
            return "token_expired", "链接已失效，请重新从杭电安全教育页面复制完整链接", None
        return "platform_error", message, None
    data = info.get("data") or {}
    last_num = xy._to_int(data.get("lastNum", 0) or 0, default=None)
    if last_num is None:
        return "platform_error", "平台返回的考试状态无效，请稍后重试", None
    if last_num > 0:
        return "ready", "", info
    if xy.load_certificate_image(s, cfg):
        return "certificate", "", None
    return "exhausted", "考试次数已用完，且未查询到合格证书", None


def run_task(task_id, cfg):
    """后台线程：重定向 stdout 到 queue，调用 xy_auto 完成课程并参加正式考试拿证书"""
    t = tasks[task_id]
    q = t["queue"]
    writer = QueueWriter(q)
    s = xy.Session()
    started = time.perf_counter()
    bank = xy.load_bank()
    t["status"] = "running"
    old = sys.stdout
    sys.stdout = writer
    try:
        q.put(f"题库已加载 {len(bank)} 题")
        exam_status, message, exam_info = existing_certificate_status(s, cfg)
        if exam_status == "certificate":
            set_certificate_result(task_id, t, cfg)
            q.put("[✓] 考试次数已用完，已直接查询到合格证书")
            q.put("证书已生成，可在页面中打开或保存")
        elif exam_status in {"exhausted", "token_expired", "platform_error"}:
            q.put(f"[!] {message}")
            set_failure(t, exam_status, message)
            t["status"] = "failed"
        else:
            q.put("步骤 1/2：完成未完成的课程章节")
            _, _, failed = xy.run_courses(s, cfg, bank)
            if failed:
                q.put("[!] 存在未完成的章节，已停止后续考试")
                set_failure(t, "chapter_incomplete", "仍有章节未完成，请稍后重新粘贴链接继续")
                t["status"] = "failed"
            elif not cfg.cancel_event.is_set():
                q.put("步骤 2/2：参加正式考试并获取证书")
                ok = xy.do_exam(s, cfg, bank, "2", test_info=exam_info)
                q.put(f"一键答题结果: {'✅ 已通过' if ok else '❌ 未通过'}")
                if ok:
                    set_certificate_result(task_id, t, cfg)
                    if t["certificate"]:
                        q.put("证书已生成，可在页面中打开或保存")
                else:
                    set_failure(t, "exam_failed", "本次未能获得证书；请查看运行记录后再重试")
                    t["status"] = "failed"
        if cfg.cancel_event.is_set():
            t["status"] = "stopped"
        elif t["status"] == "running":
            t["status"] = "done"
    except Exception as e:
        t["status"] = "error"
        q.put(f"[错误] {e}")
    finally:
        for line in xy.format_request_stats(s, (time.perf_counter() - started) * 1000).splitlines():
            q.put(line)
        sys.stdout = old
        q.put(None)  # 结束信号
        schedule_task_cleanup(task_id, t)


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
        "ah": q.get("ah", [""])[0],
    }
    if not re.fullmatch(r"[0-9]{6,}", result["userId"]):
        result["userId"] = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,}", result["ah"]):
        result["ah"] = ""

    # query 被截断、分隔符写成 ?/空格，或用户粘贴的是整段聊天文字时兜底。
    patterns = {
        "userId": r"userid\s*[=:]\s*([0-9]{6,})",
        "ah": r"ah\s*[=:]\s*([A-Za-z0-9_-]{8,})",
    }
    for key, pattern in patterns.items():
        if not result[key]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result[key] = match.group(1)
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
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("不支持分块请求体")
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("无效 Content-Length") from exc
        if n < 0:
            raise ValueError("无效 Content-Length")
        if n > MAX_JSON_BODY_BYTES:
            raise RequestBodyTooLarge(n)
        if not n:
            return {}
        data = self.rfile.read(n)
        if len(data) != n:
            raise ValueError("请求体不完整")
        result = json.loads(data.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return result

    def _serve_file(self, name, ctype):
        # 校验解析后的绝对路径仍在 WEB_DIR 内，防止 ../ 路径遍历。
        path = os.path.realpath(os.path.join(WEB_DIR, name))
        if not path.startswith(WEB_DIR + os.sep) or not os.path.isfile(path):
            return self._send_json(404, {"error": f"{name} 不存在"})
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self._send_json(500, {"error": "读取文件失败"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
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
        except RequestBodyTooLarge as exc:
            # 未读的请求体不能当作下一条请求解析。直接关闭会因接收缓冲
            # 残留数据触发 TCP RST，可能吞掉本应发出的 413 响应；
            # 因此先尽量排空（设上限防止恶意客户端只发头不发体），再关闭连接。
            remaining = min(exc.length, 64 * 1024)
            try:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 8192))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass
            self.close_connection = True
            return self._send_json(413, {"error": "JSON 请求体不能超过 16 KB"})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return self._send_json(400, {"error": "无效 JSON"})
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
        if not ah:
            return self._send_json(400, {
                "error": "没有找到 ah= 后面的登录 token",
                "params": {"userId": user_id, "collegeId": college_id, "ah": ""},
            })
        if not user_id:
            return self._send_json(400, {
                "error": "token 已提取；首次使用还需要带 userId 的完整链接",
                "params": {"userId": user_id, "collegeId": college_id, "ah": ah},
            })
        try:
            max_retry = max(1, min(int(body.get("maxRetry", 10)), 50))
            max_exam_retry = max(1, min(int(body.get("maxExamRetry", 30)), 100))
        except (TypeError, ValueError):
            return self._send_json(400, {"error": "重试次数必须是整数"})
        cancel_event = threading.Event()
        cfg = Cfg(
            user_id=user_id, college_id=college_id, ah=ah,
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
                "queue": queue.Queue(), "status": "pending",
                "cancel_event": cancel_event, "certificate": None,
                "certificate_image": None,
                "outcome": None,
            }
        threading.Thread(target=run_task, args=(tid, cfg), daemon=True).start()
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
                    outcome = t.get("outcome")
                    if outcome:
                        data = json.dumps(outcome, ensure_ascii=False)
                        self.wfile.write(f"event: outcome\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.write(f"event: done\ndata: {t['status']}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    # 流已结束，主动关闭连接：SSE 无 Content-Length，
                    # 不关闭会让读到 EOF 为止的客户端（curl 等）永久挂起。
                    self.close_connection = True
                    break
                self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # 客户端断开（关闭浏览器/网络中断）：取消后台任务，避免继续请求平台、消耗考试次数。
            t["cancel_event"].set()


def main():
    print(f"校园安全通答题服务已启动: http://localhost:{PORT}")
    print("浏览器打开上面网址，粘贴平台链接后点击开始答题。Ctrl+C 停止。")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    main()
