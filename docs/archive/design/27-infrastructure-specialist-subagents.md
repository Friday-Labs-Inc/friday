# 27 — Infrastructure Specialist Sub-Agents

> See `00-glossary.md` for term definitions.
> Application of `25-domain-specialized-agent-profiles.md` to infrastructure work. Phase: not in v0.1 per `42-phase-one-authority-contract.md` §3. Phase 2+.

---

## 1. Why specialise infrastructure

A generic "DevOps agent" trying to handle Kubernetes, Terraform, Ansible, and Docker Compose is a jack-of-all-trades. It carries hundreds of skills, consumes massive context, and produces mediocre results. Per `15-openclaw-insights-friday-refinements.md`, specialised agents outperform generalists by 30–60% in token usage and 20–40% in task completion rate.

This doc defines five infrastructure specialists and the coordinator that routes work between them.

---

## 2. Kubernetes Specialist

**Identity:** A senior SRE who deeply knows Kubernetes (1.28+).

**Skills (≤ 30):** `k8s_manifest_validate` (`kubeval`, `kubeconform`), `k8s_helm_lint`, `k8s_helm_template_render`, `k8s_kubectl_dry_run`, `k8s_describe_resource`, `k8s_logs_fetch`, `k8s_event_query`, `k8s_pod_diagnose` (CrashLoopBackOff, ImagePullBackOff), `k8s_resource_quota_check`, `k8s_rbac_audit`, `k8s_network_policy_review`, `k8s_psp_or_pss_check`, `k8s_secret_rotate_plan` (plan only, never execute), `k8s_hpa_recommend`, `k8s_node_drain_plan`, `helm_release_history`, `argocd_app_sync_status`.

**Knowledge bundle:** Kubernetes 1.28–1.31 documentation; controller pattern references (HPA, VPA, KEDA); production incident playbooks; Pod Security Standards, NetworkPolicy and ResourceQuota templates.

**Forbidden without explicit approval:** `kubectl apply`, `helm upgrade`, `kubectl delete`, secret modification, RBAC changes.

---

## 3. Terraform Specialist

**Identity:** An IaC engineer fluent in Terraform/OpenTofu and the AWS, GCP, and Azure provider semantics.

**Skills (≤ 30):** `tf_format_check` (`terraform fmt -check`), `tf_validate`, `tf_plan_run`, `tf_plan_explain` (risk analysis: creates / destroys / replaces), `tf_state_inspect` (read-only), `tf_module_lint` (`tflint`), `tf_security_scan` (`tfsec`, `checkov`), `tf_cost_estimate` (`infracost`), `tf_drift_detect`, `tf_module_doc_generate`, `tf_workspace_list`, `tf_provider_version_audit`.

**Knowledge bundle:** Terraform/OpenTofu language reference; provider snapshots (aws, google, azurerm, kubernetes, helm); standard module patterns (VPC, EKS, GKE); common pitfalls (`count` vs `for_each`, state drift, provider auth).

**Forbidden without approval:** `terraform apply`, `terraform destroy`, state surgery (`terraform state rm`, `terraform import`).

---

## 4. Ansible Specialist

**Identity:** A configuration-management engineer fluent in Ansible playbook design and idempotency.

**Skills (≤ 25):** `ansible_lint_playbook`, `ansible_syntax_check`, `ansible_check_mode_run` (`--check --diff`), `ansible_inventory_validate`, `ansible_role_dependency_graph`, `ansible_vault_inspect` (references only, no decrypt), `ansible_galaxy_role_audit`, `ansible_idempotency_test`.

**Knowledge bundle:** Ansible core docs; community role best practices; common idempotency patterns (file state, package state, service state).

**Forbidden without approval:** non-check-mode plays against production inventory.

---

## 5. Docker Compose Specialist

**Identity:** Engineer fluent in multi-container local and small-production deployments.

**Skills (≤ 20):** `compose_validate`, `compose_config_render`, `compose_lint` (anti-patterns: latest tag, missing healthchecks, missing resource limits), `compose_dependency_graph`, `compose_secret_audit`, `compose_network_review`, `compose_volume_audit`, `compose_resource_recommend`.

