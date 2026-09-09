import { Link } from 'react-router-dom'
import SiteNav from '../components/SiteNav'

const FEATURES = [
  {
    n: '01',
    title: 'Evidence-linked risk score',
    body: 'Three independent real signals — technical indicators, SEC 8-K governance events, keyword-matched news — combined with fixed, documented weights. No black-box number.',
  },
  {
    n: '02',
    title: 'A trained forecast, not a guess',
    body: 'A walk-forward-validated XGBoost model predicts 30-day risk direction, measured against a naive baseline (0.75 vs 0.50 ROC-AUC) — not a fabricated confidence figure.',
  },
  {
    n: '03',
    title: 'An LLM that explains, not invents',
    body: 'The Report Agent only restates numbers it was given, and labels every sentence FACT, MODEL PREDICTION, or AI INTERPRETATION so you know which is which.',
  },
  {
    n: '04',
    title: 'A critic that checks its own work',
    body: 'A deterministic Critic Agent flags weak evidence and can send a report back for one revision. An Evidence Verifier then confirms every figure traces to real source data.',
  },
]

const PIPELINE = [
  { i: '1', title: 'Orchestrator plans the investigation', body: 'Checks whether live data exists for the ticker before deciding which agents to run — an early abort, not a guaranteed pipeline.' },
  { i: '2', title: 'Market + Risk Analyst agents score it', body: 'Live technical indicators (RSI, MACD, volatility) combine with SEC filing and news signals into the FinGuard Risk Index.' },
  { i: '3', title: 'History + Forecast agents add context', body: 'A real backward-looking trend comparison, plus a genuinely forward-looking probability from the trained model.' },
  { i: '4', title: 'Report Agent writes the explanation', body: 'One LLM call, given only the numbers above — asked to explain, never to invent a score of its own.' },
  { i: '5', title: 'Critic + Evidence Verifier check it', body: 'One can send the report back for revision if evidence is thin; the other confirms every cited figure is real.' },
]

export default function Landing() {
  return (
    <>
      <SiteNav />
      <div className="page">
        <section className="hero">
          <div>
            <p className="eyebrow">Agentic risk intelligence</p>
            <h1 className="hero-headline">
              Risk analysis that shows its <em>work</em>.
            </h1>
            <p className="hero-sub">
              FinGuard investigates a stock's risk using real market data, SEC filings, and news —
              then has a language model explain the findings, with every claim labeled fact,
              prediction, or interpretation. Nothing is presented as certain that isn't.
            </p>
            <div className="hero-actions">
              <Link to="/app" className="primary-btn hero-link-btn">
                Open the watchlist
              </Link>
              <Link to="/about" className="primary-btn secondary hero-link-btn">
                See how it works
              </Link>
            </div>
          </div>
          <div className="hero-panel">
            <p className="hero-panel-title">Example investigation trace</p>
            <div className="hero-trace-line">
              <span className="hero-trace-agent">Orchestrator</span>
              <span className="hero-trace-text">Live data confirmed — proceeding</span>
            </div>
            <div className="hero-trace-line">
              <span className="hero-trace-agent">Risk Analyst</span>
              <span className="hero-trace-text">FRI 24.6 — 3 of 3 categories scored</span>
            </div>
            <div className="hero-trace-line">
              <span className="hero-trace-agent">Forecast</span>
              <span className="hero-trace-text">P(risk +10pts / 30d) = 64%</span>
            </div>
            <div className="hero-trace-line">
              <span className="hero-trace-agent">Critic</span>
              <span className="hero-trace-text">Insufficient — 1 revision requested</span>
            </div>
            <div className="hero-trace-line">
              <span className="hero-trace-agent">Evidence Verifier</span>
              <span className="hero-trace-text">Clean — all figures traced to source</span>
            </div>
          </div>
        </section>

        <section className="section">
          <p className="section-label">What it does</p>
          <h2 className="section-title">Four things a black-box risk score doesn't give you</h2>
          <div className="feature-list">
            {FEATURES.map((f) => (
              <div className="feature-item" key={f.n}>
                <span className="feature-item-number">{f.n}</span>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="section">
          <p className="section-label">How a request flows through the system</p>
          <h2 className="section-title">Six agents, one investigation</h2>
          <p className="section-lede">
            Not a single prompt dressed up as an "agent" — a real orchestrator that checks data
            availability before deciding what to run, and a report that gets checked before it's
            shown to you.
          </p>
          <div className="pipeline-list">
            {PIPELINE.map((p) => (
              <div className="pipeline-step" key={p.i}>
                <span className="pipeline-step-index">{p.i}</span>
                <div>
                  <h3>{p.title}</h3>
                  <p>{p.body}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="section">
          <p className="section-label">Built on real constraints</p>
          <h2 className="section-title">Measured, not claimed</h2>
          <div className="honesty-grid">
            <div className="honesty-card">
              <strong>0.75 / 0.50</strong>
              <span>Forecast model ROC-AUC vs. a naive baseline — a real, modest improvement, reported alongside the baseline it beat.</span>
            </div>
            <div className="honesty-card">
              <strong>3 signals</strong>
              <span>Market indicators, SEC filings, and news are combined with fixed weights — never an LLM-guessed number.</span>
            </div>
            <div className="honesty-card">
              <strong>null ≠ 0</strong>
              <span>Missing data is always reported as missing. A score of zero always means a real, computed zero.</span>
            </div>
          </div>
        </section>

        <section className="section" style={{ borderBottom: 'none' }}>
          <div className="cta-band">
            <div>
              <h2>Try it on a real ticker</h2>
              <p>Add a stock to your watchlist and see the real score, trend, and forecast.</p>
            </div>
            <Link to="/app" className="primary-btn hero-link-btn">
              Open the watchlist
            </Link>
          </div>
        </section>

        <footer className="site-footer">
          <span>FinGuard AI — a real, evidence-first risk investigation system.</span>
          <a href="https://github.com/goeldaksh06/FinguardAI" target="_blank" rel="noreferrer">
            Source on GitHub
          </a>
        </footer>
      </div>
    </>
  )
}
