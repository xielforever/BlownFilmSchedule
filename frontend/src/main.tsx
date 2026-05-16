import React from 'react';
import ReactDOM from 'react-dom/client';
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Download,
  FileSpreadsheet,
  Factory,
  Gauge,
  ListChecks,
  Maximize2,
  Minimize2,
  Play,
  RefreshCcw,
  Upload,
} from 'lucide-react';
import { exportUrl, getMachines, previewSchedule, runSchedule, sampleUrl } from './lib/api';
import { STATUS_META, countScheduleStatuses, deriveScheduleStatus, type ScheduleStatus } from './lib/scheduleStatus';
import type { ConstraintAuditRow, MachineCapability, MachineLoad, PreviewResponse, ScheduleAssignment, ScheduleCandidateAudit, ScheduleException, ScheduleInsight, ScheduleResult, Severity, ValidationIssue } from './types';
import './styles.css';

type BoardFilter = 'all' | 'active' | 'risk' | 'marginal';
type BoardTimeWindow = 'full' | '72h' | '7d' | 'due';

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

const BOARD_FILTERS: Array<{ value: BoardFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '当前' },
  { value: 'risk', label: '风险' },
  { value: 'marginal', label: '边界' },
];

const BOARD_WINDOWS: Array<{ value: BoardTimeWindow; label: string }> = [
  { value: 'full', label: '全程' },
  { value: '72h', label: '72h' },
  { value: '7d', label: '7天' },
  { value: 'due', label: '交期' },
];

