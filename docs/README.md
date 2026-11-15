# HandOver documentation

The root [README](../README.md) is the product and setup overview. This page routes maintainers to the source of truth for a specific concern.

## Build and operate

| Topic | Document |
| --- | --- |
| Contributor setup and change rules | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Local hub setup, configuration, and tests | [server/README.md](../server/README.md) |
| Release evidence and validation matrix | [validation.md](validation.md) |
| Runtime operations and troubleshooting | [server/docs/operations.md](../server/docs/operations.md) |
| Desktop application | [apps/desktop/README.md](../apps/desktop/README.md) |
| Databricks setup and failure recovery | [databricks/README.md](../databricks/README.md) |

## Understand the system

| Topic | Document |
| --- | --- |
| Product narrative and architecture | [project.md](project.md) |
| Hub/client protocol and compatibility | [CONTRACT.md](../CONTRACT.md) |
| Learn engine, ordering, and state | [server/docs/engine.md](../server/docs/engine.md) |
| Vision checks, motion gate, and breaker | [server/docs/checks.md](../server/docs/checks.md) |
| Recording-to-lesson pipeline | [server/docs/teach.md](../server/docs/teach.md) |
| Accounts, organizations, courses, and editor | [server/docs/library.md](../server/docs/library.md) |
| Local voice generation and mixing | [voice.md](voice.md) |
| Produced course-video rendering | [server/docs/production.md](../server/docs/production.md) |

## Trust, data, and measurement

| Topic | Document |
| --- | --- |
| Data inventory, boundaries, and retention | [privacy.md](privacy.md) |
| Event schema, profile metrics, and sinks | [analytics.md](analytics.md) |
| Databricks workspace runbook | [databricks/README.md](../databricks/README.md) |
| Experimental understanding mode | [server/docs/understanding.md](../server/docs/understanding.md) |

## Product specifications

- [Screen and behavior specification](../apps/design/SCREENS.md)
- [Theme catalog](../apps/design/THEMES.md)
- Apple feature notes live beside their Swift sources under `apps/apple/Sources/Features/`.
- Android feature notes live beside their Kotlin sources under `apps/android/app/src/main/kotlin/com/handover/app/ui/`.

## Research notes

Files under `docs/research/` and documents prefixed `RESEARCH_` are exploratory context. They may contain dated comparisons or unvalidated possibilities. They are not runtime, privacy, compatibility, or release claims; the documents above take precedence.
