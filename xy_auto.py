#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园安全通 (xiaoyuananquantong.com) 自动答题脚本

原理（纯明文 HTTP 接口，无加密/签名）：
  1. POST /wap/compulsory/list   获取课程列表           -> courseId
  2. POST /wap/directory/list    获取章节/文章目录       -> articleId, title
  3. GET  /wap/question/list     获取题目               -> questionId, 选项, 题型
  4. POST /wap/unitTest          提交答案
  5. GET  /wap/wrong/list        仅在题库未命中时作为兜底学习

提交格式（复刻页面 setVle/serialize 逻辑）：
  单选 : question={qid}-{字母}            例 165xxx-A
  判断 : question={qid}-{1|0}             例 165xxx-1   (1=正确 0=错误)
  多选 : question=~{qid}-A~{qid}-B~{qid}-C           (前导 ~，每个选项前缀 qid-)

题库 xy_bank.json 会自动积累（键: 归一化题干，值: 正确答案），越用越准，可备份复用。

本模块作为 server.py 的库被调用，不提供命令行入口。
"""

import http.cookiejar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# ==================== 默认配置 ====================
BASE = "http://wap.xiaoyuananquantong.com/guns-vip-main"
DEFAULT_COLLEGE_ID = "1940953111032012801"  # 杭电固定参数
BANK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xy_bank.json")

UA = ("Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")

# question/list 用中文题型，提交用数字，两套编码
QTYPE_CN2NUM = {"单选": "1", "多选": "2", "判断": "3"}


# ==================== HTTP Session ====================
# 需要从日志/异常 message 中抹掉的敏感参数（ah 是登录 token，userId 是学号）。
_SENSITIVE_PARAMS = ("ah", "userId", "collegeId")


def _sanitize(text):
    """抹掉字符串中的 ah=/userId= 等敏感参数值，避免 token 经 SSE 日志泄露。

    同时覆盖 URL 形式（ah=xxx）与 JSON 形式（"ah":"xxx"）。
    """
    if not text:
        return text
    out = str(text)
    for key in _SENSITIVE_PARAMS:
        # 分隔符前后允许引号，兼容 ah=xxx、"ah":"xxx"、ah: "xxx" 等形式。
        out = re.sub(rf"\b{key}[\"']?\s*[=:]\s*[\"']?[^\s&'\"]+", f"{key}=***", out, flags=re.IGNORECASE)
    return out


class Session:
    def __init__(self):
        cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj))
        # 只记录接口路径和耗时，不记录 URL 参数，避免把 ah/userId 带进日志。
        self.timings = []
        self.opener.addheaders = [
            ("User-Agent", UA),
            ("X-Requested-With", "XMLHttpRequest"),
            ("Accept", "application/json, text/plain, */*"),
        ]

    def _open(self, req):
        started = time.perf_counter()
        path = urllib.parse.urlsplit(req.full_url).path or "/"
        status = "ok"
        try:
            with self.opener.open(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            status = f"http_{e.code}"
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            return {"code": e.code, "message": _sanitize(f"HTTP {e.code}: {body}")}
        except Exception as e:
            status = "error"
            return {"code": -1, "message": _sanitize(str(e))}
        finally:
            self.timings.append({
                "path": path,
                "status": status,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
            })

    def get(self, url, params=None):
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        return self._open(urllib.request.Request(url, method="GET"))

    def post(self, url, fields):
        # fields: list[(k,v)]，支持重复 key（question/quesType 多值）
        data = urllib.parse.urlencode(fields).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        return self._open(req)


# ==================== 题库 ====================
def _to_int(value, default=0):
    """安全转 int：平台返回的数字字段可能是 None/空串/非数字串，统一兜底。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def norm(text):
    """归一化题干：去空白与标点，做匹配键（避免空格/标点差异导致命中率低）"""
    t = re.sub(r"\s+", "", text or "")
    t = re.sub(r"[，。、,.（）()\[\]【】\"'“”‘’：:；;？?！!\-—_=+]", "", t)
    return t


def load_bank():
    if os.path.exists(BANK_FILE):
        try:
            with open(BANK_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_bank(bank):
    # 原子写：先写临时文件再 os.replace，避免写一半进程中断导致题库文件截断丢失。
    tmp = BANK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BANK_FILE)


