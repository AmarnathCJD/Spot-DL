import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react'

export const api = createApi({
  reducerPath: 'api',
  baseQuery: fetchBaseQuery({ baseUrl: '/' }),
  tagTypes: ['Queue', 'Setup', 'Playlists', 'Connect'],
  endpoints: (builder) => ({
    setupState: builder.query({
      query: () => 'api/setup/state',
      providesTags: ['Setup'],
    }),
    saveSetup: builder.mutation({
      query: (body) => ({ url: 'api/setup', method: 'POST', body }),
      invalidatesTags: ['Setup'],
    }),
    connectStart: builder.mutation({
      query: () => ({ url: 'api/connect/start', method: 'POST' }),
      invalidatesTags: ['Connect'],
    }),
    connectStatus: builder.query({
      query: () => 'api/connect/status',
      providesTags: ['Connect'],
    }),
    playlists: builder.query({
      query: () => 'api/playlists',
      transformResponse: (r) => r.playlists ?? [],
      providesTags: ['Playlists'],
    }),
    addPlaylist: builder.mutation({
      query: (body) => ({ url: 'api/playlists', method: 'POST', body }),
      invalidatesTags: ['Playlists', 'Setup'],
    }),
    updatePlaylist: builder.mutation({
      query: ({ id, ...body }) => ({
        url: `api/playlists/${id}`,
        method: 'PUT',
        body,
      }),
      invalidatesTags: ['Playlists', 'Setup'],
    }),
    removePlaylist: builder.mutation({
      query: (id) => ({ url: `api/playlists/${id}`, method: 'DELETE' }),
      invalidatesTags: ['Playlists', 'Setup'],
    }),
    syncRun: builder.mutation({
      query: () => ({ url: 'api/sync/run', method: 'POST' }),
    }),
    search: builder.query({
      query: (q) => `search?q=${encodeURIComponent(q)}&lim=8`,
      transformResponse: (r) => r.results ?? [],
    }),
    queue: builder.query({
      query: () => 'api/queue',
      transformResponse: (r) => r.jobs ?? [],
      providesTags: ['Queue'],
    }),
    playlist: builder.query({
      query: ({ id, count }) => `api/playlist/${id}?count=${count}`,
    }),
    addTrack: builder.mutation({
      query: (track) => ({
        url: 'api/queue',
        method: 'POST',
        body: {
          track_id: track.id,
          title: track.name,
          artist: track.artist,
          cover: track.cover_small || track.cover || '',
        },
      }),
      invalidatesTags: ['Queue'],
    }),
    addTracks: builder.mutation({
      query: (tracks) => ({
        url: 'api/queue/batch',
        method: 'POST',
        body: {
          tracks: tracks.map((t) => ({
            track_id: t.id,
            title: t.name,
            artist: t.artist,
            cover: t.cover || '',
          })),
        },
      }),
      invalidatesTags: ['Queue'],
    }),
    removeJob: builder.mutation({
      query: (id) => ({ url: `api/queue/${id}`, method: 'DELETE' }),
      invalidatesTags: ['Queue'],
    }),
  }),
})

export const {
  useSetupStateQuery,
  useSaveSetupMutation,
  useConnectStartMutation,
  useConnectStatusQuery,
  usePlaylistsQuery,
  useAddPlaylistMutation,
  useUpdatePlaylistMutation,
  useRemovePlaylistMutation,
  useSyncRunMutation,
  useLazySearchQuery,
  useQueueQuery,
  useLazyPlaylistQuery,
  usePlaylistQuery,
  useAddTrackMutation,
  useAddTracksMutation,
  useRemoveJobMutation,
} = api
