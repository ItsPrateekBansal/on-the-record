"""Invoice Watchdog — the local model (Ollama): Nemotron 3 Super, Qwen 32B or any Ollama model.

The model only reads and writes text. It never decides PASS/FAIL or computes money: everything
it returns is checked against the documents by Python before it is used.

Pick the model with --model on the pipeline, or the WATCHDOG_MODEL environment variable.
Model names are whatever `ollama list` shows on the machine. OLLAMA_HOST overrides the address
(default http://localhost:11434), e.g. when the pipeline runs inside the OpenShell sandbox.

    python3 -m engine.llm               # list models and test that the chosen one answers
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


def host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def model_name(explicit: str | None = None) -> str | None:
    return explicit or os.environ.get("WATCHDOG_MODEL") or None


def available_models() -> list[str]:
    with urllib.request.urlopen(host() + "/api/tags", timeout=5) as resp:
        return [m["name"] for m in json.loads(resp.read())["models"]]


def _post(payload: dict, timeout: float) -> str:
    req = urllib.request.Request(host() + "/api/generate", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["response"]


def generate(prompt: str, model: str, timeout: float = 180) -> str:
    """One completion. Thinking is switched off (seconds instead of minutes) where supported."""
    payload = {"model": model, "prompt": prompt, "stream": False, "think": False,
               "options": {"temperature": 0}}
    try:
        return _post(payload, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:                     # 400: this model has no thinking switch
            raise
        payload.pop("think")
        return _post(payload, timeout)


def generate_json(prompt: str, model: str, timeout: float = 180) -> dict:
    """Completion parsed as a JSON object, with one retry. Raises ValueError, never guesses."""
    last = None
    for _ in range(2):
        try:
            out = generate(prompt, model, timeout)
            match = re.search(r"\{.*\}", out, re.S)
            if match:
                return json.loads(match.group(0))
            last = ValueError(f"no JSON in model output: {out[:200]!r}")
        except (ValueError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
    raise ValueError(f"model {model}: {last}")


def main():
    try:
        models = available_models()
    except OSError as exc:
        raise SystemExit(f"Ollama not reachable at {host()}: {exc}")
    print(f"Ollama at {host()}: {models}")
    chosen = model_name(sys.argv[1] if len(sys.argv) > 1 else None)
    if not chosen:
        raise SystemExit("set WATCHDOG_MODEL or pass a model name to test it")
    start = time.time()
    print(f"{chosen}: {generate('Answer with one word: ready', chosen).strip()!r} "
          f"in {time.time() - start:.1f} s")


if __name__ == "__main__":
    main()