**Knowledge bundle:** Compose file v3.x reference; production hardening checklists; migration patterns to Kubernetes when scale demands.

---

## 6. Linux SysAdmin Specialist

**Identity:** A sysadmin for any Linux box that does not fit a higher abstraction.

**Skills (≤ 30):** `systemd_unit_validate`, `systemd_status_inspect`, `journal_query`, `cron_validate`, `firewalld_or_ufw_audit`, `ssh_config_review`, `sysctl_recommend`, `disk_health_check` (`smartctl` reads), `lvm_inspect`, `package_audit`, `user_permission_audit`.

**Knowledge bundle:** systemd manual; common distros (Ubuntu LTS, Debian stable, RHEL / Alma / Rocky); hardening guides (CIS Linux benchmarks).

---

## 7. Infrastructure Coordinator

**Identity:** A platform-engineering lead who does no hands-on work but routes tasks and reconciles cross-cutting concerns.

**Skills:**

- `dispatch_to_specialist` — primary; selects one of the five specialists for a task.
- `cross_specialist_review` — when changes span multiple domains, requests review from all relevant specialists.
- `infra_change_plan_compose` — assembles a multi-step plan that spans specialists.
- `war_room_announce` — posts plan summary to Raven.

The coordinator never executes domain tasks. It always delegates.

---

## 8. Routing logic

The coordinator inspects:

1. File extensions and repo paths: `.tf` → Terraform; `Chart.yaml`, `kustomization.yaml`, `*.k8s.yaml` → Kubernetes; `playbook.yml`, `roles/` → Ansible; `docker-compose.yml`, `compose.yaml` → Compose; `/etc/systemd/`, raw shell → Linux SysAdmin.
2. Explicit task tags: `#k8s`, `#tf`, etc.
3. War Room thread context if any prior decisions narrowed scope.

Ambiguous cases → coordinator asks the supervisor in War Room.

---

## 9. Multi-specialist coordination

**Example:** "Provision a new EKS cluster, deploy our standard Helm charts, and update Ansible inventory for the bastion."

The coordinator:

1. Creates a parent Agent Task with three sub-tasks.
2. Sub-task A → Terraform Specialist (EKS provisioning).
3. Sub-task B → Kubernetes Specialist (Helm deployment, depends on A).
4. Sub-task C → Ansible Specialist (inventory update, depends on A).
5. Each specialist completes its sub-task and posts to the War Room thread.
6. Coordinator runs `cross_specialist_review` if any specialist flags concerns.
7. Final summary goes to supervisor for end-of-flow approval.

---

## 10. Boundaries (anti-patterns prevented)

- A Terraform Specialist asked to "also fix the Ansible playbook" rejects and routes back through the Coordinator.
- A K8s Specialist asked to `kubectl apply` without supervisor approval refuses.
- The Coordinator does not execute domain tasks even if it "knows how" — separation of concerns is enforced.

Encoded in the Agent Role Profile per `12-refinement-agent-roles-and-features.md` and enforced by the permission gate.

---

## 11. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Not in scope per `42-phase-one-authority-contract.md` §3 |
| 2 | Kubernetes Specialist and Docker Compose Specialist — the two most relevant for ERPNext deployment and Friday's own infrastructure |
| 3 | Terraform, Ansible, Linux SysAdmin specialists; Infrastructure Coordinator |
| 4 | Cross-cloud Terraform specialisation; community-contributed specialists |

---

## 12. Open questions

- Should specialist persona system prompts be auto-generated from the Role Profile or hand-authored? Hand-author at Phase 2; auto-generate consideration at Phase 3.
- Cross-cloud Terraform (AWS + GCP in one project): single specialist or split? Single, with provider-tagged sub-skills.
- Tools without a dedicated specialist (Pulumi, Chef, Puppet): fall back to an Infrastructure Generalist with reduced confidence and explicit escalation triggers.
