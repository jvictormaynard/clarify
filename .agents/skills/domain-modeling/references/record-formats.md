# Project record formats

For a glossary change, add only a stable term, its meaning, and any distinction
needed to prevent confusion in `docs/agents/domain.md`. Link the owned implementation
contract when needed. Keep pending product questions out of the glossary.

For a durable accepted design choice, use `docs/adr/<NNNN>-<slug>.md` with:

```markdown
# <Decision title>

Date: <decision date>
Status: <accepted, proposed, or superseded>

## Context

The actual requirement, current constraint, and supporting source.

## Decision

The chosen owner/interface and why it satisfies the requirement.

## Alternatives

The meaningful alternatives and the reason they were not chosen.

## Consequences

Compatibility, migration, costs, risks, and validation.
```

An agent can record an accepted decision within the authorized work. Mark a proposal
as proposed when the user still needs to choose. Do not create a record for a
routine implementation detail or label a historical inference as a confirmed decision.