def format_request_stats(session, wall_elapsed_ms=None):
    """格式化本次任务的接口耗时摘要；只输出路径，不输出敏感参数。"""
    timings = getattr(session, "timings", [])
    if not timings:
        return "请求统计：0 次"

    grouped = {}
    for item in timings:
        key = item["path"]
        group = grouped.setdefault(key, {"count": 0, "elapsed_ms": 0.0, "max_ms": 0.0, "errors": 0})
        group["count"] += 1
        group["elapsed_ms"] += item["elapsed_ms"]
        group["max_ms"] = max(group["max_ms"], item["elapsed_ms"])
        if item["status"] != "ok":
            group["errors"] += 1

    total_ms = sum(item["elapsed_ms"] for item in timings)
    suffix = f"，任务耗时约 {wall_elapsed_ms:.0f} ms" if wall_elapsed_ms is not None else ""
    lines = [f"请求统计：{len(timings)} 次，接口耗时合计 {total_ms:.0f} ms{suffix}"]
    # 按累计耗时排序，优先暴露真正值得优化的接口。
    for path, group in sorted(grouped.items(), key=lambda pair: pair[1]["elapsed_ms"], reverse=True):
        error_suffix = f"，异常 {group['errors']} 次" if group["errors"] else ""
        lines.append(
            f"  {path}: {group['count']} 次，合计 {group['elapsed_ms']:.0f} ms，"
            f"平均 {group['elapsed_ms'] / group['count']:.0f} ms，最长 {group['max_ms']:.0f} ms{error_suffix}"
        )
    return "\n".join(lines)


# ==================== 业务接口 ====================
def api_course_list(s, cfg):
    return s.post(f"{BASE}/wap/compulsory/list", [
        ("name", ""), ("courseType", cfg.course_type),
        ("userId", cfg.user_id), ("collegeId", cfg.college_id), ("ah", cfg.ah),
    ])


def api_directory_list(s, cfg, course_id):
    return s.post(f"{BASE}/wap/directory/list", [
        ("name", ""), ("courseId", course_id),
        ("userId", cfg.user_id), ("collegeId", cfg.college_id), ("ah", cfg.ah),
    ])


def api_question_list(s, cfg, article_id):
    return s.get(f"{BASE}/wap/question/list",
                 {"articleId": article_id, "ah": cfg.ah})


def api_unit_test(s, cfg, article_id, title, questions, answers):
    fields = [
        ("articleId", article_id),
        ("title", title or ""),
        ("userId", cfg.user_id),
        ("ah", cfg.ah),
    ]
    fields.extend(_answer_fields(questions, answers))
    return s.post(f"{BASE}/wap/unitTest", fields)


def api_wrong_list(s, cfg, log_id, limit=200):
    return s.get(f"{BASE}/wap/wrong/list",
                 {"errorLogId": log_id, "page": "1", "limit": str(limit)})


# ==================== 答题逻辑 ====================
def _qtype(q):
    """统一题型为数字: 1单选 2多选 3判断（兼容 question/list 的中文与 test/list 的数字编码）"""
    qt = q.get("quesType", "")
    return QTYPE_CN2NUM.get(qt, qt)


def _answer_fields(questions, answers, with_question_id=False):
    """构造每题的提交字段列表（unitTest 与 imitateTest 共用）。

    单选/判断: question=qid-A 或 qid-1
    多选:     question=~qid-A~qid-B~qid-C（前导 ~，每个选项前缀 qid-）
    """
    fields = []
    for q in questions:
        qid = q["id"]
        qt = _qtype(q)
        ans = answers.get(qid, "")
        if qt == "2":  # 多选
            val = "".join(f"~{qid}-{c}" for c in ans) if ans else ""
        else:          # 单选/判断
            val = f"{qid}-{ans}" if ans else ""
        fields.append(("question", val))
        if with_question_id:
            fields.append(("questionId", qid))
        fields.append(("quesType", qt))
    return fields


def guess(q):
    """题库未命中时的默认猜测（仅用于触发首次提交，错了会自动学习正确答案）"""
    qt = _qtype(q)
    if qt == "3":                        # 判断题，安全题“正确”偏多
        return "1"
    if qt == "2":                        # 多选，默认全选
        return "".join(c for c in "ABCDEF" if q.get(f"option{c}", ""))
    return "A"


