export type Version = {
  hash: string
  short: string
  author: string
  date: string
  message: string
  preview?: string
  timeline?: string
  file?: string
  legacy?: boolean
}

export type TimelineInfo = {
  name: string
  file: string
  has_changes: boolean | null
  message: string
  stat?: string
}

export type Status = {
  repo?: string
  is_repo: boolean
  has_changes: boolean | null
  message: string
  notice?: string | null
  candidate?: string
  current_branch?: string
  branches?: string[]
  timelines?: TimelineInfo[]
  current_timeline?: string | null
  all_timelines?: string[]
  remote_url?: string
}

export type ResolveCurrent = {
  ok?: boolean
  project: string | null
  current_timeline: string | null
  timelines: string[]
}

export type GraphCommit = {
  hash: string
  short: string
  parents?: string[]
  message: string
  relative?: string
  date: string
  lane?: number
  branchName?: string
  isBranch?: boolean
  isFork?: boolean
  isCurrent?: boolean
  branches?: string[]
}

export type Graph = {
  ok?: boolean
  current?: string
  branches?: string[]
  altBranch?: string | null
  fork?: string | null
  forks?: Record<string, string>
  commits?: GraphCommit[]
}

export type DiffChange = {
  type: string
  index_old?: number | null
  index_new?: number | null
  clip_name?: string
  kind?: string
  details?: Record<string, number | string | boolean | undefined>
}

export type TcEntry = {
  change_id?: number
  change_ids?: number[]
  timecode_s: number | null
  timecode: string | null
  label: string | null
  type: string
  kind?: string
  lines: string[]
}

export type TcSection = {
  track: string
  kind: string
  entries: TcEntry[]
}

export type VisualClip = {
  id: string
  name: string
  kind: string
  start_s: number
  duration_s: number
  status: string
  change_id: number | null
  delta_s?: number
  head_delta_s?: number
  tail_delta_s?: number
  detail?: string | null
  source?: string | null
}

export type VisualTrack = {
  name: string
  short: string
  kind: 'video' | 'audio'
  before: VisualClip[]
  after: VisualClip[]
  removed: VisualClip[]
}

export type VisualTracksData = {
  duration_s: number
  tracks: VisualTrack[]
}

export type Diff = {
  is_first_save?: boolean
  summary?: {
    added?: number
    removed?: number
    trimmed?: number
    reordered?: number
    modified?: number
    gap_changed?: number
    total_changes?: number
    old_duration_s?: number
    new_duration_s?: number
    runtime_delta_s?: number
  }
  changes?: DiffChange[]
  sections?: TcSection[]
  visual_tracks?: VisualTracksData | null
  warnings?: string[]
  new_track?: { items?: { name?: string }[] } | null
}
