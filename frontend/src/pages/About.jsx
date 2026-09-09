import SiteNav from '../components/SiteNav'

const SCOPE = [
  { component: 'Market risk score', status: 'real', badge: 'Heuristic, live', detail: 'A documented weighted formula over RSI/MACD/volatility/EMA, computed from a live market data fetch at request time — not a stale cached file.' },
  { component: 'Governance risk score', status: 'real', badge: 'Real, partial coverage', detail: 'Real SEC Form 8-K item-code data for a curated set of large-cap tickers. Returns "no data" — never a fabricated zero — outside that coverage.' },
  { component: 'News event risk', status: 'real', badge: 'Real, keyword-based', detail: 'Real headlines matched against an explicit, inspectable keyword-to-category map — not a black-box classifier.' },
  { component: 'FinGuard Risk Index', status: 'heuristic', badge: 'Documented combination', detail: 'Fixed, published weights across the three signals above, renormalized when a category is missing. Confidence reflects real data coverage.' },
  { component: 'News sentiment', status: 'real', badge: 'FinBERT', detail: 'A finance-tuned transformer scores real headlines. Kept as a separate, additive signal — not folded into the risk score.' },
  { component: 'Forecast model', status: 'real', badge: 'Walk-forward validated', detail: 'A trained classifier predicting 30-day risk direction, evaluated against a naive baseline with a strict no-look-ahead temporal split.' },
  { component: 'Report Agent', status: 'real', badge: 'One LLM call', detail: 'Explains already-computed numbers in plain language. Never asked to invent a score — every claim is labeled fact, prediction, or interpretation.' },
  { component: 'Critic Agent', status: 'real', badge: 'Deterministic', detail: 'Checks evidence sufficiency before a report is finalized and can trigger one revision. Not a second LLM judging the first.' },
  { component: 'Evidence Verifier', status: 'real', badge: 'Deterministic', detail: 'Independently checks that every factual claim in the report matches a real number in the source data — a hallucination guard.' },
  { component: 'Orchestrator', status: 'real', badge: 'Rule-based routing', detail: 'Decides which agents to invoke based on real data availability, and routes single-ticker vs. portfolio requests differently.' },
  { component: 'Knowledge graph', status: 'real', badge: 'Real, scoped', detail: 'A real graph (networkx) of same-sector relationships from live company data — not Neo4j, since a graph this size doesn’t justify a database yet. No fabricated supplier/competitor edges.' },
  { component: 'Evidence retrieval (RAG)', status: 'real', badge: 'TF-IDF, not embeddings', detail: 'Chunks real SEC filing text and ranks passages by genuine cosine similarity to a query. Lexical retrieval, not a dense embedding model — a real, honest tradeoff, not the ceiling of what’s possible here.' },
]

const STACK = [
  { title: 'Backend', items: ['FastAPI', 'pandas / scikit-learn', 'XGBoost', 'Transformers (FinBERT)', 'Groq LLM API'] },
  { title: 'Frontend', items: ['React 18', 'Vite', 'React Router', 'Plain CSS, no framework'] },
  { title: 'Data sources', items: ['Live market data (no key)', 'SEC EDGAR filings', 'Google News RSS'] },
  { title: 'Deployment', items: ['Vercel (frontend)', 'Render (backend)', 'GitHub Actions-free, git-triggered deploys'] },
]

function badgeClass(status) {
  if (status === 'real') return 'scope-real'
  if (status === 'heuristic') return 'scope-heuristic'
  return 'scope-missing'
}

export default function About() {
  return (
    <>
      <SiteNav />
      <div className="page">
        <section className="about-hero">
          <p className="eyebrow">How it works</p>
          <h1>An honest account of what's real, and what isn't yet.</h1>
          <p>
            Most "AI risk" demos hide the line between measured fact and generated text. FinGuard
            draws that line explicitly, in the product itself — this page is the same accounting,
            for anyone deciding whether to trust a number it shows.
          </p>
        </section>

        <section className="section" style={{ paddingTop: 0 }}>
          <p className="section-label">Scope, honestly</p>
          <h2 className="section-title">What's real, what's a documented heuristic, what's missing</h2>
          <div style={{ overflowX: 'auto' }}>
            <table className="scope-table">
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Status</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {SCOPE.map((row) => (
                  <tr key={row.component}>
                    <td><strong>{row.component}</strong></td>
                    <td>
                      <span className={`scope-badge ${badgeClass(row.status)}`}>{row.badge}</span>
                    </td>
                    <td style={{ color: 'var(--ink-dim)' }}>{row.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="section">
          <p className="section-label">Tech stack</p>
          <h2 className="section-title">What it's actually built with</h2>
          <div className="stack-grid">
            {STACK.map((s) => (
              <div className="stack-card" key={s.title}>
                <h3>{s.title}</h3>
                <ul>
                  {s.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className="section">
          <p className="section-label">Not a finished product</p>
          <h2 className="section-title">What would it actually take to trust this?</h2>
          <p className="section-lede">
            This is a research/triage demo, not investment advice — and the gap between the two
            is real, not just a disclaimer. The honest path from here: outcome-validated scoring
            (does a high risk score actually predict real drawdowns, measured against history),
            redundant SLA-backed data feeds instead of free tiers, and a human always in the loop
            reviewing what the system surfaces. Full accounting in{' '}
            <a
              href="https://github.com/goeldaksh06/FinguardAI/blob/main/docs/production-roadmap.md"
              target="_blank"
              rel="noreferrer"
            >
              docs/production-roadmap.md
            </a>.
          </p>
        </section>

        <section className="section" style={{ borderBottom: 'none' }}>
          <div className="cta-band">
            <div>
              <h2>Read the source</h2>
              <p>Every claim on this page maps to real code — nothing here is aspirational.</p>
            </div>
            <a
              href="https://github.com/goeldaksh06/FinguardAI"
              target="_blank"
              rel="noreferrer"
              className="primary-btn hero-link-btn"
            >
              View on GitHub
            </a>
          </div>
        </section>
      </div>
    </>
  )
}
