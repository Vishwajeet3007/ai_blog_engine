from __future__ import annotations

import operator
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict, List, Optional, Literal, Annotated

from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.callbacks.manager import get_openai_callback

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Blog Writer (Router → Research → Orchestrator → Workers → ReducerWithImages)
# Production-upgraded version
# ============================================================

# -----------------------------
# 1) Schemas
# -----------------------------
class Task(BaseModel):
    id: int
    title: str
    goal: str = Field(..., description="One sentence describing what the reader should do/understand.")
    bullets: List[str] = Field(..., min_length=3, max_length=6)
    target_words: int = Field(..., description="Target words (120–550).")

    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False


class Plan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: Literal["explainer", "tutorial", "news_roundup", "comparison", "system_design"] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[Task]


class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    snippet: Optional[str] = None
    source: Optional[str] = None


class RouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    reason: str
    queries: List[str] = Field(default_factory=list)
    max_results_per_query: int = Field(5)


class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)


class ImageSpec(BaseModel):
    placeholder: str
    filename: str
    alt: str
    caption: str
    prompt: str
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    quality: Literal["low", "medium", "high"] = "medium"


class GlobalImagePlan(BaseModel):
    md_with_placeholders: str
    images: List[ImageSpec] = Field(default_factory=list)


class State(TypedDict):
    topic: str
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[Plan]
    as_of: str
    recency_days: int
    sections: Annotated[List[tuple[int, str]], operator.add]
    merged_md: str
    md_with_placeholders: str
    image_specs: List[dict]
    final: str


# -----------------------------
# 2) LLM + Safe Wrapper
# -----------------------------
llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.3)


def safe_llm_invoke(callable_fn):
    try:
        with get_openai_callback() as cb:
            result = callable_fn()
            print(
                f"[LLM] Prompt: {cb.prompt_tokens} | "
                f"Completion: {cb.completion_tokens} | "
                f"Total: {cb.total_tokens}"
            )
        return result
    except Exception as e:
        print(f"[LLM ERROR] {e}")
        raise


# -----------------------------
# 3) Router
# -----------------------------
ROUTER_SYSTEM = """You are a routing module for a technical blog planner.

Decide whether web research is needed BEFORE planning.

Modes:
- closed_book (needs_research=false): evergreen concepts.
- hybrid (needs_research=true): evergreen + needs up-to-date examples/tools/models.
- open_book (needs_research=true): volatile weekly/news/"latest"/pricing/policy.
"""


def router_node(state: State) -> dict:
    try:
        decider = llm.with_structured_output(RouterDecision)

        decision = safe_llm_invoke(lambda: decider.invoke([
            SystemMessage(content=ROUTER_SYSTEM),
            HumanMessage(content=f"Topic: {state['topic']}\nAs-of date: {state['as_of']}")
        ]))

        recency_days = 7 if decision.mode == "open_book" else 45 if decision.mode == "hybrid" else 3650

        return {
            "needs_research": decision.needs_research,
            "mode": decision.mode,
            "queries": decision.queries,
            "recency_days": recency_days,
        }
    except Exception:
        return {
            "needs_research": False,
            "mode": "closed_book",
            "queries": [],
            "recency_days": 3650,
        }


def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"


# -----------------------------
# 4) Research
# -----------------------------
def _tavily_search(query: str, max_results: int = 5) -> List[dict]:
    if not os.getenv("TAVILY_API_KEY"):
        print("[RESEARCH] No Tavily key found.")
        return []
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        tool = TavilySearchResults(max_results=max_results)
        return tool.invoke({"query": query}) or []
    except Exception as e:
        print(f"[RESEARCH ERROR] {e}")
        return []


def research_node(state: State) -> dict:
    raw = []
    for q in (state.get("queries") or [])[:10]:
        raw.extend(_tavily_search(q))

    if not raw:
        return {"evidence": []}

    extractor = llm.with_structured_output(EvidencePack)

    pack = safe_llm_invoke(lambda: extractor.invoke([
        SystemMessage(content="Extract clean evidence items."),
        HumanMessage(content=f"Raw results:\n{raw}")
    ]))

    return {"evidence": pack.evidence}


# -----------------------------
# 5) Orchestrator
# -----------------------------
ORCH_SYSTEM = """You are a senior technical writer.

Produce 5–9 structured tasks.

If evidence is weak, reflect uncertainty professionally.
"""


def orchestrator_node(state: State) -> dict:
    planner = llm.with_structured_output(Plan)

    plan = safe_llm_invoke(lambda: planner.invoke([
        SystemMessage(content=ORCH_SYSTEM),
        HumanMessage(content=f"Topic: {state['topic']}\nMode: {state['mode']}")
    ]))

    return {"plan": plan}


# -----------------------------
# 6) Fanout
# -----------------------------
def fanout(state: State):
    return [
        Send("worker", {
            "task": task.model_dump(),
            "plan": state["plan"].model_dump(),
            "topic": state["topic"],
            "mode": state["mode"],
        })
        for task in state["plan"].tasks
    ]


# -----------------------------
# 7) Worker
# -----------------------------
WORKER_SYSTEM = """Write ONE section in markdown.

If unsupported evidence:
Write:
"Limited evidence available in provided sources."
"""


def worker_node(payload: dict) -> dict:
    task = Task(**payload["task"])
    plan = Plan(**payload["plan"])

    response = safe_llm_invoke(lambda: llm.invoke([
        SystemMessage(content=WORKER_SYSTEM),
        HumanMessage(content=f"Section: {task.title}\nGoal: {task.goal}")
    ]))

    return {"sections": [(task.id, response.content.strip())]}


# -----------------------------
# 8) Reducer
# -----------------------------
def merge_content(state: State) -> dict:
    ordered = [md for _, md in sorted(state["sections"], key=lambda x: x[0])]
    body = "\n\n".join(ordered)

    merged_md = f"""---
title: "{state['plan'].blog_title}"
date: "{state['as_of']}"
mode: "{state['mode']}"
---

# {state['plan'].blog_title}

{body}
"""
    return {"merged_md": merged_md}


def _safe_slug(title: str) -> str:
    return re.sub(r"\s+", "_", re.sub(r"[^a-z0-9 _-]+", "", title.lower())).strip("_") or "blog"


def generate_and_place_images(state: State) -> dict:
    plan = state["plan"]
    md = state["merged_md"]

    blog_slug = _safe_slug(plan.blog_title)
    blog_dir = Path("blogs") / blog_slug
    images_dir = blog_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    blog_md_path = blog_dir / "blog.md"
    blog_md_path.write_text(md, encoding="utf-8")

    return {"final": md}


# -----------------------------
# 9) Build Graph
# -----------------------------
reducer_graph = StateGraph(State)
reducer_graph.add_node("merge_content", merge_content)
reducer_graph.add_node("generate_and_place_images", generate_and_place_images)
reducer_graph.add_edge(START, "merge_content")
reducer_graph.add_edge("merge_content", "generate_and_place_images")
reducer_graph.add_edge("generate_and_place_images", END)
reducer_subgraph = reducer_graph.compile()

g = StateGraph(State)
g.add_node("router", router_node)
g.add_node("research", research_node)
g.add_node("orchestrator", orchestrator_node)
g.add_node("worker", worker_node)
g.add_node("reducer", reducer_subgraph)

g.add_edge(START, "router")
g.add_conditional_edges("router", route_next, {"research": "research", "orchestrator": "orchestrator"})
g.add_edge("research", "orchestrator")
g.add_conditional_edges("orchestrator", fanout, ["worker"])
g.add_edge("worker", "reducer")
g.add_edge("reducer", END)

app = g.compile()