function App() {
  const [fileName, setFileName] = React.useState<string>('');
  const [preview, setPreview] = React.useState<PreviewResponse | null>(null);
  const [result, setResult] = React.useState<ScheduleResult | null>(null);
  const [machines, setMachines] = React.useState<MachineCapability[]>([]);
  const [machineError, setMachineError] = React.useState<string | null>(null);
  const [selectedTask, setSelectedTask] = React.useState<ScheduleAssignment | null>(null);
  const [asOf, setAsOf] = React.useState(() => toDateTimeInput(new Date()));
  const [boardMode, setBoardMode] = React.useState(() => new URLSearchParams(window.location.search).get('view') === 'board');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    let active = true;
    getMachines()
      .then((response) => {
        if (!active) return;
        setMachines(response.machines);
        setMachineError(null);
      })
      .catch((err) => {
        if (!active) return;
        setMachineError(err instanceof Error ? err.message : '本地机台读取失败');
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    setSelectedTask(null);
    setFileName(file.name);
    try {
      const response = await previewSchedule(file);
      setPreview(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function handleRun() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const response = await runSchedule(preview.upload_id);
      setResult(response);
      setSelectedTask(response.assignments[0] ?? null);
      setAsOf(toDateTimeInput(defaultAsOfForSchedule(response.assignments)));
    } catch (err) {
      setError(err instanceof Error ? err.message : '排程失败');
    } finally {
      setBusy(false);
    }
  }

  const summary = result?.summary ?? preview?.summary;
  const localMachines = preview?.machines ?? machines;
  const assignments = result?.assignments ?? [];
  const asOfDate = React.useMemo(() => parseDateTimeInput(asOf), [asOf]);
  const scheduleBounds = React.useMemo(() => getScheduleBounds(assignments), [assignments]);
  const statusCounts = React.useMemo(() => countScheduleStatuses(assignments, asOfDate), [assignments, asOfDate]);
  const issueCount = (preview?.validation_issues.length ?? 0) + (result?.exceptions.length ?? 0);
  const readyToRun = Boolean(preview && !busy);
  const activeJobs = statusCounts.changeover + statusCounts.running;

  function enterBoardMode() {
    setBoardMode(true);
    window.history.replaceState(null, '', '?view=board');
  }

  function exitBoardMode() {
    setBoardMode(false);
    window.history.replaceState(null, '', window.location.pathname);
  }

  if (boardMode && result) {
    return (
      <BoardView
        result={result}
        selectedTask={selectedTask}
        asOf={asOf}
        asOfDate={asOfDate}
        scheduleBounds={scheduleBounds}
        statusCounts={statusCounts}
        onAsOfChange={setAsOf}
        onSelectTask={setSelectedTask}
        onExit={exitBoardMode}
      />
    );
  }

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">MVP Scheduling Console</p>
          <h1>吹膜排程工作台</h1>
        </div>
        <div className="actions">
          <a className="ghostButton" href={sampleUrl()}>
            <FileSpreadsheet size={17} />
            下载样例
          </a>
          <button className="ghostButton" type="button" onClick={() => fileInputRef.current?.click()}>
            <Upload size={17} />
            上传订单
          </button>
          <button className="primaryButton" type="button" disabled={!readyToRun} onClick={handleRun}>
            <Play size={17} />
            生成排程
          </button>
          <button className="ghostButton" type="button" disabled={!result} onClick={enterBoardMode}>
            <Maximize2 size={17} />
            大屏
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
        </div>
      </section>

      {error ? <StatusBanner severity="error" message={error} /> : null}
      {machineError ? <StatusBanner severity="warning" message={`本地机台读取失败：${machineError}`} /> : null}
      {busy ? <StatusBanner severity="info" message="正在处理订单数据..." /> : null}

      <section className="metricGrid">
        <Metric icon={<Factory size={18} />} label="内置机台" value={String(summary?.machine_count ?? localMachines.length)} />
        <Metric icon={<ListChecks size={18} />} label="总订单" value={String(summary?.total_jobs ?? 0)} />
        <Metric icon={<CalendarClock size={18} />} label="已排 / 总单" value={`${result?.summary.scheduled_jobs ?? 0} / ${summary?.total_jobs ?? 0}`} />
        <Metric icon={<Clock3 size={18} />} label="当前进行" value={String(activeJobs)} tone={activeJobs ? 'ok' : undefined} />
        <Metric icon={<AlertTriangle size={18} />} label="异常" value={String(issueCount)} tone={issueCount ? 'warn' : 'ok'} />
      </section>

      {result ? <TimeControl asOf={asOf} bounds={scheduleBounds} onChange={setAsOf} /> : null}

      <section className="workspaceGrid">
        <Panel title="订单输入" icon={<Upload size={16} />}>
          <DropZone fileName={fileName} onFile={handleFile} busy={busy} />
          <div className="ruleStack">
            <RuleRow label="输入范围" value="仅订单需求字段" />
            <RuleRow label="优化目标" value="交期优先 / 自动选机" />
            <RuleRow label="换型因素" value="换料 / 调机" />
          </div>
        </Panel>

        <Panel title="固定机台配置" icon={<Factory size={16} />}>
          <MachineSummary machines={localMachines} />
        </Panel>
      </section>

      <section className="mainGrid">
        <Panel title="排程甘特图" icon={<CalendarClock size={16} />} wide>
          <Gantt
            assignments={assignments}
            selectedTask={selectedTask}
            asOf={asOfDate}
            machineLoads={result?.machine_loads ?? []}
            onSelect={setSelectedTask}
          />
        </Panel>

        <Panel title="任务审计" icon={<CheckCircle2 size={16} />}>
          <TaskInspector task={selectedTask} asOf={asOfDate} candidateAudit={result?.candidate_audit ?? []} />
        </Panel>
      </section>

      <section className="mainGrid">
        <Panel title="机台负荷" icon={<Gauge size={16} />}>
          <MachineLoadTable loads={result?.machine_loads ?? []} />
        </Panel>
        <Panel title="排程质量" icon={<ListChecks size={16} />}>
          <ScheduleQuality result={result} statusCounts={statusCounts} />
        </Panel>
      </section>

      <section className="mainGrid">
        <Panel title="异常与未排订单" icon={<AlertTriangle size={16} />}>
          <ExceptionTable exceptions={result?.exceptions ?? []} validationIssues={preview?.validation_issues ?? []} />
        </Panel>
        <Panel title="约束审计" icon={<ListChecks size={16} />}>
          <AuditTable audit={result?.audit ?? preview?.audit ?? []} />
        </Panel>
      </section>

      <section className="footerPanel">
        <div>
          <h2>导出结果</h2>
          <p>导出文件与页面结果使用同一次排程结果生成。</p>
        </div>
        <div className="actions">
          <ExportLink exportId={result?.export_id} kind="schedule" label="排程结果 Excel" />
          <ExportLink exportId={result?.export_id} kind="audit" label="约束审计 Excel" />
          <ExportLink exportId={result?.export_id} kind="report" label="排程报告 MD" />
        </div>
      </section>
    </main>
  );
}

function TimeControl({ asOf, bounds, onChange }: { asOf: string; bounds: ScheduleBounds | null; onChange: (value: string) => void }) {
  const currentTime = parseDateTimeInput(asOf).getTime();
  const min = bounds?.min.getTime() ?? currentTime;
  const max = bounds?.max.getTime() ?? currentTime;
  const spanMinutes = Math.max(1, Math.round((max - min) / 60000));
  const sliderValue = String(Math.min(spanMinutes, Math.max(0, Math.round((currentTime - min) / 60000))));
  const setFromOffset = (offsetMinutes: number) => {
    onChange(toDateTimeInput(new Date(min + offsetMinutes * 60000)));
  };

  return (
    <section className="timeControl">
      <div>
        <span>计划时点</span>
        <strong>{formatDateTime(asOf)}</strong>
      </div>
      <input type="datetime-local" value={asOf} onChange={(event) => onChange(event.target.value)} />
      <input
        type="range"
        min={0}
        max={spanMinutes}
        value={sliderValue}
        onChange={(event) => setFromOffset(Number(event.target.value))}
        disabled={!bounds}
      />
      <button className="ghostButton compactButton" type="button" onClick={() => onChange(toDateTimeInput(new Date()))}>
        当前
      </button>
      {bounds ? (
        <>
          <button className="ghostButton compactButton" type="button" onClick={() => onChange(toDateTimeInput(bounds.min))}>
            开始
          </button>
          <button className="ghostButton compactButton" type="button" onClick={() => setFromOffset(spanMinutes / 2)}>
            中段
          </button>
          <button className="ghostButton compactButton" type="button" onClick={() => onChange(toDateTimeInput(bounds.max))}>
            结束
          </button>
        </>
      ) : null}
    </section>
  );
}

function BoardView({
  result,
  selectedTask,
  asOf,
  asOfDate,
  scheduleBounds,
  statusCounts,
  onAsOfChange,
  onSelectTask,
  onExit,
}: {
  result: ScheduleResult;
  selectedTask: ScheduleAssignment | null;
  asOf: string;
  asOfDate: Date;
  scheduleBounds: ScheduleBounds | null;
  statusCounts: Record<ScheduleStatus, number>;
  onAsOfChange: (value: string) => void;
  onSelectTask: (task: ScheduleAssignment | null) => void;
  onExit: () => void;
}) {
  const [boardFilter, setBoardFilter] = React.useState<BoardFilter>('all');
  const [timeWindow, setTimeWindow] = React.useState<BoardTimeWindow>('72h');
  const riskJobs = statusCounts.risk + statusCounts.late;
  const activeJobs = statusCounts.changeover + statusCounts.running;
  const nextDue = nextDueAssignment(result.assignments, asOfDate);
  const filterCounts = React.useMemo(() => countBoardFilters(result.assignments, asOfDate), [result.assignments, asOfDate]);
  const visibleAssignments = React.useMemo(
    () => result.assignments.filter((task) => matchesBoardFilter(task, boardFilter, asOfDate)).filter((task) => matchesBoardWindow(task, timeWindow, asOfDate)),
    [result.assignments, boardFilter, timeWindow, asOfDate],
  );
  const boardTimeRange = React.useMemo(() => getBoardTimeRange(timeWindow, visibleAssignments, asOfDate), [timeWindow, visibleAssignments, asOfDate]);
  const selectedVisible = selectedTask ? visibleAssignments.some((task) => task.job_id === selectedTask.job_id) : false;
  const visibleSelectedTask = selectedVisible ? selectedTask : null;
  const queueTasks = React.useMemo(() => buildBoardQueue(visibleAssignments, asOfDate), [visibleAssignments, asOfDate]);

  React.useEffect(() => {
    const nextSelected = visibleAssignments[0] ?? null;
    if (!selectedTask) {
      if (nextSelected) onSelectTask(nextSelected);
      return;
    }
    if (!visibleAssignments.some((task) => task.job_id === selectedTask.job_id)) {
      onSelectTask(nextSelected);
    }
  }, [selectedTask, visibleAssignments, onSelectTask]);

  return (
    <main className="boardShell">
      <header className="boardHeader">
        <div>
          <p className="eyebrow">Production Board</p>
          <h1>吹膜排程大屏</h1>
        </div>
        <div className="boardHeaderMeta">
          <span>{formatDateTime(asOf)}</span>
          <button className="ghostButton boardExit" type="button" onClick={onExit}>
            <Minimize2 size={17} />
            返回工作台
          </button>
        </div>
      </header>

      <section className="boardStats">
        <BoardStat label="已排订单" value={`${result.summary.scheduled_jobs}/${result.summary.total_jobs}`} />
        <BoardStat label="当前进行" value={String(activeJobs)} />
        <BoardStat label="换型中" value={String(statusCounts.changeover)} />
        <BoardStat label="生产中" value={String(statusCounts.running)} />
        <BoardStat label="已完成" value={String(statusCounts.completed)} />
        <BoardStat label="风险/延期" value={String(riskJobs)} tone={riskJobs ? 'warn' : 'ok'} />
        <BoardStat label="平均负荷" value={`${(result.summary.average_load_pct ?? 0).toFixed(1)}%`} />
        <BoardStat label="下一交期" value={nextDue ? nextDue.job_id : '-'} note={nextDue ? formatDateTime(nextDue.plan_finish_time) : undefined} />
      </section>

      <section className="boardControls">
        <TimeControl asOf={asOf} bounds={scheduleBounds} onChange={onAsOfChange} />
        <div className="boardSwitches">
          <SegmentedControl
            label="订单视角"
            options={BOARD_FILTERS.map((option) => ({
              value: option.value,
              label: option.label,
              count: filterCounts[option.value],
            }))}
            value={boardFilter}
            onChange={(value) => setBoardFilter(value as BoardFilter)}
          />
          <SegmentedControl
            label="时间窗口"
            options={BOARD_WINDOWS}
            value={timeWindow}
            onChange={(value) => setTimeWindow(value as BoardTimeWindow)}
          />
          <span className="boardVisibleCount">显示 {visibleAssignments.length}/{result.assignments.length}</span>
        </div>
        <div className="boardLegend">
          {(Object.keys(STATUS_META) as ScheduleStatus[]).map((status) => (
            <span className={`pill status ${STATUS_META[status].className}`} key={status}>{STATUS_META[status].label}</span>
          ))}
        </div>
      </section>

      <section className="boardGrid">
        <div className="boardGantt">
          <Gantt
            assignments={visibleAssignments}
            selectedTask={visibleSelectedTask}
            asOf={asOfDate}
            machineLoads={result.machine_loads}
            variant="board"
            timeRange={boardTimeRange}
            onSelect={onSelectTask}
          />
        </div>
        <aside className="boardInspector">
          <h2>选中订单</h2>
          {visibleSelectedTask ? <BoardTaskSummary task={visibleSelectedTask} asOf={asOfDate} /> : <p className="empty">当前视图无选中订单。</p>}
          <BoardQueue tasks={queueTasks} selectedTask={visibleSelectedTask} asOf={asOfDate} onSelect={onSelectTask} />
        </aside>
      </section>
    </main>
  );
}

function SegmentedControl({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ value: string; label: string; count?: number }>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="segmentedControl" aria-label={label}>
      <span>{label}</span>
      <div>
        {options.map((option) => (
          <button
            className={option.value === value ? 'active' : ''}
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
          >
            {option.label}
            {option.count !== undefined ? <small>{option.count}</small> : null}
          </button>
        ))}
      </div>
    </div>
  );
}

