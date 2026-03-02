const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('Unable to read file'))
        return
      }
      const parts = reader.result.split(',')
      resolve(parts.length > 1 ? parts[1] : parts[0])
    }
    reader.onerror = () => reject(new Error('Unable to read file'))
    reader.readAsDataURL(file)
  })
}

function withQueryParams(path, params = {}) {
  const url = new URL(`${API_BASE_URL}${path}`)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value)
    }
  })
  return url.toString()
}

async function request(path, { method = 'GET', params, body } = {}) {
  const url = withQueryParams(path, params)
  const headers = {}
  let requestBody

  if (body instanceof FormData) {
    requestBody = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    requestBody = JSON.stringify(body)
  }

  const response = await fetch(url, {
    method,
    headers,
    body: requestBody,
  })

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const payload = isJson ? await response.json() : await response.text()

  if (!response.ok) {
    const detail = typeof payload === 'object' ? payload.detail || JSON.stringify(payload) : payload
    throw new Error(detail || `Request failed with status ${response.status}`)
  }

  return payload
}

export const api = {
  getHealth: () => request('/health'),

  signup: (payload) => request('/auth/signup', { method: 'POST', body: payload }),
  login: (payload) => request('/auth/login', { method: 'POST', body: payload }),

  getTopics: (userId) => request('/topics', { params: { user_id: userId } }),
  createTopic: (payload) => request('/topics', { method: 'POST', body: payload }),
  ingestTopicPdf: async ({ user_id, title, file, importance = 'medium' }) => {
    if (!file) {
      throw new Error('Please select a PDF file')
    }

    const file_base64 = await readFileAsBase64(file)
    return request('/topics/ingest', {
      method: 'POST',
      body: {
        user_id,
        title,
        importance,
        file_name: file.name || 'uploaded.pdf',
        file_base64,
      },
    })
  },
  updateTopic: (topicId, payload) => request(`/topics/${topicId}`, { method: 'PATCH', body: payload }),
  createSubtopic: (topicId, payload) => request(`/topics/${topicId}/subtopics`, { method: 'POST', body: payload }),
  updateSubtopic: (subtopicId, payload) => request(`/topics/subtopics/${subtopicId}`, { method: 'PATCH', body: payload }),
  getNotes: (subtopicId, userId) => request(`/topics/subtopics/${subtopicId}/notes`, { params: { user_id: userId } }),
  createNote: (subtopicId, payload) => request(`/topics/subtopics/${subtopicId}/notes`, { method: 'POST', body: payload }),
  getQuestions: (subtopicId, userId) =>
    request(`/topics/subtopics/${subtopicId}/questions`, { params: { user_id: userId } }),
  createQuestion: (subtopicId, payload) =>
    request(`/topics/subtopics/${subtopicId}/questions`, { method: 'POST', body: payload }),
  generateQuestions: (subtopicId, payload) =>
    request(`/topics/subtopics/${subtopicId}/questions/generate`, { method: 'POST', body: payload }),

  startSession: (payload) => request('/quiz/sessions/start', { method: 'POST', body: payload }),
  getSession: (sessionId, userId) => request(`/quiz/sessions/${sessionId}`, { params: { user_id: userId } }),
  submitAttempt: (sessionId, payload) => request(`/quiz/sessions/${sessionId}/attempt`, { method: 'POST', body: payload }),
  finishSession: (sessionId, payload) => request(`/quiz/sessions/${sessionId}/finish`, { method: 'POST', body: payload }),

  getDashboardSummary: (userId) => request('/dashboard/summary', { params: { user_id: userId } }),
  getDashboardTrends: (userId, days = 14) =>
    request('/dashboard/trends', { params: { user_id: userId, days } }),
  getDashboardMistakePatterns: (userId, { topicId, subtopicId } = {}) =>
    request('/dashboard/mistake-patterns', {
      params: { user_id: userId, topic_id: topicId, subtopic_id: subtopicId },
    }),

  getReportOverview: (userId) => request('/reports/overview', { params: { user_id: userId } }),
  getTopicReport: (topicId, userId) => request(`/reports/topic/${topicId}`, { params: { user_id: userId } }),

  generatePlan: (payload) => request('/planner/generate', { method: 'POST', body: payload }),
}
