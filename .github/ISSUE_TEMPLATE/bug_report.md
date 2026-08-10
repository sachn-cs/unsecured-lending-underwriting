---
name: Bug report
about: Report a defect in underwrite
title: "[BUG] "
labels: ["bug"]
assignees: []
---

## Summary

A concise description of the bug.

## Environment

- **OS**: (e.g. macOS 14.4, Ubuntu 22.04)
- **Python**: (output of `python --version`)
- **underwrite version**: (output of `python -c "import underwrite; print(underwrite.__version__)"`)
- **Store backend**: (memory / disk / sqlite / postgres)
- **Bus backend**: (local / sqs / modal)
- **Extras installed**: (e.g. `underwrite[risk,serve,postgres]`)

## Reproduction

Minimal snippet or steps to reproduce. Include a working `pytest` snippet if
possible.

```python
# Paste a minimal reproducer here
```

## Expected behaviour

What you expected to happen.

## Actual behaviour

What actually happened. Include the full traceback if applicable.

```text
Paste traceback here
```

## Impact

How severe is this bug? Does it block a release, cause data corruption, or is
it cosmetic?

## Possible cause

Optional. If you have already located the bug in the source, link the file and
line.

## Additional context

Anything else that may help — links, related issues, screenshots.
