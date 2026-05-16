import type { ScheduleAssignment } from '../types';

export type ScheduleStatus = 'pending' | 'changeover' | 'running' | 'completed' | 'risk' | 'late';

export interface ScheduleStatusMeta {
  label: string;
  className: string;
}

const RISK_WINDOW_MS = 8 * 60 * 60 * 1000;

export const STATUS_META: Record<ScheduleStatus, ScheduleStatusMeta> = {
  pending: { label: '待生产', className: 'pending' },
  changeover: { label: '换型中', className: 'changeover' },
  running: { label: '生产中', className: 'running' },
  completed: { label: '已完成', className: 'completed' },
  risk: { label: '延期风险', className: 'risk' },
  late: { label: '已延期', className: 'lateStatus' },
};

export function deriveScheduleStatus(task: ScheduleAssignment, asOf: Date): ScheduleStatus {
  const start = toTime(task.start_time);
  const productionStart = toTime(task.production_start_time);
  const end = toTime(task.end_time);
  const due = task.plan_finish_time ? toTime(task.plan_finish_time) : null;
  const current = asOf.getTime();

  if (due !== null && end > due) {
    return current > due ? 'late' : 'risk';
  }
  if (current >= end) return 'completed';
  if (due !== null && due - end <= RISK_WINDOW_MS) return 'risk';
  if (current < start) return 'pending';
  if (task.changeover_hours > 0 && current < productionStart) return 'changeover';
  return 'running';
}

export function countScheduleStatuses(assignments: ScheduleAssignment[], asOf: Date): Record<ScheduleStatus, number> {
  return assignments.reduce<Record<ScheduleStatus, number>>(
    (counts, assignment) => {
      counts[deriveScheduleStatus(assignment, asOf)] += 1;
      return counts;
    },
    { pending: 0, changeover: 0, running: 0, completed: 0, risk: 0, late: 0 },
  );
}

function toTime(value: string): number {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}
