# Revocation

## Rule

A sponsor may reduce (or increase) delegation to a child only if the subtree rooted at the child remains solvent.

## Required delegation

```python
required = mechanism.required_delegation("child")
```

This is the minimum delegation `R_v` that must remain on the edge into `v`.

## Adjust delegation

```python
mechanism.revoke("sponsor", "child", new_delegation=required)
```

- `new_delegation` must be `>= required`
- If `new_delegation` is larger than the current amount, the sponsor must have enough free `credit_limit` to cover the delta.

## What happens

If the new delegation is below `required`, an `InfeasibleOperationError` is raised because the subtree would become insolvent.
