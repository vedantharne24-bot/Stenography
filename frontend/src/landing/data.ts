import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Algorithm, ClassName, EvaluationReport, Probabilities, Quality, Risk, TechniqueSummary, TraceEvent } from '../lib/types'

export interface PublicModel {
  version: string
  trained_at: string | null
  accuracy: number | null
  f1: number | null
  roc_auc: number | null
  binary: EvaluationReport['binary'] | null
  per_class: EvaluationReport['multiclass']['per_class'] | null
  confusion_matrix: number[][] | null
  by_utilisation: EvaluationReport['by_utilisation'] | null
  samples: number | null
}

export interface Overview {
  models: Record<string, PublicModel | null>
  counters: { images_analyzed: number; stego_detected: number; embeddings: number; attack_runs: number }
  dataset: {
    sources: Record<string, number>
    images: Record<string, number>
    leakage_check: { passed: boolean; source_overlap: Record<string, number> }
    embedding_quality: Record<Algorithm, { psnr: { mean: number }; ssim: { mean: number }; utilisation: { mean: number } }>
    source_datasets: Record<string, number>
  } | null
  algorithms: { name: Algorithm; label: string; domain: string; ecc_parity: number }[]
  latest_experiment: {
    created_at: string
    config: Record<string, unknown>
    summary: Record<Algorithm, Omit<TechniqueSummary, 'psnr_values'>>
    ranking: Algorithm[]
    answer: string
    balance_score: Record<Algorithm, number>
  } | null
}

export interface DemoSide {
  prediction: 'cover' | 'stego'
  p_stego: number
  predicted_technique: ClassName
  probabilities: Probabilities
  rf: { probabilities: Probabilities; anomaly: number } | null
  risk: Risk
  model: { name: string; version: string }
  explanation: { target_class: ClassName; branch_share: Record<string, number>; note: string } | null
  overlay: string | null
}

export interface Demo {
  carrier: string
  algorithm: Algorithm
  payload_bytes: number
  envelope_sha256: string
  utilization: number
  quality: Quality
  images: { cover: string; stego: string; difference: string }
  cover: DemoSide
  stego: DemoSide
  trace: TraceEvent[]
}

export function useOverview() {
  const [data, setData] = useState<Overview | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    api<Overview>('/api/public/overview').then(setData).catch(() => setFailed(true))
  }, [])
  return { data, failed }
}

export function useDemo() {
  const [demo, setDemo] = useState<Demo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async (algorithm: Algorithm | 'random' = 'random') => {
    setLoading(true)
    setError(null)
    try {
      setDemo(await api<Demo>('/api/public/demo', { method: 'POST', json: { algorithm } }))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])
  return { demo, loading, error, run }
}
