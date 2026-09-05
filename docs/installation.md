# Installation

`amp_push` is not yet published to PyPI. For now, install it directly from
this repository:

```bash
uv add "amp_push @ git+https://github.com/philhendren/amp_push"
# or
pip install "amp_push @ git+https://github.com/philhendren/amp_push"
```

Once it's published, this will become the usual:

```bash
pip install amp_push
```

## Requirements

- Python 3.11+
- AWS credentials resolvable through boto3's normal credential chain
  (environment variables, a shared config/credentials file, an attached
  role, ...) - `amp_push` doesn't manage credentials itself, it just signs
  with whatever `boto3.Session()` finds.
- An [AWS Managed Prometheus](https://aws.amazon.com/prometheus/) workspace
  to write to, and credentials with `aps:RemoteWrite` on it - see
  [Usage](usage.md#required-iam-permission).
