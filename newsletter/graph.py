"""START → collect → select → report → verify → publish → END

verify에서 5건이 모자라면 예비 후보로 report를 한 번 더 돈다.
"""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from .llm import LLM
from .nodes.collect import collect
from .nodes.publish import publish, send_discord
from .nodes.report import fetch_body, report
from .nodes.select import select
from .nodes.verify import route_after_verify, verify
from .state import NewsState


def build_graph(llm: LLM, fetchers: dict | None = None, fetch=fetch_body, send=send_discord):
    g = StateGraph(NewsState)
    g.add_node("collect", partial(collect, fetchers=fetchers))
    g.add_node("select", partial(select, llm=llm))
    g.add_node("report", partial(report, llm=llm, fetch=fetch))
    g.add_node("verify", partial(verify, llm=llm))
    g.add_node("publish", partial(publish, send=send))

    g.add_edge(START, "collect")
    g.add_edge("collect", "select")
    g.add_edge("select", "report")
    g.add_edge("report", "verify")
    g.add_conditional_edges("verify", route_after_verify, {"report": "report", "publish": "publish"})
    g.add_edge("publish", END)
    return g.compile()
