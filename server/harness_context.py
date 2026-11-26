import json
import os
import re
from dataclasses import dataclass, field
from time import monotonic


def integer(name, default, minimum, maximum):
    value = int(os.environ.get("LOCAL_AI_" + name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"LOCAL_AI_{name} must be between {minimum} and {maximum}.")
    return value


CONTEXT = integer("CONTEXT", 8192 if os.name == "nt" else 4096, 1024, 40960)
REPLY = integer("REPLY_TOKENS", 512, 64, 4096)
REVIEW_WINDOW = integer("REVIEW_CONTEXT", 3072, 512, 40960)
REVIEW_TOKENS = integer("REVIEW_TOKENS", 320, 64, 2048)
THINK = integer("THINK_TOKENS", 640, 32, 4096)
SUMMARY = integer("SUMMARY_TOKENS", 192, 64, 512)
PRESSURE = integer("COMPACT_PERCENT", 80, 50, 100) / 100
CALLS = integer("MAX_CALLS", 16, 2, 100)
GENERATED = integer("MAX_GENERATED", 4096, 256, 32768)
EXTRA = integer("MAX_ESCALATIONS", 1, 0, 4)
RETRIEVE = integer("RETRIEVE", 1, 0, 1)
ADAPTIVE = integer("ADAPTIVE", 1, 0, 1)
TASK_STATE = integer("TASK_STATE", 1, 0, 1)
LOG = integer("DIAGNOSTICS", 0, 0, 1)
CACHE = integer("PROMPT_CACHE", 1, 0, 1)
CACHE_RAM = integer("CACHE_RAM_MIB", 256, 0, 8192)


class BudgetError(ValueError):
    pass


@dataclass
class Diagnostics:
    started: float = field(default_factory=monotonic)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    events: dict = field(default_factory=dict)
    token_counts: dict = field(default_factory=dict)
    reservations: int = 0

    def event(self, key, amount=1):
        self.events[key] = self.events.get(key, 0) + amount

    def start(self, limit, reserve=0, reserve_calls=0):
        if self.calls + reserve_calls >= CALLS:
            raise BudgetError("Inference call budget exhausted.")
        if self.reservations + limit + reserve > GENERATED:
            raise BudgetError("Generation budget exhausted.")
        self.calls += 1
        self.reservations += limit

    def finish(self, limit, prompt, generated):
        self.input_tokens += prompt
        self.output_tokens += generated if generated is not None else limit
        if generated is not None:
            self.reservations += generated - limit

    def report(self, operation):
        result = {
            "inference_calls": self.calls, "total_input_tokens": self.input_tokens,
            "total_generated_tokens": self.output_tokens,
            "latency_ms": round((monotonic() - self.started) * 1000),
            **self.events,
        }
        if LOG:
            print(json.dumps({"operation": operation, **result}), flush=True)
        return result


def build_context(count, system, prompt, sections, thinking, reserve, window=None):
    """Greedily admit independent items by priority using the real rendered prompt."""
    ceiling = min(CONTEXT, window if window is not None else CONTEXT) - reserve - 32
    threshold = int(ceiling * PRESSURE)

    def messages(parts):
        history = [{"role": "system", "content": system}]
        if parts:
            context = "\n\n".join(f"{label}:\n{body}" for label, body in parts)
            history += [
                {"role": "user", "content": "Background data for the next request:\n\n" + context},
                {"role": "assistant", "content": "I will use it as background evidence."},
            ]
        return history + [{"role": "user", "content": prompt}]

    options = {"enable_thinking": thinking}
    admitted = []
    size = count(messages(admitted), options)
    if size > ceiling:
        raise BudgetError(f"Current request uses {size} input tokens, above the {ceiling}-token input budget.")
    dropped = 0
    seen = set()
    for label, body, important in sections:
        body = body.strip()
        fingerprint = " ".join(body.casefold().split())
        if not body or fingerprint in seen:
            continue
        seen.add(fingerprint)
        trial = admitted + [(label, body)]
        candidate = count(messages(trial), options)
        if candidate <= (ceiling if important else threshold):
            admitted, size = trial, candidate
        else:
            dropped += 1
    return messages(admitted), size, dropped, admitted


def route(prompt, mode):
    if mode in ("think", "quick"):
        return mode == "think", False
    if not ADAPTIVE:
        return False, False
    if re.search(
        r"\b(?:prove|derive|debug|race condition|refactor|architecture|multi.step|trade.off|"
        r"reason step|show (?:your|the) (?:work|calculation))\b", prompt, re.I,
    ):
        return True, False
    if len(prompt) < 160 and not re.search(r"\b(?:why|design|explain|analyse|analyze|compare)\b", prompt, re.I):
        return False, False
    return False, True
