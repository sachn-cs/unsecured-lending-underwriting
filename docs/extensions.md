# Possible Extensions Review

This document reviews extensions mentioned in the paper and classifies them relative to the baseline implementation.

## Classification

- **In paper** — already part of the baseline mechanism.
- **Out of scope** — explicitly excluded by the paper; not in baseline.
- **Plausible extension** — natural addition not discussed in detail.

---

## Recovery modeling

- **Status:** Out of scope
- **Paper reference:** Section 4 ("abstract from recovery")
- **Note:** The baseline assumes total loss on default. Recovery could be modeled as a partial repayment that reduces residual loss before propagation.

## Servicing costs

- **Status:** Out of scope
- **Paper reference:** Section 4 ("abstract from servicing costs")
- **Note:** Origination, monitoring, and liquidation costs are ignored. These could be subtracted from protocol premium revenue.

## Correlated shocks

- **Status:** Out of scope
- **Paper reference:** Section 4 ("abstract from correlated shocks")
- **Note:** Defaults are treated as independent. Correlated defaults would violate the break-even rate for a given borrower because joint failure probability exceeds the sum of individual probabilities.

## Dynamic reputation

- **Status:** Out of scope
- **Paper reference:** Section 4 ("abstract from dynamic reputation")
- **Note:** Earned credit is a static accumulation. A dynamic version could let credit decay or adjust based on age of repayment history.

## Richer underwriting signals

- **Status:** Out of scope
- **Paper reference:** Section 4 ("abstract from richer underwriting signals")
- **Note:** The paper treats `D_v` as exogenous. The optional `ulu.risk_model` module supplies one estimation approach, but richer signals (on-chain behavior, social graphs) are outside scope.

## Sponsor coalition behavior

- **Status:** Out of scope
- **Paper reference:** Section 4 ("abstract from strategic coalition formation among sponsors")
- **Note:** Sponsors are modeled as independent. Collusive cartels that distort delegation or default propagation are not addressed.

## Visualization of sponsor forests

- **Status:** Plausible extension
- **Note:** Not discussed in the paper. A simple Graphviz or D3.js renderer could visualize the rooted forest, credit limits, and locked delegation.

## Monte Carlo stress testing

- **Status:** Plausible extension
- **Note:** Not discussed in the paper. Could simulate correlated default draws over the forest to measure tail risk to seed base budgets.

## Auditing and explanation tooling

- **Status:** Plausible extension
- **Note:** Not discussed in the paper. Could build a tool that, given a default event, produces a human-readable explanation of the exact loss path and buffer consumptions.
