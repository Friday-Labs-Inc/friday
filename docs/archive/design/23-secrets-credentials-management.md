# 23 — Secrets & Credentials Management

> See `00-glossary.md` for term definitions.
> A leaked credential is worse than a leaked document — it grants ongoing access. This design errs strongly toward least-privilege, short-lived access, and audit.

---

## 1. Threat model

What this subsystem defends against:

1. Compromised agent prompt that tries to exfiltrate credentials.
2. Compromised skill that logs credentials.
3. Insider operator with Frappe document access who should not see raw secrets.
4. Compromised LLM provider that sees prompt context.
5. Compromised host — secrets at rest must be encrypted.
6. Log / telemetry leak — credentials accidentally captured in audit trail.
7. Memory dump of a long-running process.
8. Credential reuse across agents — one compromised agent must not expose another's secrets.

---

## 2. Storage architecture

### 2.1 Three tiers

| Tier | Where | Use case |
|---|---|---|
| **Frappe Password field** | Encrypted in the Frappe DB using the site encryption key | Default; sufficient for most secrets |
| **External Vault** (HashiCorp Vault, AWS Secrets Manager, etc.) | External service via plugin | High-value secrets requiring rotation, HSM backing, or regulatory compliance |
| **Per-execution short-lived token** | Issued at skill dispatch; expires when the container exits | Friday-internal API access from sandbox containers |

### 2.2 Credential Profile DocType

A credential is a bundle (e.g. "AWS account X = access_key + secret + region + role"), not a single string.

| Field | Type | Notes |
|---|---|---|
| `credential_code` | Data (unique) | e.g. `aws_prod_devops`, `erpnext_finance_user` |
| `description` | Text | |
| `category` | Select | API Key / DB / SSH / Cloud / ERPNext User / Service Token |
| `storage_backend` | Select | Frappe / Vault / Other |
| `vault_path` | Data (nullable) | When `storage_backend = Vault` |
| `secret_fields` | Table | Field name → encrypted value (each row uses Password type) |
| `non_secret_metadata` | JSON | Region, account ID — not sensitive |
| `permitted_role_profiles` | Table → Agent Role Profile | Which profiles may use this credential |
| `permitted_skills` | Table → Skill | Which skills may invoke it |
| `requires_approval` | Check | If true, any use generates a Workflow Request |
| `rotation_interval_days` | Int | 0 = no rotation policy |
| `last_rotated_at` | Datetime | |
| `rotation_status` | Select | Healthy / Due / Overdue / Failed |
| `status` | Select | Active / Suspended / Retired |

---

## 3. Access pattern

Credentials reach the container, never the prompt.

### 3.1 Skill declaration

```yaml
# Skill: deploy_to_aws
required_credentials:
  - credential_code: aws_prod_devops
    bind_as_env:
      access_key: AWS_ACCESS_KEY_ID
      secret_key: AWS_SECRET_ACCESS_KEY
      region:     AWS_DEFAULT_REGION
```

### 3.2 Permission gate at dispatch

```
Agent invokes deploy_to_aws
  → Gateway checks: agent.role_profile permits this skill?           (skill perm)
  → Gateway checks: agent.role_profile ∈ credential.permitted_role_profiles?
  → Gateway checks: this skill ∈ credential.permitted_skills?
  → If credential.requires_approval: create Workflow Request, pause.
  → Otherwise: fetch credential, inject into container env, run.
```

### 3.3 Container receives secrets

Container starts with credential values bound to env vars per the skill manifest. The agent's LLM context never sees the raw values. Skill code reads from env inside the container.

### 3.4 Cleanup

When the container exits, env vars die with it. No persistent file containing the credential is written.

---

## 4. Masking in logs and War Room

Every user-visible output path passes through a masker:

```python
def mask(text: str) -> str:
    """Replace known secret patterns with ***REDACTED***."""
    # Pattern-based: AWS keys, JWT, generic API keys (32+ char alphanum), passwords.
    # Plus: lookup table of currently-issued credential values.
    ...
```

Applied to:

- Execution Log `parameters` and `result` (on save).
- Chat Message content (on write).
- Frappe Communication content (on write).
- War Room messages via Raven hook (on post).
- Error messages surfaced to users.
- LLM prompt history retained for memory — the credential value is replaced with a placeholder before storage.

If a credential is accidentally embedded in a string the agent constructed, it gets masked before persistence. The original cleartext exists only in the live container.

Masking is defence-in-depth. The primary control is: **don't put credentials in agent context at all**.

---

## 5. Rotation

For credentials with `rotation_interval_days > 0`, a nightly job runs:

```python
def rotation_tick():
    overdue = frappe.get_all('Credential Profile',
        filters={'status': 'Active', 'rotation_status': 'Due'})

    for cred in overdue:
        if cred.category == 'AWS':
            rotate_aws_access_key(cred)
        elif cred.category == 'API Key':
            notify_admin_to_rotate_manually(cred)
        # ...

        if rotation_succeeded:
            cred.last_rotated_at = now()
            cred.rotation_status = 'Healthy'
        else:
            cred.rotation_status = 'Failed'
            escalate(cred)
```

