"""
A Streamlit-in-Snowflake chat UI over the Cortex Agent -- the concrete,
demoable "AI Data Assistant" at the end of the architecture diagram, and the
easiest artifact to screenshot/record for a portfolio (no Snowsight tour
needed, just this page).

Deploy as a Streamlit-in-Snowflake app (Snowsight -> Streamlit -> Create),
which runs inside your Snowflake account using its own session -- no
separate hosting, and the Row Access Policy / role restrictions apply exactly
as they do everywhere else in this project, since the app runs as whatever
role you assign it (ANALYST_AGENT, so it's bound by the same 15-minute-delay
rule as every other entry point).

To run locally against a non-Snowflake-hosted session instead, set the env
vars cortex_agent_client.py expects and run: streamlit run streamlit_app.py
"""

import sys

import streamlit as st

sys.path.insert(0, "../agent")
from cortex_agent_client import ask_market_data_agent  # noqa: E402

st.set_page_config(page_title="Market Data AI Assistant", page_icon="📈")
st.title("📈 Market Data AI Assistant")
st.caption(
    "Ask about real-time equities data or recent news. Answers reflect a "
    "15-minute delayed-data policy — see sql/07_governance."
)

if "history" not in st.session_state:
    st.session_state.history = []

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.write(turn["content"])
        if turn.get("sql"):
            with st.expander("Generated SQL"):
                st.code(turn["sql"], language="sql")
        for citation in turn.get("citations", []):
            if citation.get("url"):
                st.caption(f"Source: [{citation.get('headline', citation['url'])}]({citation['url']})")

question = st.chat_input("e.g. What was AAPL's return today?")
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Asking the agent..."):
            result = ask_market_data_agent(question)
        answer = result.text or "The agent didn't return a text answer for this question."
        st.write(answer)
        if result.sql:
            with st.expander("Generated SQL"):
                st.code(result.sql, language="sql")
        for citation in result.citations:
            if citation.url:
                st.caption(f"Source: [{citation.headline or citation.url}]({citation.url})")

    st.session_state.history.append(
        {
            "role": "assistant",
            "content": answer,
            "sql": result.sql,
            "citations": [c.model_dump() for c in result.citations],
        }
    )
