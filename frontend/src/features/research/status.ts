export function isTerminalRunStatus(status: string): boolean {
  return ["COMPLETED", "FAILED", "CANCELLED"].includes(status);
}
