#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园安全通 (xiaoyuananquantong.com) 自动答题脚本

原理（纯明文 HTTP 接口，无加密/签名）：
  1. POST /wap/compulsory/list   获取课程列表           -> courseId
  2. POST /wap/directory/list    获取章节/文章目录       -> articleId, title
  3. GET  /wap/question/list     获取题目               -> questionId, 选项, 题型
  4. POST /wap/unitTest          提交答案
  5. GET  /wap/wrong/list        获取错题(含正确答案)    -> 自动学习并重试

提交格式（复刻页面 setVle/serialize 逻辑）：
  单选 : question={qid}-{字母}            例 165xxx-A
  判断 : question={qid}-{1|0}             例 165xxx-1   (1=正确 0=错误)
  多选 : question=~{qid}-A~{qid}-B~{qid}-C           (前导 ~，每个选项前缀 qid-)

题库 xy_bank.json 会自动积累（键: 归一化题干，值: 正确答案），越用越准，可备份复用。

用法：
  python3 xy_auto.py --dry-run                 # 先只看题目不提交（验证链路）
  python3 xy_auto.py                           # 一键完成所有未完成文章
  python3 xy_auto.py --force                   # 重做（含已完成）
  python3 xy_auto.py --course-id 1656483732162404354   # 只处理指定课程
  python3 xy_auto.py --ah 新token               # ah 过期后换新 token
