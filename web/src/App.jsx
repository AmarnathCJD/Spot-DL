import { useEffect, useMemo, useState } from 'react'

import {
  useAddPlaylistMutation,
  useAddTrackMutation,
  useAddTracksMutation,
  useConnectStartMutation,
  useConnectStatusQuery,
  useLazySearchQuery,
  usePlaylistQuery,
  usePlaylistsQuery,
  useQueueQuery,
  useRemoveJobMutation,
  useRemovePlaylistMutation,
  useSaveSetupMutation,
  useSetupStateQuery,
  useSyncRunMutation,
  useUpdatePlaylistMutation,
} from './api'

const PLAYLIST_REF = /(?:\/playlist\/|spotify:playlist:)([0-9A-Za-z]{22})/
const BARE_ID = /^[0-9A-Za-z]{22}$/
const DEFAULT_COUNT = 10

function Results({ tracks, onAdd }) {
  if (!tracks.length) return null
  return (
    <ul className="list">
      {tracks.map((t) => (
        <li key={t.id} className="row">
          {t.cover_small ? <img src={t.cover_small} alt="" width="48" height="48" /> : null}
          <span className="grow">
            <strong>{t.name}</strong>
            <em>{t.artist}</em>
          </span>
          <button onClick={() => onAdd(t)}>add</button>
        </li>
      ))}
    </ul>
  )
}

function PlaylistPreview({ id, onClose }) {
  const [count, setCount] = useState(DEFAULT_COUNT)
  const [debounced, setDebounced] = useState(DEFAULT_COUNT)
  const { data, isFetching, error } = usePlaylistQuery({ id, count: debounced })
  const [addTracks, { isLoading: isAdding }] = useAddTracksMutation()

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(count), 500)
    return () => clearTimeout(timer)
  }, [count])

  if (error) {
    return (
      <section className="panel">
        <p className="error">could not load that playlist</p>
        <button onClick={onClose}>close</button>
      </section>
    )
  }

  const tracks = data?.tracks ?? []
  const total = data?.total ?? 0

  return (
    <section className="panel">
      <header className="panel-head">
        <span className="grow">
          <strong>{data?.name || 'loading…'}</strong>
          <em>{total ? `${tracks.length} of ${total} songs` : ''}</em>
        </span>
        <label>
          songs
          <input
            type="number"
            aria-label="song count"
            min="1"
            max={total || undefined}
            value={count}
            onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>
        <button disabled={!tracks.length || isAdding} onClick={() => addTracks(tracks)}>
          {isAdding ? 'adding…' : `add ${tracks.length}`}
        </button>
        <button onClick={onClose}>x</button>
      </header>
      {data?.truncated || (total && data?.returned < total) ? (
        <p className="error">
          Spotify returned {data.returned} of {total} tracks; the selection can only use those.
        </p>
      ) : null}
      <ol className="list">
        {tracks.map((t) => (
          <li key={t.id} className="row">
            {t.cover ? <img src={t.cover} alt="" width="48" height="48" /> : null}
            <span className="grow">
              <strong>{t.name}</strong>
              <em>
                {t.artist}
                {t.year ? ` · ${t.year}` : ''}
              </em>
            </span>
          </li>
        ))}
      </ol>
      {isFetching ? <p className="empty">loading songs…</p> : null}
    </section>
  )
}

