"""Local, free, open-source AI (llama.cpp). No API key, no cloud: the model file is downloaded once from Hugging Face
and runs on the CPU of the machine."""
import os, re, time
import config

_llm = None
_start = [time.time()]
_total = [config.AI_BUDGET_MIN * 60]


def start_budget(minutes):
    _start[0], _total[0] = time.time(), minutes * 60


def time_left():
    return _total[0] - (time.time() - _start[0])


def budget_total():
    return _total[0]


def load():
    global _llm
    if _llm is not None:
        return _llm
    from huggingface_hub import hf_hub_download
    from llama_cpp import Llama
    last = None
    for repo, fname in config.AI_MODELS:
        try:
            path = hf_hub_download(repo_id=repo, filename=fname)
            _llm = Llama(model_path=path, n_ctx=config.AI_CTX, n_threads=os.cpu_count() or 4, n_batch=512, verbose=False)
            print(f"[ai] model loaded: {repo} / {fname}", flush=True)
            return _llm
        except Exception as e:
            last = e
            print(f"[ai] could not load {repo}: {str(e)[:120]}", flush=True)
    raise RuntimeError(f"no local model could be loaded: {last}")


def _fit(prompt, max_tokens):
    """Keep prompt + answer inside the context window (cut from the middle if needed)."""
    allowed = int((config.AI_CTX - max_tokens - 250) / 1.5)
    words = prompt.split(" ")
    if len(words) <= allowed:
        return prompt
    keep_head, keep_tail = int(allowed * 0.5), int(allowed * 0.5)
    return " ".join(words[:keep_head]) + " ... " + " ".join(words[-keep_tail:])


def chat(prompt, system="You are a helpful, precise writer.", max_tokens=700, temperature=0.7):
    llm = load()
    max_tokens = min(max_tokens, config.AI_CTX - 600)
    for attempt in range(2):
        try:
            t0 = time.time()
            r = llm.create_chat_completion(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": _fit(prompt, max_tokens)}],
                max_tokens=max_tokens, temperature=temperature, top_p=0.92, repeat_penalty=1.12)
            out = r["choices"][0]["message"]["content"].strip()
            used = r.get("usage", {}).get("completion_tokens", 0)
            if used and time.time() - t0 > 1:
                print(f"[ai] {used} tokens, {used / (time.time() - t0):.1f} tok/s", flush=True)
            return out
        except Exception as e:
            print("[ai] generation error:", str(e)[:120], flush=True)
            time.sleep(2)
    return ""
