"""Streamlit chat interface for the HR policy assistant.

    streamlit run app.py
"""
import re
from datetime import date

import pandas as pd
import streamlit as st

import config
from rag import RAG, Answer

ROLE_SETS = {
    "Employee": ["employee"],
    "Line manager": ["employee", "line_manager"],
    "People admin": ["employee", "people_admin"],
}
EXAMPLES = [
    "How many annual leave days does a full-time permanent UK employee get?",
    "Can I claim my normal train fare for required office days on hybrid?",
    "What is the salary range for Band 3?",
    "Can I take leave next week?",
]

st.set_page_config(page_title="Northstar HR Assistant", page_icon="📘", layout="centered")


@st.cache_resource(show_spinner="Loading retriever…")
def get_rag() -> RAG:
    return RAG()


def render_answer_text(text: str) -> str:
    """Show citations as inline code so they stand out from the prose."""
    return re.sub(r"\[([a-z0-9_]+#[a-z0-9-]+)\]", r"`\1`", text)


def render_details(a: Answer, show_trace: bool):
    if a.invalid_citations:
        st.warning(f"The answer cites sources that were not retrieved: {', '.join(a.invalid_citations)}")
    if a.hits:
        with st.expander(f"Sources ({len(a.hits)})"):
            for h in a.hits:
                cited = "✅ cited" if h.id in a.citations else "not cited"
                st.markdown(f"**`{h.id}`** · {h.meta['title']} › {h.meta['heading']} · "
                            f"v{h.meta['version']} · {h.meta['status']} · rerank {h.rerank_score:.3f} · {cited}")
                st.caption(h.text.split("\n\n", 1)[-1])
    if show_trace and a.retrieval:
        with st.expander("Retrieval trace"):
            final = {h.id for h in a.hits}
            st.dataframe(pd.DataFrame([{
                "chunk": h.id, "to LLM": h.id in final, "dense rank": h.dense_rank, "BM25 rank": h.bm25_rank,
                "RRF": round(h.rrf_score, 4), "rerank": round(h.rerank_score or 0, 3),
            } for h in a.retrieval.candidates]), hide_index=True, width="stretch")
            st.caption(f"Filter: `{a.retrieval.filter}`")
            st.caption(f"Latency: retrieval {a.latency_s['retrieval']} s · generation {a.latency_s['generation']} s"
                       + (f" · model {a.model}" if a.model else " · no LLM call (no evidence)"))


with st.sidebar:
    st.header("Settings")
    role_label = st.radio("Signed in as", list(ROLE_SETS), help="Simulated user. Controls which documents can be searched.")
    roles = ROLE_SETS[role_label]
    as_of = st.date_input("Policies in force on", value=date.today())
    include_expired = st.toggle(
        "Include expired policies", value=False,
        help="Switches off the status and date filter. Only has an effect if you ran "
             "`python ingest.py --include-expired`. Use for the stale-policy test.")
    show_trace = st.toggle("Show retrieval trace", value=True)
    if st.button("Clear chat", width="stretch"):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption(f"Roles: {', '.join(roles)}  \nModel: {config.LLM_MODEL} (Groq)  \n"
               f"Retrieval: Pinecone {config.EMBED_MODEL} + BM25 → RRF → {config.RERANK_MODEL}")
    st.caption("Synthetic demo policies for a fictional company. Not real HR or legal guidance.")

st.title("Northstar HR Assistant")
st.caption("Answers come only from Northstar's HR policies, with a source for every claim.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
            st.caption(msg["as"])
        else:
            st.markdown(render_answer_text(msg["answer"].text))
            render_details(msg["answer"], show_trace)

if not st.session_state.messages:
    st.write("Try one of these:")
    cols = st.columns(2)
    for i, example in enumerate(EXAMPLES):
        if cols[i % 2].button(example, key=f"ex{i}", width="stretch"):
            st.session_state.pending = example
            st.rerun()

question = st.chat_input("Ask about leave, expenses, remote work…") or st.session_state.pop("pending", None)
if question:
    st.session_state.messages.append({"role": "user", "content": question, "as": f"asked as {role_label}"})
    with st.chat_message("user"):
        st.markdown(question)
        st.caption(f"asked as {role_label}")
    with st.chat_message("assistant"):
        with st.spinner("Searching the policies…"):
            try:
                answer = get_rag().answer(question, roles, as_of, include_expired)
            except Exception as e:  # network or API errors: show them instead of a blank page
                st.error(f"Something went wrong: {type(e).__name__}: {e}")
                st.stop()
        st.markdown(render_answer_text(answer.text))
        render_details(answer, show_trace)
    st.session_state.messages.append({"role": "assistant", "answer": answer})
