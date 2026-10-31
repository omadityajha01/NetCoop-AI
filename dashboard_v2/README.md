# dashboard_v2

Put new UIs here. The built-in dashboard (`netcoop/api/static/`) stays the default and is unchanged.

```
netcoop serve --ui dashboard_v2              # real backend: index.html at /, files at /ui/<path>
python tools/mock_api.py --ui dashboard_v2   # no backend: recorded fixtures on the same endpoints
```

Rules (enforced by the server's headers and by review):
- Content-Security-Policy: `default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self';
  base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. That means no CDN, no inline `<script>` or `style=""`,
  no remote fonts, and every request goes to the same origin.
- Render data with `textContent` / `setAttribute`, never `innerHTML` (PI8). Device names, limitations and LLM text are
  data.
- Allowed file types under `/ui/`: .html .js .mjs .css .json .svg .png .jpg .ico .woff2 .txt
- API, SSE stream, payloads and glossary: [`docs/FRONTEND_API.md`](../docs/FRONTEND_API.md). Recorded streams:
  [`docs/frontend_fixtures/`](../docs/frontend_fixtures/).
