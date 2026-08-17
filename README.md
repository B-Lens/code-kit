# Common Workflows

Reusable GitHub Actions for Codex-assisted pull-request review and repository
automation. These workflows were extracted from the Orbit project and made
repository-neutral.

## Included workflows

| Workflow | Purpose | GitHub permissions |
| --- | --- | --- |
| `pr-code-review.yml` | Reviews a pull request, posts one updated review comment, and fails on blocking findings | `contents: read`, `pull-requests: write` |
| `codex-automation.yml` | Implements labeled issues and applies requested review changes to same-repository pull-request branches | `contents: write`, `issues: read`, `pull-requests: write` |

All workflows pin the Codex CLI version, configure Ubuntu's AppArmor profile for
Bubblewrap user namespaces, run Codex ephemerally, keep GitHub credentials out of
the Codex process, and delete Codex authentication after use.

## Setup

1. Add an Actions secret named `CODEX_AUTH_JSON` to the consuming repository.
   Its value is the complete, unencoded content of a Codex CLI `auth.json` file.
2. For write-capable automation, create a protected GitHub environment named
   `Codex-Automation` and require approval from a trusted reviewer.
3. Copy the desired caller files from [`examples/`](examples/) into the consuming
   repository's `.github/workflows/` directory.
4. Adjust inputs such as `review_prompt`, `extra_instructions`, `base_branch`, and
   `reviewer` for the repository.
5. Create the `ai-autonomous` and `codex` labels if issue automation is enabled.

Callers should pin a release tag or commit SHA. The examples use `@v1` for the
stable major release line.

## Custom review policy

The default review prompt is language- and project-neutral. A caller can supply
domain-specific safety rules:

```yaml
jobs:
  review:
    uses: ipankaj18/code-kit/.github/workflows/pr-code-review.yml@v1
    with:
      review_prompt: |
        Review this change as a strict production-safety gate.
        Focus on concrete correctness, security, and data-integrity defects.
        Ignore style and pre-existing issues outside the diff.
    secrets:
      CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}
```

## Trust and security model

Issue bodies, reviews, and repository content are untrusted input. The workflows
instruct Codex not to expose credentials or change GitHub state. Checkout does not
persist credentials; authentication is configured only after Codex exits.

The write-capable automation workflow deliberately requires a protected environment. Generated
changes are committed for review, never merged. Keep branch protection and normal
CI enabled, review generated diffs, and rotate `CODEX_AUTH_JSON` if any log,
artifact, or commit appears to contain credentials.

Pull requests from forks are reviewed only when the caller's secret policy allows
the job to run. Automated repair skips fork branches because the repository token
cannot safely push to them.

## Versioning

Breaking changes are released under a new major tag. Consumers should use a major
tag such as `v1` for updates within a compatible line, or a full commit SHA for
maximum supply-chain control.
