export interface Project {
  id: string
  user_id: string
  topic: string
  duration_minutes: number
  tone: string | null
  status: ProjectStatus
  progress: number
  current_phase: string | null
  estimated_completion: string | null
  total_cost: string
  created_at: string
  completed_at: string | null
  error_message: string | null
}

export type ProjectStatus =
  | 'pending'
  | 'processing'
  | 'researching'
  | 'scripting'
  | 'storyboarding'
  | 'generating_assets'
  | 'assembling'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface ProjectListResponse {
  items: Project[]
  total: number
  limit: number
  offset: number
}

export interface CreateProjectPayload {
  topic: string
  duration_minutes: number
  tone?: string
  style?: string
}

export interface HealthResponse {
  status: string
  timestamp: string
}

export interface ReadyResponse {
  status: string
  checks: Record<string, string>
}

export interface PhaseStep {
  key: string
  label: string
  description: string
  progressRange: [number, number]
}

export const PHASES: PhaseStep[] = [
  { key: 'research', label: 'Research', description: 'Gathering facts and context', progressRange: [0, 25] },
  { key: 'script', label: 'Script', description: 'Writing narration script', progressRange: [25, 50] },
  { key: 'storyboard', label: 'Storyboard', description: 'Creating visual descriptions', progressRange: [50, 65] },
  { key: 'assets', label: 'Assets', description: 'Generating voice, images, music', progressRange: [65, 85] },
  { key: 'assembly', label: 'Assembly', description: 'Rendering final video', progressRange: [85, 100] },
]
