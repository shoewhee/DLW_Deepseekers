import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'

const PIE_COLORS = ['#1f7a63', '#f58f00', '#4a72d8', '#de6b48', '#75944b', '#9370db']

function MetricCard({ label, value, helper }) {
  return (
    <div className="metric-card">
      <p>{label}</p>
      <h3>{value}</h3>
      {helper && <small>{helper}</small>}
    </div>
  )
}

function TrendBars({ title, points, valueKey, formatter, colorClass }) {
  const maxValue = useMemo(() => {
    if (!points.length) return 1
    return Math.max(...points.map((point) => Number(point[valueKey] || 0)), 1)
  }, [points, valueKey])
  const chartHeightPx = 170

  return (
    <article className="panel">
      <h2>{title}</h2>
      {!points.length ? (
        <p className="muted">No trend data yet.</p>
      ) : (
        <div className="trend-chart">
          {points.map((point) => {
            const raw = Number(point[valueKey] || 0)
            const heightPx = Math.max((raw / maxValue) * chartHeightPx, raw > 0 ? 8 : 2)
            return (
              <div key={`${title}-${point.date}`} className="trend-bar-wrap">
                <div className={`trend-bar ${colorClass}`} style={{ height: `${heightPx}px` }} />
                <small>{formatter(raw)}</small>
                <span>{point.date.slice(5)}</span>
              </div>
            )
          })}
        </div>
      )}
    </article>
  )
}

