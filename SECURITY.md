# Security

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private vulnerability reporting
(Security tab → "Report a vulnerability") on this repository once it is public. Include steps to reproduce and the
impact. Expect a first reply within a week.

## What the project protects against

- **The Obscura binary.** It is pinned to a version and SHA256, and re-verified before every launch.
  It runs under macOS `sandbox-exec`: no reads of your home folder (except its own), writes only to its
  temp dir, and inbound connections only on localhost. Its CDP port needs a random per-launch token.
- **Private networks.** localhost, LAN and cloud-metadata addresses are blocked on **both** engines
  unless you set `allow_private_network`. Hostnames that resolve to those addresses are blocked too.
- **Prompt injection from pages.** Page content is wrapped in `<page untrusted="true">`, and hidden text
  (`display:none`, off-screen, `aria-hidden`, tiny fonts) is dropped from snapshots. This *reduces* the
  risk; it does not remove it. Agents must still treat page text as data.
- **Secrets.** Password field values are never shown. Uploads are limited to absolute paths inside
  `allowed_upload_dirs`.
- **Repeated side effects.** Submits, payments, deletes and sends are never retried automatically, and
  repeating one after an uncertain or successful outcome needs an explicit `value="repeat"`. `dry_run`
  previews an action without dispatching it.

## Traces

- **Off by default.** Turn them on with `--trace`, `trace = true` or `LEANB_TRACE=1`.
- **Local only.** Traces are stored in `~/.lean-browser/traces/` (folder `700`, files `600`) and are
  never uploaded.
- **Kept until you delete them.** Use `leanb trace delete latest|all|<run>`.
- **Redacted by default:**
  - values typed into password fields, and into fields that look like card numbers, CVVs, one-time
    codes, PINs, tokens, secrets or ID numbers;
  - sensitive URL parameters (token, code, key, session, signature, …), which become `REDACTED`.
- **No page text by default.** A record keeps only the status and header lines. Full page text is
  stored only with `trace_page_text = true`.
- **Exports.** `leanb trace export` writes a `600` file and reminds you to review it before sharing.

## Known limits

- The sandbox only applies to Obscura. Chromium is Playwright's bundled build with a throwaway profile.
- Visible text written to manipulate agents still reaches the agent, inside the untrusted wrapper.
- Only macOS (Apple Silicon) is supported and tested.
