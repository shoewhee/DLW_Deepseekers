import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'

export default function TopicsPage({ userId }) {
  const [topics, setTopics] = useState([])
  const [activeSubtopicForNotes, setActiveSubtopicForNotes] = useState('')
  const [activeSubtopicForQuestions, setActiveSubtopicForQuestions] = useState('')
  const [notes, setNotes] = useState([])
  const [questions, setQuestions] = useState([])
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')

  const [topicForm, setTopicForm] = useState({ title: '', description: '', importance: 'medium' })
  const [ingestForm, setIngestForm] = useState({ title: '', importance: 'medium', file: null })
  const [isIngesting, setIsIngesting] = useState(false)
  const [subtopicForms, setSubtopicForms] = useState({})
  const [noteForm, setNoteForm] = useState({ title: '', body_md: '', source_url: '' })
  const [questionForm, setQuestionForm] = useState({
    prompt: '',
    difficulty: 'basic',
    format: 'mcq',
    intent: 'concept',
    options: ['Option A', 'Option B', 'Option C', 'Option D'],
    correct_answer: 'Option A',
  })
  const [generationCount, setGenerationCount] = useState(6)

  const [editingTopicId, setEditingTopicId] = useState('')
  const [editingTopicForm, setEditingTopicForm] = useState({ title: '', description: '', importance: 'medium' })

  const [editingSubtopicId, setEditingSubtopicId] = useState('')
  const [editingSubtopicForm, setEditingSubtopicForm] = useState({ title: '', description: '', exam_weight: 1 })

  const allSubtopics = useMemo(
    () =>
      topics.flatMap((topic) =>
        (topic.subtopics || []).map((subtopic) => ({
          ...subtopic,
          main_topic_title: topic.title,
        })),
      ),
    [topics],
  )

  const refreshTopics = async () => {
    const data = await api.getTopics(userId)
    setTopics(data)
  }

  useEffect(() => {
    refreshTopics().catch((err) => setError(err.message || 'Unable to load topics'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  const handleCreateTopic = async (event) => {
    event.preventDefault()
    try {
      setError('')
      setStatus('')
      await api.createTopic({ ...topicForm, user_id: userId })
      setTopicForm({ title: '', description: '', importance: 'medium' })
      await refreshTopics()
      setStatus('Topic added')
    } catch (err) {
      setError(err.message || 'Unable to create topic')
    }
  }

  const startEditTopic = (topic) => {
    setEditingTopicId(topic.id)
    setEditingTopicForm({
      title: topic.title || '',
      description: topic.description || '',
      importance: topic.importance || 'medium',
    })
  }

  const saveTopicEdit = async () => {
    try {
      setError('')
      setStatus('')
      await api.updateTopic(editingTopicId, {
        user_id: userId,
        ...editingTopicForm,
      })
      setEditingTopicId('')
      await refreshTopics()
      setStatus('Topic updated')
    } catch (err) {
      setError(err.message || 'Unable to update topic')
    }
  }

  const handleIngestTopicPdf = async (event) => {
    event.preventDefault()
    const formElement = event.currentTarget
    if (!ingestForm.file) {
      setError('Please choose a PDF file to import')
      return
    }

    try {
      setError('')
      setStatus('Extracting PDF text and asking AI to split into subtopics...')
      setIsIngesting(true)

      const result = await api.ingestTopicPdf({
        user_id: userId,
        title: ingestForm.title,
        file: ingestForm.file,
        importance: ingestForm.importance,
      })

      formElement.reset()
      setIngestForm({ title: '', importance: 'medium', file: null })
      await refreshTopics()
      setStatus(
        `AI imported ${result.subtopics_created || 0} subtopics and ${result.concepts_captured || 0} concepts.`,
      )
    } catch (err) {
      setError(err.message || 'Unable to import topic from PDF')
    } finally {
      setIsIngesting(false)
    }
  }

  const handleCreateSubtopic = async (event, topicId) => {
    event.preventDefault()
    const payload = subtopicForms[topicId]
    if (!payload?.title) return

    try {
      setError('')
      setStatus('')
      await api.createSubtopic(topicId, {
        user_id: userId,
        title: payload.title,
        description: payload.description || '',
        exam_weight: Number(payload.exam_weight || 1),
      })
      setSubtopicForms((prev) => ({ ...prev, [topicId]: { title: '', description: '', exam_weight: 1 } }))
      await refreshTopics()
      setStatus('Subtopic added')
    } catch (err) {
      setError(err.message || 'Unable to create subtopic')
    }
  }

  const startEditSubtopic = (subtopic) => {
    setEditingSubtopicId(subtopic.id)
    setEditingSubtopicForm({
      title: subtopic.title || '',
      description: subtopic.description || '',
      exam_weight: subtopic.exam_weight || 1,
    })
  }

  const saveSubtopicEdit = async () => {
    try {
      setError('')
      setStatus('')
      await api.updateSubtopic(editingSubtopicId, {
        user_id: userId,
        ...editingSubtopicForm,
        exam_weight: Number(editingSubtopicForm.exam_weight || 1),
      })
      setEditingSubtopicId('')
      await refreshTopics()
      setStatus('Subtopic updated')
    } catch (err) {
      setError(err.message || 'Unable to update subtopic')
    }
  }

  const openNotes = async (subtopicId) => {
    setActiveSubtopicForNotes(subtopicId)
    try {
      const noteRows = await api.getNotes(subtopicId, userId)
      setNotes(noteRows)
    } catch (err) {
      setError(err.message || 'Unable to load notes')
    }
  }

  const openQuestions = async (subtopicId) => {
    setActiveSubtopicForQuestions(subtopicId)
    try {
      const rows = await api.getQuestions(subtopicId, userId)
      setQuestions(rows)
    } catch (err) {
      setError(err.message || 'Unable to load questions')
    }
  }

  const handleCreateNote = async (event) => {
    event.preventDefault()
    if (!activeSubtopicForNotes) return

    try {
      setError('')
      setStatus('')
      await api.createNote(activeSubtopicForNotes, {
        user_id: userId,
        ...noteForm,
      })
      setNoteForm({ title: '', body_md: '', source_url: '' })
      await openNotes(activeSubtopicForNotes)
      setStatus('Note saved')
    } catch (err) {
      setError(err.message || 'Unable to create note')
    }
  }

  const updateQuestionOption = (index, value) => {
    setQuestionForm((prev) => {
      const next = [...prev.options]
      next[index] = value
      return { ...prev, options: next }
    })
  }

  const addQuestionOption = () => {
    setQuestionForm((prev) => ({
      ...prev,
      options: [...prev.options, `Option ${String.fromCharCode(65 + prev.options.length)}`],
    }))
  }

  const removeQuestionOption = (index) => {
    setQuestionForm((prev) => {
      if (prev.options.length <= 2) return prev
      const next = prev.options.filter((_, idx) => idx !== index)
      const nextCorrect = next.includes(prev.correct_answer) ? prev.correct_answer : next[0]
      return {
        ...prev,
        options: next,
        correct_answer: nextCorrect,
      }
    })
  }

  const handleCreateQuestion = async (event) => {
    event.preventDefault()
    if (!activeSubtopicForQuestions) return

    try {
      setError('')
      setStatus('')

      const payload = {
        user_id: userId,
        prompt: questionForm.prompt,
        difficulty: questionForm.difficulty,
        format: questionForm.format,
        intent: questionForm.intent,
        correct_answer: questionForm.correct_answer,
      }

      if (questionForm.format === 'mcq') {
        payload.options = questionForm.options
      }

      await api.createQuestion(activeSubtopicForQuestions, payload)

      setQuestionForm((prev) => ({
        ...prev,
        prompt: '',
        correct_answer: prev.format === 'mcq' ? prev.options[0] : '',
      }))
      await openQuestions(activeSubtopicForQuestions)
      setStatus('Question added')
    } catch (err) {
      setError(err.message || 'Unable to create question')
    }
  }

  const handleGenerateQuestions = async () => {
    if (!activeSubtopicForQuestions) return
    try {
      setError('')
      setStatus('Generating AI questions...')
      const result = await api.generateQuestions(activeSubtopicForQuestions, {
        user_id: userId,
        count: Number(generationCount || 6),
      })
      await openQuestions(activeSubtopicForQuestions)
      setStatus(`Generated ${result.questions?.length || 0} questions using ${result.generated_by}`)
    } catch (err) {
      setError(err.message || 'Unable to generate questions')
      setStatus('')
    }
  }

  const activeSubtopicMeta = allSubtopics.find((item) => item.id === activeSubtopicForQuestions)

  return (
    <section className="page-stack">
      <div>
        <h1>Topics, Subtopics, and Notes</h1>
      </div>

      {error && <p className="error-text">{error}</p>}
      {status && <p className="success-text">{status}</p>}

      <article className="panel">
        <h2>Create Main Topic</h2>
        <form className="grid-form" onSubmit={handleCreateTopic}>
          <input
            placeholder="Main topic title"
            value={topicForm.title}
            onChange={(event) => setTopicForm((prev) => ({ ...prev, title: event.target.value }))}
            required
          />
          <input
            placeholder="Description"
            value={topicForm.description}
            onChange={(event) => setTopicForm((prev) => ({ ...prev, description: event.target.value }))}
          />
          <select
            value={topicForm.importance}
            onChange={(event) => setTopicForm((prev) => ({ ...prev, importance: event.target.value }))}
          >
            <option value="low">Low importance</option>
            <option value="medium">Medium importance</option>
            <option value="high">High importance</option>
          </select>
          <button className="btn primary" type="submit">
            Add topic
          </button>
        </form>
      </article>

      <article className="panel">
        <h2>Import Topic From PDF</h2>
        <p className="muted">
          Upload lecture notes or textbook pages. AI reads the document text and splits it into subtopics and concept
          notes.
        </p>
        <form className="grid-form" onSubmit={handleIngestTopicPdf}>
          <input
            placeholder="Main topic title"
            value={ingestForm.title}
            onChange={(event) => setIngestForm((prev) => ({ ...prev, title: event.target.value }))}
            required
          />
          <select
            value={ingestForm.importance}
            onChange={(event) => setIngestForm((prev) => ({ ...prev, importance: event.target.value }))}
          >
            <option value="low">Low importance</option>
            <option value="medium">Medium importance</option>
            <option value="high">High importance</option>
          </select>
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={(event) =>
              setIngestForm((prev) => ({
                ...prev,
                file: event.target.files?.[0] || null,
              }))
            }
            required
          />
          <button className="btn primary" type="submit" disabled={isIngesting}>
            {isIngesting ? 'Importing...' : 'Import from PDF'}
          </button>
        </form>
      </article>

      <div className="card-grid">
        {topics.map((topic) => (
          <article className="panel" key={topic.id}>
            {editingTopicId === topic.id ? (
              <div className="grid-form">
                <input
                  value={editingTopicForm.title}
                  onChange={(event) => setEditingTopicForm((prev) => ({ ...prev, title: event.target.value }))}
                />
                <input
                  value={editingTopicForm.description}
                  onChange={(event) => setEditingTopicForm((prev) => ({ ...prev, description: event.target.value }))}
                />
                <select
                  value={editingTopicForm.importance}
                  onChange={(event) => setEditingTopicForm((prev) => ({ ...prev, importance: event.target.value }))}
                >
                  <option value="low">Low importance</option>
                  <option value="medium">Medium importance</option>
                  <option value="high">High importance</option>
                </select>
                <div className="row-wrap">
                  <button className="btn primary small" type="button" onClick={saveTopicEdit}>
                    Save topic
                  </button>
                  <button className="btn small" type="button" onClick={() => setEditingTopicId('')}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="row-between">
                  <h2>{topic.title}</h2>
                  <button className="btn small" type="button" onClick={() => startEditTopic(topic)}>
                    Edit topic
                  </button>
                </div>
                <p className="muted">{topic.description || 'No description'}</p>
                <p className="pill">Importance: {topic.importance}</p>
              </>
            )}

            <ul className="flat-list">
              {topic.subtopics?.map((subtopic) => (
                <li key={subtopic.id}>
                  {editingSubtopicId === subtopic.id ? (
                    <div className="grid-form">
                      <input
                        value={editingSubtopicForm.title}
                        onChange={(event) =>
                          setEditingSubtopicForm((prev) => ({
                            ...prev,
                            title: event.target.value,
                          }))
                        }
                      />
                      <input
                        value={editingSubtopicForm.description}
                        onChange={(event) =>
                          setEditingSubtopicForm((prev) => ({
                            ...prev,
                            description: event.target.value,
                          }))
                        }
                      />
                      <input
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={editingSubtopicForm.exam_weight}
                        onChange={(event) =>
                          setEditingSubtopicForm((prev) => ({
                            ...prev,
                            exam_weight: event.target.value,
                          }))
                        }
                      />
                      <div className="row-wrap">
                        <button className="btn primary small" type="button" onClick={saveSubtopicEdit}>
                          Save subtopic
                        </button>
                        <button className="btn small" type="button" onClick={() => setEditingSubtopicId('')}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="row-between">
                      <div>
                        <strong>{subtopic.title}</strong>
                        <p className="muted">Exam weight: {subtopic.exam_weight}</p>
                        {subtopic.latest_mastery && (
                          <p className="muted">
                            Adjusted mastery: {Math.round(subtopic.latest_mastery.adjusted_mastery * 100)}% ·
                            Confidence: {Math.round(subtopic.latest_mastery.confidence_score * 100)}%
                          </p>
                        )}
                      </div>
                      <div className="row-wrap">
                        <button className="btn small" type="button" onClick={() => startEditSubtopic(subtopic)}>
                          Edit
                        </button>
                        <button className="btn small" type="button" onClick={() => openNotes(subtopic.id)}>
                          Notes
                        </button>
                        <button className="btn small" type="button" onClick={() => openQuestions(subtopic.id)}>
                          Questions
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ul>

            <form className="grid-form" onSubmit={(event) => handleCreateSubtopic(event, topic.id)}>
              <input
                placeholder="Subtopic title"
                required
                value={subtopicForms[topic.id]?.title || ''}
                onChange={(event) =>
                  setSubtopicForms((prev) => ({
                    ...prev,
                    [topic.id]: {
                      ...prev[topic.id],
                      title: event.target.value,
                    },
                  }))
                }
              />
              <input
                placeholder="Description"
                value={subtopicForms[topic.id]?.description || ''}
                onChange={(event) =>
                  setSubtopicForms((prev) => ({
                    ...prev,
                    [topic.id]: {
                      ...prev[topic.id],
                      description: event.target.value,
                    },
                  }))
                }
              />
              <input
                type="number"
                min="0.1"
                step="0.1"
                placeholder="Exam weight"
                value={subtopicForms[topic.id]?.exam_weight || 1}
                onChange={(event) =>
                  setSubtopicForms((prev) => ({
                    ...prev,
                    [topic.id]: {
                      ...prev[topic.id],
                      exam_weight: event.target.value,
                    },
                  }))
                }
              />
              <button className="btn" type="submit">
                Add subtopic
              </button>
            </form>
          </article>
        ))}
      </div>

      {activeSubtopicForNotes && (
        <article className="panel">
          <h2>Subtopic Notes</h2>
          <form className="grid-form" onSubmit={handleCreateNote}>
            <input
              placeholder="Note title"
              value={noteForm.title}
              onChange={(event) => setNoteForm((prev) => ({ ...prev, title: event.target.value }))}
              required
            />
            <input
              placeholder="Source URL (optional)"
              value={noteForm.source_url}
              onChange={(event) => setNoteForm((prev) => ({ ...prev, source_url: event.target.value }))}
            />
            <textarea
              placeholder="Markdown note body"
              value={noteForm.body_md}
              onChange={(event) => setNoteForm((prev) => ({ ...prev, body_md: event.target.value }))}
              required
              rows={4}
            />
            <button className="btn primary" type="submit">
              Save note
            </button>
          </form>

          <ul className="flat-list">
            {notes.map((note) => (
              <li key={note.id}>
                <strong>{note.title}</strong>
                <p className="muted">{note.body_md}</p>
                {note.source_url && (
                  <a href={note.source_url} target="_blank" rel="noreferrer">
                    {note.source_url}
                  </a>
                )}
              </li>
            ))}
          </ul>
        </article>
      )}

      {activeSubtopicForQuestions && (
        <article className="panel">
          <div className="row-between">
            <div>
              <h2>Question Bank</h2>
              {activeSubtopicMeta && (
                <p className="muted">
                  {activeSubtopicMeta.main_topic_title} · {activeSubtopicMeta.title}
                </p>
              )}
            </div>
            <div className="row-wrap">
              <input
                type="number"
                min="1"
                max="20"
                value={generationCount}
                onChange={(event) => setGenerationCount(event.target.value)}
                style={{ width: '90px' }}
              />
              <button className="btn ghost" type="button" onClick={handleGenerateQuestions}>
                Generate with AI
              </button>
            </div>
          </div>

          <form className="grid-form" onSubmit={handleCreateQuestion}>
            <textarea
              placeholder="Question prompt"
              value={questionForm.prompt}
              onChange={(event) => setQuestionForm((prev) => ({ ...prev, prompt: event.target.value }))}
              required
              rows={3}
            />
            <select
              value={questionForm.difficulty}
              onChange={(event) => setQuestionForm((prev) => ({ ...prev, difficulty: event.target.value }))}
            >
              <option value="basic">Basic</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
            <select
              value={questionForm.format}
              onChange={(event) =>
                setQuestionForm((prev) => ({
                  ...prev,
                  format: event.target.value,
                  correct_answer: event.target.value === 'mcq' ? prev.options[0] : '',
                }))
              }
            >
              <option value="mcq">MCQ</option>
              <option value="open_ended">Open ended</option>
            </select>
            <select
              value={questionForm.intent}
              onChange={(event) => setQuestionForm((prev) => ({ ...prev, intent: event.target.value }))}
            >
              <option value="concept">Concept</option>
              <option value="application">Application</option>
            </select>

            {questionForm.format === 'mcq' ? (
              <>
                <div className="panel-subtle">
                  <strong>MCQ Options</strong>
                  <div className="flat-list compact">
                    {questionForm.options.map((option, index) => (
                      <div className="row-wrap" key={`opt-${index}`}>
                        <input
                          value={option}
                          onChange={(event) => updateQuestionOption(index, event.target.value)}
                          placeholder={`Option ${index + 1}`}
                        />
                        <button className="btn small" type="button" onClick={() => removeQuestionOption(index)}>
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="row-wrap" style={{ marginTop: '0.5rem' }}>
                    <button className="btn small" type="button" onClick={addQuestionOption}>
                      Add option
                    </button>
                    <select
                      value={questionForm.correct_answer}
                      onChange={(event) => setQuestionForm((prev) => ({ ...prev, correct_answer: event.target.value }))}
                    >
                      {questionForm.options.map((option, index) => (
                        <option key={`correct-${index}`} value={option}>
                          Correct: {option}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </>
            ) : (
              <textarea
                placeholder="Reference correct answer"
                value={questionForm.correct_answer}
                onChange={(event) => setQuestionForm((prev) => ({ ...prev, correct_answer: event.target.value }))}
                rows={3}
                required
              />
            )}

            <button className="btn primary" type="submit">
              Add question
            </button>
          </form>

          <ul className="flat-list" style={{ marginTop: '0.8rem' }}>
            {questions.map((question) => (
              <li key={question.id}>
                <strong>{question.prompt}</strong>
                <p className="muted">
                  {question.difficulty} · {question.format} · {question.intent} · expected {question.expected_seconds}s
                </p>
                {question.format === 'mcq' && question.options?.length > 0 && (
                  <p className="muted">Options: {question.options.join(' | ')}</p>
                )}
                <p className="muted">Answer key: {question.correct_answer}</p>
              </li>
            ))}
          </ul>
        </article>
      )}
    </section>
  )
}
