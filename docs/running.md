# Running the Simulator

## CLI demo

```bash
PYTHONPATH=. python demo.py run-demo
PYTHONPATH=. python demo.py run-demo --state-path ./state.json
```

## API server

```bash
pip install -e ".[api]"
uvicorn ulu.api:app --host 0.0.0.0 --port 8000
```

## Endpoints

- `GET /health` — liveness
- `GET /ready` — readiness with invariant check
- `POST /seed` — add seed
- `POST /user` — add sponsored user
- `POST /quote` — price a loan
- `POST /originate` — originate a loan
- `POST /repay` — apply repayment
- `POST /default` — apply default
- `POST /revoke` — adjust delegation
- `POST /state/save` — persist state
- `POST /state/load` — restore state
- `POST /admin/reset` — reset runtime

## Python API

```python
from ulu import DelegatedUnderwriting

m = DelegatedUnderwriting()
m.add_seed("s", 100.0)
m.add_user("s", "a", 40.0)
m.add_user("a", "b", 20.0)

q = m.quote_loan("b", principal=10.0, term=1.0,
                 default_probability=0.1,
                 protocol_rate=0.2, max_delegation_rate=0.1)
print(q.total_interest)

m.originate_loan("b", principal=10.0, term=1.0,
                 default_probability=0.1,
                 protocol_rate=0.2, max_delegation_rate=0.1)

m.repay("b", 2.5)
m.assert_invariants()
```
