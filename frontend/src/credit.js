/**
 * Panel authorship credit.
 *
 * The text and LinkedIn URL are NOT in this file — they come from the backend
 * (/api/meta, see backend/app/credit.py) at runtime, so the built JS bundle
 * contains no copy of them to edit.
 *
 * The element is appended to <body>, deliberately OUTSIDE React's #root: route
 * changes and re-renders never touch it, and React never fights the observer
 * below over the same nodes. A MutationObserver watches for its removal and a
 * slow interval acts as a backstop, so deleting it from devtools or hiding it
 * with inline styles only lasts until the next tick.
 */
const NODE_ID = 'sh-credit'
const POLL_MS = 2000

const SHELL_STYLE = [
  'position:fixed',
  'right:14px',
  'bottom:12px',
  'z-index:2147483647',
  "font:500 11px/1.5 ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif",
  'letter-spacing:.02em',
  'color:#94a3b8',
  'background:rgba(8,20,17,.78)',
  'border:1px solid rgba(63,227,155,.18)',
  'border-radius:999px',
  'padding:5px 12px',
  'backdrop-filter:blur(6px)',
  '-webkit-backdrop-filter:blur(6px)',
  'white-space:nowrap',
  'box-shadow:0 2px 10px rgba(0,0,0,.3)',
  'pointer-events:auto',
].join(';')

const LINK_STYLE = 'color:#3FE39B;text-decoration:none;font-weight:600'

let data = null
let busy = false

/** (Re)build the contents. Uses text nodes, never innerHTML. */
function fill(el) {
  el.textContent = ''
  el.appendChild(document.createTextNode(`${data.prefix} `))

  const link = document.createElement('a')
  link.href = data.url
  link.target = '_blank'
  link.rel = 'noopener noreferrer'
  link.textContent = data.name
  link.style.cssText = LINK_STYLE
  el.appendChild(link)

  el.appendChild(document.createTextNode(` © ${data.year}`))
}

/** Reassert the styles that keep it on screen. */
function paint(el) {
  el.style.cssText = SHELL_STYLE
  el.style.setProperty('display', 'block', 'important')
  el.style.setProperty('visibility', 'visible', 'important')
  el.style.setProperty('opacity', '1', 'important')
  el.removeAttribute('hidden')
}

/** Put it back if it went missing, or got emptied, or got hidden. */
function ensure() {
  if (!data || busy) return
  busy = true
  try {
    let el = document.getElementById(NODE_ID)
    if (!el || !el.isConnected) {
      el = document.createElement('div')
      el.id = NODE_ID
      fill(el)
      paint(el)
      document.body.appendChild(el)
      watchAttributes(el)
      return
    }
    if (!el.firstChild) fill(el)
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) < 0.4) {
      paint(el)
    }
  } finally {
    busy = false
  }
}

/** Watch the node's own attributes — narrower than observing the whole tree,
 *  which would fire on every React render. */
function watchAttributes(el) {
  new MutationObserver(ensure).observe(el, {
    attributes: true,
    attributeFilter: ['style', 'class', 'hidden'],
    childList: true,
  })
}

export function mountCredit() {
  fetch('/api/meta')
    .then((res) => res.json())
    .then((json) => {
      if (!json?.credit?.name) return
      data = json.credit
      ensure()
      // Our node is a direct child of <body>, so childList alone catches removal.
      new MutationObserver(ensure).observe(document.body, { childList: true })
      setInterval(ensure, POLL_MS)
    })
    .catch(() => {
      /* offline or API down — the panel itself is unusable anyway */
    })
}
