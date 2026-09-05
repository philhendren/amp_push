#!/usr/bin/env python3
r"""A minimal CLI wrapping amp_push - push one metric, then exit.

    uv run python examples/push_metric.py \
        --workspace-id ws-xxxx --region eu-west-2 \
        --metric-name job_duration_seconds --value 12.4 \
        --label job=etl-daily

Or, if you only know the workspace's alias, not its id:

    uv run python examples/push_metric.py \
        --workspace-alias prod-services --region eu-west-2 \
        --metric-name job_duration_seconds --value 12.4 \
        --label job=etl-daily

`--workspace-id` and `--workspace-alias` are mutually exclusive - pass
exactly one. Resolving an alias needs `aps:ListWorkspaces`, a separate IAM
permission from `aps:RemoteWrite` - see src/amp_push/README.md.

This is an example of using the amp_push library, not part of the `snow`
CLI - it imports only amp_push, click, and the standard library, so it can
move with amp_push into its own repo/examples folder later without carrying
any of this project's other code with it.

Credentials are assumed to already be in place (environment variables, an
assumed role, a shared config file, ...): this reads them through boto3's
normal credential chain and does nothing to configure them itself. See
src/amp_push/README.md for what IAM permission the credentials need.
"""

from __future__ import annotations

import sys

import click
import requests

from amp_push import AMPClient, Metric


def _parse_label(raw: str) -> tuple[str, str]:
    """Parse one `--label KEY=VALUE` option into a (key, value) pair."""
    key, separator, value = raw.partition("=")
    if not separator or not key or not value:
        message = f"--label must be KEY=VALUE, got {raw!r}"
        raise click.BadParameter(message)
    return key, value


@click.command()
@click.option(
    "--workspace-id",
    envvar="AMP_WORKSPACE_ID",
    default=None,
    help="AWS Managed Prometheus workspace to push to, e.g. ws-xxxx. "
    "Mutually exclusive with --workspace-alias.",
)
@click.option(
    "--workspace-alias",
    envvar="AMP_WORKSPACE_ALIAS",
    default=None,
    help="AWS Managed Prometheus workspace alias, e.g. prod-services - "
    "looked up via aps:ListWorkspaces. Mutually exclusive with --workspace-id.",
)
@click.option(
    "--region",
    envvar="AWS_REGION",
    required=True,
    help="AWS region the workspace is in.",
)
@click.option(
    "--metric-name",
    required=True,
    help="Prometheus metric name, e.g. job_duration_seconds.",
)
@click.option(
    "--value",
    type=float,
    default=1.0,
    show_default=True,
    help="Metric value. Defaults to 1 - the usual value for a 'this happened' event.",
)
@click.option(
    "--label",
    "labels",
    multiple=True,
    metavar="KEY=VALUE",
    help="A metric label. Repeatable, e.g. --label outcome=success --label service=x.",
)
@click.option(
    "--timeout",
    type=float,
    default=10.0,
    show_default=True,
    help="HTTP timeout in seconds for the remote_write request.",
)
def push_metric(
    workspace_id: str | None,
    workspace_alias: str | None,
    region: str,
    metric_name: str,
    value: float,
    labels: tuple[str, ...],
    timeout: float,
) -> None:
    """Push one metric to AWS Managed Prometheus via amp_push."""
    label_pairs = (_parse_label(label) for label in labels)
    try:
        metric = Metric(metric_name, value, labels=dict(label_pairs))
    except ValueError as error:
        message = f"Invalid metric: {error}"
        raise click.ClickException(message) from error

    try:
        client = AMPClient(
            workspace_id=workspace_id,
            workspace_alias=workspace_alias,
            region=region,
            timeout=timeout,
        )
    except ValueError as error:
        # --workspace-id/--workspace-alias, not the metric - a usage error.
        raise click.UsageError(str(error)) from error

    try:
        client.push([metric])
    except RuntimeError as error:
        # No AWS credentials found - see the module docstring.
        raise click.ClickException(str(error)) from error
    except ValueError as error:
        # --workspace-alias resolved to zero or more than one workspace -
        # only possible once push() actually needs the id, not at
        # construction (see AMPClient.workspace_id).
        raise click.ClickException(str(error)) from error
    except requests.RequestException as error:
        # AMP rejected the request, or a network-level failure (timeout,
        # DNS, connection refused, ...).
        message = f"Failed to push to AMP: {error}"
        raise click.ClickException(message) from error

    click.echo(
        f"Pushed {metric.name}{metric.wire_labels()} "
        f"to workspace {client.workspace_id!r}.",
    )


if __name__ == "__main__":
    sys.exit(push_metric())
