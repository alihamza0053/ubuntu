import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'
import StatusBadge from '../components/StatusBadge'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import Tabs from '../components/ui/Tabs'
import { useAuth } from '../context/AuthContext'
import { appUrl } from '../lib/appUrl'

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'screen', label: 'Screen' },      // desktop apps only
  { key: 'models', label: 'Models' },      // API apps (Ollama) only
  { key: 'domain', label: 'Domain & SSL' },
  { key: 'logs', label: 'Logs' },
]

function tabsFor(app) {
  return TABS.filter((t) =>
    (t.key !== 'screen' || app.kind === 'desktop') &&
    (t.key !== 'models' || app.kind === 'api'))
}

const KIND_LABEL = {
  desktop: 'Browser on a virtual display (noVNC)',
  web: 'Web service',
  api: 'API only (key-protected, no web page)',
}

/** Public base URL of an API app, or null until a domain is assigned. */
function apiBase(app) {
  return app.domain ? `${app.ssl ? 'https' : 'http'}://${app.domain}` : null
}

function formatBytes(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1)
  return `${(n / 1024 ** i).toFixed(i >= 3 ? 1 : 0)} ${units[i]}`
}

export default function AppDetail() {
  const { key } = useParams()
  const { isAdmin } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [app, setApp] = useState(null)
  const [msg, setMsg] = useState('')

  const refresh = useCallback(() => {
    api.get(`/apps/${key}`).then((res) => setApp(res.data)).catch(() => setApp(null))
  }, [key])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function action(name) {
    setMsg('')
    try {
      const res = await api.post(`/apps/${key}/action/${name}`)
      setMsg(res.data.detail || `${name} ${key}`)
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function uninstall() {
    const deleteData = window.confirm(
      `Remove ${app.label}?\n\nOK = also delete its data (browser profile / workflows)\n` +
      'Cancel = keep the data so a re-install picks up where you left off',
    )
    try {
      const res = await api.delete(`/apps/${key}`, { params: { delete_data: deleteData } })
      setMsg(res.data.detail)
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  if (!app) return <div className="empty-state">Loading…</div>

  const installed = app.install_state === 'INSTALLED'
  const tab = searchParams.get('tab') || 'overview'
  const openUrl = appUrl(app)

  return (
    <div className="space-y-5">
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            <span className="text-xl">{app.icon}</span>
            {app.label}
          </span>
        }
        crumbs={[{ label: 'Apps', to: '/apps' }, { label: app.label }]}
        actions={
          <>
            {installed && <StatusBadge status={app.status} />}
            {installed && app.status === 'RUNNING' && app.kind !== 'api' && (
              <a href={openUrl} target="_blank" rel="noreferrer" className="btn-secondary">
                <Icon name="external" size={15} />
                Open
              </a>
            )}
            <Link to="/apps" className="btn-secondary">
              <Icon name="arrow-left" size={15} />
              All apps
            </Link>
          </>
        }
      />

      {!installed && (
        <div className="flex items-start gap-2 rounded-xl border border-panel-border bg-panel-card/70 px-4 py-3 text-sm text-slate-400">
          <Icon name="info" size={15} className="mt-0.5 text-mint-400" />
          {app.install_state === 'INSTALLING'
            ? 'Installing right now — the Logs tab shows what the installer is doing.'
            : `${app.label} isn't installed on this server yet. Install it from the Apps page.`}
        </div>
      )}

      <Tabs tabs={tabsFor(app)} active={tab} onChange={(t) => setSearchParams({ tab: t })} />

      {msg && <p className="break-words text-sm text-slate-300">{msg}</p>}

      {tab === 'overview' && (
        <OverviewTab app={app} installed={installed} isAdmin={isAdmin}
          openUrl={openUrl} onAction={action} onUninstall={uninstall}
          onChanged={refresh} setMsg={setMsg} />
      )}
      {tab === 'screen' && <ScreenTab app={app} openUrl={openUrl} />}
      {tab === 'models' && <ModelsTab app={app} isAdmin={isAdmin} />}
      {tab === 'domain' && <DomainTab app={app} onChanged={refresh} />}
      {tab === 'logs' && <LogsTab app={app} />}
    </div>
  )
}

function OverviewTab({ app, installed, isAdmin, openUrl, onAction, onUninstall,
                      onChanged, setMsg }) {
  return (
    <div className="space-y-4 max-w-2xl">
      <div className="card space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h3 className="section-title">Service</h3>
          <div className="flex gap-2 flex-wrap">
            <button className="btn-primary" disabled={!installed}
              onClick={() => onAction('start')}><Icon name="play" size={15} />Start</button>
            <button className="btn-secondary" disabled={!installed}
              onClick={() => onAction('stop')}><Icon name="stop" size={15} />Stop</button>
            <button className="btn-secondary" disabled={!installed}
              onClick={() => onAction('restart')}><Icon name="refresh" size={15} />Restart</button>
          </div>
        </div>

        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-500">Kind</dt>
            <dd>{KIND_LABEL[app.kind] || app.kind}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Port</dt>
            <dd className="font-mono">
              {app.port ?? '—'}
              {app.kind === 'api' && app.port && (
                <span className="text-xs text-slate-500 font-sans"> (127.0.0.1 only — not public)</span>
              )}
            </dd>
          </div>
          {app.kind === 'desktop' && (
            <div className="flex justify-between">
              <dt className="text-slate-500">Display</dt>
              <dd className="font-mono">:{app.display ?? '—'}</dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-slate-500">Domain</dt><dd>{app.domain || '—'}</dd>
          </div>
          {app.kind !== 'api' && (
            <div className="flex justify-between items-center">
              <dt className="text-slate-500">URL</dt>
              <dd>
                {installed
                  ? <a className="text-sky-400 hover:underline break-all" href={openUrl}
                      target="_blank" rel="noreferrer">{openUrl}</a>
                  : '—'}
              </dd>
            </div>
          )}
        </dl>

        <p className="text-xs text-slate-500">{app.notes}</p>
      </div>

      {app.kind === 'api' && installed && (
        <ApiAccess app={app} isAdmin={isAdmin} onChanged={onChanged} setMsg={setMsg} />
      )}

      {app.kind === 'desktop' && installed && (
        <BrowserSettings app={app} onChanged={onChanged} setMsg={setMsg} />
      )}

      {isAdmin && installed && (
        <div className="card space-y-2">
          <h3 className="section-title text-red-300">Remove</h3>
          <p className="text-xs text-slate-500">
            Stops {app.label}, removes its nginx block and uninstalls the packages.
            You choose whether its data goes too.
          </p>
          <button className="btn-secondary text-red-400" onClick={onUninstall}>
            <Icon name="trash" size={15} />Uninstall {app.label}
          </button>
        </div>
      )}
    </div>
  )
}

/** Start page + noVNC password for a browser app. */
function BrowserSettings({ app, onChanged, setMsg }) {
  const [startUrl, setStartUrl] = useState(app.start_url || '')
  const [password, setPassword] = useState(app.vnc_password || '')
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true); setMsg('')
    try {
      const res = await api.put(`/apps/${app.key}/settings`, {
        start_url: startUrl, vnc_password: password,
      })
      setMsg(res.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  return (
    <div className="card space-y-3">
      <h3 className="section-title">Browser settings</h3>
      <div>
        <label className="label">Start page</label>
        <input className="input" value={startUrl} placeholder="https://example.com"
          onChange={(e) => setStartUrl(e.target.value)} />
      </div>
      <div>
        <label className="label">noVNC password</label>
        <input className="input font-mono" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <p className="text-xs text-slate-500 mt-1">
          Typed into noVNC when you open the screen. 6–8 characters — x11vnc ignores
          anything past the eighth.
        </p>
      </div>
      <button className="btn-primary" onClick={save} disabled={busy}>Save</button>
      <p className="text-xs text-slate-500">Restart the app to apply.</p>
    </div>
  )
}

/** The browser's virtual screen, embedded via noVNC. */
function ScreenTab({ app, openUrl }) {
  if (app.install_state !== 'INSTALLED') {
    return <div className="card text-slate-500">Install {app.label} first.</div>
  }
  if (app.status !== 'RUNNING') {
    return (
      <div className="card text-slate-500">
        {app.label} isn&apos;t running — start it from the Overview tab, then come back.
      </div>
    )
  }
  // The panel is usually on https; an http frame inside it is blocked as mixed
  // content and would just render blank, so say what to do instead.
  const mixedContent = window.location.protocol === 'https:' && openUrl.startsWith('http:')

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 flex-wrap text-xs text-slate-500">
        <span>Password: <code className="text-slate-300">{app.vnc_password}</code></span>
        <a href={openUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
          open in a full tab ↗
        </a>
      </div>

      {mixedContent ? (
        <div className="card text-sm text-slate-400 space-y-2">
          <p>
            This panel is on https and {app.label} is only reachable over plain http
            (<code className="text-slate-300">{openUrl}</code>), so your browser won&apos;t
            let it be embedded here.
          </p>
          <p className="text-xs">
            Assign a domain and request SSL on the Domain &amp; SSL tab and the screen
            appears here — or use &ldquo;open in a full tab&rdquo; above in the meantime.
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-lg border border-panel-border overflow-hidden bg-black">
            <iframe title={`${app.label} screen`} src={openUrl}
              className="w-full h-[70vh]" allow="clipboard-read; clipboard-write" />
          </div>
          <p className="text-xs text-slate-500">
            Served straight from the app&apos;s own address, so the frame stays blank if
            that port is firewalled off from your machine — assigning a domain routes it
            through nginx on 80/443 instead.
          </p>
        </>
      )}
    </div>
  )
}

/** Base URL + API key + copy-paste examples for an API app (Ollama). */
function ApiAccess({ app, isAdmin, onChanged, setMsg }) {
  const [show, setShow] = useState(false)
  const [copied, setCopied] = useState('')
  const base = apiBase(app)
  const key = app.api_key || ''
  const shownKey = show ? key : `${key.slice(0, 6)}${'•'.repeat(24)}`

  async function copy(text, what) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(what); setTimeout(() => setCopied(''), 1500)
    } catch { /* clipboard blocked (http) — the text is selectable anyway */ }
  }

  async function regenerate() {
    if (!window.confirm('Create a new API key? The current key stops working immediately — '
      + 'every app or script using it must be updated.')) return
    try {
      const res = await api.post(`/apps/${app.key}/api-key/regenerate`)
      setMsg(res.data.detail)
      setShow(true)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  const host = base || 'https://YOUR-DOMAIN'
  const examples = [
    {
      title: 'curl (Ollama API)',
      code: `curl ${host}/api/generate \\\n  -H "Authorization: Bearer ${show ? key : 'YOUR_API_KEY'}" \\\n  -d '{"model": "llama3.2:3b", "prompt": "Hello!", "stream": false}'`,
    },
    {
      title: 'Python — OpenAI SDK (any OpenAI-compatible tool works the same way)',
      code: `from openai import OpenAI\n\nclient = OpenAI(base_url="${host}/v1", api_key="${show ? key : 'YOUR_API_KEY'}")\nreply = client.chat.completions.create(\n    model="llama3.2:3b",\n    messages=[{"role": "user", "content": "Hello!"}],\n)\nprint(reply.choices[0].message.content)`,
    },
  ]

  return (
    <div className="card space-y-3">
      <h3 className="section-title">API access</h3>
      {!base && (
        <p className="rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-2 text-xs text-yellow-200">
          Assign a domain (Domain &amp; SSL tab) to use the API from outside — until then
          Ollama is reachable only on this server. Request SSL too, so the key isn&apos;t sent
          in plain text.
        </p>
      )}
      {base && !app.ssl && (
        <p className="rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-2 text-xs text-yellow-200">
          No SSL yet — the API key travels unencrypted. Request SSL on the Domain &amp; SSL tab.
        </p>
      )}
      <dl className="space-y-2 text-sm">
        <div className="flex justify-between gap-3 items-center">
          <dt className="text-slate-500 shrink-0">Base URL</dt>
          <dd className="font-mono text-right break-all">
            {base ? <>
              {base}{' '}
              <button className="text-xs text-sky-400 hover:underline" onClick={() => copy(base, 'url')}>
                {copied === 'url' ? 'copied ✓' : 'copy'}
              </button>
            </> : '—'}
          </dd>
        </div>
        <div className="flex justify-between gap-3 items-center">
          <dt className="text-slate-500 shrink-0">OpenAI-compatible</dt>
          <dd className="font-mono text-right break-all">{base ? `${base}/v1` : '—'}</dd>
        </div>
        <div className="flex justify-between gap-3 items-center">
          <dt className="text-slate-500 shrink-0">API key</dt>
          <dd className="font-mono text-right break-all">
            {key ? shownKey : '—'}{' '}
            {key && <>
              <button className="text-xs text-sky-400 hover:underline" onClick={() => setShow(!show)}>
                {show ? 'hide' : 'show'}
              </button>{' '}
              <button className="text-xs text-sky-400 hover:underline" onClick={() => copy(key, 'key')}>
                {copied === 'key' ? 'copied ✓' : 'copy'}
              </button>
            </>}
          </dd>
        </div>
      </dl>
      <p className="text-xs text-slate-500">
        Send the key on every request as <code className="text-slate-300">Authorization: Bearer &lt;key&gt;</code>.
        Requests without it get 401. Keep it secret — anyone with it can use your models.
      </p>
      {isAdmin && (
        <button className="btn-secondary" onClick={regenerate}>
          <Icon name="refresh" size={15} />Regenerate key
        </button>
      )}

      <div className="space-y-3 pt-2">
        {examples.map((ex) => (
          <div key={ex.title} className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">{ex.title}</span>
              <button className="text-xs text-sky-400 hover:underline" onClick={() => copy(ex.code, ex.title)}>
                {copied === ex.title ? 'copied ✓' : 'copy'}
              </button>
            </div>
            <pre className="overflow-x-auto rounded-lg border border-panel-border bg-slate-950 p-3 text-xs text-slate-300">{ex.code}</pre>
          </div>
        ))}
        <p className="text-xs text-slate-500">Replace llama3.2:3b with any model from the Models tab.</p>
      </div>
    </div>
  )
}

// A few good starting points for a CPU server (sizes are the download).
const SUGGESTED_MODELS = [
  { name: 'llama3.2:1b', note: '1.3 GB · fastest' },
  { name: 'llama3.2:3b', note: '2.0 GB · good all-rounder' },
  { name: 'qwen2.5:3b', note: '1.9 GB · strong for its size' },
  { name: 'gemma2:2b', note: '1.6 GB · Google' },
  { name: 'qwen2.5:7b', note: '4.7 GB · better, needs ~8 GB RAM' },
  { name: 'nomic-embed-text', note: '274 MB · embeddings' },
]

/** Pull / list / delete / try models (Ollama). */
function ModelsTab({ app, isAdmin }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [msg, setMsg] = useState('')
  const [testModel, setTestModel] = useState('')
  const [prompt, setPrompt] = useState('Say hello in one short sentence.')
  const [testing, setTesting] = useState(false)
  const [answer, setAnswer] = useState(null)

  const load = useCallback(() => {
    api.get('/apps/ollama/models')
      .then((res) => { setData(res.data); setError('') })
      .catch((err) => setError(errorMessage(err)))
  }, [])

  useEffect(() => { load() }, [load])

  // While a pull runs, poll its progress (and refresh the list when it ends).
  const pulling = data?.pull?.running
  useEffect(() => {
    if (!pulling) return undefined
    const t = setInterval(load, 1500)
    return () => clearInterval(t)
  }, [pulling, load])

  useEffect(() => {
    if (data?.models?.length && !data.models.some((m) => m.name === testModel)) {
      setTestModel(data.models[0].name)
    }
  }, [data, testModel])

  if (app.install_state !== 'INSTALLED') {
    return <div className="card text-slate-500">Install Ollama first.</div>
  }
  if (app.status !== 'RUNNING') {
    return <div className="card text-slate-500">Ollama isn&apos;t running — start it on the Overview tab.</div>
  }
  if (error) return <div className="card text-sm text-red-300 break-words">{error}</div>
  if (!data) return <div className="card text-slate-500">Loading…</div>

  async function pull(model) {
    setMsg('')
    try {
      const res = await api.post('/apps/ollama/models/pull', { model: model || name })
      setMsg(res.data.detail); setName('')
      load()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  async function remove(model) {
    if (!window.confirm(`Delete ${model}? It can be pulled again later.`)) return
    setMsg('')
    try {
      const res = await api.delete(`/apps/ollama/models/${model}`)
      setMsg(res.data.detail)
      load()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  async function test() {
    setTesting(true); setAnswer(null)
    try {
      const res = await api.post('/apps/ollama/models/test', { model: testModel, prompt },
        { timeout: 600000 })
      setAnswer(res.data)
    } catch (err) { setAnswer({ error: errorMessage(err) }) } finally { setTesting(false) }
  }

  const p = data.pull || {}
  const pct = p.total ? Math.round((p.completed / p.total) * 100) : null
  const installedNames = new Set(data.models.map((m) => m.name))

  return (
    <div className="space-y-4 max-w-3xl">
      {isAdmin && (
        <div className="card space-y-3">
          <h3 className="section-title">Pull a model</h3>
          <div className="flex gap-2 flex-wrap">
            <input className="input max-w-xs font-mono" placeholder="e.g. llama3.2:3b" value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) pull() }} />
            <button className="btn-primary" disabled={!name.trim() || pulling} onClick={() => pull()}>
              <Icon name="download" size={15} />Pull
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTED_MODELS.map((m) => (
              <button key={m.name} className="btn-secondary btn-sm" title={m.note}
                disabled={pulling || installedNames.has(m.name)} onClick={() => pull(m.name)}>
                {m.name} <span className="text-slate-500">· {m.note}</span>
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-500">
            Browse all models at <a className="text-sky-400 hover:underline" href="https://ollama.com/library"
              target="_blank" rel="noreferrer">ollama.com/library</a>. On a CPU-only server, models up to
            3B answer quickly; 7–8B need about 8 GB of free RAM and are slower.
          </p>

          {(p.running || p.error || (p.model && p.status === 'success')) && (
            <div className="rounded-lg border border-panel-border bg-slate-900 p-3 space-y-2 text-sm">
              <div className="flex justify-between gap-2">
                <span className="font-mono">{p.model}</span>
                <span className={p.error ? 'text-red-300' : p.running ? 'text-slate-300' : 'text-green-400'}>
                  {p.error ? 'failed' : p.running ? (p.status || 'starting') : 'done ✓'}
                </span>
              </div>
              {p.running && pct !== null && (
                <>
                  <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full bg-mint-400 transition-all" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="text-xs text-slate-500">
                    {formatBytes(p.completed)} of {formatBytes(p.total)} · {pct}%
                  </div>
                </>
              )}
              {p.error && <p className="text-xs text-red-300 break-words">{p.error}</p>}
            </div>
          )}
          {msg && <p className="text-sm text-slate-300 break-words">{msg}</p>}
        </div>
      )}

      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="section-title">Installed models</h3>
          <span className="text-xs text-slate-500">
            {data.version ? `Ollama ${data.version}` : ''}
            {data.models.length ? ` · ${formatBytes(data.models.reduce((s, m) => s + (m.size || 0), 0))} on disk` : ''}
          </span>
        </div>
        {data.models.length === 0 ? (
          <p className="text-sm text-slate-500">No models yet — pull one above.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                <th className="py-1">Model</th><th>Size</th><th className="hidden sm:table-cell">Details</th><th />
              </tr>
            </thead>
            <tbody className="divide-y divide-panel-border">
              {data.models.map((m) => (
                <tr key={m.name}>
                  <td className="py-2 font-mono">
                    {m.name}
                    {m.loaded && <span className="ml-2 badge bg-green-500/15 text-green-400">in memory</span>}
                  </td>
                  <td className="text-slate-400 whitespace-nowrap">{formatBytes(m.size)}</td>
                  <td className="text-xs text-slate-500 hidden sm:table-cell">
                    {[m.family, m.parameters, m.quantization].filter(Boolean).join(' · ')}
                  </td>
                  <td className="text-right">
                    {isAdmin && (
                      <button className="btn-secondary btn-sm text-red-400" onClick={() => remove(m.name)}>
                        <Icon name="trash" size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {data.models.length > 0 && (
        <div className="card space-y-3">
          <h3 className="section-title">Try a model</h3>
          <div className="flex gap-2 flex-wrap">
            <select className="select max-w-xs font-mono" value={testModel}
              onChange={(e) => setTestModel(e.target.value)}>
              {data.models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select>
          </div>
          <textarea className="input min-h-[80px]" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button className="btn-primary" disabled={testing || !prompt.trim()} onClick={test}>
            {testing ? 'Thinking… (the first answer loads the model)' : 'Send'}
          </button>
          {answer && (answer.error ? (
            <p className="text-sm text-red-300 break-words">{answer.error}</p>
          ) : (
            <div className="space-y-1">
              <pre className="whitespace-pre-wrap rounded-lg border border-panel-border bg-slate-950 p-3 text-sm text-slate-200">{answer.response}</pre>
              <p className="text-xs text-slate-500">
                {answer.seconds}s total · {answer.tokens} tokens
                {answer.tokens_per_second ? ` · ${answer.tokens_per_second} tokens/s` : ''}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function DomainTab({ app, onChanged }) {
  const [domain, setDomain] = useState(app.domain || '')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function assign() {
    setBusy(true); setMsg('')
    try {
      const res = await api.post(`/apps/${app.key}/assign-domain`, { domain })
      setMsg(res.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  async function ssl() {
    setBusy(true); setMsg('')
    try {
      const res = await api.post(`/apps/${app.key}/ssl`)
      setMsg(res.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  return (
    <div className="card max-w-xl space-y-3">
      <h3 className="section-title">Domain &amp; SSL</h3>
      <div className="flex gap-2 items-center flex-wrap">
        <input className="input max-w-xs" placeholder="n8n.example.com" value={domain}
          onChange={(e) => setDomain(e.target.value)} />
        <button className="btn-primary" onClick={assign} disabled={busy || !domain}>
          Assign domain
        </button>
        <button className="btn-secondary" onClick={ssl} disabled={busy || !app.domain}>
          🔒 Request SSL
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Assigning writes a websocket-capable nginx proxy to 127.0.0.1:{app.port} and reloads
        nginx. SSL runs certbot for the domain (DNS must already point at this server).
        {app.key === 'n8n' && ' n8n is restarted on both, because it builds its webhook URLs from this address.'}
        {app.kind === 'api' && ' The proxy only lets requests carrying the API key through (see Overview → API access).'}
      </p>
      {msg && <p className="text-sm text-slate-300 break-words">{msg}</p>}
    </div>
  )
}

function LogsTab({ app }) {
  const [source, setSource] = useState('app')
  return (
    <div className="card space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="section-title">Logs</h3>
        <select className="select max-w-[12rem]" value={source}
          onChange={(e) => setSource(e.target.value)}>
          <option value="app">Running app</option>
          <option value="install">Installer</option>
        </select>
      </div>
      <LiveLog path={`/ws/apps/${app.key}/logs?source=${source}`} />
    </div>
  )
}