def solve(questions, bank):
    """根据题库+默认猜测生成答案；返回 (答案字典, 未命中数)"""
    answers, miss = {}, 0
    for q in questions:
        key = norm(q["question"])
        entry = bank.get(key)
        if isinstance(entry, dict) and entry.get("answer"):
            answers[q["id"]] = entry["answer"]
        else:
            answers[q["id"]] = guess(q)
            miss += 1
    return answers, miss


def learn_from_wrong(s, cfg, log_id, bank):
    """从错题接口学习正确答案，返回新学/更新的题数"""
    if not log_id:
        return 0
    data = api_wrong_list(s, cfg, log_id)
    resp = data.get("data") or {}
    if not isinstance(resp, dict):
        return 0
    items = resp.get("data") or []
    if not isinstance(items, list):
        return 0
    learned = 0
    for item in items:
        q = item.get("question") or {} if isinstance(item, dict) else {}
        ans = (q.get("answer", "") or "").replace(",", "")  # 多选 "A,C,D," -> "ACD"
        if ans and q.get("question"):
            key = norm(q["question"])
            entry = bank.get(key)
            if not (isinstance(entry, dict) and entry.get("answer") == ans):
                bank[key] = {"answer": ans, "quesType": q.get("quesType", "")}
                learned += 1
    return learned


def _cancelled(cfg):
    event = getattr(cfg, "cancel_event", None)
    return bool(event and event.is_set())


def _pause(cfg):
    """可被 Web 停止按钮打断的请求间隔。"""
    event = getattr(cfg, "cancel_event", None)
    if event:
        event.wait(cfg.delay)
    else:
        time.sleep(cfg.delay)


def do_article(s, cfg, bank, article_id, title):
    print(f"\n  ▸ 文章[{title}]  id={article_id}")

    for attempt in range(1, cfg.max_retry + 1):
        if _cancelled(cfg):
            print("    [停止] 已取消，不再提交")
            return False
        qdata = api_question_list(s, cfg, article_id)
        if qdata.get("code") != 200:
            print(f"    [!] 取题失败: {qdata.get('message') or qdata}")
            return False
        questions = (qdata.get("data") or {}).get("list") or []
        if not questions:
            print("    [!] 该文章无题目，跳过")
            return True

        answers, miss = solve(questions, bank)
        if _cancelled(cfg):
            print("    [停止] 已取消，不再提交")
            return False
        result = api_unit_test(s, cfg, article_id, title, questions, answers)

        if result.get("code") != 200:
            msg = result.get("message") or result
            print(f"    [!] 提交异常: {msg}")
            if "303" in str(msg) or "登录" in str(msg) or result.get("code") == 303:
                print("    [!] ah/token 可能已过期，请重新从平台复制完整链接")
            return False

        d = result.get("data") or {}
        if d.get("isSuccess"):
            print(f"    [✓] 第 {attempt} 次提交通过（本次题库未命中 {miss} 题）")
            return True

        err = d.get("num", "?")
        log_id = d.get("logId", "")
        next_step = "拉取错题学习" if miss else "停止并保留内置题库"
        print(f"    [×] 第 {attempt} 次未通过，错 {err} 题，未命中 {miss} 题 → {next_step}")
        if not miss:
            print("    [!] 内置题库已覆盖本题，停止，不再请求错题接口")
            return False
        learned = learn_from_wrong(s, cfg, log_id, bank)
        print(f"        本轮学到/更新 {learned} 题正确答案")
        if learned:
            save_bank(bank)
        else:
            # 没学到新答案，重试只会提交相同答案，继续只会浪费请求。
            print("    [!] 未学到新答案，重试无意义，停止该篇")
            return False
        _pause(cfg)

    print(f"    [!] 达到最大重试次数 {cfg.max_retry}，放弃该篇")
    return False


# ==================== 考试模式 ====================
def api_test_get_test(s, cfg, exam_type):
    return s.post(f"{BASE}/wap/test/getTest", [
        ("examType", exam_type), ("examClass", cfg.exam_class),
        ("userId", cfg.user_id), ("ah", cfg.ah),
    ])


def api_test_create(s, cfg, exam_id):
    # 注意：每次 create 会消耗一次考试机会
    return s.post(f"{BASE}/wap/test/create", [
        ("examId", exam_id), ("userId", cfg.user_id), ("ah", cfg.ah),
    ])


