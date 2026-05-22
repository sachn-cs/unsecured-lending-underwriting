# Getting Started

## Installation

```bash
pip install underwrite

# With risk scoring
pip install "underwrite[risk]"

# With Postgres
pip install "underwrite[postgres]"

# Development installation
git clone https://github.com/sachn-cs/unsecured-lending-underwriting.git
cd underwrite
pip install -e ".[dev,risk,postgres]"
```

## Minimal Example

```python
from underwrite import Runtime, Configuration

config = Configuration.default()
rt = Runtime(config=config)
rt.start()
# ... your application logic ...
rt.stop()
```

## CLI

```bash
# View available services
underwrite list

# Run the mechanism and risk services
underwrite run mechanism risk

# Check runtime health
underwrite health
```

## Configuration

Create a JSON configuration file:

```json
{
    "store": {
        "backend": "filesystem",
        "dsn": "./data"
    },
    "services": {
        "mechanism": { "enabled": true },
        "risk": { "enabled": true },
        "audit": { "enabled": true }
    }
}
```

Then start with:

```bash
underwrite run --config config.json
```
