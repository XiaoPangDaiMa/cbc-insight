/** 与 8.1 API 草案一一对应的类型。字段名必须和后端 payload 完全一致，
 * 任何改名都要同时改后端，否则界面上会出现 ``undefined`` 而不是报错。
 */

export type Status = "LOW" | "NORMAL" | "HIGH" | "NA";
export type MetricStatusSummary = "LOW" | "NORMAL" | "HIGH" | "NA" | "MIXED";

export interface AuthTokens {
  user_id: string;
  username: string;
  role: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserPayload {
  user_id: string;
  username: string;
  role: string;
  created_at: string;
  last_login_at: string | null;
}

export interface WorkspacePayload {
  username: string;
  dataset_count: number;
  datasets: DatasetPayload[];
  latest: DatasetPayload | null;
  empty: boolean;
}

export interface DatasetPayload {
  dataset_id: string;
  name: string;
  original_filename: string;
  rows: number;
  columns: number;
  status: "uploaded" | "cleaned" | "failed";
  ri_version: string;
  created_at: string;
  updated_at: string;
  health: string;
  anomaly_rate: number | null;
}

export interface GenderBand {
  gender: "male" | "female";
  low: number;
  high: number;
}

export interface MetricStatusItem {
  metric: string;
  name_cn: string;
  unit: string;
  decimals: number;
  n: number;
  low: number | null;
  high: number | null;
  median: number | null;
  q1: number | null;
  q3: number | null;
  min: number | null;
  max: number | null;
  max_deviation_pct: number | null;
  gender_dependent: boolean;
  ranges_by_gender: GenderBand[];
  status: MetricStatusSummary;
  pct_low: number;
  pct_normal: number;
  pct_above: number;
  pct_na: number;
}

export interface MetricStatusPayload {
  ri_version: string;
  metrics: MetricStatusItem[];
  gender_missing_samples: number;
  anomaly_rate: number | null;
}

export interface ProfileItem {
  metric: string;
  name_cn: string;
  unit: string;
  decimals: number;
  value: number | null;
  low: number | null;
  high: number | null;
  status: Status;
  pos: number | null;
  deviation_pct: number | null;
  reason: string | null;
}

export interface SampleProfilePayload {
  sample_index: number;
  gender: string | null;
  age: number | null;
  gender_missing: boolean;
  items: ProfileItem[];
}

export interface StatItem {
  metric: string;
  name_cn: string;
  unit: string;
  decimals: number;
  n: number;
  missing: number;
  mean: number | null;
  std: number | null;
  median: number | null;
  q1: number | null;
  q3: number | null;
  min: number | null;
  max: number | null;
  low: number | null;
  high: number | null;
  gender_dependent: boolean;
  ranges_by_gender: GenderBand[];
  max_deviation_pct?: number | null;
}

export interface GroupStat {
  metric: string;
  name_cn: string;
  unit: string;
  decimals: number;
  group: string;
  n: number;
  mean: number | null;
  median: number | null;
  std: number | null;
}

export interface StatsPayload {
  n: number;
  ri_version: string;
  overview: StatItem[];
  by_gender: GroupStat[];
  by_age_band: GroupStat[];
  comparisons: Record<string, unknown>;
  correlation: unknown;
  gender_missing_samples: number;
}

export interface ChartPoint {
  sample_index: number;
  status: Status;
  deviation_pct: number | null;
  pct: number | null;
  pair?: [number, number];
}

export interface ChartPayload {
  kind: "box" | "hist" | "corr" | "scatter";
  metric: string;
  title: string;
  unit: string;
  echarts_option: Record<string, unknown>;
  points: ChartPoint[];
  sampled: boolean;
  caption: string;
  caption_branch: string;
  supporting: Record<string, unknown>;
}

export interface QualityIssue {
  code: string;
  field: string | null;
  severity: "ERROR" | "WARN" | "INFO";
  count: number;
  message: string;
  fix: string;
}

export interface QualityPayload {
  issues: QualityIssue[];
  dq_metrics: Record<string, number | null>;
}

export interface CleanReportPayload {
  before: Record<string, number>;
  after: Record<string, number>;
  removed_by_reason: Record<string, number>;
  log: { step: number; action: string; field: string | null; count: number; note: string }[];
  dropped_columns: string[];
  filled: Record<string, number>;
  unit_log: string[];
  health: string;
}

export interface AnomalyPayload {
  samples: number;
  abnormal_samples: number;
  anomaly_rate: number;
  abnormal_items: number;
  pattern_counts: Record<string, number>;
  na_samples: number;
  gender_missing_samples: number;
  ri_version: string;
}

export interface UploadPayload {
  dataset: DatasetPayload;
  mapping: MappingPayload;
  quality: { rows: number; columns: number; issues: QualityIssue[]; dq: Record<string, number | null>; completeness: Record<string, number> };
  clean_report: CleanReportPayload;
  anomaly: AnomalyPayload;
}

export interface MappingItem {
  source: string;
  target: string | null;
  confidence: number;
  method: string;
  needs_confirm: boolean;
  candidates?: string[];
}

export interface MappingPayload {
  mapping: Record<string, string>;
  items: MappingItem[];
  missing_required: string[];
  unresolved: string[];
  needs_confirmation: boolean;
  ignored: string[];
  notes?: string[];
}

export interface ExportPreviewPayload {
  headers: string[];
  rows: (string | number | null)[][];
  total: number;
  filename: string;
  scope: string;
}

export interface FilterClause {
  metric: string;
  op: "lt" | "lte" | "gt" | "gte" | "eq" | "between";
  value: number;
  upper?: number | null;
}

export interface QueryPayload {
  rows: Record<string, string | number | null>[];
  total: number;
  page: number;
  size: number;
  headers?: string[];
}
