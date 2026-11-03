import api, { errorMessage } from '../api/client'

/**
 * Open the code editor (code-server at /ide/) in a new tab, on a project or
 * website folder. The tab is opened first (so the popup blocker allows it),
 * then pointed at the link the panel returns after setting the editor cookie.
 *
 * target: { kind: 'project' | 'website', name, sub?: 'dashboard' | 'code' | … }
 *         or nothing for the whole projects folder.
 */
export async function openInEditor(target = {}) {
  const tab = window.open('about:blank', '_blank')
  try {
    const params = {}
    if (target.kind) { params.kind = target.kind; params.name = target.name }
    if (target.sub) params.sub = target.sub
    const res = await api.post('/code/session', null, { params })
    if (tab) tab.location.href = res.data.url
    else window.location.href = res.data.url
  } catch (err) {
    if (tab) tab.close()
    alert(`Couldn't open the editor: ${errorMessage(err)}`)
  }
}