def api_test_list(s, cfg, log_id):
    return s.get(f"{BASE}/wap/test/list", {
        "logId": log_id, "page": "1", "limit": "200",
        "ah": cfg.ah, "userId": cfg.user_id,
    })


def api_certificate_image(s, cfg):
    """读取平台生成的合格证书图片（data:image/... URI）。"""
    return s.post(f"{BASE}/wap/user/hegeImg", [
        ("userId", cfg.user_id), ("ah", cfg.ah),
    ])


def load_certificate_image(s, cfg):
    """将有效的证书图片保存到 cfg，供 Web 前端直接展示或下载。"""
    result = api_certificate_image(s, cfg)
    image = result.get("data") if isinstance(result, dict) else None
    if isinstance(image, str) and image.startswith("data:image/"):
        cfg.certificate_image = image
        return True
    return False


def api_imitate_test(s, cfg, exam_id, exam_type, log_id, questions, answers):
    fields = [
        ("examId", exam_id), ("examType", exam_type),
        ("sysSource", cfg.exam_class),   # sysSource 即 examClass
        ("logId", log_id), ("userId", cfg.user_id), ("ah", cfg.ah),
    ]
    fields.extend(_answer_fields(questions, answers, with_question_id=True))
    return s.post(f"{BASE}/wap/imitateTest", fields)


def _extract_questions(data):
    """统一抽取题目列表：
       question/list -> data.list[i] 即题目；
       test/list     -> data.data[i].question 才是题目"""
    resp = data.get("data") or {}
    if isinstance(resp, dict) and isinstance(resp.get("data"), list):
        return [it["question"] for it in resp["data"] if isinstance(it, dict) and it.get("question")]
    lst = resp.get("list") if isinstance(resp, dict) else None
    return lst or []


def do_exam(s, cfg, bank, exam_type, test_info=None):
    """参加考试；调用方已查询考试状态时可传入 test_info，避免重复请求。"""
    info = test_info if test_info is not None else api_test_get_test(s, cfg, exam_type)
    if info.get("code") != 200:
        print(f"获取考试信息失败: {info.get('message') or info}")
        return False
    d = info.get("data") or {}
    exam_id = d.get("id", "")
    name = d.get("name", "")
    last_num = _to_int(d.get("lastNum", 0) or 0)
    print(f"\n=== 考试: {name}  (examType={exam_type}, id={exam_id}) ===")
    print(f"    题数 {d.get('total')}  时长 {d.get('duration')} 分钟  "
          f"及格 {d.get('pass')} 分  剩余次数 {last_num}  (补考 {d.get('lastRasitNum')})")
    if last_num <= 0:
        if load_certificate_image(s, cfg):
            print("    [✓] 考试次数已用完，但已查询到合格证书")
            return True
        print("    [!] 考试次数已用完，且未查询到合格证书")
        return False

    # 模拟考默认允许重试刷题；正式考由 retry_exam 控制是否自动重考
    is_mock = "模拟" in name
    allow_retry = cfg.retry_exam or is_mock
    max_try = min(last_num, cfg.max_exam_retry) if allow_retry else 1

    for attempt in range(1, max_try + 1):
        if _cancelled(cfg):
            print("    [停止] 已取消，不再创建或提交考卷")
            return False
        print(f"\n  ▸ 第 {attempt}/{max_try} 次考试")
        cre = api_test_create(s, cfg, exam_id)
        if cre.get("code") != 200:
            print(f"    [!] 创建考卷失败: {cre.get('message') or cre}")
            return False
        cd = cre.get("data") or {}
        log_id = cd.get("logId", "")
        print(f"    考卷已创建 logId={log_id}  (本次消耗 1 次，剩 {last_num - attempt})")

        qdata = api_test_list(s, cfg, log_id)
        for fetch_try in range(2):
            if qdata.get("code") == 200:
                break
            print(f"    [!] 取题失败: {qdata.get('message') or qdata}（第 {fetch_try + 1}/3 次）")
            _pause(cfg)
            qdata = api_test_list(s, cfg, log_id)
        if qdata.get("code") != 200:
            # 不创建新考卷：每次 create 都会消耗一次考试机会。
            print("    [!] 同一考卷多次取题失败，中止本次考试，不再消耗剩余次数")
            return False
        questions = _extract_questions(qdata)
        if not questions:
            print("    [!] 该考卷无题目，中止本次考试，不再消耗剩余次数")
            return False
        hit = sum(1 for q in questions if norm(q.get("question", "")) in bank)
        print(f"    共 {len(questions)} 题，题库命中 {hit} 题")
        answers, miss = solve(questions, bank)

        if _cancelled(cfg):
            print("    [停止] 已取消，不再提交考卷")
            return False
        result = api_imitate_test(s, cfg, exam_id, str(exam_type), log_id, questions, answers)
        if result.get("code") not in (200, "200"):
            print(f"    [!] 提交异常: {result.get('message') or result}")
            return False
        rd = result.get("data") or {}
        score, err = rd.get("count", "?"), rd.get("num", "?")
        if rd.get("isSuccess"):
            print(f"    [✓] 通过！得分 {score}  错题 {err}")
            if rd.get("certificate"):
                # 保持 do_exam 的布尔返回值兼容命令行调用；Web 服务可从 cfg
                # 读取证书 ID，向前端推送可打开的证书页面。
                cfg.certificate_id = str(rd.get("certificate"))
                print(f"    合格证书 id: {cfg.certificate_id}")
                if load_certificate_image(s, cfg):
                    print("    证书图片已读取，可在页面中保存")
            if _to_int(err) > 0:
                # 仅在本卷有未命中题目时，才用错题接口作为兜底学习。
                if miss:
                    learned = learn_from_wrong(s, cfg, log_id, bank)
                    if learned:
                        save_bank(bank)
                        print(f"        通过后顺带学到/更新 {learned} 题正确答案")
                else:
                    print("        内置题库已覆盖本卷，不再请求错题接口")
            return True
        next_step = "拉取错题学习" if miss else "停止并保留内置题库"
        print(f"    [×] 未通过  得分 {score}  错题 {err}  -> {next_step}")
        if not miss:
            print("    [!] 内置题库已覆盖本卷，停止，不再请求错题接口")
            return False
        learned = learn_from_wrong(s, cfg, log_id, bank)
        print(f"        本轮学到/更新 {learned} 题正确答案")
        if learned:
            save_bank(bank)
        if not allow_retry or attempt >= max_try:
            print(f"    [!] 停止。剩余考试次数 {last_num - attempt}")
            return False
        _pause(cfg)
    return False


