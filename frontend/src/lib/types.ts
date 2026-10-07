/* API response types - mirror backend/app schemas and service return shapes. */

export type Role = 'USER' | 'ANALYST' | 'ADMIN'
export type ClassName = 'normal' | 'lsb' | 'dct' | 'dwt'
export type Algorithm = 'lsb' | 'dct' | 'dwt'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type Probabilities = Record<ClassName, number>

export interface User {
  id: string
  name: string
  email: string
  role: Role
  is_active: boolean
  created_at: string
  last_login: string | null
  permissions: string[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}

export interface TraceEvent {
  type: 'log'
  ts: string
  elapsed_ms: number
  stage: string
  level: 'info' | 'warn' | 'error'
  message: string
  data?: Record<string, unknown>
}

export interface Health {
  status: string
  database: string
  compute: { framework: string | null; device: string; cuda_available: boolean; gpu_name: string | null }
  models: Record<string, string | null>
  time: string
}

export interface ImageSummary {
  filename: string
  format: string
  width: number
  height: number
  file_size: number
  sha256: string
  mode?: string
  warnings?: string[]
}

export interface Quality {
  mse: number
  psnr: number | null
  psnr_infinite?: boolean
  ssim: number
}

export interface CapacityInfo {
  algorithm: Algorithm
  slots: number
  raw_capacity_bytes: number
  ecc_parity: number
  max_envelope_bytes: number
  max_payload_bytes: number
  info?: AlgorithmInfo
}

export interface AlgorithmInfo {
  name: Algorithm
  label: string
  domain: string
  ecc_parity: number
  [key: string]: unknown
}

export interface EmbedResult {
  operation_id: string
  algorithm: Algorithm
  algorithm_info: AlgorithmInfo
  cover: ImageSummary
  stego: { sha256: string; size: number; format: string }
  encryption: {
    cipher: string
    kdf: string
    kdf_params: { time_cost: number; memory_kib: number; parallelism: number } | null
    envelope_bytes: number
    envelope_sha256: string
    content_sha256: string
    compressed: boolean
    nonce_hex: string
  }
  generated_key: string | null
  payload: { kind: 'text' | 'file'; size: number; filename: string | null }
  capacity: CapacityInfo
  frame_bits: number
  utilization: number
  quality: Quality
  qim: { iterations: number; residual_errors: number } | null
  artifacts: Record<'stego' | 'cover_preview' | 'stego_preview' | 'difference' | 'difference_amplified', string>
  timings_ms: Record<string, number>
}

export interface ExtractResult {
  operation_id: string
  image: ImageSummary
  detected_algorithm: Algorithm | null
  tried: Algorithm[]
  integrity: {
    status: 'verified' | 'failed' | 'not_found'
    expected_sha256: string | null
    actual_sha256: string | null
    ecc_parity: number
    header_symbols_corrected: number
    body_symbols_corrected: number
    notes: string[]
  }
  envelope_bytes: number | null
  decryption: { status: 'success' | 'failed' | 'not_attempted'; message: string | null }
  payload: {
    kind: 'text' | 'file'
    text: string | null
    filename: string | null
    content_b64: string | null
    size: number
    content_sha256: string
    integrity_verified: boolean
    kdf: string
  } | null
  timings_ms: Record<string, number>
}

export interface RiskFactor {
  key: string
  label: string
  value: number | string | null
  weight: number | null
  effective_weight: number | null
  contribution: number
  available: boolean
}

export interface Risk {
  score: number
  level: RiskLevel
  evidence: number
  floor: number
  factors: RiskFactor[]
  agreement: 'agree' | 'disagree' | null
  recommendation: string
  formula: string
}

export interface TileProbability {
  y: number
  x: number
  h: number
  w: number
  p_stego: number
  argmax: ClassName
}

export interface AnalysisResult {
  analysis_id: string
  prediction: 'cover' | 'stego'
  confidence: number
  p_stego: number
  predicted_technique: ClassName
  technique_confidence: number | null
  probabilities: Probabilities
  rf: {
    probabilities: Probabilities
    anomaly: number
    top_features: { feature: string; importance: number; value: number; z_vs_covers: number }[]
  } | null
  signature: { algorithm: Algorithm; integrity: string } | null
  risk: Risk
  model: { name: string; version: string }
  rf_model: { name: string; version: string } | null
  tiles: TileProbability[]
  explanation: {
    method: string
    target_class: ClassName
    branch_share: Record<'spatial' | 'dct' | 'dwt', number>
    tiles: number
    note: string
  } | null
  timings_ms: Record<string, number>
  image: ImageSummary
  artifacts: Partial<Record<'image_preview' | 'heatmap' | 'overlay', string>>
  created_at: string
  duration_ms: number
}

export interface ForensicResult {
  analysis_id: string
  file: ImageSummary & { megapixels: number; mode: string }
  metadata: Record<string, unknown> & { exif?: Record<string, string>; jpeg_quality_estimate?: number | null; icc_profile?: string; text_chunks?: string[] }
  entropy: { luma_bits: number; R: number; G: number; B: number }
  histograms: Record<'R' | 'G' | 'B', number[]>
  pixel_stats: Record<'R' | 'G' | 'B', { mean: number; std: number; min: number; max: number; skewness: number; kurtosis: number; saturated_fraction: number; entropy_bits: number }>
  lsb_analysis: Record<'R' | 'G' | 'B', { chi_square_embedding_probability: number; pair_asymmetry: number; spa_estimate: number; ones_fraction: number; lsb_horizontal_correlation: number }>
  dct_stats: {
    blocks: number
    blockiness: number
    coefficient_histograms: { range: [number, number]; positions: Record<string, number[]> }
    periodicity: Record<string, { score: number; period: number }>
    max_periodicity: number
  }
  dwt_stats: Record<string, { mean_abs: number; std: number; periodicity: number; period: number }>
  ai: Omit<AnalysisResult, 'analysis_id' | 'image' | 'artifacts' | 'created_at' | 'duration_ms'>
  findings: { severity: 'info' | 'medium' | 'high'; title: string; detail: string }[]
  disclaimer: string
  artifacts: Partial<Record<'preview' | 'noise_residual' | 'lsb_plane' | 'heatmap' | 'overlay', string>>
  duration_ms: number
}

export interface AttackParamSpec {
  min: number
  max: number
  default: number
}

export interface AttackSpec {
  key: string
  label: string
  description: string
  params: Record<string, AttackParamSpec>
}

export interface AttackBaseline {
  detection_probability: number
  predicted_technique: ClassName
  prediction: 'cover' | 'stego'
  extraction: { integrity: string; algorithm: Algorithm | null; success: boolean; ecc_corrected: number; decryption: string }
  model_version: string
}

export interface AttackRow {
  attack: string
  label: string
  params: Record<string, number>
  shape: [number, number]
  detection_probability: number
  predicted_technique: ClassName
  prediction: 'cover' | 'stego'
  extraction: { integrity: string; algorithm: Algorithm | null; success: boolean; ecc_corrected: number; decryption: string }
  bit_error_rate: number | null
  quality: Quality & { reference: string }
  ms: number
}

export interface AttackSingleResult {
  experiment_id: string
  image: { filename: string; sha256: string; width: number; height: number }
  before: AttackBaseline
  after: AttackRow
  artifacts: Record<'attacked' | 'before_preview' | 'after_preview', string>
}

export interface AttackBatchResult {
  batch_id: string
  image: { filename: string; sha256: string; width: number; height: number }
  before: AttackBaseline
  rows: AttackRow[]
  summary: { attacks: number; extraction_survival_rate: number; detection_rate: number; mean_psnr: number | null }
}

export interface TechniqueSummary {
  algorithm: Algorithm
  label: string
  images: number
  skipped: number
  capacity_bytes: number | null
  capacity_bpp: number | null
  payload_bytes: number | null
  psnr: number | null
  psnr_std: number | null
  ssim: number | null
  mse: number | null
  extraction_success: number | null
  detection_rate: number | null
  technique_accuracy: number | null
  mean_p_stego: number | null
  robustness: number | null
  embed_ms: number | null
  extract_ms: number | null
  per_attack: Record<string, number | null>
  psnr_values?: number[]
}

export interface ExperimentResult {
  run_id: string
  created_at: string
  duration_ms: number
  config: Record<string, unknown>
  summary: Record<Algorithm, TechniqueSummary>
  cover_false_positive_rate: number | null
  normalised: Record<string, Record<Algorithm, number>>
  weights: Record<string, number>
  balance_score: Record<Algorithm, number>
  ranking: Algorithm[]
  winners?: Record<string, Algorithm | 'tie'>
  answer: string
  methodology: string
  attacks: string[]
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ModelRow {
  id: string
  model_name: string
  version: string
  kind: string
  framework: string
  accuracy: number | null
  precision: number | null
  recall: number | null
  f1: number | null
  roc_auc: number | null
  binary: { accuracy?: number; detection_rate?: number; false_positive_rate?: number; roc_auc?: number; f1?: number }
  is_active: boolean
  trained_at: string | null
  weights_sha256: string | null
  created_at: string
}

export interface RocCurve {
  fpr: number[]
  tpr: number[]
  thresholds: number[]
}

export interface EvaluationReport {
  samples: number
  classes: ClassName[]
  multiclass: {
    accuracy: number
    precision_macro: number
    recall_macro: number
    f1_macro: number
    roc_auc_macro_ovr: number | null
    per_class: Record<ClassName, { precision: number; recall: number; f1: number; support: number; roc_auc: number | null }>
    confusion_matrix: number[][]
    classification_report: Record<string, unknown>
  }
  binary: {
    accuracy: number
    precision: number
    recall: number
    detection_rate: number
    false_positive_rate: number
    f1: number
    roc_auc: number | null
    confusion: { tp: number; tn: number; fp: number; fn: number }
  }
  roc_curves: Record<string, RocCurve>
  by_utilisation?: { technique: Algorithm; bin: string; samples: number; detection_rate: number; technique_accuracy: number }[]
  by_cover_variant?: { variant: string; covers: number; false_positive_rate: number | null; stego: number; detection_rate: number | null; accuracy: number }[]
  feature_importance?: { feature: string; importance: number }[]
  feature_group_importance?: Record<string, number>
  anomaly_model?: { method: string; test_auc_cover_vs_stego: number; calibration_samples: number }
  loss?: number
}

export interface ModelDetail extends ModelRow {
  metrics: EvaluationReport
  history?: { history: { epoch: number; train_loss: number; train_accuracy: number; val_loss: number; val_accuracy: number; val_f1_macro: number; lr: number; seconds: number }[]; best: { f1: number; epoch: number; loss: number } }
  val_metrics?: EvaluationReport
  card?: Record<string, unknown>
}
