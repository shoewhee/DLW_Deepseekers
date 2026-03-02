import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api/client'

function formatClock(totalSeconds) {
  const safe = Math.max(0, Number(totalSeconds || 0))
  const minutes = Math.floor(safe / 60)
  const seconds = safe % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export default function QuizPage({ userId }) {
  const [topics, setTopics] = useState([])
  const [selectedSubtopicId, setSelectedSubtopicId] = useState('')
  const [sessionData, setSessionData] = useState(null)
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)
  const [finishSummary, setFinishSummary] = useState(null)
  const [answerValue, setAnswerValue] = useState('')
  const [timeRemaining, setTimeRemaining] = useState(0)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const attemptStartRef = useRef(Date.now())
  const timeoutTriggeredRef = useRef(false)

  const loadTopics = async () => {
    const data = await api.getTopics(userId)
    setTopics(data)
  }

  useEffect(() => {
    loadTopics().catch((err) => setError(err.message || 'Unable to load subtopics'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  const subtopics = useMemo(
    () =>
      topics.flatMap((topic) =>
        (topic.subtopics || []).map((subtopic) => ({
          ...subtopic,
          main_topic_id: topic.id,
          main_topic_title: topic.title,
        })),
      ),
    [topics],
  )

  const currentQuestionRow = sessionData?.questions?.[currentQuestionIndex] || null
  const currentQuestion = currentQuestionRow?.question || null
  const usedAttempts = currentQuestionRow?.attempts?.length || 0

  const resetForQuestion = (row) => {
    setAnswerValue('')
    setStatus('')
    timeoutTriggeredRef.current = false
    const allocated = Number(row?.allocated_seconds || row?.question?.expected_seconds || 120)
    setTimeRemaining(allocated)
    attemptStartRef.current = Date.now()
  }

  useEffect(() => {
    if (!currentQuestionRow) return
    resetForQuestion(currentQuestionRow)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentQuestionRow?.id])

  useEffect(() => {
    if (!currentQuestionRow || finishSummary) return undefined

    const interval = setInterval(() => {
      setTimeRemaining((previous) => {
        if (previous <= 0) {
          return 0
        }
        return previous - 1
      })
    }, 1000)

    return () => clearInterval(interval)
  }, [currentQuestionRow, finishSummary])

  const refreshSession = async () => {
    if (!sessionData?.session?.id) return
    const reloaded = await api.getSession(sessionData.session.id, userId)
    setSessionData(reloaded)
    return reloaded
  }

  const finishSession = async () => {
    if (!sessionData?.session?.id) return
    const result = await api.finishSession(sessionData.session.id, { user_id: userId })
    setFinishSummary(result.summary)
    setStatus('Quiz completed')
  }

  const moveToNextQuestionOrFinish = async (latestSessionData) => {
    const total = latestSessionData?.questions?.length || sessionData?.questions?.length || 0
    if (currentQuestionIndex >= total - 1) {
      await finishSession()
      return
    }

    setCurrentQuestionIndex((previous) => previous + 1)
  }

  const submitAttempt = async ({ timedOut }) => {
    if (!currentQuestionRow || !currentQuestion || isSubmitting) return

    setIsSubmitting(true)
    setError('')

    try {
      const elapsedSeconds = Math.max(1, Math.round((Date.now() - attemptStartRef.current) / 1000))
      const payload = {
        user_id: userId,
        session_question_id: currentQuestionRow.id || currentQuestionRow.session_question_id,
        submitted_answer: timedOut ? '' : answerValue,
        response_seconds: elapsedSeconds,
      }

      const result = await api.submitAttempt(sessionData.session.id, payload)
      const latest = await refreshSession()

      if (timedOut) {
        setStatus('Time is up. Moving to next question.')
        await moveToNextQuestionOrFinish(latest)
        return
      }

      if (result.attempt.is_correct) {
        setStatus('Correct. Moving to next question...')
        await moveToNextQuestionOrFinish(latest)
        return
      }

      if (result.remaining_attempts > 0) {
        setStatus(`Incorrect. ${result.remaining_attempts} attempt left.`)
        setAnswerValue('')
        attemptStartRef.current = Date.now()
        return
      }

      setStatus('No attempts left. Moving to next question...')
      await moveToNextQuestionOrFinish(latest)
    } catch (err) {
      setError(err.message || 'Unable to submit attempt')
    } finally {
      setIsSubmitting(false)
    }
  }

  useEffect(() => {
    if (!currentQuestionRow || finishSummary || isSubmitting) return
    if (timeRemaining > 0) return
    if (timeoutTriggeredRef.current) return

    timeoutTriggeredRef.current = true
    submitAttempt({ timedOut: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRemaining, currentQuestionRow, finishSummary, isSubmitting])

  const startQuiz = async () => {
    if (!selectedSubtopicId) return

    const selected = subtopics.find((item) => item.id === selectedSubtopicId)
    try {
      setError('')
      setStatus('')
      setFinishSummary(null)
      const result = await api.startSession({
        user_id: userId,
        subtopic_id: selectedSubtopicId,
        main_topic_id: selected?.main_topic_id,
        question_count: 6,
      })
      setSessionData(result)
      setCurrentQuestionIndex(0)
    } catch (err) {
      setError(err.message || 'Unable to start quiz')
    }
  }

  return (
    <section className="page-stack">
      <div>
        <h1>Quiz Runner</h1>
      </div>

      {error && <p className="error-text">{error}</p>}
      {status && <p className="success-text">{status}</p>}

      <article className="panel">
        <h2>Start New Quiz Session</h2>
        <div className="row-wrap">
          <select value={selectedSubtopicId} onChange={(event) => setSelectedSubtopicId(event.target.value)}>
            <option value="">Select a subtopic</option>
            {subtopics.map((subtopic) => (
              <option key={subtopic.id} value={subtopic.id}>
                {subtopic.main_topic_title} · {subtopic.title}
              </option>
            ))}
          </select>
          <button className="btn primary" type="button" onClick={startQuiz} disabled={!selectedSubtopicId}>
            Start quiz
          </button>
        </div>
      </article>

      {currentQuestionRow && !finishSummary && (
        <article className="panel quiz-runner">
          <div className="row-between">
            <h2>
              Question {currentQuestionIndex + 1} / {sessionData?.questions?.length || 0}
            </h2>
            <div className="row-wrap">
              <p className="pill">
                Attempts: {usedAttempts}/{currentQuestionRow.max_attempts}
              </p>
              <p className={`timer-pill ${timeRemaining <= 10 ? 'urgent' : ''}`}>{formatClock(timeRemaining)}</p>
            </div>
          </div>

          <p className="pill">
            {currentQuestion.difficulty} · {currentQuestion.format} · {currentQuestion.intent}
          </p>
          <h3 style={{ marginTop: '0.6rem' }}>{currentQuestion.prompt}</h3>

          {currentQuestion.format === 'mcq' ? (
            <div className="flat-list" style={{ marginTop: '0.8rem' }}>
              {(currentQuestion.options || []).map((option, index) => (
                <label key={`opt-${index}`} className="choice-item">
                  <input
                    type="radio"
                    name={`question-${currentQuestionRow.id}`}
                    value={option}
                    checked={answerValue === option}
                    onChange={(event) => setAnswerValue(event.target.value)}
                    disabled={isSubmitting}
                  />
                  <span>{option}</span>
                </label>
              ))}
            </div>
          ) : (
            <textarea
              rows={4}
              placeholder="Type your answer"
              value={answerValue}
              onChange={(event) => setAnswerValue(event.target.value)}
              disabled={isSubmitting}
              style={{ marginTop: '0.8rem' }}
            />
          )}

          <div className="row-wrap" style={{ marginTop: '0.8rem' }}>
            <button
              className="btn primary"
              type="button"
              onClick={() => submitAttempt({ timedOut: false })}
              disabled={isSubmitting || !answerValue.trim()}
            >
              {isSubmitting ? 'Submitting...' : 'Submit answer'}
            </button>
          </div>
        </article>
      )}

      {finishSummary && (
        <article className="panel">
          <h2>Session Summary</h2>
          <div className="metric-grid" style={{ marginTop: '0.6rem' }}>
            <div className="metric-card">
              <p>Overall Score</p>
              <h3>{Math.round(finishSummary.overall_score || 0)}%</h3>
            </div>
            <div className="metric-card">
              <p>Correct Questions</p>
              <h3>
                {finishSummary.correct_questions}/{finishSummary.total_questions}
              </h3>
            </div>
            <div className="metric-card">
              <p>Total Answer Time</p>
              <h3>{Math.round((finishSummary.total_time_seconds || 0) / 60)} min</h3>
            </div>
            <div className="metric-card">
              <p>Session Duration</p>
              <h3>{Math.round((finishSummary.session_duration_seconds || 0) / 60)} min</h3>
            </div>
          </div>

          <div className="card-grid two" style={{ marginTop: '0.8rem' }}>
            <div>
              <h3>Strengths</h3>
              <ul className="flat-list compact">
                {(finishSummary.strengths || []).map((row) => (
                  <li key={row.id || row.subtopic_id}>{Math.round((row.adjusted_mastery || 0) * 100)}% adjusted mastery</li>
                ))}
              </ul>
            </div>
            <div>
              <h3>Weaknesses</h3>
              <ul className="flat-list compact">
                {(finishSummary.weaknesses || []).map((row) => (
                  <li key={row.id || row.subtopic_id}>{Math.round((row.adjusted_mastery || 0) * 100)}% adjusted mastery</li>
                ))}
              </ul>
            </div>
          </div>
        </article>
      )}
    </section>
  )
}
