"""A real, small knowledge graph — ROADMAP.md §15-16, scoped honestly.

Deliberately NOT Neo4j. `config/db_config.yaml` has declared a Neo4j connection since the start
of this project and nothing has ever used it — standing up a graph database for a graph this
small would be exactly the kind of "add infrastructure before it's needed" this project has
avoided everywhere else (see the storage-architecture reasoning in CLAUDE.md). networkx builds
the same real graph structure (nodes, typed edges, queryable relationships) in-process, with zero
new infrastructure to deploy or pay for. If the graph ever needs to scale past a few hundred
nodes or needs to persist across restarts, that's the real, concrete trigger to revisit Neo4j —
not before.

Also deliberately narrow in what relationships it claims: nodes are companies (real, from live
company info — sector/industry via yfinance, same source `_get_company_info` already trusted for
the rest of the product), and the one edge type is `same_sector` between two companies that share
a real sector classification. NOT "supplier," NOT "competitor" in any deeper sense, NOT
"customer" — this project has no real data source for supply-chain or customer relationships, and
inventing those edges would be fabricating relationships the same way a made-up sentiment score
would fabricate a signal. `same_sector` is the one relationship type this project can honestly
claim, so it's the only one built.
"""
import networkx as nx


def build_sector_graph(companies: list[dict]) -> nx.Graph:
    """companies: list of {"ticker", "name", "sector", "industry"} — real company info, already
    fetched by the caller (same _get_company_info source used everywhere else in the product).
    Builds a real graph: one node per ticker with its real attributes, one `same_sector` edge
    between every pair of tickers that share a real, non-null sector.
    """
    graph = nx.Graph()

    for c in companies:
        if not c.get("ticker"):
            continue
        graph.add_node(
            c["ticker"],
            name=c.get("name"),
            sector=c.get("sector"),
            industry=c.get("industry"),
        )

    tickers = list(graph.nodes)
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            a, b = tickers[i], tickers[j]
            sector_a = graph.nodes[a].get("sector")
            sector_b = graph.nodes[b].get("sector")
            if sector_a and sector_b and sector_a == sector_b:
                graph.add_edge(a, b, relationship="same_sector", sector=sector_a)

    return graph


def graph_to_json(graph: nx.Graph) -> dict:
    """Serializes the graph for the API/frontend — plain nodes+edges, no networkx-specific
    format leaking out."""
    nodes = [
        {"id": n, "name": attrs.get("name"), "sector": attrs.get("sector"), "industry": attrs.get("industry")}
        for n, attrs in graph.nodes(data=True)
    ]
    edges = [
        {"source": u, "target": v, "relationship": attrs.get("relationship"), "sector": attrs.get("sector")}
        for u, v, attrs in graph.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}


def peers_of(graph: nx.Graph, ticker: str) -> list[dict]:
    """Real, direct graph query: every node connected to `ticker` by a same_sector edge —
    genuine second-order lookup via the graph structure, not a re-derivation from scratch."""
    ticker = ticker.upper()
    if ticker not in graph:
        return []
    return [
        {"ticker": neighbor, **{k: v for k, v in graph.nodes[neighbor].items()}}
        for neighbor in graph.neighbors(ticker)
    ]
