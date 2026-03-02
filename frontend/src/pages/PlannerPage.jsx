import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'

export default function PlannerPage({ userId }) {
  const [topics, setTopics] = useState([])
  const [selectedSubtopicIds, setSelectedSubtopicIds] = useState([])
  const [form, setForm] = useState({ exam_date: '' })
  const [plan, setPlan] = useState(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  const loadTopics = async () => {
    const result = await api.getTopics(userId)
    setTopics(result)
  }

  useEffect(() => {
    loadTopics().catch((err) => setError(err.message || 'Unable to load topics'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  const subtopics = useMemo(
    () =>
      topics.flatMap((topic) =>
        (topic.subtopics || []).map((subtopic) => ({
          ...subtopic,
          main_topic_title: topic.title,
        })),
      ),
    [topics],
  )

  useEffect(() => {
    if (!subtopics.length) return
    if (selectedSubtopicIds.length) return
    setSelectedSubtopicIds(subtopics.map((subtopic) => subtopic.id))
  }, [subtopics, selectedSubtopicIds.length])

  const toggleSubtopic = (subtopicId) => {
    setSelectedSubtopicIds((prev) => {
      if (prev.includes(subtopicId)) {
        return prev.filter((id) => id !== subtopicId)
      }
      return [...prev, subtopicId]
    })
  }

  const generatePlan = async (event) => {
    event.preventDefault()

    if (!selectedSubtopicIds.length) {
      setError('Select at least one subtopic')
      return
    }

    setError('')
    setStatus('Generating study plan...')

    try {
      const result = await api.generatePlan({
        user_id: userId,
        exam_date: form.exam_date,
        subtopic_ids: selectedSubtopicIds,
      })
      setPlan(result)
      setStatus(`Plan generated (${result.generated_by})`)
    } catch (err) {
      setStatus('')
      setError(err.message || 'Unable to generate plan')
    }
  }

  return (
    <section className="page-stack">
      <div>
        <h1>Exam-Time Study Planner</h1>
      </div>

      {error && <p className="error-text">{error}</p>}
      {status && <p className="success-text">{status}</p>}

      <article className="panel">
        <h2>Generate Plan</h2>
        <form className="grid-form" onSubmit={generatePlan}>
          <label>
            Exam date
            <input
              type="date"
              value={form.exam_date}
              onChange={(event) => setForm((prev) => ({ ...prev, exam_date: event.target.value }))}
              required
            />
          </label>
          <button className="btn primary" type="submit">
            Generate study plan
          </button>
        </form>
      </article>

      <article className="panel">
        <h2>Subtopics Tested</h2>
        {!subtopics.length ? (
          <p className="muted">Create topics and subtopics first.</p>
        ) : (
          <div className="checkbox-grid">
            {subtopics.map((subtopic) => (
              <label key={subtopic.id} className="choice-item">
                <input
                  type="checkbox"
                  checked={selectedSubtopicIds.includes(subtopic.id)}
                  onChange={() => toggleSubtopic(subtopic.id)}
                />
                <span>
                  {subtopic.main_topic_title} · {subtopic.title}
                </span>
              </label>
            ))}
          </div>
        )}
      </article>

      {plan && (
        <article className="panel">
          <h2>Generated Plan</h2>
          <p>
            Exam date: <strong>{plan.exam_date}</strong> · Days left: <strong>{plan.days_until_exam}</strong> · Source:{' '}
            <strong>{plan.generated_by}</strong>
          </p>
          <p className="muted">{plan.summary}</p>

          <ol className="flat-list ordered" style={{ marginTop: '0.6rem' }}>
            {plan.recommendations.map((row, index) => (
              <li key={row.subtopic_id || `${row.subtopic}-${index}`}>
                <strong>
                  {row.main_topic || 'Topic'} · {row.subtopic || 'Study focus'}
                </strong>
                {row.day && <p className="muted">Day {row.day}</p>}
                {row.allocated_hours && <p className="muted">Allocate {row.allocated_hours} hour(s)</p>}
                {row.projected_mastery && (
                  <p className="muted">Projected mastery: {Math.round(row.projected_mastery * 100)}%</p>
                )}
                {Array.isArray(row.tasks) && row.tasks.length > 0 && (
                  <ul className="flat-list compact">
                    {row.tasks.map((task, taskIndex) => (
                      <li key={`${row.subtopic}-${taskIndex}`}>{task}</li>
                    ))}
                  </ul>
                )}
                {row.reason && <p className="muted">{row.reason}</p>}
              </li>
            ))}
          </ol>
        </article>
      )}
    </section>
  )
}
