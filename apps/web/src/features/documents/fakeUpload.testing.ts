// Test support only (not imported by the application).

/** XMLHttpRequest stand-in: the test decides when and how each upload answers. */
export class FakeUpload {
  static sent: FakeUpload[] = [];
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  responseType = "";
  status = 0;
  statusText = "";
  response: unknown = null;
  url = "";
  headers: Record<string, string> = {};
  body: unknown = null;
  open(_method: string, url: string) {
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  responseHeaders: Record<string, string> = {};
  getResponseHeader(name: string) {
    return this.responseHeaders[name] ?? null;
  }
  send(body: unknown) {
    this.body = body;
    FakeUpload.sent.push(this);
  }
  abort() {}
  answer(status: number, body: unknown, headers: Record<string, string> = {}, statusText = "") {
    this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 1 } as ProgressEvent);
    this.status = status;
    this.statusText = statusText;
    this.responseHeaders = headers;
    this.response = body;
    this.onload?.();
  }
}

