export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  })

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent('fa:unauthorized'))
    throw new ApiError('登录状态已失效，请重新登录', 401)
  }

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new ApiError(data.detail || data.message || response.statusText, response.status)
  }
  return data
}

export const api = {
  get: (path) => request(path),
  post: (path, body = {}) => request(path, { method: 'POST', body }),
  put: (path, body = {}) => request(path, { method: 'PUT', body }),
  del: (path) => request(path, { method: 'DELETE' }),
}
