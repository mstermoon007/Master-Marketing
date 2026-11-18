export interface WorkspaceBrief {
  id: string
  workspace_code: string
  name: string
}

export interface TeamSummary {
  team_id: string
  name: string
  workspace_id: string
  department_id: string | null
  role?: string
}

export interface SpaceSummary {
  workspace: WorkspaceBrief & { owner_uid?: string; config?: Record<string, unknown> }
  role: string
  teams: TeamSummary[]
}

export interface DepartmentNode {
  id: string
  workspace_id: string
  parent_id: string | null
  name: string
  depth: number
  leader_uid?: string | null
  status: string
  children?: DepartmentNode[]
}

export interface WorkspaceMember {
  id: string
  workspace_id: string
  user_id: string
  name: string
  role: string
  status: string
  joined_at: string
}

export interface FieldDef {
  fieldKey: string
  label?: string
  type?: string
  unit?: string
  required?: boolean
  options?: string[]
}

export interface TemplateRow {
  id: string
  team_id: string
  template_id: string
  version: number
  name: string
  description?: string
  entry_mode?: string
  status: string
  fields?: FieldDef[]
  scope?: Record<string, unknown>
  effective_from?: string
  created_at?: string
  published_at?: string
}

export interface ReportTaskRow {
  id: string
  team_id: string
  title: string
  template_id: string
  template_version: number
  start_date: string
  end_date?: string | null
  due_time?: string | null
  status: string
  statusText?: string
  scopeText?: string
  dateText?: string
  templateName?: string
}

export interface EntryRow {
  id: string
  team_id: string
  user_id: string
  entry_date: string
  template_id?: string
  template_version?: number
  form_data?: Array<{ rowId?: string; values: Record<string, unknown> }>
  status: string
}

export interface DailyPoint {
  date: string
  expectedCount: number
  submittedCount: number
  rate: number | null
  rateText: string
}

export interface OverviewTeam {
  team_id: string
  name: string
  department_id: string | null
  expectedCount: number
  submittedCount: number
  rate: number | null
  rateText: string
}

export interface WorkspaceOverview {
  workspace: WorkspaceBrief
  role: string
  today: string
  todayExpected: number
  todaySubmitted: number
  todayRate: number | null
  todayRateText: string
  missingCount: number
  activeTaskCount: number
  anomalyCount: number
  trend: DailyPoint[]
  teams: OverviewTeam[]
}

export interface AuditRow {
  id: string
  team_id: string | null
  workspace_id: string | null
  actor: string
  action: string
  target_type: string | null
  target_id: string | null
  detail?: unknown
  created_at: string
}

export interface AuditPage {
  items: AuditRow[]
  total: number
  page: number
  pageSize: number
}

export interface AnalysisTaskRow {
  id: string
  teamId: string
  analysisType: string
  from: string
  to: string
  status: string
  statusText: string
  metricVersion?: number
  ruleVersion?: number
  retryCount?: number
  errorMessage?: string
  createdAt?: string
  finishedAt?: string
}

export interface AnalysisFinding {
  id: string
  ruleCode: string
  level: string
  levelText: string
  findingCode: string
  title: string
  detail?: unknown
  dataRefs?: unknown
}

export interface AnalysisTaskView {
  task: AnalysisTaskRow
  result: {
    id: string | null
    dataSnapshotTime: string | null
    metricVersion?: number
    ruleVersion?: number
    executionId?: string | null
    summary?: Record<string, unknown> | null
    reportText?: string
    createdAt?: string | null
  }
  findings: AnalysisFinding[]
  reused: boolean
}

export interface AnalysisOverview {
  latest: AnalysisTaskView | null
  tasks: AnalysisTaskRow[]
  taskCount: number
  findingCount: number
  metrics: Array<Record<string, unknown>>
  rules: Array<Record<string, unknown>>
}
