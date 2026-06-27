"""Generate a sample batch input file (an array of prompt items).

Usage:
    python scripts/generate_sample_batch.py [count] [output_path]

Defaults: 1000 items -> ./sample_batch.json
Each item: {"id": "prompt-0001", "prompt": "..."}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TEMPLATES = [
    "Explain {topic} in one sentence.",
    "Summarize the key idea behind {topic}.",
    "Give three bullet points about {topic}.",
    "What is a common misconception about {topic}?",
    "Write a short tip for someone learning {topic}.",
    "Translate the word '{topic}' into French.",
    "Provide a simple analogy for {topic}.",
    "List two pros and two cons of {topic}.",
]

TOPICS = [
    "photosynthesis", "recursion", "the water cycle", "compound interest",
    "machine learning", "the French Revolution", "black holes", "REST APIs",
    "supply and demand", "DNA replication", "the internet", "vaccines",
    "quantum computing", "climate change", "blockchain", "the stock market",
    "neural networks", "gravity", "evolution", "encryption",
]


def generate(count: int) -> list[dict]:
    items = []
    for i in range(1, count + 1):
        template = TEMPLATES[i % len(TEMPLATES)]
        topic = TOPICS[i % len(TOPICS)]
        items.append(
            {"id": f"prompt-{i:04d}", "prompt": template.format(topic=topic)}
        )
    return items


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("sample_batch.json")
    items = generate(count)
    out.write_text(json.dumps(items, indent=2), encoding="utf-8")
    print(f"Wrote {len(items)} items to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
