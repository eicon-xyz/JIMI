"""
HAJIMI local integration test — mimics Postman call chain
Usage: python test_api.py
"""
import json, urllib.request, urllib.error, time

BASE = "http://127.0.0.1:8010"
HEADERS = {"X-Demo-Key": "hajimi-demo-2026", "Content-Type": "application/json"}


def req(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health():
    code, data = req("GET", "/api/demo/health")
    print(f"[HEALTH] {code} - omniparser_ready={data.get('omniparser_ready')}")
    return code in (200, 503)


def test_execute(query):
    code, data = req("POST", "/api/demo/execute", {"query": query, "image": None})
    if code == 200:
        print(f"[EXECUTE] task_id={data['task_id']}")
        print(f"  goal: {data['plan']['goal']}")
        for s in data["plan"]["steps"]:
            print(f"  step {s['step_index']}: {s['instruction'][:80]}")
        return data["task_id"]
    else:
        print(f"[EXECUTE] ERROR: {data.get('error',{}).get('message',data)}")
        return None


def test_stream(task_id, timeout=180):
    print(f"[STREAM] listening on task_id={task_id} ...")
    url = f"{BASE}/api/demo/stream/{task_id}"
    r = urllib.request.Request(url, headers={"X-Demo-Key": "hajimi-demo-2026"})
    events = []
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            buf = b""
            while True:
                ch = resp.read(1024)
                if not ch: break
                buf += ch
                while b"\n\n" in buf:
                    line, buf = buf.split(b"\n\n", 1)
                    txt = line.decode("utf-8", errors="replace")
                    ev = data = ""
                    for p in txt.split("\n"):
                        if p.startswith("event: "): ev = p[7:]
                        elif p.startswith("data: "): data = json.loads(p[6:])
                    if ev:
                        msg = json.dumps(data, ensure_ascii=False)[:150]
                        print(f"  -> {ev}: {msg}")
                        events.append((ev, data))
                        if ev in ("task_done", "task_failed", "task_cancelled"):
                            return ev, events
    except Exception as e:
        print(f"[STREAM] error: {e}")
        return None, events
    return None, events


def check_memories():
    from server.database import init_db, SessionLocal
    from server.database.models import Memory
    from sqlalchemy import func
    import re

    init_db()
    db = SessionLocal()
    types = db.query(Memory.memory_type, func.count(Memory.memory_id))\
              .filter(Memory.is_active == True)\
              .group_by(Memory.memory_type).all()
    resolved = db.query(func.count(Memory.memory_id)).filter(
        Memory.is_active == False,
        Memory.memory_type == "failure_lesson",
        Memory.resolved_count > 0
    ).scalar()
    recent = db.query(Memory).filter(
        Memory.is_active == True,
        Memory.memory_type == "success_pattern"
    ).order_by(Memory.created_at.desc()).limit(5).all()
    db.close()

    print()
    print("=== MEMORY SYSTEM STATE ===")
    print(f"Active memories: {sum(c for _,c in types)} total")
    for t, c in types:
        print(f"  {t}: {c}")
    print(f"Resolved failure lessons: {resolved}")
    print()
    print("Recent success patterns:")
    for m in recent:
        clean = re.sub(r"[^\x20-\x7e一-鿿]", "", m.summary[:80])
        print(f"  [{m.category}] {clean}")


if __name__ == "__main__":
    QUERY = """打开浏览器访问 github.com/trending 页面，
浏览前三个热门项目，分别点击进入查看详情，
提取每个项目的名称、Star数和项目简介，
最后用VSCode新建一个文件，将三个项目整理成Markdown表格保存到桌面"""

    print("=" * 60)
    print("HAJIMI Complex Task Test")
    print("=" * 60)

    if not test_health():
        print("FAIL: server not ready — run python server/main.py")
        exit(1)

    task_id = test_execute(QUERY)
    if not task_id:
        print("FAIL: planning")
        exit(1)

    result, events = test_stream(task_id, timeout=300)
    status = result or "timeout"
    print(f"\nRESULT: {status}")

    # Verify that this run produced both success and failure memories
    check_memories()

    print()
    print("=" * 60)
    print("Done.")
