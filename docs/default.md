# Default Handling

## Rule

When borrower `u` defaults on principal `x_u > 0`:

1. Burn the borrower's earned credit: `G_u -= min(G_u, x_u)`.
2. Propagate residual loss `\ell = x_u - min(G_u, x_u)` up the sponsor path.
3. At each sponsor `v` on the path:
   - Reduce delegation `a_{v \to j}` by current `\ell`.
   - Burn sponsor earned credit: `G_v -= min(G_v, \ell)`.
   - Reduce `\ell` by the amount absorbed.
4. If a seed is reached with remaining `\ell > 0`, charge the remainder to the seed's base budget `\hat{E}_s`.
5. Set `x_u = 0`.

## Invariants preserved

- Every upstream node (other than the borrower) retains its credit limit.
- Aggregate credit capacity falls by exactly `x_u`.
- No delegation edge is overdrawn (guaranteed by Theorem 3).

## API

```python
mechanism.default("borrower")
mechanism.assert_invariants()
```
