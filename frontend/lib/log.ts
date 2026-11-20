// Server-side logging with the same fields as Django (backend/modules/log):
// one line per event on stdout, JSON in production, colored columns in development.
// Channels: request (proxy.ts), error (instrumentation.ts).

type Level = "info" | "warning" | "error";
type Fields = { request_id?: string; [key: string]: unknown };

export function log(
  level: Level,
  channel: string,
  event: string,
  fields: Fields = {},
) {
  if (process.env.NODE_ENV === "production") {
    const line = {
      event,
      ...fields,
      level,
      timestamp: new Date().toISOString(),
      service: "frontend",
      channel,
    };
    console.log(JSON.stringify(line));
    return;
  }
  console.log(pretty(level, channel, event, fields));
}

// The colors and layout of structlog's ConsoleRenderer, so `make dev` reads
// the same on both sides: dim time, [level], bold `channel  id  event`, then
// key=value. A stack goes on the lines below, dimmed.
const ansi = (code: string) => (text: string) => `\x1b[${code}m${text}\x1b[0m`;
const dim = ansi("2");
const bold = ansi("1");
const key = ansi("36");
const value = ansi("35");
const levelColor = {
  info: ansi("32;1"),
  warning: ansi("33;1"),
  error: ansi("31;1"),
};

function pretty(level: Level, channel: string, event: string, fields: Fields) {
  const { request_id = "-", stack, ...rest } = fields;
  const head = `${channel.padEnd(7)}  ${request_id.padEnd(8)}  ${event}`;
  const extra = Object.entries(rest)
    .filter(([, v]) => v !== undefined)
    .map(
      ([k, v]) =>
        `${key(k)}=${value(typeof v === "string" ? v : JSON.stringify(v))}`,
    )
    .join(" ");
  const line = [
    dim(new Date().toISOString()),
    `[${levelColor[level](level.padEnd(9))}]`,
    bold(head.padEnd(30)),
    extra,
  ]
    .filter(Boolean)
    .join(" ");
  return typeof stack === "string" ? `${line}\n${dim(stack)}` : line;
}
