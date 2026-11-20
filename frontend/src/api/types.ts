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
  /** 判定口径：user#v3 / default@2026.11.1 / unified@… —— 列表页与对比页都要显示 */
  ri_source?: string;
  judged_at?: string | null;
  unified_ranges?: boolean;
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
  /** `quality` 是质量图（FR-13）：它没有单一指标，也不返回点位。 */
  kind: "box" | "hist" | "corr" | "scatter" | "quality";
  metric: string | null;
  title: string;
  unit: string;
  echarts_option?: Record<string, unknown>;
  points: ChartPoint[];
  sampled: boolean;
  caption: string;
  caption_branch: string;
  supporting: Record<string, unknown>;
  /** 质量图专属：完整率 / DQ 评分 / 剔除原因三块独立的图，纵向排列 */
  panels?: ChartPanel[];
  /** 这张图是按哪套区间画出来的（3.5.1）。trial=true 表示用户正在试算，未保存。 */
  ri_effective?: RangesEffective;
}

/** 质量图的一个 panel（FR-13） */
export interface ChartPanel {
  id: "completeness" | "dq" | "removed";
  title: string;
  unit: string;
  echarts_option: Record<string, unknown>;
}

/** 一层区间的身份：默认表 / 我的第 n 版 / 一次临时试算。 */
export interface RangesEffective {
  kind?: "default" | "user" | "temp";
  source: string;
  version?: string;
  digest: string;
  note?: string;
  trial?: boolean;
  items?: Record<string, RangeItem>;
}

export interface RangeItem {
  metric: string;
  name_cn: string;
  unit: string;
  low: number;
  high: number;
  female_low: number | null;
  female_high: number | null;
  gender_dependent: boolean;
}

/** 提交给 PUT /me/reference-ranges 的形状：只带数值，整份 15 项。 */
export type RangeDraft = Record<string, { low: number; high: number; female_low?: number | null; female_high?: number | null }>;

export interface MyRangesPayload {
  default: { source: string; version: string; digest: string; items: Record<string, RangeItem> };
  mine: {
    source: string;
    version: string;
    digest: string;
    note: string;
    items: Record<string, RangeItem>;
  } | null;
  effective: RangesEffective;
  metrics: string[];
}

export interface RangeVersionPayload {
  version: number;
  digest: string;
  note: string;
  created_at: string;
}

export interface RangesSnapshotPayload {
  dataset_id: string;
  ri_version: string;
  ri_source: string | null;
  judged_at: string | null;
  snapshot: {
    source?: string;
    digest?: string;
    version?: string;
    note?: string;
    unified?: boolean;
    saved_at?: string;
    items?: Record<string, RangeItem>;
  };
  current: { source: string; digest: string; version: string };
  /** 判定时是否留下了快照；B3 之前判定的老数据会是 false（"没留证据"≠"不陈旧"）。 */
  has_snapshot?: boolean;
  stale: boolean;
}

export interface RejudgePayload {
  ok: boolean;
  dataset: DatasetPayload;
  changed: { items?: number; samples?: number; comparable?: boolean };
  timings: Record<string, number>;
  ri_source: string;
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
  rows: (string | number | null)[][];
  headers: string[];
  total: number;
  page: number;
  size: number;
  /** 与 total 相同，单独给出是为了让"筛选命中数"这个词在接口里有名字 */
  matched?: number;
}

export interface FilterState {
  filters: FilterClause[];
  gender?: string | null;
  age_min?: number | null;
  age_max?: number | null;
}

/** 并排对比里"某一格"的统计量（FR-29）。
 *
 * 四个占比相加为 1（MIXED 计入 pct_na），`n + missing` 等于该数据集的样本数——
 * 前端据此检查"这一列是不是少了一截人"，而不是默认所有行都参与了计算。
 */
export interface CompareCell {
  dataset_id: string;
  n: number;
  missing: number;
  mean: number | null;
  sd: number | null;
  median: number | null;
  q1: number | null;
  q3: number | null;
  min: number | null;
  max: number | null;
  pct_low: number | null;
  pct_normal: number | null;
  pct_above: number | null;
  pct_na: number | null;
}

export interface CompareRow {
  metric: string;
  name_cn: string;
  unit: string;
  decimals: number;
  cells: CompareCell[];
}

export interface CompareDataset {
  dataset_id: string;
  name: string;
  rows: number;
  ri_version: string;
  ri_source: string;
  unified_ranges: boolean;
  judged_at: string | null;
}

export interface ComparePayload {
  datasets: CompareDataset[];
  metrics: string[];
  side_by_side: CompareRow[];
  excluded: { dataset_id: string; dataset_name: string; metric: string; reason: string }[];
  notes: string[];
  disclaimer: string;
}