function PieChart({ title, slices }) {
  const total = useMemo(() => slices.reduce((sum, slice) => sum + Number(slice.count || 0), 0), [slices])

  const gradient = useMemo(() => {
    if (!total) return 'conic-gradient(#e8edf2 0deg 360deg)'

    let running = 0
    const stops = slices.map((slice, idx) => {
      const value = Number(slice.count || 0)
      const start = (running / total) * 360
      running += value
      const end = (running / total) * 360
      const color = PIE_COLORS[idx % PIE_COLORS.length]
      return `${color} ${start}deg ${end}deg`
    })
    return `conic-gradient(${stops.join(', ')})`
  }, [slices, total])

  return (
    <article className="panel">
      <h2>{title}</h2>
      {total === 0 ? (
        <p className="muted">No incorrect attempts yet for this scope.</p>
      ) : (
        <div className="pie-layout">
          <div className="pie-visual" style={{ background: gradient }} aria-label={`${title} pie chart`} />
          <ul className="flat-list pie-legend">
            {slices.map((slice, idx) => {
              const value = Number(slice.count || 0)
              const share = Math.round((value / total) * 100)
              return (
                <li key={`${title}-${slice.label}`}>
                  <span className="legend-row">
                    <span className="legend-dot" style={{ backgroundColor: PIE_COLORS[idx % PIE_COLORS.length] }} />
                    <strong>{slice.label}</strong>
                  </span>
                  <small>
                    {value} wrong attempt{value === 1 ? '' : 's'} ({share}%)
                  </small>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </article>
  )
}

export default function DashboardPage({ userId }) {
  const [summary, setSummary] = useState(null)
  const [trends, setTrends] = useState([])
  const [reportOverview, setReportOverview] = useState([])
  const [topics, setTopics] = useState([])
  const [selectedTopicId, setSelectedTopicId] = useState('')
  const [selectedSubtopicId, setSelectedSubtopicId] = useState('')
  const [mistakePatterns, setMistakePatterns] = useState({
    scope: {},
    difficulty_distribution: [],
    type_distribution: [],
  })
  const [error, setError] = useState('')
  const [patternError, setPatternError] = useState('')

  useEffect(() => {
    let active = true

    async function load() {
      try {
        setError('')
        const [dashboardData, trendData, reportData, topicData] = await Promise.all([
          api.getDashboardSummary(userId),
          api.getDashboardTrends(userId, 14),
          api.getReportOverview(userId),
          api.getTopics(userId),
        ])

        if (!active) return
        setSummary(dashboardData)
        setTrends(trendData.points || [])
        setReportOverview(reportData)
        setTopics(topicData || [])
        setSelectedTopicId((prev) => {
          if (prev && (topicData || []).some((topic) => topic.id === prev)) return prev
          return topicData?.[0]?.id || ''
        })
        setSelectedSubtopicId('')
      } catch (err) {
        if (!active) return
        setError(err.message || 'Failed to load dashboard')
      }
    }

    load()
    return () => {
      active = false
    }
  }, [userId])

  const selectedTopic = useMemo(
    () => topics.find((topic) => topic.id === selectedTopicId) || null,
    [topics, selectedTopicId],
  )
  const subtopicsInScope = useMemo(() => selectedTopic?.subtopics || [], [selectedTopic])

  useEffect(() => {
    const allowedIds = new Set(subtopicsInScope.map((subtopic) => subtopic.id))
    setSelectedSubtopicId((prev) => (prev && allowedIds.has(prev) ? prev : ''))
  }, [subtopicsInScope])

  useEffect(() => {
    let active = true

    async function loadMistakePatterns() {
      if (!selectedTopicId) {
        setMistakePatterns({
          scope: {},
          difficulty_distribution: [],
          type_distribution: [],
        })
        return
      }

      try {
        setPatternError('')
        const data = await api.getDashboardMistakePatterns(userId, {
          topicId: selectedTopicId,
          subtopicId: selectedSubtopicId || undefined,
        })
        if (!active) return
        setMistakePatterns(data)
      } catch (err) {
        if (!active) return
        setPatternError(err.message || 'Failed to load mistake patterns')
      }
    }

    loadMistakePatterns()
    return () => {
      active = false
    }
  }, [userId, selectedTopicId, selectedSubtopicId])

  if (error) {
    return <p className="error-text">{error}</p>
  }

  if (!summary) {
    return <p className="loading-state">Loading dashboard...</p>
  }

  const accuracyPct = `${Math.round(summary.recent_accuracy * 100)}%`
  const confidencePct = `${Math.round(summary.average_confidence * 100)}%`

  return (
    <section className="page-stack">
      <div>
        <h1>Live Study Dashboard</h1>
      </div>

      <div className="metric-grid">
        <MetricCard
          label="Time Spent Today"
          value={`${Math.round(summary.today_time_spent_seconds / 60)} min`}
          helper="Accumulated from all quiz attempts"
        />
        <MetricCard
          label="Repeated Attempts"
          value={summary.repeated_attempt_questions}
          helper="Questions with more than one try"
        />
        <MetricCard label="Recent Accuracy" value={accuracyPct} helper="Last 14 days of attempts" />
        <MetricCard
          label="Average Confidence"
          value={confidencePct}
          helper={`${summary.low_confidence_subtopics} low-confidence subtopics`}
        />
        <MetricCard
          label="Completed Quizzes"
          value={summary.sessions_completed_last_14d}
          helper="Sessions completed in last 14 days"
        />
      </div>

      <div className="card-grid two">
        <TrendBars
          title="Daily Study Minutes"
          points={trends}
          valueKey="study_minutes"
          formatter={(value) => `${Math.round(value)}m`}
          colorClass="mint"
        />
        <TrendBars
          title="Daily Accuracy"
          points={trends}
          valueKey="accuracy"
          formatter={(value) => `${Math.round(value * 100)}%`}
          colorClass="sun"
        />
      </div>

      <article className="panel">
        <div className="row-between">
          <h2>Mistake Patterns</h2>
          <p className="muted">Filter by topic or subtopic to inspect where errors cluster.</p>
        </div>

        {topics.length === 0 ? (
          <p className="muted">No topics yet. Add topics and complete quizzes to view mistake patterns.</p>
        ) : (
          <div className="mistake-filters">
            <label>
              Topic
              <select value={selectedTopicId} onChange={(event) => setSelectedTopicId(event.target.value)}>
                {topics.map((topic) => (
                  <option key={topic.id} value={topic.id}>
                    {topic.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Subtopic
              <select value={selectedSubtopicId} onChange={(event) => setSelectedSubtopicId(event.target.value)}>
                <option value="">All subtopics</option>
                {subtopicsInScope.map((subtopic) => (
                  <option key={subtopic.id} value={subtopic.id}>
                    {subtopic.title}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {patternError && <p className="error-text">{patternError}</p>}

        <div className="card-grid two">
          <PieChart title="Mistakes by Question Difficulty" slices={mistakePatterns.difficulty_distribution || []} />
          <PieChart title="Mistakes by Question Type" slices={mistakePatterns.type_distribution || []} />
        </div>
      </article>

      <article className="panel">
        <h2>Main Topic Strength Report</h2>
        {reportOverview.length === 0 ? (
          <p className="muted">No topic report yet. Complete a quiz first.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Main Topic</th>
                  <th>Avg Adjusted Mastery</th>
                  <th>Weakest Subtopic</th>
                  <th>Strongest Subtopic</th>
                  <th>Avg Confidence</th>
                </tr>
              </thead>
              <tbody>
                {reportOverview.map((row) => (
                  <tr key={row.main_topic_id}>
                    <td>{row.main_topic_title}</td>
                    <td>{Math.round(row.avg_adjusted_mastery * 100)}%</td>
                    <td>{Math.round(row.weakest_subtopic_score * 100)}%</td>
                    <td>{Math.round(row.strongest_subtopic_score * 100)}%</td>
                    <td>{Math.round(row.avg_confidence * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  )
}
