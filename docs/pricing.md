# Pricing

## Protocol premium

Compensates the protocol for expected default loss.

```
I^R = r^R * L_v * T
```

Break-even rate (Theorem 5):

```
r^R >= D_v / ((1 - D_v) * T)
```

## Delegation premium

Compensates sponsors for locked delegation along the unique sponsor path.

```
r^D = r^D_max * (1 - U^D)
```

where `U^D` is seed-level delegation utilization.

Locked delegation on edge `(u_k, u_{k+1})`:

```
m_k = max(0, L_v - B_k)
```

Sponsor payout:

```
payout(u_k) = r^D * m_k * T
```

Total delegation premium:

```
I^D = sum(payouts)
```

Budget-balanced by construction.

## Quote a loan

```python
quote = mechanism.quote_loan(
    borrower="v",
    principal=10.0,
    term=1.0,
    default_probability=0.1,
    protocol_rate=0.2,
    max_delegation_rate=0.1,
)
print(quote.total_interest)  # I^R + I^D
```
