export function ErrorNotice({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "请求失败";
  return <div className="error-notice">{message}</div>;
}
