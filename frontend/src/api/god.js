import service from './index'

/**
 * URL of the God View live stream (Server-Sent Events).
 * @param {string} simulationId
 * @param {string} [cursor] - resume position from the last received event id
 */
export const godStreamUrl = (simulationId, cursor) => {
  const base = service.defaults.baseURL || ''
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return `${base}/api/god/${encodeURIComponent(simulationId)}/stream${query}`
}

/* Interventions. Each returns the audit entry the backend recorded. */

const god = (simulationId, path) => `/api/god/${encodeURIComponent(simulationId)}/${path}`

export const godPause = (simulationId) => service.post(god(simulationId, 'pause'))
export const godResume = (simulationId) => service.post(god(simulationId, 'resume'))
export const godStep = (simulationId) => service.post(god(simulationId, 'step'))

/** @param {Object} data - { text, agent_id?, platform? } */
export const godInject = (simulationId, data) => service.post(god(simulationId, 'inject'), data)

/** @param {Object} data - { agent_id, text, platform? } */
export const godWhisper = (simulationId, data) => service.post(god(simulationId, 'whisper'), data)

/** @param {Object} data - { agent_id, question, platform? } */
export const godInterview = (simulationId, data) => service.post(god(simulationId, 'interview'), data)

/** @param {Object} data - { question, options?, agent_ids?, platform? } */
export const godPoll = (simulationId, data) =>
  service.post(god(simulationId, 'poll'), data, { timeout: 660000 })

export const godReport = (simulationId) => service.post(god(simulationId, 'report'))

/** One agent's working memory, read from the running simulation process. */
export const getAgentMemory = (simulationId, agentId) =>
  service.get(god(simulationId, `agents/${agentId}/memory`))

/* Branches. */

/** Branch the world at the current round. @param {string} name */
export const godFork = (simulationId, name) => service.post(god(simulationId, 'fork'), { name })

/** The base run and every fork in this simulation's family. */
export const getBranches = (simulationId) => service.get(god(simulationId, 'branches'))

/** Compare two branches by name ('base' is the original run). */
export const getBranchDiff = (simulationId, a, b) =>
  service.get(god(simulationId, 'diff'), { params: { a, b } })
