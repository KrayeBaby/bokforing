#!/usr/bin/env python3
"""PreToolUse-spärr för Krayes repon.

Molnet (Linux): släpper igenom allt utom det farliga, så att ingen tråd står
och väntar på ett klick. Det farliga nekas med ett skäl som tråden kan läsa
och agera på. Lokalt (Mac/Windows) körs redan allt utan frågor; där nekas
bara det som inte går att ångra.
"""
import json
import os
import re
import shlex
import sys

CLOUD = sys.platform.startswith("linux")


def split_top(cmd):
    parts, buf, q, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            buf.append(ch)
            if ch == "\\" and q == '"' and i + 1 < len(cmd):
                buf.append(cmd[i + 1])
                i += 1
            elif ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            buf.append(ch)
        elif ch in ";\n|&":
            parts.append("".join(buf))
            buf = []
            while i + 1 < len(cmd) and cmd[i + 1] in "|&":
                i += 1
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def words(seg):
    try:
        t = shlex.split(seg, posix=True)
    except ValueError:
        t = seg.split()
    while t and (t[0] in ("sudo", "env", "time", "nohup", "command", "do", "then", "else", "{", "(")
                 or re.match(r"^[A-Za-z_]\w*=", t[0])):
        t = t[1:]
    return t


def real(path, cwd):
    p = os.path.expandvars(os.path.expanduser(path))
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd, p))


def inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def temp_dirs():
    dirs = ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders", "/var/tmp"]
    if os.environ.get("TMPDIR"):
        dirs.append(os.path.realpath(os.environ["TMPDIR"]))
    return dirs


def check_rm(t, cwd, project):
    flags = "".join(w[1:] for w in t[1:] if w.startswith("-") and not w.startswith("--"))
    recursive = "r" in flags or "R" in flags or "--recursive" in t
    if not recursive:
        return None
    home = os.path.realpath(os.path.expanduser("~"))
    for w in t[1:]:
        if w.startswith("-"):
            continue
        p = real(w, cwd)
        if p in ("/", home, project) or p == os.path.dirname(project):
            return f"rm -r på {w} skulle radera hela {p}."
        if os.path.basename(p) == ".git" or "/.git/" in p + "/" and inside(p, project):
            return f"rm -r på {w} raderar git-historiken."
        if w in ("*", "./*") and os.path.realpath(cwd) == project:
            return "rm -r * i projektroten raderar hela arbetskopian."
        if CLOUD and not inside(p, project) and not any(inside(p, d) for d in temp_dirs()):
            return f"rm -r utanför projektet ({p})."
    return None


DENY_ALWAYS = [
    (r"\bgit\b[^;&|\n]*\bpush\b[^;&|\n]*(\s--force(-with-lease)?\b|\s-[a-zA-Z]*f\b|\s\+\S)",
     "force-push skriver över historik på GitHub."),
    (r"\bgit\b[^;&|\n]*\breset\b[^;&|\n]*--hard", "git reset --hard kastar ocommittat arbete."),
    (r"\bgit\b[^;&|\n]*\bclean\b[^;&|\n]*\s-[a-zA-Z]*f", "git clean -f raderar ospårade filer."),
    (r"\bgh\s+repo\s+(delete|archive|rename)\b", "gh repo delete/archive/rename ändrar hela repot."),
    (r"\bgh\s+api\b[^;&|\n]*(-X|--method)\s*DELETE\b", "DELETE mot GitHubs API raderar data."),
    (r"\bgh\s+(secret|variable)\s+(set|delete)\b", "ändrar hemligheter på GitHub."),
]
DENY_CLOUD = [
    (r"\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "kör ett skript direkt från nätet."),
    (r"\bcurl\b[^;&|\n]*(\s-d\b|\s--data|\s-F\b|\s--form\b|\s-T\b|\s--upload-file|\s(-X|--request)\s*(POST|PUT|PATCH|DELETE))",
     "skickar data från molnet till en extern server."),
    (r"(>>?\s*|\b(tee|cp|mv|rm|ln|chmod)\b[^;&|\n]*|\bsed\b[^;&|\n]*\s-i[^;&|\n]*)\S*\.claude/(settings[^/\s]*\.json|hooks/)",
     "ändrar trådens egna behörigheter eller spärren."),
]
PROTECTED = re.compile(r"(^|/)\.claude/(settings[^/]*\.json|hooks/)|(^|/)\.git/")


def decide(data):
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    project = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)

    if tool == "Bash":
        cmd = inp.get("command", "")
        for pat, why in DENY_ALWAYS + (DENY_CLOUD if CLOUD else []):
            if re.search(pat, cmd):
                return "deny", why
        for seg in split_top(cmd):
            t = words(seg)
            if t and os.path.basename(t[0]) == "rm":
                why = check_rm(t, cwd, project)
                if why:
                    return "deny", why
        return ("allow", "spärren släppte igenom") if CLOUD else (None, None)

    path = inp.get("file_path") or inp.get("notebook_path")
    if path:
        p = real(path, cwd)
        if CLOUD and PROTECTED.search(p):
            return "deny", "filen styr trådens behörigheter, spärren eller git-historiken."
        if CLOUD and (inside(p, project) or any(inside(p, d) for d in temp_dirs())):
            return "allow", "fil i projektet"
    return None, None


def main():
    try:
        decision, why = decide(json.load(sys.stdin))
    except Exception:
        return
    if not decision:
        return
    if decision == "deny":
        why = ("Spärren stoppade det här: " + why +
               " Välj ett säkrare sätt, eller be Kraye i chatten om det verkligen behövs.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": why,
    }}, ensure_ascii=False))


if __name__ == "__main__":
    main()
