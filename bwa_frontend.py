from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, List, Iterator, Tuple

import pandas as pd
import streamlit as st

from bwa_backend import app

IMAGE_DISPLAY_WIDTH = 780


# -----------------------------
# Helpers
# -----------------------------
def safe_slug(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9 _-]+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "blog"


def bundle_zip(blog_dir: Path) -> Optional[bytes]:
    if not blog_dir.exists():
        return None

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in blog_dir.rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(blog_dir)))
    return buf.getvalue()


def try_stream(graph_app, inputs: Dict[str, Any]) -> Iterator[Tuple[str, Any]]:
    """
    FIXED VERSION:
    - NO double invoke
    - Final state comes from stream
    """
    final_state = None
    try:
        for step in graph_app.stream(inputs, stream_mode="values"):
            final_state = step
            yield ("values", step)
        yield ("final", final_state)
        return
    except Exception:
        pass

    final_state = graph_app.invoke(inputs)
    yield ("final", final_state)


# -----------------------------
# Markdown renderer
# -----------------------------
_MD_IMG_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)")


def render_markdown(md: str, base_dir: Optional[Path] = None):
    matches = list(_MD_IMG_RE.finditer(md))
    if not matches:
        st.markdown(md)
        return

    last = 0
    for m in matches:
        before = md[last:m.start()]
        if before:
            st.markdown(before)

        alt = m.group("alt")
        src = m.group("src")

        img_path = Path(src)
        if not img_path.is_absolute() and base_dir is not None:
            img_path = base_dir / img_path
        if img_path.exists():
            st.image(str(img_path), caption=alt or None, width=IMAGE_DISPLAY_WIDTH)
        else:
            st.warning(f"Image not found: {src}")

        last = m.end()

    tail = md[last:]
    if tail:
        st.markdown(tail)


# -----------------------------
# Blog Loader (new structure compatible)
# -----------------------------
def list_past_blogs() -> List[Path]:
    blog_root = Path("blogs")
    if not blog_root.exists():
        return []

    blog_files = list(blog_root.glob("*/blog.md"))
    blog_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return blog_files


def load_blog(md_path: Path):
    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    st.session_state["last_out"] = {
        "plan": None,
        "evidence": [],
        "image_specs": [],
        "final": md_text,
    }
    st.session_state["last_blog_dir"] = md_path.parent


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="LangGraph Blog Writer", layout="wide")
st.title("Blog Writing Agent")

if "last_out" not in st.session_state:
    st.session_state["last_out"] = None

if "logs" not in st.session_state:
    st.session_state["logs"] = []

if "last_blog_dir" not in st.session_state:
    st.session_state["last_blog_dir"] = None


# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("Generate New Blog")

    topic = st.text_area("Topic", height=120)
    as_of = st.date_input("As-of date", value=date.today())
    run_btn = st.button("🚀 Generate Blog", type="primary")

    st.divider()
    st.subheader("Past Blogs")

    blogs = list_past_blogs()

    if not blogs:
        st.caption("No blogs found in blogs/ directory.")
    else:
        blog_labels = [p.parent.name for p in blogs]
        selected_label = st.radio("Select Blog", blog_labels, label_visibility="collapsed")
        selected_path = next((p for p in blogs if p.parent.name == selected_label), None)

        if st.button("📂 Load Selected"):
            if selected_path:
                load_blog(selected_path)


# -----------------------------
# Tabs
# -----------------------------
tab_plan, tab_evidence, tab_preview, tab_images, tab_logs = st.tabs(
    ["🧩 Plan", "🔎 Evidence", "📝 Preview", "🖼️ Images", "🧾 Logs"]
)


# -----------------------------
# Run Graph
# -----------------------------
if run_btn:
    if not topic.strip():
        st.warning("Please enter a topic.")
        st.stop()

    inputs = {
        "topic": topic.strip(),
        "mode": "",
        "needs_research": False,
        "queries": [],
        "evidence": [],
        "plan": None,
        "as_of": as_of.isoformat(),
        "recency_days": 7,
        "sections": [],
        "merged_md": "",
        "md_with_placeholders": "",
        "image_specs": [],
        "final": "",
    }

    status = st.status("Running graph...", expanded=True)

    for kind, payload in try_stream(app, inputs):
        if kind == "values":
            st.session_state["logs"].append(
                f"[progress] {json.dumps(payload, default=str)[:800]}"
            )
        elif kind == "final":
            st.session_state["last_out"] = payload
            plan = (payload or {}).get("plan") if isinstance(payload, dict) else None
            title = None
            if isinstance(plan, dict):
                title = plan.get("blog_title")
            elif hasattr(plan, "blog_title"):
                title = plan.blog_title
            if title:
                st.session_state["last_blog_dir"] = Path("blogs") / safe_slug(title)
            status.update(label="✅ Done", state="complete", expanded=False)


# -----------------------------
# Render Output
# -----------------------------
out = st.session_state.get("last_out")

if out:

    # -------- Plan --------
    with tab_plan:
        plan = out.get("plan")
        if not plan:
            st.info("No plan available.")
        else:
            if hasattr(plan, "model_dump"):
                plan = plan.model_dump()

            st.write("###", plan.get("blog_title"))
            st.write("**Audience:**", plan.get("audience"))
            st.write("**Tone:**", plan.get("tone"))
            st.write("**Kind:**", plan.get("blog_kind"))

            tasks = plan.get("tasks", [])
            if tasks:
                df = pd.DataFrame(tasks)
                st.dataframe(df, use_container_width=True, hide_index=True)

    # -------- Evidence --------
    with tab_evidence:
        evidence = out.get("evidence") or []
        if not evidence:
            st.info("No evidence used.")
        else:
            rows = []
            for e in evidence:
                if hasattr(e, "model_dump"):
                    e = e.model_dump()
                rows.append(e)
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # -------- Preview --------
    with tab_preview:
        final_md = out.get("final") or ""
        if final_md:
            blog_dir = st.session_state.get("last_blog_dir")
            with st.spinner("Rendering blog..."):
                render_markdown(final_md, base_dir=blog_dir)

            # find blog folder
            title = None
            plan = out.get("plan")
            if isinstance(plan, dict):
                title = plan.get("blog_title")
            elif plan and hasattr(plan, "blog_title"):
                title = plan.blog_title

            if title:
                blog_dir = Path("blogs") / safe_slug(title)
                st.session_state["last_blog_dir"] = blog_dir
                zip_data = bundle_zip(blog_dir)

                if zip_data:
                    st.download_button(
                        "📦 Download Blog Bundle",
                        data=zip_data,
                        file_name=f"{safe_slug(title)}.zip",
                        mime="application/zip",
                    )

    # -------- Images --------
    with tab_images:
        plan = out.get("plan")
        title = None
        if isinstance(plan, dict):
            title = plan.get("blog_title")
        elif plan and hasattr(plan, "blog_title"):
            title = plan.blog_title

        blog_dir = Path("blogs") / safe_slug(title) if title else st.session_state.get("last_blog_dir")
        if blog_dir:
            images_dir = blog_dir / "images"

            if images_dir.exists():
                files = list(images_dir.glob("*"))
                if files:
                    for f in files:
                        st.image(str(f), caption=f.name, width=IMAGE_DISPLAY_WIDTH)
                else:
                    st.info("No images generated.")
            else:
                st.info("No images directory found.")

    # -------- Logs --------
    with tab_logs:
        st.text_area(
            "Event log",
            value="\n\n".join(st.session_state["logs"][-200:]),
            height=500,
        )

else:
    st.info("Enter a topic and click Generate Blog.")
