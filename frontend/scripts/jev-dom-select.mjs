import { choice, noul, TypeSafeClient } from '@typesafe-ai/sdk'

const client = new TypeSafeClient()

function textOf(element) {
  return String(element.textContent || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120)
}

function labelOf(element) {
  return textOf(element)
    || element.getAttribute('aria-label')
    || element.getAttribute('placeholder')
    || element.getAttribute('title')
    || element.value
    || element.name
    || element.tagName.toLowerCase()
}

function locatorOf(element) {
  if (element.id) return `#${CSS.escape(element.id)}`
  if (element.getAttribute('data-jev-id')) return `[data-jev-id="${element.getAttribute('data-jev-id')}"]`

  const path = []
  let current = element
  while (current && current.nodeType === Node.ELEMENT_NODE && path.length < 5) {
    const tag = current.tagName.toLowerCase()
    const parent = current.parentElement
    if (!parent) break
    const peers = [...parent.children].filter((item) => item.tagName === current.tagName)
    path.unshift(peers.length > 1 ? `${tag}:nth-of-type(${peers.indexOf(current) + 1})` : tag)
    current = parent
  }
  return path.join(' > ')
}

export async function readDomCandidates(page, limit = 80) {
  return page.evaluate((maxCandidates) => {
    const selector = [
      'a[href]',
      'button',
      'input',
      'select',
      'textarea',
      'label',
      '[role="button"]',
      '[role="combobox"]',
      '[role="option"]',
      '[role="menuitem"]',
      '[role="switch"]',
      '[role="checkbox"]',
      '.el-checkbox',
      '.el-switch',
      '.el-select__wrapper',
      '.el-radio-button__inner',
    ].join(',')

    return [...document.querySelectorAll(selector)]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && rect.width >= 4
          && rect.height >= 4
          && rect.bottom >= 0
          && rect.right >= 0
          && rect.top <= innerHeight
          && rect.left <= innerWidth
      })
      .slice(0, maxCandidates)
      .map((element, index) => {
        const id = `c${index}`
        element.setAttribute('data-jev-id', id)
        const rect = element.getBoundingClientRect()
        const text = String(element.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120)
        return {
          id,
          tag: element.tagName.toLowerCase(),
          type: element.getAttribute('type') || element.type || '',
          role: element.getAttribute('role') || '',
          text,
          label: text
            || element.getAttribute('aria-label')
            || element.getAttribute('placeholder')
            || element.getAttribute('title')
            || String(element.value || '')
            || element.tagName.toLowerCase(),
          ariaLabel: element.getAttribute('aria-label') || '',
          placeholder: element.getAttribute('placeholder') || '',
          value: String(element.value ?? '').slice(0, 120),
          disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
          css: element.className && typeof element.className === 'string' ? element.className.slice(0, 180) : '',
          rect: {
            x: Math.round(rect.x + rect.width / 2),
            y: Math.round(rect.y + rect.height / 2),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          },
        }
      })
  }, limit)
}

export async function jevSelect(page, goal, options = {}) {
  const candidates = await readDomCandidates(page, options.limit || 80)
  if (!candidates.length) throw new Error('Jev selection failed: no visible DOM candidates')

  const destructive = /delete|remove|logout|prune|清空|删除|退出|立即清理/i.test(goal)
  const threshold = options.threshold ?? (destructive ? 0.92 : 0.75)
  const response = await client.systemOne({
    model: 'jev-latest',
    state: {
      goal,
      page: {
        url: await page.url(),
        title: await page.title(),
        viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight })),
      },
      rule: 'Choose exactly one visible interactive element. Choose none only when no candidate satisfies the goal.',
      candidates,
    },
    questions: {
      element: choice('Which candidate should be activated for `goal`?', {
        none: 'No visible candidate satisfies the goal.',
        ...Object.fromEntries(candidates.map((candidate) => [candidate.id, candidate])),
      }),
      targetPresent: noul('Does the page visibly contain an interactive element satisfying `goal`?', {
        true: 'At least one listed candidate clearly satisfies the goal.',
        false: 'No listed candidate satisfies the goal.',
      }),
    },
  })

  const selectedId = response.answers.element.choice
  const present = response.answers.targetPresent.noul
  const confidence = response.answers.element.confidence
  const selected = candidates.find((candidate) => candidate.id === selectedId)

  if (present < 0.7 || selectedId === 'none' || !selected) {
    throw new Error(`Jev selection failed: no confident match (goal=${goal}, noul=${present.toFixed(2)})`)
  }
  if (confidence < threshold) {
    throw new Error(`Jev selection stopped: confidence ${confidence.toFixed(2)} < ${threshold} (goal=${goal})`)
  }
  if (selected.disabled) {
    throw new Error(`Jev selection stopped: candidate is disabled (goal=${goal}, id=${selected.id})`)
  }

  if (options.click === false) {
    return { selected, confidence, probabilities: response.answers.element.probabilities }
  }

  const point = await page.evaluate((id) => {
    const element = document.querySelector(`[data-jev-id="${id}"]`)
    if (!element) return null
    const rect = element.getBoundingClientRect()
    return {
      x: Math.round(rect.x + rect.width / 2),
      y: Math.round(rect.y + rect.height / 2),
    }
  }, selected.id)
  if (!point) throw new Error(`Jev selection failed: selected element disappeared (${selected.id})`)

  await page.mouse.click(point.x, point.y, { label: `Jev select: ${goal}` })
  return {
    selected,
    confidence,
    probabilities: response.answers.element.probabilities,
    point,
    threshold,
  }
}

export async function jevClick(page, goal, options = {}) {
  const result = await jevSelect(page, goal, options)
  return result.selected
}

if (process.env.JEV_GOAL) {
  const spaceInput = process.env.EGO_SPACE
  if (typeof globalThis.taskSpace !== 'function') {
    throw new Error('JEV_GOAL requires the ego-browser taskSpace global')
  }
  const task = await globalThis.taskSpace(
    spaceInput && /^\d+$/.test(spaceInput) ? Number(spaceInput) : spaceInput || 'jev dom selection',
  )
  const page = task.page(process.env.EGO_PAGE || 'p1')
  const result = await jevSelect(page, process.env.JEV_GOAL, {
    click: process.env.JEV_CLICK !== 'false',
    threshold: process.env.JEV_THRESHOLD ? Number(process.env.JEV_THRESHOLD) : undefined,
    limit: process.env.JEV_LIMIT ? Number(process.env.JEV_LIMIT) : undefined,
  })
  console.log(JSON.stringify(result, null, 2))
}