function Queue({ jobs, onRemove }) {
  if (!jobs.length) return <p className="empty">queue is empty</p>
  return (
    <ul className="list">
      {jobs.map((j) => (
        <li key={j.id} className="row" data-job-status={j.status}>
          {j.cover ? <img src={j.cover} alt="" width="48" height="48" /> : null}
          <span className="grow">
            <strong>{j.title || j.track_id}</strong>
            <em>{j.artist}</em>
          </span>
          <span className={`status ${j.status}`}>{j.status}</span>
          {j.status === 'done' ? (
            <a href={`/api/file/${j.id}`} download>
              download
            </a>
          ) : null}
          {j.status === 'error' ? <span className="error">{j.error}</span> : null}
          {['queued', 'done', 'error'].includes(j.status) ? (
            <button onClick={() => onRemove(j.id)}>x</button>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

function ConnectWizardPanel() {
  const { data } = useConnectStatusQuery(undefined, { pollingInterval: 1500 })
  const [start, { isLoading }] = useConnectStartMutation()

  return (
    <section className="panel">
      <h2>spotify connect</h2>
      <p>
        Start the wizard, then choose <code>{data?.device_name || 'spotify-connect-local'}</code> in Spotify
        Connect.
      </p>
      <button onClick={() => start()} disabled={isLoading}>
        {isLoading ? 'starting…' : 'start connect wizard'}
      </button>
      <p className="status-line">status: {data?.state || 'idle'}</p>
      {data?.error ? <p className="error">{data.error}</p> : null}
    </section>
  )
}

function PlaylistManager() {
  const { data: playlists = [] } = usePlaylistsQuery()
  const [draftRef, setDraftRef] = useState('')
  const [draftName, setDraftName] = useState('')
  const [error, setError] = useState('')
  const [addPlaylist, { isLoading: adding }] = useAddPlaylistMutation()
  const [updatePlaylist] = useUpdatePlaylistMutation()
  const [removePlaylist] = useRemovePlaylistMutation()
  const [edits, setEdits] = useState({})

  const rows = useMemo(
    () => playlists.map((p) => ({ ...p, edit: edits[p.id] || { ref: p.ref, name: p.name } })),
    [playlists, edits],
  )

  async function add() {
    setError('')
    try {
      await addPlaylist({ playlist: draftRef.trim(), name: draftName.trim() }).unwrap()
      setDraftRef('')
      setDraftName('')
    } catch (e) {
      setError(e?.data?.error || 'could not add playlist')
    }
  }

  async function save(row) {
    setError('')
    try {
      await updatePlaylist({ id: row.id, playlist: row.edit.ref.trim(), name: row.edit.name.trim() }).unwrap()
    } catch (e) {
      setError(e?.data?.error || 'could not update playlist')
    }
  }

  async function remove(id) {
    setError('')
    try {
      await removePlaylist(id).unwrap()
    } catch (e) {
      setError(e?.data?.error || 'could not remove playlist')
    }
  }

  return (
    <section className="panel">
      <h2>playlists to sync</h2>
      <div className="playlist-new">
        <input
          aria-label="playlist ref"
          placeholder="playlist URL, URI or ID"
          value={draftRef}
          onChange={(e) => setDraftRef(e.target.value)}
        />
        <input
          aria-label="playlist name"
          placeholder="name (optional)"
          value={draftName}
          onChange={(e) => setDraftName(e.target.value)}
        />
        <button onClick={add} disabled={adding || !draftRef.trim()}>
          {adding ? 'adding…' : 'add playlist'}
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <ul className="list">
        {rows.map((row) => (
          <li key={row.id} className="row playlist-row">
            <span className="grow">
              <input
                value={row.edit.name || ''}
                onChange={(e) =>
                  setEdits((state) => ({ ...state, [row.id]: { ...row.edit, name: e.target.value } }))
                }
              />
              <input
                value={row.edit.ref || ''}
                onChange={(e) =>
                  setEdits((state) => ({ ...state, [row.id]: { ...row.edit, ref: e.target.value } }))
                }
              />
            </span>
            <button onClick={() => save(row)}>save</button>
            <button onClick={() => remove(row.id)}>remove</button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function SetupPanel({ setup }) {
  const [mp3Folder, setMp3Folder] = useState(setup?.mp3_folder || '')
  const [syncInterval, setSyncInterval] = useState(setup?.sync_interval_seconds || 3600)
  const [syncIntervalTouched, setSyncIntervalTouched] = useState(false)
  const [saveSetup, { isLoading }] = useSaveSetupMutation()
  const [error, setError] = useState('')

  useEffect(() => {
    if (!mp3Folder && setup?.mp3_folder) {
      setMp3Folder(setup.mp3_folder)
    }
    if (!syncIntervalTouched && setup?.sync_interval_seconds) {
      setSyncInterval(setup.sync_interval_seconds)
    }
  }, [setup, mp3Folder, syncIntervalTouched])

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      await saveSetup({
        mp3_folder: mp3Folder.trim(),
        sync_interval_seconds: Number(syncInterval),
      }).unwrap()
    } catch (err) {
      setError(err?.data?.error || 'could not save setup')
    }
  }

  return (
    <section className="panel">
      <h2>one-time setup</h2>
      <form className="setup-form" onSubmit={submit}>
        <label>
          MP3 folder
          <input
            aria-label="mp3 folder"
            placeholder="/volume1/music/spotdl"
            value={mp3Folder}
            onChange={(e) => setMp3Folder(e.target.value)}
          />
        </label>
        <label>
          Sync interval (seconds)
          <input
            aria-label="sync interval"
            type="number"
            min="1"
            value={syncInterval}
            onChange={(e) => {
              setSyncIntervalTouched(true)
              setSyncInterval(Math.max(1, Number(e.target.value) || 1))
            }}
          />
        </label>
        <button type="submit" disabled={isLoading}>
          {isLoading ? 'saving…' : 'save setup'}
        </button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      <p className="empty">
        Setup required before search and queue features appear.
      </p>
    </section>
  )
}

export default function App() {
  const [term, setTerm] = useState('')
  const [playlistId, setPlaylistId] = useState(null)
  const { data: setup } = useSetupStateQuery()
  const [runSync, { isLoading: syncing }] = useSyncRunMutation()
  const [syncError, setSyncError] = useState('')
  const [search, { data: tracks = [], isFetching }] = useLazySearchQuery()
  const { data: jobs = [] } = useQueueQuery(undefined, { pollingInterval: 1500 })
  const [addTrack] = useAddTrackMutation()
  const [removeJob] = useRemoveJobMutation()

  const setupRequired = setup?.setup_required ?? true

  async function submit(e) {
    e.preventDefault()
    const q = term.trim()
    if (!q || setupRequired) return
    const ref = q.match(PLAYLIST_REF)
    if (ref) {
      setPlaylistId(ref[1])
      return
    }
    setPlaylistId(null)
    const results = await search(q).unwrap()
    if (!results.length && BARE_ID.test(q)) setPlaylistId(q)
  }

  async function manualSync() {
    setSyncError('')
    try {
      await runSync().unwrap()
    } catch (e) {
      setSyncError(e?.data?.error || 'sync failed')
    }
  }

  return (
    <main>
      <h1>Spot-DL</h1>
      <SetupPanel setup={setup} />
      <ConnectWizardPanel />
      <PlaylistManager />

      {setupRequired ? null : (
        <>
          <section className="panel actions-panel">
            <button onClick={manualSync} disabled={syncing}>
              {syncing ? 'syncing…' : 'run sync now'}
            </button>
            {syncError ? <p className="error">{syncError}</p> : null}
          </section>

          <form onSubmit={submit}>
            <input
              aria-label="search"
              placeholder="song, artist, track id or playlist link"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
            />
            <button type="submit">{isFetching ? 'searching…' : 'search'}</button>
          </form>

          {playlistId ? (
            <PlaylistPreview id={playlistId} onClose={() => setPlaylistId(null)} />
          ) : (
            <Results tracks={tracks} onAdd={addTrack} />
          )}

          <h2>queue</h2>
          <Queue jobs={jobs} onRemove={removeJob} />
        </>
      )}
    </main>
  )
}
