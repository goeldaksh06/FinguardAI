import { useEffect, useState } from 'react'

const API_BASE = 'http://localhost:8000'
const WATCHLIST_KEY = 'finguard_watchlist'
const LAST_SEEN_KEY = 'finguard_last_seen'
// Minimum FRI point change to count as a real alert, not just noise from the heuristic's
// day-to-day jitter. Same spirit as /api/risk-trend's own +/-5 "stable" band, kept independent
// since this compares against the user's last visit, not a fixed 30-day window.
const ALERT_THRESHOLD = 5

function loadWatchlist() {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY)
    return raw ? JSON.parse(raw) : ['AAPL', 'NVDA', 'MSFT']
  } catch {
    return ['AAPL', 'NVDA', 'MSFT']
  }
}

function saveWatchlist(tickers) {
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(tickers))
}

function loadLastSeen() {
  try {
    const raw = localStorage.getItem(LAST_SEEN_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveLastSeen(snapshot) {
  localStorage.setItem(LAST_SEEN_KEY, JSON.stringify(snapshot))
}

function StaleDataBanner({ freshness }) {
  if (!freshness || !freshness.is_stale) return null
  return (
    <div className="stale-banner">
      ⚠ Data as of {freshness.as_of?.slice(0, 10)} — {freshness.age_days} days old. Prices and
      scores below are NOT current; the underlying market data hasn't been refreshed since then.
    </div>
  )
}

function riskLabel(score) {
  if (score === null || score === undefined) return 'No data'
  if (score >= 70) return 'High Risk'
  if (score >= 40) return 'Elevated'
  if (score >= 20) return 'Moderate'
  return 'Low Risk'
}

function TickerSearchInput({ onSelect, placeholder }) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])

  useEffect(() => {
    if (!query) {
      setSuggestions([])
      return
    }
    const controller = new AbortController()
    fetch(`${API_BASE}/api/stock-tickers?q=${encodeURIComponent(query)}&limit=8`, {
      signal: controller.signal,
    })
      .then((res) => res.json())
      .then((data) => setSuggestions(data.tickers || []))
      .catch(() => {})
    return () => controller.abort()
  }, [query])

  return (
    <div className="ticker-search">
      <input
        className="ticker-input"
        value={query}
        placeholder={placeholder}
        onChange={(e) => setQuery(e.target.value.toUpperCase())}
      />
      {suggestions.length > 0 && (
        <ul className="ticker-suggestions">
          {suggestions.map((t) => (
            <li
              key={t}
              onClick={() => {
                onSelect(t)
                setQuery('')
                setSuggestions([])
              }}
            >
              {t}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function PortfolioReportPanel({ tickers }) {
  const [investigation, setInvestigation] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const investigate = () => {
    setLoading(true)
    setError(null)
    setInvestigation(null)
    fetch(`${API_BASE}/api/investigate-portfolio?tickers=${encodeURIComponent(tickers.join(','))}`)
      .then((res) => {
        if (!res.ok) throw new Error('Portfolio investigation failed')
        return res.json()
      })
      .then(setInvestigation)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  const labelClass = (label) =>
    label === 'FACT' ? 'label-fact' : label === 'MODEL PREDICTION' ? 'label-prediction' : 'label-interpretation'

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Portfolio AI report</h2>
        <span className="status">Orchestrator's second route — not a per-ticker report</span>
      </div>
      <p className="tester-hint">
        Runs the Orchestrator's portfolio path: checks each watchlist ticker's real FRI, then one
        LLM call synthesizes across all of them (average risk, highest-risk ticker, concentration)
        — a genuinely different route than the single-ticker "Investigate" view.
      </p>

      {!investigation && !loading && (
        <button className="primary-btn" onClick={investigate}>
          Generate portfolio report
        </button>
      )}
      {loading && <p className="tester-hint">Running portfolio investigation...</p>}
      {error && <p className="tester-error">{error}</p>}

      {investigation && investigation.result.report && (
        <>
          {investigation.result.report.critic && (
            <p className="tester-hint">
              Portfolio Critic Agent: <strong>{investigation.result.report.critic.verdict}</strong>
              {investigation.result.report.critic.revisions_requested > 0 &&
                ` — requested ${investigation.result.report.critic.revisions_requested} revision(s)`}
              {investigation.result.report.critic.issues.length > 0 && (
                <ul>
                  {investigation.result.report.critic.issues.map((issue, i) => <li key={i}>{issue}</li>)}
                </ul>
              )}
            </p>
          )}
          <p>{investigation.result.report.report}</p>
          <div className="labeled-claims">
            {investigation.result.report.labeled_claims.map((c, i) => (
              <div key={i} className={`labeled-claim ${labelClass(c.label)}`}>
                <span className="claim-label">{c.label}</span>
                <span>{c.text}</span>
                {c.verification === 'UNSUPPORTED' && (
                  <span className="verify-badge verify-bad" title={c.verification_detail}>⚠ unverified figure</span>
                )}
                {c.verification === 'SUPPORTED' && (
                  <span className="verify-badge verify-good" title={c.verification_detail}>✓ verified</span>
                )}
              </div>
            ))}
          </div>
          <p className="tester-hint">{investigation.result.report.note}</p>
          <button className="primary-btn secondary small" onClick={investigate}>
            Regenerate
          </button>
        </>
      )}
      {investigation && !investigation.result.report && (
        <p className="tester-error">No portfolio report could be generated — see trace for why.</p>
      )}
    </section>
  )
}

function Watchlist({ onOpenTicker }) {
  const [tickers, setTickers] = useState(loadWatchlist)
  const [results, setResults] = useState({})
  const [changes, setChanges] = useState({}) // ticker -> { delta, previousFri, previousSeenAt }
  const [loading, setLoading] = useState(false)

  const refresh = (list) => {
    if (list.length === 0) {
      setResults({})
      setChanges({})
      return
    }
    setLoading(true)
    fetch(`${API_BASE}/api/watchlist-risk?tickers=${encodeURIComponent(list.join(','))}`)
      .then((res) => res.json())
      .then((data) => {
        const byTicker = {}
        for (const r of data.results) byTicker[r.ticker] = r
        setResults(byTicker)

        // Real "what changed since you last looked" — compares each ticker's current FRI to the
        // FRI recorded the last time this watchlist was loaded (persisted in localStorage), not
        // a fixed lookback window like /api/risk-trend. Only flags a change if it clears
        // ALERT_THRESHOLD, so normal day-to-day heuristic jitter doesn't read as a false alarm.
        const lastSeen = loadLastSeen()
        const newChanges = {}
        const newSnapshot = { ...lastSeen }
        for (const r of data.results) {
          if (r.error || !r.fri || r.fri.score === null) continue
          const prev = lastSeen[r.ticker]
          if (prev && prev.fri !== null && prev.fri !== undefined) {
            const delta = Math.round((r.fri.score - prev.fri) * 10) / 10
            if (Math.abs(delta) >= ALERT_THRESHOLD) {
              newChanges[r.ticker] = { delta, previousFri: prev.fri, previousSeenAt: prev.seenAt }
            }
          }
          newSnapshot[r.ticker] = { fri: r.fri.score, seenAt: new Date().toISOString() }
        }
        setChanges(newChanges)
        saveLastSeen(newSnapshot)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh(tickers)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const addTicker = (t) => {
    if (tickers.includes(t)) return
    const next = [...tickers, t]
    setTickers(next)
    saveWatchlist(next)
    refresh(next)
  }

  const removeTicker = (t) => {
    const next = tickers.filter((x) => x !== t)
    setTickers(next)
    saveWatchlist(next)
    setResults((r) => {
      const copy = { ...r }
      delete copy[t]
      return copy
    })
  }

  const validResults = Object.values(results).filter((r) => !r.error)
  const portfolioFri =
    validResults.length > 0
      ? Math.round(
          validResults.reduce((sum, r) => sum + (r.fri.score ?? 0), 0) / validResults.length
        )
      : null

  return (
    <>
      <section className="panel">
        <div className="panel-header">
          <h2>Watchlist</h2>
          <span className="status">Your holdings, tracked over time</span>
        </div>
        <p className="tester-hint">
          Add tickers you actually hold or follow. FinGuard checks each one's real risk taxonomy
          (market indicators, SEC 8-K governance events, keyword-matched news) and, where
          historical data exists, whether its risk has been rising or falling — a real
          backward-looking comparison, not a forecast. Stored locally in your browser, no account
          needed.
        </p>
        <TickerSearchInput onSelect={addTicker} placeholder="Add a ticker, e.g. AAPL" />
      </section>

      {portfolioFri !== null && (
        <section className="stats-grid">
          <div className="card highlight">
            <span>Watchlist average FRI</span>
            <strong>{portfolioFri}</strong>
            <small>{riskLabel(portfolioFri)} · across {validResults.length} tickers</small>
          </div>
        </section>
      )}

      {tickers.length > 1 && <PortfolioReportPanel tickers={tickers} />}

      {Object.keys(changes).length > 0 && (
        <section className="panel alert-panel">
          <div className="panel-header">
            <h2>Changed since your last visit</h2>
            <span className="status">Real, not a forecast</span>
          </div>
          <p className="tester-hint">
            Compares each ticker's FRI now to its FRI the last time you loaded this watchlist
            (stored in your browser) — only shown when the change is at least {ALERT_THRESHOLD}
            points, so ordinary day-to-day movement doesn't read as a false alarm.
          </p>
          <ul className="alert-changes-list">
            {Object.entries(changes).map(([t, c]) => (
              <li key={t} onClick={() => onOpenTicker(t)}>
                <strong>{t}</strong>
                <span className={c.delta > 0 ? 'trend-increasing' : 'trend-decreasing'}>
                  {c.previousFri} → {results[t].fri.score} ({c.delta > 0 ? '+' : ''}
                  {c.delta})
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {loading && <div className="panel loading">Loading watchlist...</div>}

      <div className="watchlist-grid">
        {tickers.map((t) => {
          const r = results[t]
          if (!r) return null
          if (r.error) {
            return (
              <div className="watchlist-card" key={t}>
                <div className="watchlist-card-header">
                  <strong>{t}</strong>
                  <button className="remove-btn" onClick={() => removeTicker(t)}>
                    ×
                  </button>
                </div>
                <p className="tester-error">{r.error}</p>
              </div>
            )
          }
          const trend = r.trend
          const changed = changes[t]
          return (
            <div
              className={`watchlist-card ${changed ? 'watchlist-card-changed' : ''}`}
              key={t}
              onClick={() => onOpenTicker(t)}
            >
              <div className="watchlist-card-header">
                <strong>{t}</strong>
                <button
                  className="remove-btn"
                  onClick={(e) => {
                    e.stopPropagation()
                    removeTicker(t)
                  }}
                >
                  ×
                </button>
              </div>
              {changed && (
                <span className="changed-badge">
                  {changed.delta > 0 ? '↑' : '↓'} {changed.delta > 0 ? '+' : ''}
                  {changed.delta} since last visit
                </span>
              )}
              {r.company && <small className="tester-hint">{r.company.name}</small>}
              {r.freshness?.is_stale && (
                <span className="stale-badge">⚠ {r.freshness.age_days}d old data</span>
              )}
              <div className="watchlist-fri">
                <span className="fri-score">{r.fri.score ?? '—'}</span>
                <span>{riskLabel(r.fri.score)}</span>
              </div>
              {trend && (
                <div className={`watchlist-trend trend-${trend.direction}`}>
                  {trend.direction === 'increasing' ? '↑' : trend.direction === 'decreasing' ? '↓' : '→'}
                  {' '}
                  {trend.market_risk_change > 0 ? '+' : ''}
                  {trend.market_risk_change} market risk over {trend.lookback_trading_days}d
                </div>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}

function RiskTrendPanel({ ticker }) {
  const [trend, setTrend] = useState(null)

  useEffect(() => {
    setTrend(null)
    fetch(`${API_BASE}/api/risk-trend/${encodeURIComponent(ticker)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setTrend)
      .catch(() => {})
  }, [ticker])

  if (!trend) return null

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Risk trend</h2>
        <span className="status">Real history, not a forecast</span>
      </div>
      <div className={`trend-banner trend-${trend.direction}`}>
        <span className="fri-score">
          {trend.direction === 'increasing' ? '↑' : trend.direction === 'decreasing' ? '↓' : '→'}
          {' '}
          {trend.market_risk_change > 0 ? '+' : ''}
          {trend.market_risk_change}
        </span>
        <small>
          market_risk change, {trend.from_date} ({trend.from_value}) to {trend.to_date} ({trend.to_value})
        </small>
        {trend.governance_risk_change !== undefined && (
          <small>governance_risk change: {trend.governance_risk_change > 0 ? '+' : ''}{trend.governance_risk_change}</small>
        )}
      </div>
      <p className="tester-hint">{trend.method}</p>
    </section>
  )
}

function RiskTaxonomy({ ticker }) {
  const [taxonomy, setTaxonomy] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    setTaxonomy(null)
    fetch(`${API_BASE}/api/risk-taxonomy/${encodeURIComponent(ticker)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setTaxonomy)
      .finally(() => setLoading(false))
  }, [ticker])

  if (loading) return null
  if (!taxonomy) return null

  const { categories, not_yet_available, note, fri, freshness } = taxonomy

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Risk taxonomy</h2>
        <span className="status">FinGuard Risk Index</span>
      </div>

      <StaleDataBanner freshness={freshness} />

      {fri && fri.score !== null && (
        <div className="fri-banner">
          <div>
            <span className="fri-score">{fri.score}</span>
            <small>FRI / 100</small>
          </div>
          <div>
            <span className="fri-score">{Math.round(fri.confidence * 100)}%</span>
            <small>Confidence (data coverage)</small>
          </div>
          <div className="fri-weights">
            {Object.entries(fri.weights_used).map(([k, w]) => (
              <span key={k}>
                {k.replace(/_/g, ' ')}: {Math.round(w * 100)}%
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="tester-hint">{note}</p>

      <div className="taxonomy-grid">
        {Object.entries(categories).map(([key, cat]) => (
          <div className="taxonomy-card" key={key}>
            <div className="taxonomy-card-header">
              <strong>{key.replace(/_/g, ' ')}</strong>
              <span className="taxonomy-score">
                {cat.score === null || cat.score === undefined ? 'No data' : cat.score}
              </span>
            </div>
            <small className="tester-hint" style={{ margin: 0 }}>
              Basis: {cat.basis}
            </small>
            {Array.isArray(cat.reasons) && cat.reasons.length > 0 && (
              <ul className="taxonomy-reasons">
                {cat.reasons.map((r, i) => {
                  let text = r
                  let url = null
                  let date = null
                  if (typeof r === 'object') {
                    url = r.document_url || r.url || null
                    date = r.filed_at || (r.published_at ? r.published_at.slice(0, 10) : null)
                    text = r.headline || r.label || JSON.stringify(r)
                    if (date) text = `${text} (${date})`
                  }
                  return (
                    <li key={i}>
                      {url ? (
                        <a href={url} target="_blank" rel="noreferrer">
                          {text}
                        </a>
                      ) : (
                        text
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        ))}
      </div>

      {not_yet_available && not_yet_available.length > 0 && (
        <p className="tester-hint">
          Not yet computable (no underlying data collected): {not_yet_available.join(', ')}.
        </p>
      )}
    </section>
  )
}

function CompanyFilings({ ticker }) {
  const [filings, setFilings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [openSection, setOpenSection] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setFilings(null)
    setOpenSection(null)
    fetch(`${API_BASE}/api/filings/${encodeURIComponent(ticker)}`)
      .then((res) => {
        if (!res.ok) throw new Error(`No collected SEC filings for ${ticker}`)
        return res.json()
      })
      .then((data) => setFilings(data.filings))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [ticker])

  const loadSection = async (filing, section) => {
    const key = `${filing.accession_no}:${section}`
    setOpenSection({ key, loading: true })
    try {
      const res = await fetch(
        `${API_BASE}/api/filings/${encodeURIComponent(ticker)}/section?` +
          new URLSearchParams({
            accession_no: filing.accession_no,
            document_url: filing.document_url,
            section,
          })
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `${section} not found in this filing`)
      }
      const data = await res.json()
      setOpenSection({ key, text: data.text, sourceUrl: data.document_url })
    } catch (err) {
      setOpenSection({ key, error: err.message })
    }
  }

  if (loading) return <div className="panel loading">Loading filings for {ticker}...</div>
  if (error) return null
  if (!filings || filings.length === 0) return null

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>SEC filings</h2>
        <span className="status">Real EDGAR documents</span>
      </div>
      <p className="tester-hint">
        Filing metadata collected by <code>scripts/sec_filings.py</code>. Clicking "Risk Factors"
        or "MD&amp;A" fetches the real filing document from SEC EDGAR and extracts that section's
        actual text — not a summary, the source text itself, traceable to the original document.
      </p>
      <ul className="filing-list">
        {filings.map((f) => (
          <li key={f.accession_no} className="filing-item">
            <div className="filing-meta">
              <strong>{f.form_type}</strong>
              <span>{f.filed_at?.slice(0, 10)}</span>
              <a href={f.document_url} target="_blank" rel="noreferrer">
                View on SEC.gov
              </a>
            </div>
            <div className="filing-actions">
              <button className="primary-btn secondary small" onClick={() => loadSection(f, 'risk_factors')}>
                Risk Factors
              </button>
              <button className="primary-btn secondary small" onClick={() => loadSection(f, 'mdna')}>
                MD&amp;A
              </button>
            </div>
            {openSection && openSection.key?.startsWith(f.accession_no) && (
              <div className="filing-section-body">
                {openSection.loading && <p className="tester-hint">Fetching from SEC EDGAR...</p>}
                {openSection.error && <p className="tester-error">{openSection.error}</p>}
                {openSection.text && (
                  <>
                    <p className="tester-hint">
                      Source: <a href={openSection.sourceUrl} target="_blank" rel="noreferrer">{openSection.sourceUrl}</a>
                    </p>
                    <pre className="filing-text">{openSection.text.slice(0, 4000)}</pre>
                  </>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function RiskForecastPanel({ ticker }) {
  const [forecast, setForecast] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setForecast(null)
    setError(null)
    fetch(`${API_BASE}/api/risk-forecast/${encodeURIComponent(ticker)}`)
      .then((res) => {
        if (!res.ok) throw new Error('Forecast unavailable for this ticker')
        return res.json()
      })
      .then(setForecast)
      .catch((err) => setError(err.message))
  }, [ticker])

  if (error) return null
  if (!forecast) return null

  const pct = Math.round(forecast.probability_market_risk_increase_10pt * 100)
  const level = pct >= 60 ? 'high' : pct >= 35 ? 'medium' : 'low'

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Risk forecast</h2>
        <span className="status">Trained model, not a backward-looking comparison</span>
      </div>
      <div className={`trend-banner trend-${level === 'high' ? 'increasing' : level === 'low' ? 'decreasing' : 'stable'}`}>
        <span className="fri-score">{pct}%</span>
        <small>
          Probability market_risk rises ≥10 points over the next {forecast.horizon_trading_days} trading days
        </small>
        <small>Current market_risk: {forecast.current_market_risk} (as of {forecast.as_of})</small>
      </div>
      <p className="tester-hint">{forecast.method}</p>
      {forecast.model_test_metrics && (
        <p className="tester-hint">
          Model's own measured test performance — ROC-AUC {forecast.model_test_metrics.roc_auc},
          PR-AUC {forecast.model_test_metrics.pr_auc}, vs. a naive baseline's{' '}
          {forecast.naive_baseline_test_metrics?.roc_auc} / {forecast.naive_baseline_test_metrics?.pr_auc}.
          A real, modest improvement — treat this as an early signal, not a certainty.
        </p>
      )}
    </section>
  )
}

function NewsSentimentPanel({ ticker }) {
  const [sentiment, setSentiment] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showHeadlines, setShowHeadlines] = useState(false)

  useEffect(() => {
    setLoading(true)
    setSentiment(null)
    setShowHeadlines(false)
    fetch(`${API_BASE}/api/news-sentiment/${encodeURIComponent(ticker)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setSentiment)
      .finally(() => setLoading(false))
  }, [ticker])

  if (loading) return <div className="panel loading">Loading news sentiment for {ticker}...</div>
  if (!sentiment || sentiment.net_sentiment === null) return null

  const net = sentiment.net_sentiment
  const tone = net > 15 ? 'decreasing' : net < -15 ? 'increasing' : 'stable'

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>News sentiment (FinBERT)</h2>
        <span className="status">Additive signal, separate from FRI</span>
      </div>
      <div className={`trend-banner trend-${tone}`}>
        <span className="fri-score">{net > 0 ? '+' : ''}{net}</span>
        <small>Net sentiment (-100 to +100), {sentiment.counts.positive} positive / {sentiment.counts.negative} negative / {sentiment.counts.neutral} neutral headlines</small>
        {sentiment.trend && <small>Trend: {sentiment.trend}</small>}
      </div>
      {sentiment.divergence && (
        <p className="tester-hint">
          {sentiment.divergence.diverges ? '⚠ Divergence: ' : 'No divergence: '}
          sentiment {sentiment.divergence.net_sentiment > 0 ? 'positive' : 'negative'} while price moved{' '}
          {sentiment.divergence.price_change_pct > 0 ? '+' : ''}{sentiment.divergence.price_change_pct}% over 5 sessions.
        </p>
      )}
      <p className="tester-hint">{sentiment.note}</p>
      <button className="primary-btn secondary small" onClick={() => setShowHeadlines((v) => !v)}>
        {showHeadlines ? 'Hide' : 'Show'} scored headlines ({sentiment.headlines.length})
      </button>
      {showHeadlines && (
        <ul className="filing-list">
          {sentiment.headlines.map((h, i) => (
            <li key={i} className="filing-item">
              <div className="filing-meta">
                <strong>{h.sentiment}</strong>
                <span>{h.sentiment_confidence}</span>
                <a href={h.url} target="_blank" rel="noreferrer">{h.title}</a>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function AIReportPanel({ ticker }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const generate = () => {
    setLoading(true)
    setError(null)
    setReport(null)
    fetch(`${API_BASE}/api/report/${encodeURIComponent(ticker)}`)
      .then((res) => {
        if (!res.ok) throw new Error('Report generation unavailable (no Groq API key configured, or the model is unreachable)')
        return res.json()
      })
      .then(setReport)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  const labelClass = (label) =>
    label === 'FACT' ? 'label-fact' : label === 'MODEL PREDICTION' ? 'label-prediction' : 'label-interpretation'

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>AI risk report</h2>
        <span className="status">The only LLM call in FinGuard — explains, doesn't invent</span>
      </div>

      {!report && !loading && (
        <button className="primary-btn" onClick={generate}>
          Generate report for {ticker}
        </button>
      )}
      {loading && <p className="tester-hint">Asking the Report Agent (Groq)...</p>}
      {error && <p className="tester-error">{error}</p>}

      {report && (
        <>
          {report.critic && (
            <p className="tester-hint">
              Critic Agent: <strong>{report.critic.verdict}</strong>
              {report.critic.revisions_requested > 0 && ` — requested ${report.critic.revisions_requested} revision(s)`}
              {report.critic.issues.length > 0 && (
                <ul>
                  {report.critic.issues.map((issue, i) => <li key={i}>{issue}</li>)}
                </ul>
              )}
            </p>
          )}
          {report.evidence_verification && (
            <p className="tester-hint">
              Evidence Verifier: <strong>{report.evidence_verification.verdict}</strong>
              {' '}({report.evidence_verification.total_checked - report.evidence_verification.unsupported_count}/{report.evidence_verification.total_checked} claims' figures traced to real source data)
            </p>
          )}
          <p>{report.report}</p>
          <div className="labeled-claims">
            {report.labeled_claims.map((c, i) => (
              <div key={i} className={`labeled-claim ${labelClass(c.label)}`}>
                <span className="claim-label">{c.label}</span>
                <span>{c.text}</span>
                {c.verification === 'UNSUPPORTED' && (
                  <span className="verify-badge verify-bad" title={c.verification_detail}>⚠ unverified figure</span>
                )}
                {c.verification === 'SUPPORTED' && (
                  <span className="verify-badge verify-good" title={c.verification_detail}>✓ verified</span>
                )}
              </div>
            ))}
          </div>
          <p className="tester-hint">{report.note}</p>
          <button className="primary-btn secondary small" onClick={generate}>
            Regenerate
          </button>
        </>
      )}
    </section>
  )
}

function AgentTracePanel({ ticker }) {
  const [investigation, setInvestigation] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const investigate = () => {
    setLoading(true)
    setError(null)
    setInvestigation(null)
    fetch(`${API_BASE}/api/investigate/${encodeURIComponent(ticker)}`)
      .then((res) => {
        if (!res.ok) throw new Error('Investigation failed')
        return res.json()
      })
      .then(setInvestigation)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Orchestrated investigation</h2>
        <span className="status">Real agent routing, not a fixed pipeline</span>
      </div>
      <p className="tester-hint">
        Runs the Orchestrator: checks what data actually exists for {ticker} first, then routes
        to the Market, Risk Analyst, History, Forecast, Report, and Critic agents accordingly —
        skipping or aborting steps a fixed pipeline would have run blindly.
      </p>

      {!investigation && !loading && (
        <button className="primary-btn" onClick={investigate}>
          Investigate {ticker}
        </button>
      )}
      {loading && <p className="tester-hint">Running orchestrated investigation...</p>}
      {error && <p className="tester-error">{error}</p>}

      {investigation && (
        <>
          <p className="tester-hint">
            Status: <strong>{investigation.status}</strong>
          </p>
          <ul className="agent-trace">
            {investigation.trace.map((step, i) => (
              <li key={i} className="agent-trace-step">
                <span className="agent-trace-time">
                  {new Date(step.timestamp).toLocaleTimeString()}
                </span>
                <span className="agent-trace-agent">{step.agent}</span>
                <span className="agent-trace-decision">{step.decision}</span>
                <span className="agent-trace-detail">{step.detail}</span>
              </li>
            ))}
          </ul>
          <button className="primary-btn secondary small" onClick={investigate}>
            Re-run
          </button>
        </>
      )}
    </section>
  )
}

function TickerLookup({ initialTicker, onConsumeInitial }) {
  const [ticker, setTicker] = useState(null)
  const [risk, setRisk] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const loadTicker = async (t) => {
    setTicker(t)
    setLoading(true)
    setError(null)
    setRisk(null)
    try {
      const res = await fetch(`${API_BASE}/api/stock-risk/${encodeURIComponent(t)}`)
      if (!res.ok) throw new Error(`No indicator data for ${t}`)
      const data = await res.json()
      setRisk(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (initialTicker) {
      loadTicker(initialTicker)
      onConsumeInitial()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTicker])

  return (
    <>
      <section className="panel">
        <div className="panel-header">
          <h2>Ticker lookup</h2>
          <span className="status">Rule-based, not ML</span>
        </div>
        <p className="tester-hint">
          Deep-dive on any single ticker: technical risk score, taxonomy, trend, and real SEC
          filings. Data comes from ~9,700 tickers already collected by
          <code> scripts/generate_indicators.py</code>, not from a trained classifier.
        </p>
        <TickerSearchInput onSelect={loadTicker} placeholder="Search ticker, e.g. AAPL" />
        {error && <p className="tester-error">{error}</p>}
      </section>

      {loading && <div className="panel loading">Loading {ticker}...</div>}

      {risk && !loading && (
        <>
          <StaleDataBanner freshness={risk.freshness} />
          {risk.company && (
            <p className="tester-hint" style={{ marginTop: -8 }}>
              <strong>{risk.company.name}</strong> — {risk.company.sector} / {risk.company.industry}
              {' '}({risk.company.exchange})
            </p>
          )}
          <section className="stats-grid">
            <div className="card highlight">
              <span>{risk.ticker} Risk Score</span>
              <strong>{risk.risk_score}</strong>
              <small>{risk.risk_label}</small>
            </div>
            <div className="card">
              <span>Close</span>
              <strong>${risk.close}</strong>
              <small>As of {risk.as_of?.slice(0, 10)}</small>
            </div>
            <div className="card">
              <span>RSI (14)</span>
              <strong>{risk.indicators.rsi_14}</strong>
              <small>Momentum</small>
            </div>
            <div className="card">
              <span>Volatility (20d)</span>
              <strong>{risk.indicators.volatility_20}</strong>
              <small>Recent swing size</small>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Why this score</h2>
            </div>
            {risk.reasons.length > 0 ? (
              <ul className="alert-list">
                {risk.reasons.map((reason, i) => (
                  <li key={i}>
                    <div>
                      <strong>{reason}</strong>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="tester-hint">No elevated risk factors detected.</p>
            )}
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Recent close price ({risk.history.length} sessions)</h2>
            </div>
            <div className="trend">
              {risk.history.map((h, i) => {
                const closes = risk.history.map((r) => r.Close)
                const min = Math.min(...closes)
                const max = Math.max(...closes)
                const pct = max > min ? ((h.Close - min) / (max - min)) * 100 : 50
                return (
                  <div key={i} className="bar-wrap">
                    <div className="bar" style={{ height: `${Math.max(pct, 4)}%` }} />
                  </div>
                )
              })}
            </div>
          </section>

          <AgentTracePanel ticker={risk.ticker} />
          <RiskTrendPanel ticker={risk.ticker} />
          <RiskForecastPanel ticker={risk.ticker} />
          <RiskTaxonomy ticker={risk.ticker} />
          <NewsSentimentPanel ticker={risk.ticker} />
          <AIReportPanel ticker={risk.ticker} />
          <CompanyFilings ticker={risk.ticker} />
        </>
      )}
    </>
  )
}

function App() {
  const [tab, setTab] = useState('watchlist')
  const [pendingTicker, setPendingTicker] = useState(null)

  const openTicker = (t) => {
    setPendingTicker(t)
    setTab('lookup')
  }

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">FINANCIAL INTELLIGENCE</p>
          <h1>FinGuard AI</h1>
        </div>
        <div className="tab-switch">
          <button
            className={`tab-btn ${tab === 'watchlist' ? 'active' : ''}`}
            onClick={() => setTab('watchlist')}
          >
            Watchlist
          </button>
          <button
            className={`tab-btn ${tab === 'lookup' ? 'active' : ''}`}
            onClick={() => setTab('lookup')}
          >
            Ticker Lookup
          </button>
        </div>
      </header>

      {tab === 'watchlist' ? (
        <Watchlist onOpenTicker={openTicker} />
      ) : (
        <TickerLookup initialTicker={pendingTicker} onConsumeInitial={() => setPendingTicker(null)} />
      )}
    </div>
  )
}

export default App
