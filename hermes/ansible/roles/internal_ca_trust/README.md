# Role: internal_ca_trust

Make hermes-30 — **host and containers** — trust Caddy's internal CA, so
`.internal` services served over TLS validate without `-k`.

## Mental Model

```
caddy-70                          hermes-30
┌──────────────┐    (commite)   ┌──────────────────────────────────┐
│ pki/.../     │ ─ ─ ─ ─ ─ ─ ─▶ │ /usr/local/share/ca-certificates/│
│  root.crt    │   files/       │        caddy-internal.crt        │
└──────────────┘                │              │                   │
                                │  update-ca-certificates          │
                                │              ▼                   │
                                │ /etc/ssl/certs/ca-certificates.crt
                                │   publiques + Caddy              │
                                │              │ bind mount :ro    │
                                │              ▼                   │
                                │  conteneur hermes : meme chemin  │
                                └──────────────────────────────────┘
```

## Why the bind mount instead of env vars

The container ships its own trust store (Debian 13). Rather than setting
`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` and `NODE_EXTRA_CA_CERTS` — each covering
one library, and which one matters depends on the HTTP client implementation —
the host bundle is mounted **at the same path** the container already reads.
Every library picks it up without knowing.

The mount lives in `hermes_agent`'s compose template, so **that role must run
after this one**: mounting the bundle before the CA is added would ship a
bundle without it.

## Two probes, on purpose

| Probe | Owned by | Proves |
|---|---|---|
| Subject present in decoded bundle | `internal_ca_trust` | the `.crt` was actually picked up |
| `https://kandidat.internal/health` without `-k`, from the host | `internal_ca_trust` | the chain validates |
| Same URL, **from inside the container** | `hermes_agent` | the agent sees it too |
| `https://api.deepseek.com/` from the container | `hermes_agent` | public trust was **not** broken |

That last one is not decoration. Mounting the host bundle over the container's
could perfectly well add the Caddy CA while dropping a public one — inference
would die, with a non-obvious cause.

## ⚠️ Do not grep the bundle for the subject

`/etc/ssl/certs/ca-certificates.crt` is a concatenation of base64 PEM blocks.
The CN appears **nowhere** in clear text. `grep "Caddy Local Authority"` returns
0 even when the CA is perfectly installed. The check decodes first:

```bash
openssl crl2pkcs7 -nocrl -certfile /etc/ssl/certs/ca-certificates.crt \
  | openssl pkcs7 -print_certs -noout | grep -c 'Caddy Local Authority'
```

Also: `update-ca-certificates` only picks up files ending in **`.crt`**. A
`.pem` dropped in that directory is ignored silently — no error, no effect.

## The committed certificate

`files/caddy-root.crt` is checked in. It is a **public root certificate**, not a
secret: `CN = Caddy Local Authority - 2026 ECC Root`, valid until 2036-02-06.

The alternative — fetching it from caddy-70 on every run — would mean adding
caddy-70 to hermes's inventory and coupling this playbook to the Caddy LXC being
up, breaking the per-subproject isolation this repo is built on.

If Caddy's PKI is ever regenerated, the committed copy goes stale and the probes
**fail loudly** on the next run. Refresh it with the runbook's command:

```bash
scp ansible@192.168.10.70:/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt \
    hermes/ansible/roles/internal_ca_trust/files/caddy-root.crt
```

See `caddy/docs/runbook-https-internal.md` §3, which documents this as a manual
per-machine step. This role automates it for hermes-30.

## Usage

```bash
cd hermes
ansible-playbook ansible/deploy.yml --tags ca      # host half
ansible-playbook ansible/deploy.yml --tags hermes  # container half (mount + probes)
```