function BoardStat({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: 'ok' | 'warn' }) {
  return (
    <div className={`boardStat ${tone ?? ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {note ? <small>{note}</small> : null}
    </div>
  );
}

function BoardTaskSummary({ task, asOf }: { task: ScheduleAssignment; asOf: Date }) {
  const status = deriveScheduleStatus(task, asOf);
  return (
    <div className="boardTaskSummary">
      <strong>{task.job_id}</strong>
      <span className={`pill status ${STATUS_META[status].className}`}>{STATUS_META[status].label}</span>
      <RuleRow label="机台" value={task.machine_id} />
      <RuleRow label="时间" value={`${formatDateTime(task.start_time)} - ${formatDateTime(task.end_time)}`} />
      <RuleRow label="生产开始" value={formatDateTime(task.production_start_time)} />
      <RuleRow label="生产/换型" value={`${task.production_hours.toFixed(1)}h / ${task.changeover_hours.toFixed(1)}h`} />
      <RuleRow label="交期" value={formatDateTime(task.plan_finish_time)} />
      <RuleRow label="规格" value={task.spec_raw} />
      <p className="reason">{task.reason}</p>
    </div>
  );
}

function BoardQueue({
  tasks,
  selectedTask,
  asOf,
  onSelect,
}: {
  tasks: ScheduleAssignment[];
  selectedTask: ScheduleAssignment | null;
  asOf: Date;
  onSelect: (task: ScheduleAssignment) => void;
}) {
  return (
    <div className="boardQueue">
      <h3>关键队列</h3>
      {tasks.length ? (
        <div className="queueRows">
          {tasks.slice(0, 8).map((task) => {
            const status = deriveScheduleStatus(task, asOf);
            return (
              <button className={selectedTask?.job_id === task.job_id ? 'queueRow selected' : 'queueRow'} key={task.job_id} type="button" onClick={() => onSelect(task)}>
                <strong>{task.job_id}</strong>
                <span className={`pill status ${STATUS_META[status].className}`}>{STATUS_META[status].label}</span>
                <small>{task.machine_id} · {formatDateTime(task.end_time)}</small>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="empty">当前视图暂无关键订单。</p>
      )}
    </div>
  );
}

function Panel({ title, icon, children, wide = false }: { title: string; icon: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return (
    <section className={wide ? 'panel panelWide' : 'panel'}>
      <div className="panelHeader">
        <span className="panelIcon">{icon}</span>
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Metric({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone?: 'ok' | 'warn' }) {
  return (
    <div className={`metric ${tone ?? ''}`}>
      <span>{icon}</span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function DropZone({ fileName, onFile, busy }: { fileName: string; onFile: (file: File) => void; busy: boolean }) {
  return (
    <label
      className="dropZone"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const file = event.dataTransfer.files[0];
        if (file) onFile(file);
      }}
    >
      <input type="file" accept=".xlsx" hidden disabled={busy} onChange={(event) => event.target.files?.[0] && onFile(event.target.files[0])} />
      <FileSpreadsheet size={28} />
      <span>{fileName || '拖入或选择订单 Excel'}</span>
      <small>orders 为订单输入表，排程计划由算法生成</small>
    </label>
  );
}

function RuleRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="ruleRow">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MachineSummary({ machines }: { machines: MachineCapability[] }) {
  if (!machines.length) {
    return <p className="empty">正在读取本地机台能力表。</p>;
  }
  const tagged = machines.filter((machine) => machine.rule_tags.length);
  return (
    <div className="machineList">
      {machines.slice(0, 8).map((machine) => (
        <div className="machineItem" key={machine.machine_id}>
          <strong>{machine.machine_id}</strong>
          <span>{machine.capacity_min_kg_h ?? '-'}-{machine.capacity_max_kg_h ?? '-'} kg/h</span>
          <small>{machine.rule_tags.join(', ') || machine.remark || '标准规则'}</small>
        </div>
      ))}
      <p className="hint">特殊规则机台：{tagged.map((machine) => `${machine.machine_id}:${machine.rule_tags.join('/')}`).join('，') || '无'}</p>
    </div>
  );
}

function Gantt({
  assignments,
  selectedTask,
  asOf,
  machineLoads = [],
  variant = 'workbench',
  timeRange = null,
  onSelect,
}: {
  assignments: ScheduleAssignment[];
  selectedTask: ScheduleAssignment | null;
  asOf: Date;
  machineLoads?: MachineLoad[];
  variant?: 'workbench' | 'board';
  timeRange?: ScheduleBounds | null;
  onSelect: (task: ScheduleAssignment) => void;
}) {
  if (!assignments.length) {
    return <div className="empty ganttEmpty">生成排程后显示按机台分泳道的时间轴。</div>;
  }
  const times = timeRange
    ? [timeRange.min.getTime(), timeRange.max.getTime()]
    : assignments.flatMap((item) => {
        const base = [new Date(item.start_time).getTime(), new Date(item.end_time).getTime()];
        if (variant !== 'board' && item.plan_finish_time) base.push(new Date(item.plan_finish_time).getTime());
        return base;
      });
  const min = Math.min(...times);
  const max = Math.max(...times);
  const span = Math.max(max - min, 1);
  const byMachine = groupBy(assignments, (item) => item.machine_id);
  const loadByMachine = new Map(machineLoads.map((load) => [load.machine_id, load]));
  const asOfPosition = ((asOf.getTime() - min) / span) * 100;
  const dueMarkers = uniqueDueMarkers(assignments, min, max);

  return (
    <div className={`gantt ${variant === 'board' ? 'ganttBoard' : ''}`}>
      <div className="ganttScale">
        <span>{formatDateTime(new Date(min).toISOString())}</span>
        <span>当前时点 {formatDateTime(asOf.toISOString())}</span>
        <span>{formatDateTime(new Date(max).toISOString())}</span>
      </div>
      {Object.entries(byMachine).map(([machineId, items]) => (
        <div className="lane" key={machineId}>
          <div className="laneLabel">
            <strong>{machineId}</strong>
            {loadByMachine.has(machineId) ? (
              <small>{loadByMachine.get(machineId)?.job_count}单 · {loadByMachine.get(machineId)?.load_pct.toFixed(0)}%</small>
            ) : null}
          </div>
          <div className="laneTrack">
            {dueMarkers.map((marker) => (
              <i className="dueMarker" key={marker.key} style={{ left: `${marker.left}%` }} title={`交期 ${formatDateTime(marker.date.toISOString())}`} />
            ))}
            {asOfPosition >= 0 && asOfPosition <= 100 ? <i className="nowMarker" style={{ left: `${asOfPosition}%` }} /> : null}
            {items.map((item) => {
              const rawStart = new Date(item.start_time).getTime();
              const rawEnd = new Date(item.end_time).getTime();
              if (rawEnd < min || rawStart > max) return null;
              const clippedStart = Math.max(rawStart, min);
              const clippedEnd = Math.min(rawEnd, max);
              const visibleDuration = Math.max(clippedEnd - clippedStart, 1);
              const left = ((clippedStart - min) / span) * 100;
              const width = Math.max((visibleDuration / span) * 100, 1.5);
              const status = deriveScheduleStatus(item, asOf);
              const statusMeta = STATUS_META[status];
              const productionStart = new Date(item.production_start_time).getTime();
              const visibleChangeover = item.changeover_hours > 0 ? Math.max(0, Math.min(productionStart, clippedEnd) - Math.max(rawStart, clippedStart)) : 0;
              const changeoverWidth = Math.min(100, Math.max(0, (visibleChangeover / visibleDuration) * 100));
              const className = ['taskBlock', statusMeta.className, selectedTask?.job_id === item.job_id ? 'selected' : ''].join(' ');
              return (
                <button className={className} key={item.job_id} style={{ left: `${left}%`, width: `${width}%` }} type="button" onClick={() => onSelect(item)} title={`${item.job_id} ${statusMeta.label} ${item.reason}`}>
                  {changeoverWidth > 0 ? <i className="changeoverSlice" style={{ width: `${changeoverWidth}%` }} /> : null}
                  <span>{item.job_id} · {statusMeta.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function TaskInspector({ task, asOf, candidateAudit }: { task: ScheduleAssignment | null; asOf: Date; candidateAudit: ScheduleCandidateAudit[] }) {
  if (!task) return <p className="empty">选择甘特图中的任务查看排程原因。</p>;
  const idleBefore = task.idle_before_hours ?? 0;
  const status = deriveScheduleStatus(task, asOf);
  const candidateRows = candidateAudit.filter((row) => row.job_id === task.job_id).sort((a, b) => a.rank - b.rank);
  return (
    <div className="inspector">
      <strong>{task.job_id}</strong>
      <RuleRow label="当前状态" value={STATUS_META[status].label} />
      <RuleRow label="机台" value={task.machine_id} />
      <RuleRow label="适配" value={fitLabel(task.fit_level)} />
      <RuleRow label="排序依据" value={task.priority_reason ?? '-'} />
      <RuleRow label="时间" value={`${formatDateTime(task.start_time)} - ${formatDateTime(task.end_time)}`} />
      <RuleRow label="生产开始" value={formatDateTime(task.production_start_time)} />
      <RuleRow label="生产 / 换型" value={`${task.production_hours.toFixed(1)}h / ${task.changeover_hours.toFixed(1)}h`} />
      <RuleRow label="前序空档" value={idleBefore > 0 ? `${idleBefore.toFixed(1)}h` : '无'} />
      <RuleRow label="配方 / 规格" value={`${task.formula ?? '-'} / ${task.spec_raw}`} />
      <RuleRow label="宽度 / 厚度" value={`${task.width_mm ?? '-'}mm / ${task.thickness_mm ?? '-'}mm`} />
      <RuleRow label="延期" value={task.is_late ? `${task.late_hours.toFixed(1)}h` : '无'} />
      <RuleRow label="评分" value={task.score == null ? '-' : task.score.toFixed(1)} />
      {task.changeover_detail ? <p className="reason">{task.changeover_detail}</p> : null}
      {task.idle_before_reason ? <p className="reason neutral">{task.idle_before_reason}</p> : null}
      <p className="reason">{task.reason}</p>
      <CandidateAuditRows rows={candidateRows} />
    </div>
  );
}

function CandidateAuditRows({ rows }: { rows: ScheduleCandidateAudit[] }) {
  if (!rows.length) return null;
  return (
    <div className="candidateAuditRows">
      <h3>候选机台</h3>
      {rows.map((row) => (
        <div className={row.selected ? 'candidateRow selected' : 'candidateRow'} key={`${row.job_id}-${row.machine_id}`}>
          <div className="candidateHead">
            <strong>{row.rank}. {row.machine_id}</strong>
            <FitPill level={row.fit_level} />
          </div>
          <div className="candidateMetrics">
            <span>评分 {row.score.toFixed(1)}</span>
            <span>差值 {row.score_delta.toFixed(1)}</span>
            <span>生产 {row.production_hours.toFixed(1)}h</span>
            <span>换型 {row.changeover_hours.toFixed(1)}h</span>
          </div>
          <small>{formatDateTime(row.start_time)} - {formatDateTime(row.end_time)}</small>
          <p>{row.decision_reason}</p>
        </div>
      ))}
    </div>
  );
}

function MachineLoadTable({ loads }: { loads: MachineLoad[] }) {
  const active = loads
    .filter((load) => load.job_count > 0)
    .sort((a, b) => b.load_pct - a.load_pct || b.occupied_hours - a.occupied_hours);
  if (!active.length) return <p className="empty">生成排程后显示机台负荷。</p>;
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>机台</th>
            <th>订单</th>
            <th>生产 / 换型</th>
            <th>空档</th>
            <th>负荷</th>
            <th>边界</th>
          </tr>
        </thead>
        <tbody>
          {active.slice(0, 12).map((load) => (
            <tr key={load.machine_id}>
              <td>{load.machine_id}</td>
              <td>{load.job_count}</td>
              <td>{load.production_hours.toFixed(1)}h / {load.changeover_hours.toFixed(1)}h</td>
              <td>{load.idle_hours.toFixed(1)}h</td>
              <td>{load.load_pct.toFixed(1)}%</td>
              <td>{load.marginal_jobs}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScheduleQuality({ result, statusCounts }: { result: ScheduleResult | null; statusCounts: Record<ScheduleStatus, number> }) {
  if (!result) return <p className="empty">生成排程后显示质量指标。</p>;
  const unusedMachines = result.machine_loads.filter((load) => load.job_count === 0).length;
  return (
    <div className="qualityStack">
      <div className="ruleStack compact">
        <RuleRow label="待生产" value={`${statusCounts.pending} 单`} />
        <RuleRow label="换型中" value={`${statusCounts.changeover} 单`} />
        <RuleRow label="生产中" value={`${statusCounts.running} 单`} />
        <RuleRow label="已完成" value={`${statusCounts.completed} 单`} />
        <RuleRow label="风险/延期" value={`${statusCounts.risk + statusCounts.late} 单`} />
        <RuleRow label="生产小时" value={`${(result.summary.total_production_hours ?? 0).toFixed(1)}h`} />
        <RuleRow label="换型小时" value={`${(result.summary.total_changeover_hours ?? 0).toFixed(1)}h`} />
        <RuleRow label="空档小时" value={`${(result.summary.total_idle_hours ?? 0).toFixed(1)}h`} />
        <RuleRow label="平均负荷" value={`${(result.summary.average_load_pct ?? 0).toFixed(1)}%`} />
        <RuleRow label="边界适配" value={`${result.summary.marginal_jobs ?? 0} 单`} />
        <RuleRow label="未用机台" value={`${unusedMachines} 台`} />
      </div>
      <ScheduleInsightList insights={result.schedule_insights ?? []} />
    </div>
  );
}

function ScheduleInsightList({ insights }: { insights: ScheduleInsight[] }) {
  if (!insights.length) return <p className="empty compactEmpty">暂无需要特别解释的长空档、同交期分散、交期余量或边界适配。</p>;
  return (
    <div className="insightList">
      <h3>排程解释</h3>
      {insights.slice(0, 8).map((insight, index) => (
        <div className={`insightItem ${insight.severity}`} key={`${insight.code}-${insight.job_id ?? 'all'}-${index}`}>
          <div className="insightHead">
            <strong>{insight.title}</strong>
            <SeverityPill severity={insight.severity} />
          </div>
          <p>{insight.message}</p>
          <small>
            {[insight.job_id, insight.related_job_id, insight.machine_id, insight.metric_hours != null ? formatHoursCompact(insight.metric_hours) : null]
              .filter(Boolean)
              .join(' · ')}
          </small>
        </div>
      ))}
    </div>
  );
}

function ExceptionTable({ exceptions, validationIssues }: { exceptions: ScheduleException[]; validationIssues: ValidationIssue[] }) {
  const rows = [
    ...validationIssues.map((issue) => ({ job_id: issue.job_id ?? '-', severity: issue.severity, reason: issue.field ?? '字段校验', detail: issue.message })),
    ...exceptions.map((issue) => ({ job_id: issue.job_id, severity: issue.severity, reason: issue.reason, detail: issue.detail ?? '' })),
  ];
  if (!rows.length) return <p className="empty">暂无异常。</p>;
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>订单</th>
            <th>级别</th>
            <th>原因</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 12).map((row, index) => (
            <tr key={`${row.job_id}-${index}`}>
              <td>{row.job_id}</td>
              <td><SeverityPill severity={row.severity} /></td>
              <td>{row.reason}</td>
              <td>{row.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditTable({ audit }: { audit: ConstraintAuditRow[] }) {
  if (!audit.length) return <p className="empty">上传订单后显示约束校验。</p>;
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>订单</th>
            <th>机台</th>
            <th>适配</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {audit.slice(0, 18).map((row, index) => (
            <tr key={`${row.job_id}-${row.machine_id}-${index}`}>
              <td>{row.job_id}</td>
              <td>{row.machine_id ?? '-'}</td>
              <td><FitPill level={row.fit_level ?? (row.passed ? 'recommended' : 'blocked')} /></td>
              <td>{row.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FitPill({ level }: { level?: ConstraintAuditRow['fit_level'] }) {
  const value = level ?? 'recommended';
  return <span className={`pill fit ${value}`}>{fitLabel(value)}</span>;
}

function SeverityPill({ severity }: { severity: Severity }) {
  return <span className={`pill ${severity}`}>{severity}</span>;
}

function fitLabel(level?: ConstraintAuditRow['fit_level']) {
  switch (level) {
    case 'best':
      return '最佳';
    case 'recommended':
      return '推荐';
    case 'marginal':
      return '边界';
    case 'blocked':
      return '禁止';
    default:
      return '-';
  }
}

function StatusBanner({ severity, message }: { severity: Severity; message: string }) {
  const Icon = severity === 'error' ? AlertTriangle : RefreshCcw;
  return (
    <div className={`statusBanner ${severity}`}>
      <Icon size={16} />
      <span>{message}</span>
    </div>
  );
}

function ExportLink({ exportId, kind, label }: { exportId?: string | null; kind: 'schedule' | 'audit' | 'report'; label: string }) {
  if (!exportId) {
    return (
      <button className="ghostButton" disabled type="button">
        <Download size={17} />
        {label}
      </button>
    );
  }
  return (
    <a className="ghostButton" href={exportUrl(exportId, kind)}>
      <Download size={17} />
      {label}
    </a>
  );
}

function groupBy<T>(items: T[], key: (item: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((acc, item) => {
    const value = key(item);
    acc[value] = acc[value] ?? [];
    acc[value].push(item);
    return acc;
  }, {});
}

function formatDateTime(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (input: number) => String(input).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatHoursCompact(hours: number) {
  if (hours >= 48) return `${(hours / 24).toFixed(1)}天`;
  return `${hours.toFixed(1)}h`;
}

interface ScheduleBounds {
  min: Date;
  max: Date;
}

function getScheduleBounds(assignments: ScheduleAssignment[]): ScheduleBounds | null {
  if (!assignments.length) return null;
  const times = assignments.flatMap((item) => [
    new Date(item.start_time).getTime(),
    new Date(item.end_time).getTime(),
    item.plan_finish_time ? new Date(item.plan_finish_time).getTime() : new Date(item.end_time).getTime(),
  ]);
  return { min: new Date(Math.min(...times)), max: new Date(Math.max(...times)) };
}

function defaultAsOfForSchedule(assignments: ScheduleAssignment[]) {
  const bounds = getScheduleBounds(assignments);
  if (!bounds) return new Date();
  const now = new Date();
  if (now < bounds.min) return bounds.min;
  if (now > bounds.max) return bounds.max;
  return now;
}

function nextDueAssignment(assignments: ScheduleAssignment[], asOf: Date) {
  const now = asOf.getTime();
  return assignments
    .filter((item) => item.plan_finish_time && new Date(item.end_time).getTime() >= now)
    .sort((a, b) => new Date(a.plan_finish_time ?? 0).getTime() - new Date(b.plan_finish_time ?? 0).getTime())[0];
}

function uniqueDueMarkers(assignments: ScheduleAssignment[], min: number, max: number) {
  const span = Math.max(max - min, 1);
  const seen = new Set<string>();
  return assignments
    .filter((item) => item.plan_finish_time)
    .map((item) => new Date(item.plan_finish_time as string))
    .filter((date) => {
      const time = date.getTime();
      if (Number.isNaN(time) || time < min || time > max) return false;
      const key = date.toISOString().slice(0, 16);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((date) => ({ key: date.toISOString(), date, left: ((date.getTime() - min) / span) * 100 }));
}

function countBoardFilters(assignments: ScheduleAssignment[], asOf: Date): Record<BoardFilter, number> {
  return assignments.reduce<Record<BoardFilter, number>>(
    (counts, task) => {
      counts.all += 1;
      const status = deriveScheduleStatus(task, asOf);
      if (status === 'changeover' || status === 'running') counts.active += 1;
      if (status === 'risk' || status === 'late') counts.risk += 1;
      if (task.fit_level === 'marginal') counts.marginal += 1;
      return counts;
    },
    { all: 0, active: 0, risk: 0, marginal: 0 },
  );
}

function matchesBoardFilter(task: ScheduleAssignment, filter: BoardFilter, asOf: Date) {
  if (filter === 'all') return true;
  if (filter === 'marginal') return task.fit_level === 'marginal';
  const status = deriveScheduleStatus(task, asOf);
  if (filter === 'active') return status === 'changeover' || status === 'running';
  return status === 'risk' || status === 'late';
}

function matchesBoardWindow(task: ScheduleAssignment, window: BoardTimeWindow, asOf: Date) {
  if (window === 'full') return true;
  const now = asOf.getTime();
  const start = safeTime(task.start_time);
  const end = safeTime(task.end_time);
  if (start === null || end === null) return true;
  if (window === '72h') return overlapsWindow(start, end, now - 12 * HOUR_MS, now + 60 * HOUR_MS);
  if (window === '7d') return overlapsWindow(start, end, now, now + 7 * DAY_MS);
  const due = safeTime(task.plan_finish_time);
  if (due === null) return false;
  const status = deriveScheduleStatus(task, asOf);
  return status === 'risk' || status === 'late' || (due >= now - DAY_MS && due <= now + 7 * DAY_MS);
}

function getBoardTimeRange(window: BoardTimeWindow, assignments: ScheduleAssignment[], asOf: Date): ScheduleBounds | null {
  if (!assignments.length) return null;
  const now = asOf.getTime();
  if (window === '72h') return { min: new Date(now - 12 * HOUR_MS), max: new Date(now + 60 * HOUR_MS) };
  if (window === '7d') return { min: asOf, max: new Date(now + 7 * DAY_MS) };
  return null;
}

function buildBoardQueue(assignments: ScheduleAssignment[], asOf: Date) {
  const important = assignments.filter((task) => {
    const status = deriveScheduleStatus(task, asOf);
    return status === 'late' || status === 'risk' || status === 'changeover' || status === 'running' || task.fit_level === 'marginal';
  });
  return [...(important.length ? important : assignments)].sort((a, b) => {
    const statusA = deriveScheduleStatus(a, asOf);
    const statusB = deriveScheduleStatus(b, asOf);
    return queueRank(a, statusA) - queueRank(b, statusB) || sortTime(a.plan_finish_time) - sortTime(b.plan_finish_time) || sortTime(a.start_time) - sortTime(b.start_time);
  });
}

function queueRank(task: ScheduleAssignment, status: ScheduleStatus) {
  if (status === 'late') return 0;
  if (status === 'risk') return 1;
  if (status === 'changeover') return 2;
  if (status === 'running') return 3;
  if (task.fit_level === 'marginal') return 4;
  if (status === 'pending') return 5;
  return 6;
}

function overlapsWindow(start: number, end: number, windowStart: number, windowEnd: number) {
  return start <= windowEnd && end >= windowStart;
}

function safeTime(value?: string | null) {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : time;
}

function sortTime(value?: string | null) {
  return safeTime(value) ?? Number.MAX_SAFE_INTEGER;
}

function parseDateTimeInput(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

function toDateTimeInput(date: Date) {
  const pad = (input: number) => String(input).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