def run_courses(s, cfg, bank):
    """遍历所有课程/章节/文章并答题，返回 (通过, 跳过, 失败)。供 main 和 web 后台共用。"""
    cl = api_course_list(s, cfg)
    if cl.get("code") != 200:
        print(f"\n获取课程列表失败: {cl.get('message') or cl}")
        print("提示：ah/token 可能已过期，请重新从平台复制完整链接。")
        return 0, 0, 1
    courses = cl.get("data") or []
    print(f"\n共 {len(courses)} 门课程")

    total_done = total_skip = total_fail = 0
    total_course_skip = 0

    for c in courses:
        if _cancelled(cfg):
            print("\n[停止] 已取消，不再处理后续课程")
            break
        flag = "已完成" if c.get("isFinsh") else "未完成"
        print(f"\n=== 课程: {c['name']}  (id={c['id']})  [{flag}] ===")

        if c.get("isFinsh"):
            print("  ▸ 课程已完成，跳过目录请求")
            total_course_skip += 1
            continue

        dl = api_directory_list(s, cfg, c["id"])
        if dl.get("code") != 200:
            print(f"  获取目录失败: {dl.get('message')}")
            total_fail += 1
            continue
        chapters = dl.get("data") or []

        for ch in chapters:
            for art in (ch.get("list") or []):
                if _cancelled(cfg):
                    print("\n[停止] 已取消，不再处理后续章节")
                    break
                aid = art.get("id")
                title = art.get("course", "")
                if art.get("isFinsh"):
                    print(f"  ▸ [{title}] 已完成，跳过")
                    total_skip += 1
                    continue
                ok = do_article(s, cfg, bank, aid, title)
                if ok:
                    total_done += 1
                else:
                    total_fail += 1
                _pause(cfg)
            if _cancelled(cfg):
                break
        if _cancelled(cfg):
            break

    print("\n==================== 结束 ====================")
    print(f"通过 {total_done}  跳过课程 {total_course_skip}  跳过文章 {total_skip}  失败 {total_fail}")
    print(f"题库现有 {len(bank)} 题，可备份复用: {BANK_FILE}")
    return total_done, total_skip, total_fail
