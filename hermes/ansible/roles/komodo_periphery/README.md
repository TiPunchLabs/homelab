# Role: komodo_periphery

Connect **hermes-30** to the Komodo Core running on dockhost-90, as a
**read-only observer**. Deploys the Periphery agent as a Docker Compose stack.

## Mental Model

```
┌─ dockhost-90 ─────────┐        ┌─ hermes-30 ───────────────────────┐
│ komodo-core   :9120   │◀═══════│ komodo-periphery                  │
│ (role dockhost/komodo)│  ws:// │  ↳ docker.sock  :ro  ← the fence   │
└───────────────────────┘outbound│  ↳ /proc, keys (named volume)     │
                                 │                                   │
  Server "hermes-30"             │ hermes / hermes-dashboard          │
  visible in the UI              │  ↳ still owned by `hermes_agent`   │
                                 └───────────────────────────────────┘
```

The connection is **outbound**: Periphery dials Core, never the reverse. UFW on
hermes-30 is untouched by this role — nothing to open.

## The fence

`/var/run/docker.sock` is mounted **read-only**. Komodo can list containers,
read logs, stream stats, run `inspect`. It **cannot** start, stop, restart or
remove anything — the Docker daemon itself refuses.

This makes "observe only" a property of the system rather than a discipline.
Ansible (`hermes_agent`) stays the sole controller of the Hermes stack.

> To let Komodo restart Hermes from the UI, set
> `komodo_periphery_docker_socket_mode: "rw"`. Understand what you give up:
> Periphery could then also destroy the stack Ansible owns.

## Required Vault secret

In `hermes/ansible/group_vars/hermes/vault/config.yml`:

```yaml
vault_komodo_onboarding_key: "O-..."
```

Generate it in the Komodo UI: **Settings → Onboarding → Create Onboarding Key**.

## ⚠️ The onboarding key is single-use

Core exchanges it, on first contact, for the public key Periphery generates —
then discards it. The private key now lives in the `keys` named volume on
hermes-30. **That volume is the server's identity.**

| Situation | Result |
|---|---|
| Playbook replayed, volume intact | Key in the env file is inert. Agent authenticates with the volume. ✅ |
| `docker compose down` (no `-v`) | Volume survives. Agent reconnects. ✅ |
| `docker compose down -v`, VM rebuilt | Agent regenerates a keypair Core rejects. **Crash loop.** ❌ |

### Re-onboarding procedure

Needed whenever the `keys` volume is lost:

1. Komodo UI → **Servers** → delete `hermes-30`
2. **Settings → Onboarding** → create a **new** key
3. `ansible-vault edit hermes/ansible/group_vars/hermes/vault/config.yml` →
   replace `vault_komodo_onboarding_key`
4. `ansible-playbook ansible/deploy.yml --tags komodo-periphery`

The role's final assertion catches this case: a `docker compose up` that
"succeeds" while the agent crash-loops would otherwise leave the playbook
entirely green with the server disconnected.

## Playbook usage

```bash
cd hermes
ansible-playbook ansible/deploy.yml --tags komodo-periphery
```

Then check the UI at `https://komodo.internal` → Servers → **hermes-30** green,
with `hermes` and `hermes-dashboard` listed.

## Why `ws://` and not `https://komodo.internal`

Caddy serves that vhost with an internal CA the Periphery container does not
carry. Installing it there would be wasted effort: the Core↔Periphery channel
is encrypted by a **Noise handshake**, independent of TLS. Nothing readable
crosses the LAN.

## Note on upstream docs

The upstream docsite shows a Periphery compose example using
`KOMODO_CORE_ADDRESS` / `KOMODO_CONNECT_AS` / `KOMODO_ONBOARDING_KEY`. Those
names are wrong. The v2 reference config declares `Env: PERIPHERY_*`, which is
also what the working `compose.env` on dockhost uses.
