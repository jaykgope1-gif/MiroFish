"""
God View demo: one command, no API keys.

    npm run demo          (from the repository root)

What it does:
1. Starts a stand-in LLM on 127.0.0.1:5055 (see stub_llm.py), unless the
   repository's .env has a real LLM key, in which case that LLM is used.
2. Writes a small fictional simulation (see make_demo.py).
3. Starts the MiroFish backend (port 5001) and frontend (port 3000).
4. Starts the simulation on both platforms and opens the God View at
   http://localhost:3000/god/sim_god_demo

Ctrl+C stops everything.

The first run downloads the Twitter recommender model from Hugging Face
(about 1 GB), so the Twitter side may take a few minutes to begin.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, HERE)

STUB_PORT = 5055
BACKEND_URL = "http://127.0.0.1:5001"
GOD_URL = "http://localhost:3000/god/"
IS_WINDOWS = sys.platform == "win32"
# Local calls must not go through a corporate proxy.
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def port_busy(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def read_env_file():
    path = os.path.join(ROOT_DIR, ".env")
    values = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip('"').strip("'")
    return path, values


def http(method, path, payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BACKEND_URL + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    with NO_PROXY.open(request, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def start(cmd, cwd, env):
    kwargs = {"cwd": cwd, "env": env}
    if IS_WINDOWS:
        kwargs["shell"] = True
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd if not IS_WINDOWS else subprocess.list2cmdline(cmd), **kwargs)


def stop(process):
    if process.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def main():
    busy = [p for p in (5001, 3000) if port_busy(p)]
    if busy:
        sys.exit(f"Port(s) {', '.join(map(str, busy))} already in use. Stop whatever is running there "
                 "(another MiroFish?) and try again.")

    env = os.environ.copy()
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    env_path, env_file = read_env_file()
    provider = env_file.get("LLM_PROVIDER", "openai").lower()
    key = env_file.get("ANTHROPIC_API_KEY" if provider == "anthropic" else "LLM_API_KEY", "")
    if env_file and (not key or key.startswith("your_")):
        sys.exit(f"{env_path} exists but has no real API key. Either fill it in (the demo then uses "
                 "that LLM) or delete/rename it to run the demo with the built-in stand-in.")

    if key:
        print(f"Using the LLM configured in {env_path}.")
    else:
        if port_busy(STUB_PORT):
            sys.exit(f"Port {STUB_PORT} (demo LLM stand-in) is already in use.")
        import stub_llm
        stub_llm.serve(STUB_PORT)
        env.update({
            # The demo runs MiroFish's Claude code path against the stand-in.
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "demo-key",
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{STUB_PORT}",
            # Only needed by the graph panel and reports, which the demo cannot use.
            "ZEP_API_KEY": "demo-key",
        })
        print("No .env found: agents are driven by the demo stand-in (canned text, no real LLM).")

    from make_demo import DEMO_ID, make_demo
    make_demo()
    print(f"Demo simulation written: {DEMO_ID}")

    processes = [
        start([sys.executable, "run.py"], BACKEND_DIR, env),
        start(["npm", "run", "dev", "--", "--strictPort", "--open", f"/god/{DEMO_ID}"],
              os.path.join(ROOT_DIR, "frontend"), env),
    ]
    try:
        print("Waiting for the backend to start (this can take a minute)...")
        for _ in range(240):
            if processes[0].poll() is not None:
                sys.exit("The backend exited during start-up; see its output above.")
            try:
                http("GET", "/health")
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit("The backend did not answer within 2 minutes.")

        result = http("POST", "/api/simulation/start",
                      {"simulation_id": DEMO_ID, "platform": "parallel", "force": True}, timeout=60)
        if not result.get("success"):
            sys.exit(f"Could not start the simulation: {result.get('error')}")

        print("\n" + "=" * 64)
        print(f"  God View: {GOD_URL}{DEMO_ID}")
        print("  Press : to type a command, ? for every key and command.")
        print("  Try: pause / inject <news> / step / interview Maya Chen <question>")
        print("       poll <question> / fork whatif / resume / diff base whatif")
        print("  Ctrl+C here stops everything.")
        print("=" * 64 + "\n")

        while all(p.poll() is None for p in processes):
            time.sleep(1)
        print("A MiroFish process exited; stopping the demo.")
    except KeyboardInterrupt:
        print("\nStopping the demo...")
    finally:
        for process in reversed(processes):
            stop(process)


if __name__ == "__main__":
    main()
