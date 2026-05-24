export function screeningDetailLines(item) {
  if (!item || item.screening_status === 'ready') return [];
  const recommendation = item.recommendations?.find(action => action?.guidance || action?.label);
  return [
    item.root_cause,
    recommendation?.guidance || recommendation?.label,
  ].filter(Boolean);
}
