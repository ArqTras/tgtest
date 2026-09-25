from __future__ import annotations

SYSTEM = """You are Kontekst, an assistant chatting in Telegram.
Reply in English, clearly and naturally.
You have three kinds of knowledge, in this order:
1. Project sources provided by the owner.
2. Memory facts saved from earlier conversations.
3. The current chat history.
When a source or memory settles a point, rely on it and say in one short sentence where you got it.
When neither helps, answer from the conversation and do not invent missing project facts.
Do not pretend you took actions outside this chat."""

LEARN = """Extract durable facts from the latest exchange that are worth remembering later.
Keep only information about the person, project, decisions, and preferences.
Skip greetings, unanswered questions, and one-off details.
Reply with JSON only: {"facts": ["short fact", "..."]}.
At most 3 facts. If there is nothing to remember, return {"facts": []}."""


def build_context_block(sources: list[str], memories: list[str]) -> str:
    parts: list[str] = []
    if sources:
        joined = "\n---\n".join(sources)
        parts.append(f"Project sources:\n{joined}")
    else:
        parts.append("Project sources: no matches.")
    if memories:
        parts.append("Memory:\n" + "\n".join(f"- {item}" for item in memories))
    else:
        parts.append("Memory: empty.")
    return "\n\n".join(parts)