Some categories (AWS access keys, generated service tokens) rotate automatically. Others (vendor-specific keys) require a human to fetch and update. Status is tracked either way.

---

## 6. Audit

Three log surfaces.

### 6.1 Credential Access Log

Submittable; one row per credential read.

| Field | Type |
|---|---|
| `credential` | Link → Credential Profile |
| `accessed_by_agent` | Link → Agent Profile |
| `for_skill` | Link → Skill |
| `for_execution` | Link → Execution Log |
| `accessed_at` | Datetime |
| `purpose` | Text — auto-generated (e.g. "skill X requested AWS credentials") |
| `result` | Select (granted / denied / approval_pending) |

### 6.2 Workflow Request

When `requires_approval` triggers, request + decision recorded per `05-module-design.md`.

### 6.3 Rotation log

Each rotation attempt logged with outcome on the Credential Profile.

The three together answer: "On date D, agent A accessed credential C for execution E, approved by user U."

---

## 7. One user per agent (credential forensics)

A critical case whenever an agent acts on records on a user's behalf.

Naive setup: one shared API user across all Friday agents. Audit trail says "API User created record #123" — useless for forensics.

Friday's pattern:

1. **System Manager Agent** has elevated permissions and a corresponding Credential Profile.
2. On project setup, it creates one platform user per agent: `research.agent@friday.local`, `support.agent@friday.local`, and so on.
3. Each user receives:
   - The appropriate role (e.g. Note Writer, Knowledge User).
   - An API key + secret.
   - Stored as a Credential Profile in Friday, scoped to that specific Agent Profile.
4. The Friday Agent Profile links to its user via `linked_user`.
5. When the agent invokes a skill, it uses **its own** credentials, never a shared service account.

The audit then shows "research.agent created record #123" — full forensic clarity.

---

## 8. Multi-tenant per-site isolation

Each site is a separate Friday tenant. Credentials are strictly site-scoped:

- Each site has its own encryption key.
- Credential Profiles in site A are not readable from site B.
- Cross-site agent communication (`37-multi-site-inter-agent-communication.md`) uses inter-site tokens through a separate trust path — never shared secrets.
- Friday Labs multi-tenant hosting maintains separate stores per tenant.

---

## 9. Bootstrapping at install time

Friday needs initial secrets (LLM provider key, optional Vault address). Configuration paths:

| Method | Use case |
|---|---|
| `bench set-config` | Local dev; encrypted in site config |
| Environment variables read at startup | Container deployments (Docker Compose, Kubernetes) |
| Vault auto-fetch | Production; site authenticates to Vault, fetches initial secrets |
| Framework Console first-run wizard | Operator pastes; immediately encrypted as Password field |

Bootstrap secrets are the weakest link by definition. Minimise their scope, rotate them often, store them with the same care as production keys.

---

## 10. Residual risks

| Risk | Status |
|---|---|
| Compromised container reads its own env vars | Accepted — only that execution's credentials at risk; container is short-lived |
| LLM prompt with embedded credential reaches the model | Mitigated by never putting credentials in prompt; cannot be fully eliminated if a buggy skill violates this |
| Frappe encryption key compromise | Mitigated by Vault for high-value secrets; full compromise still possible at OS level |
| Memory dump of running container | Accepted — same risk class as any production system |
| Social engineering of approval flow | Mitigated by multi-supervisor approval on high-risk skills |
| Insider with DB access bypasses Frappe permissions | Mitigated by Vault for high-value secrets; DB-only access does not yield Vault contents |

---

## 11. Operator hardening checklist (production)

- [ ] Site encryption key stored outside the Frappe site (env var or external KMS).
- [ ] Vault integration enabled for `Critical`-risk credentials.
- [ ] All credentials have rotation policies (no infinite-lived keys).
- [ ] Network egress from worker containers restricted to known target hosts.
- [ ] Framework Console access to Credential Profile restricted to a single `Credential Admin` role.
- [ ] Credential Access Log retention ≥ 1 year for compliance.
- [ ] Quarterly review of credential usage; retire unused credentials.
- [ ] Encryption keys backed up separately from data backups.
- [ ] Disaster-recovery plan for Vault unavailability documented.

---

## 12. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Frappe Password fields; per-execution scoped tokens for ERPNext; basic masking |
| 2 | Vault integration plugin; Credential Access Log; rotation for AWS-style credentials |
| 3 | Auto-rotation across more categories; masking calibration; KMS for site encryption keys |
| 4 | HSM support; multi-region Vault replication; compliance attestations |

Phase 1 must include masking and per-execution tokens. Vault is optional but recommended for production.
