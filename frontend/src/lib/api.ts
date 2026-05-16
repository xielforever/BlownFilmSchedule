import type { MachinesResponse, PreviewResponse, ScheduleResult } from '../types';

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

export async function getMachines(): Promise<MachinesResponse> {
  const response = await fetch(`${API_BASE}/api/machines`);
  return parseResponse(response);
}

export async function previewSchedule(file: File): Promise<PreviewResponse> {
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(`${API_BASE}/api/schedule/preview`, {
    method: 'POST',
    body: form,
  });
  return parseResponse(response);
}

export async function runSchedule(uploadId: string): Promise<ScheduleResult> {
  const response = await fetch(`${API_BASE}/api/schedule/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: uploadId, config: {} }),
  });
  return parseResponse(response);
}

export function exportUrl(exportId: string, kind: 'schedule' | 'audit' | 'report'): string {
  return `${API_BASE}/api/schedule/export/${exportId}/${kind}`;
}

export function sampleUrl(): string {
  return `${API_BASE}/api/examples/mock-orders`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Keep HTTP status text.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
