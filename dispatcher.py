# -*- coding: utf-8 -*-
import os, time, subprocess, datetime, re, shutil

# === ПУТИ ===
DRIVE      = r"G:\Мой диск\AgentBus"
PROJECT    = r"D:\Workspace"
OPENCODE   = r"D:\Progs\opencode.exe"
INCOMING   = os.path.join(DRIVE, "incoming")
PROCESSING = os.path.join(DRIVE, "processing")
DONE       = os.path.join(DRIVE, "done")
ERRORS     = os.path.join(DRIVE, "errors")

# === НАСТРОЙКИ ===
MAX_TRIES   = 3
STALE_TIME  = 3600
GIT_ENABLED = True   

def read(p):
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

def write(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(t)

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

def timestamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M")

def wait_stable(path, timeout=30):
    prev = -1
    start = time.time()
    while time.time() - start < timeout:
        try:
            cur = os.path.getsize(path)
        except OSError:
            return False
        if cur == prev:
            return True
        prev = cur
        time.sleep(3)
    return False

def parse_tasks(text):
    items = []
    for line in text.splitlines():
        m = re.match(r"^-?\s*\[([ x~])(\d?)\]\s*(.+)$", line.strip())
        if m:
            items.append((m.group(1), m.group(3), int(m.group(2) or 0)))
        elif line.strip():
            items.append((None, line, 0))
    return items

def run_coder(task_text):
    try:
        res = subprocess.run(
            [OPENCODE, "run", task_text],
            cwd=PROJECT, capture_output=True, text=True, timeout=1800
        )
        out = res.stdout + "\n" + res.stderr
        if res.returncode != 0:
            return False, out
        if "traceback" in out.lower():
            return False, out
        return True, out
    except subprocess.TimeoutExpired:
        return False, "Таймаут >30 минут"
    except Exception as e:
        return False, f"Исключение: {e}"

def git_push(task_text):
    if not GIT_ENABLED:
        return True
    try:
        subprocess.run(["git", "add", "-A"], cwd=PROJECT, check=True)
        if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=PROJECT).returncode == 0:
            return True
        subprocess.run(["git", "commit", "-m", f"auto: {task_text[:80]}"], cwd=PROJECT, check=True)
        subprocess.run(["git", "push"], cwd=PROJECT, check=True, timeout=60)
        return True
    except Exception as e:
        print(f"git ошибка: {e}")
        return False

def recover_stale():
    for f in os.listdir(PROCESSING):
        if f.startswith("tasks_"):
            p = os.path.join(PROCESSING, f)
            if time.time() - os.path.getmtime(p) > STALE_TIME:
                shutil.move(p, os.path.join(INCOMING, f))
                print(f"[{now()}] восстановлен: {f}")

def main_loop():
    print(f"[{now()}] диспетчер запущен")
    print(f"Drive: {DRIVE}")
    print(f"Проект: {PROJECT}\n")
    for d in [INCOMING, PROCESSING, DONE, ERRORS]:
        os.makedirs(d, exist_ok=True)
    while True:
        try:
            recover_stale()
            files = sorted(f for f in os.listdir(INCOMING)
                           if f.startswith("tasks_") and f.endswith(".md"))
            if not files:
                time.sleep(15)
                continue
            filename = files[0]
            inc_path = os.path.join(INCOMING, filename)
            prc_path = os.path.join(PROCESSING, filename)
            if not wait_stable(inc_path):
                time.sleep(5)
                continue
            shutil.move(inc_path, prc_path)
            print(f"[{now()}] взял: {filename}")
            items = parse_tasks(read(prc_path))
            done_tasks, error_tasks = [], []
            for status, task, attempt in items:
                if status != " ":
                    continue
                if attempt >= MAX_TRIES:
                    error_tasks.append((task, f"Превышено {MAX_TRIES} попыток"))
                    continue
                print(f"[{now()}] кодер ({attempt+1}/{MAX_TRIES}): {task}")
                ok, output = run_coder(task)
                if ok and git_push(task):
                    done_tasks.append((task, output))
                    print(f"[{now()}] ✓ готово")
                else:
                    error_tasks.append((task, output))
                    print(f"[{now()}] ✗ ошибка")
            if done_tasks:
                report = f"# Отчёт {now()}\n\n" + "".join(
                    f"## ✓ {t}\n\n```\n{o[-1500:]}\n```\n\n" for t, o in done_tasks)
                write(os.path.join(DONE, f"report_{timestamp()}.md"), report)
            if error_tasks:
                errors_text = f"# Ошибки {now()}\n\n**Разбей на подзадачи и верни в incoming/**\n\n" + "".join(
                    f"## Задача: {t}\n\n```\n{o[-2000:]}\n```\n\n" for t, o in error_tasks)
                write(os.path.join(ERRORS, f"fail_{timestamp()}.md"), errors_text)
            os.remove(prc_path)
            print(f"[{now()}] файл обработан\n")
        except Exception as e:
            print(f"[{now()}] ошибка: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main_loop()