"""

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ==================== 默认配置（可用命令行覆盖）====================
BASE = "http://wap.xiaoyuananquantong.com/guns-vip-main"
DEFAULT_USER_ID = ""
DEFAULT_COLLEGE_ID = "1940953111032012801"
DEFAULT_AH = ""
DEFAULT_COURSE_TYPE = "1"
BANK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xy_bank.json")

UA = ("Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")

# question/list 用中文题型，提交用数字，两套编码
QTYPE_CN2NUM = {"单选": "1", "多选": "2", "判断": "3"}


# ==================== HTTP Session ====================
class Session:
    def __init__(self):
        cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj))
        self.opener.addheaders = [
            ("User-Agent", UA),
            ("X-Requested-With", "XMLHttpRequest"),
            ("Accept", "application/json, text/plain, */*"),
        ]

    def _open(self, req):
        try:
            with self.opener.open(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            return {"code": e.code, "message": f"HTTP {e.code}: {body}"}
        except Exception as e:
            return {"code": -1, "message": str(e)}

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
    with open(BANK_FILE, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


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
    for q in questions:
        qid = q["id"]
        qt = _qtype(q)
        ans = answers.get(qid, "")
        if qt == "2":  # 多选：~qid-A~qid-B~qid-C
            val = "".join(f"~{qid}-{c}" for c in ans) if ans else ""
        else:          # 单选/判断：qid-A 或 qid-1
            val = f"{qid}-{ans}" if ans else ""
        fields.append(("question", val))
        fields.append(("quesType", qt))
    return s.post(f"{BASE}/wap/unitTest", fields)


def api_wrong_list(s, cfg, log_id, limit=200):
    return s.get(f"{BASE}/wap/wrong/list",
                 {"errorLogId": log_id, "page": "1", "limit": str(limit)})


# ==================== 答题逻辑 ====================
def _qtype(q):
    """统一题型为数字: 1单选 2多选 3判断（兼容 question/list 的中文与 test/list 的数字编码）"""
    qt = q.get("quesType", "")
    return QTYPE_CN2NUM.get(qt, qt)


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
        if key in bank and bank[key].get("answer"):
            answers[q["id"]] = bank[key]["answer"]
        else:
            answers[q["id"]] = guess(q)
            miss += 1
    return answers, miss


def learn_from_wrong(s, cfg, log_id, bank):
    """从错题接口学习正确答案，返回新学/更新的题数"""
    if not log_id:
        return 0
    data = api_wrong_list(s, cfg, log_id)
    re = data.get("data") or {}
    learned = 0
    for item in (re.get("data") or []):
        q = item.get("question") or {}
        ans = (q.get("answer", "") or "").replace(",", "")  # 多选 "A,C,D," -> "ACD"
        if ans and q.get("question"):
            key = norm(q["question"])
            if bank.get(key, {}).get("answer") != ans:
                bank[key] = {"answer": ans, "quesType": q.get("quesType", "")}
                learned += 1
    return learned


def do_article(s, cfg, bank, article_id, title):
    print(f"\n  ▸ 文章[{title}]  id={article_id}")

    if cfg.dry_run:
        qdata = api_question_list(s, cfg, article_id)
        qs = (qdata.get("data") or {}).get("list") or []
        print(f"    (dry-run) 共 {len(qs)} 题，不提交")
        for i, q in enumerate(qs, 1):
            bank_ans = bank.get(norm(q["question"]), {}).get("answer", "—")
            print(f"      {i}.[{q.get('quesType')}] {q['question']}")
            for c in "ABCDEF":
                if q.get(f"option{c}"):
                    mark = "  <-- 题库" if bank_ans == c else ""
                    print(f"         {c}. {q[f'option{c}']}{mark}")
        return True

    for attempt in range(1, cfg.max_retry + 1):
        qdata = api_question_list(s, cfg, article_id)
        if qdata.get("code") != 200:
            print(f"    [!] 取题失败: {qdata.get('message') or qdata}")
            return False
        questions = (qdata.get("data") or {}).get("list") or []
        if not questions:
            print("    [!] 该文章无题目，跳过")
            return True

        answers, miss = solve(questions, bank)
        result = api_unit_test(s, cfg, article_id, title, questions, answers)

        if result.get("code") != 200:
            msg = result.get("message") or result
            print(f"    [!] 提交异常: {msg}")
            if "303" in str(msg) or "登录" in str(msg) or result.get("code") == 303:
                print("    [!] ah/token 可能已过期，请重新登录获取新 ah 后用 --ah 传入")
            return False

        d = result.get("data") or {}
        if d.get("isSuccess"):
            print(f"    [✓] 第 {attempt} 次提交通过（本次题库未命中 {miss} 题）")
            return True

        err = d.get("num", "?")
        log_id = d.get("logId", "")
        print(f"    [×] 第 {attempt} 次未通过，错 {err} 题，未命中 {miss} 题 → 拉取错题学习")
        learned = learn_from_wrong(s, cfg, log_id, bank)
        print(f"        本轮学到/更新 {learned} 题正确答案")
        if learned:
            save_bank(bank)
        elif miss == 0:
            # 题库全命中却仍错：可能多选/判断格式或匹配有误，避免空转
            print("    [!] 题库已全命中但未通过，可能答案格式异常，停止该篇以排查")
            return False
        time.sleep(cfg.delay)

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


def api_imitate_test(s, cfg, exam_id, exam_type, log_id, questions, answers):
    fields = [
        ("examId", exam_id), ("examType", exam_type),
        ("sysSource", cfg.exam_class),   # sysSource 即 examClass
        ("logId", log_id), ("userId", cfg.user_id), ("ah", cfg.ah),
    ]
    for q in questions:
        qid = q["id"]
        qt = _qtype(q)
        ans = answers.get(qid, "")
        if qt == "2":
            val = "".join(f"~{qid}-{c}" for c in ans) if ans else ""
        else:
            val = f"{qid}-{ans}" if ans else ""
        fields.append(("question", val))
        fields.append(("questionId", qid))
        fields.append(("quesType", qt))
    return s.post(f"{BASE}/wap/imitateTest", fields)


def _extract_questions(data):
    """统一抽取题目列表：
       question/list -> data.list[i] 即题目；
       test/list     -> data.data[i].question 才是题目"""
    re = data.get("data") or {}
    if isinstance(re, dict) and re.get("data"):
        return [it["question"] for it in re["data"] if isinstance(it, dict) and it.get("question")]
    lst = re.get("list") if isinstance(re, dict) else None
    return lst or []


def do_exam(s, cfg, bank, exam_type):
    info = api_test_get_test(s, cfg, exam_type)
    if info.get("code") != 200:
        print(f"获取考试信息失败: {info.get('message') or info}")
        return False
    d = info.get("data") or {}
    exam_id = d.get("id", "")
    name = d.get("name", "")
    last_num = int(d.get("lastNum", 0) or 0)
    print(f"\n=== 考试: {name}  (examType={exam_type}, id={exam_id}) ===")
    print(f"    题数 {d.get('total')}  时长 {d.get('duration')} 分钟  "
          f"及格 {d.get('pass')} 分  剩余次数 {last_num}  (补考 {d.get('lastRasitNum')})")
    if last_num <= 0:
        print("    [!] 考试次数已用完")
        return False
    if cfg.dry_run:
        print("    (dry-run) 不创建考卷、不提交")
        return True

    # 模拟考默认允许重试刷题；正式考默认只考1次，需 --retry-exam 才自动重考
    is_mock = "模拟" in name
    allow_retry = cfg.retry_exam or is_mock
    max_try = min(last_num, cfg.max_exam_retry) if allow_retry else 1

    for attempt in range(1, max_try + 1):
        print(f"\n  ▸ 第 {attempt}/{max_try} 次考试")
        cre = api_test_create(s, cfg, exam_id)
        if cre.get("code") != 200:
            print(f"    [!] 创建考卷失败: {cre.get('message') or cre}")
            return False
        cd = cre.get("data") or {}
        log_id = cd.get("logId", "")
        print(f"    考卷已创建 logId={log_id}  (本次消耗 1 次，剩 {last_num - attempt})")

        qdata = api_test_list(s, cfg, log_id)
        if qdata.get("code") != 200:
            print(f"    [!] 取题失败: {qdata.get('message') or qdata}")
            continue
        questions = _extract_questions(qdata)
        if not questions:
            print("    [!] 无题目，跳过")
            continue
        hit = sum(1 for q in questions if norm(q.get("question", "")) in bank)
        print(f"    共 {len(questions)} 题，题库命中 {hit} 题")
        answers, miss = solve(questions, bank)

        result = api_imitate_test(s, cfg, exam_id, str(exam_type), log_id, questions, answers)
        if result.get("code") not in (200, "200"):
            print(f"    [!] 提交异常: {result.get('message') or result}")
            return False
        rd = result.get("data") or {}
        score, err = rd.get("count", "?"), rd.get("num", "?")
        if rd.get("isSuccess"):
            print(f"    [✓] 通过！得分 {score}  错题 {err}")
            if rd.get("certificate"):
                print(f"    合格证书 id: {rd.get('certificate')}")
            return True
        print(f"    [×] 未通过  得分 {score}  错题 {err}  -> 拉取错题学习")
        learned = learn_from_wrong(s, cfg, log_id, bank)
        print(f"        本轮学到/更新 {learned} 题正确答案")
        if learned:
            save_bank(bank)
        if not allow_retry or attempt >= max_try:
            print(f"    [!] 停止。剩余考试次数 {last_num - attempt}")
            return False
        time.sleep(cfg.delay)
    return False


def do_learn_all(s, cfg, bank, exam_type):
    """全错提交快速学习：每轮提交无效答案让 50 题全错，一次学完全部正确答案。
    比正常刷题(只学猜错的)快几十倍，几轮即可覆盖整个题库。"""
    info = api_test_get_test(s, cfg, exam_type)
    if info.get("code") != 200:
        print(f"获取考试信息失败: {info.get('message') or info}"); return
    d = info.get("data") or {}
    exam_id = d.get("id", "")
    print(f"\n=== 快速学习模式: {d.get('name')}  (题库现有 {len(bank)} 题) ===")
    if cfg.dry_run:
        print("    (dry-run) 不创建考卷"); return
    empty, total = 0, 0
    for attempt in range(1, cfg.max_exam_retry + 1):
        cre = api_test_create(s, cfg, exam_id)
        if cre.get("code") != 200:
            print(f"  第{attempt}轮创建考卷失败: {cre.get('message')}"); break
        log_id = (cre.get("data") or {}).get("logId", "")
        qdata = api_test_list(s, cfg, log_id)
        qs = _extract_questions(qdata)
        if not qs:
            print(f"  第{attempt}轮无题目"); continue
        # 全部提交无效答案(单选/多选 Z、判断 9)，确保每题都错 -> 触发错题回传全部正确答案
        answers = {q["id"]: ("9" if _qtype(q) == "3" else "Z") for q in qs}
        api_imitate_test(s, cfg, exam_id, str(exam_type), log_id, qs, answers)
        learned = learn_from_wrong(s, cfg, log_id, bank)
        total += learned
        save_bank(bank)
        print(f"  第{attempt:2d}轮: 学到 {learned:2d} 新题  (题库累计 {len(bank)})")
        if learned == 0:
            empty += 1
            if empty >= 2:
                print("  ✓ 连续 2 轮无新题，题库已覆盖完成"); break
        else:
            empty = 0
        time.sleep(cfg.delay)
    print(f"学习结束：本轮共学 {total} 题，题库累计 {len(bank)} 题  (文件: {BANK_FILE})")


# ==================== 主流程 ====================
def main():
    p = argparse.ArgumentParser(
        description="校园安全通自动答题（自动学习错题，闭环完成）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user-id", default=DEFAULT_USER_ID)
    p.add_argument("--college-id", default=DEFAULT_COLLEGE_ID)
    p.add_argument("--ah", default=DEFAULT_AH, help="登录 token（会话凭证，过期需更换）")
    p.add_argument("--course-type", default=DEFAULT_COURSE_TYPE, help="课程类型，默认 1")
    p.add_argument("--course-id", help="只处理指定课程 id（逗号分隔）")
    p.add_argument("--force", action="store_true", help="重做已完成的文章")
    p.add_argument("--dry-run", action="store_true", help="只看题目不提交")
    p.add_argument("--delay", type=float, default=0.5, help="请求间隔秒，默认 0.5")
    p.add_argument("--max-retry", type=int, default=10, help="每篇文章最大重试次数，默认 10")
    p.add_argument("--yes", action="store_true", help="跳过开始前确认")
    p.add_argument("--exam", action="store_true", help="考试模式(simulate)")
    p.add_argument("--exam-type", default="1", help="1=模拟考试(无限次) 2=正式考试(限次)")
    p.add_argument("--exam-class", default="10")
    p.add_argument("--retry-exam", action="store_true", help="正式考试未通过也自动重考(消耗次数)")
    p.add_argument("--max-exam-retry", type=int, default=30, help="考试最大尝试次数(模拟考刷题用)")
    p.add_argument("--learn-all", action="store_true", help="全错提交快速学习:每轮学全部50题正确答案,刷满题库")
    cfg = p.parse_args()

    s = Session()
    bank = load_bank()
    print(f"题库已加载 {len(bank)} 题  (文件: {BANK_FILE})")
    print(f"用户 {cfg.user_id}  课程类型 {cfg.course_type}  force={cfg.force}  dry-run={cfg.dry_run}")

    if not cfg.dry_run and not cfg.yes:
        print("\n即将开始自动答题并真实提交到你的账号。回车继续，Ctrl+C 取消。")
        try:
            input()
        except KeyboardInterrupt:
            print("已取消"); return

    if cfg.exam:
        if cfg.learn_all:
            do_learn_all(s, cfg, bank, cfg.exam_type)
        else:
            ok = do_exam(s, cfg, bank, cfg.exam_type)
            print(f"\n考试结果: {'通过' if ok else '未通过'}  题库现有 {len(bank)} 题  (文件: {BANK_FILE})")
        return

    # 1. 课程列表
    cl = api_course_list(s, cfg)
    if cl.get("code") != 200:
        print(f"\n获取课程列表失败: {cl.get('message') or cl}")
        print("提示：ah/token 可能已过期，请重新登录 wap.xiaoyuananquantong.com，"
              "从 URL 复制新的 ah 值后用 --ah 传入。")
        return
    courses = cl.get("data") or []
    print(f"\n共 {len(courses)} 门课程")

    only_ids = set(x.strip() for x in cfg.course_id.split(",")) if cfg.course_id else None
    total_done = total_skip = total_fail = 0

    for c in courses:
        if only_ids and c["id"] not in only_ids:
            continue
        flag = "已完成" if c.get("isFinsh") else "未完成"
        print(f"\n=== 课程: {c['name']}  (id={c['id']})  [{flag}] ===")

        dl = api_directory_list(s, cfg, c["id"])
        if dl.get("code") != 200:
            print(f"  获取目录失败: {dl.get('message')}")
            continue
        chapters = dl.get("data") or []

        for ch in chapters:
            for art in (ch.get("list") or []):
                aid = art.get("id")
                title = art.get("course", "")
                if art.get("isFinsh") and not cfg.force:
                    print(f"  ▸ [{title}] 已完成，跳过（--force 可重做）")
                    total_skip += 1
                    continue
                ok = do_article(s, cfg, bank, aid, title)
                if ok:
                    total_done += 1
                else:
                    total_fail += 1
                time.sleep(cfg.delay)

    print(f"\n==================== 结束 ====================")
    print(f"通过 {total_done}  跳过 {total_skip}  失败 {total_fail}")
    print(f"题库现有 {len(bank)} 题，可备份复用: {BANK_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断"); sys.exit(130)
