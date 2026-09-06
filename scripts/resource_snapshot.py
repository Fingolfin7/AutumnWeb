"""Read bounded provider metrics without connecting to the application database.

Use the authenticated Neon CLI and either RENDER_API_KEY or Render CLI credentials.
Only metrics are written; credentials and full project responses are never saved.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def render_key():
    if os.environ.get("RENDER_API_KEY"):
        return os.environ["RENDER_API_KEY"]
    import yaml  # Development dependency; never imported by the web application.

    config = yaml.safe_load((Path.home() / ".render" / "cli.yaml").read_text())
    return config["api"]["key"]


def render_metric(key, service, metric, start, end):
    params = {
        "resource": service,
        "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if metric != "bandwidth":
        params["resolutionSeconds"] = 900
    request = Request(
        "https://api.render.com/v1/metrics/" + metric + "?" + urlencode(params),
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        return {"unavailable_http_status": exc.code}
    except (URLError, TimeoutError):
        return {"unavailable": "Provider request failed or timed out"}


def neon_counters(project):
    executable = shutil.which("neon") or shutil.which("neonctl")
    if not executable:
        return {"unavailable": "Neon CLI not found"}
    # IDs are validated before invoking a Windows .cmd launcher. No shell text
    # or provider credentials are interpolated into the command.
    try:
        result = subprocess.run(
            [executable, "api", "/projects/" + project, "-o", "json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"unavailable": "Neon CLI failed or timed out"}
    if result.returncode:
        return {"unavailable": "Neon CLI request failed"}
    data = json.loads(result.stdout)["project"]
    return {name: data.get(name) for name in (
        "compute_time_seconds", "active_time_seconds", "data_transfer_bytes",
        "written_data_bytes", "synthetic_storage_size",
        "consumption_period_start", "consumption_period_end", "updated_at",
    )}


def counter_delta(before, after):
    """Never treat a billing reset or unavailable counter as usage savings."""
    if not before.get("consumption_period_start") or (
        before.get("consumption_period_start") != after.get("consumption_period_start")
    ):
        return {"unavailable": "Consumption period changed or is unavailable"}
    result = {}
    for name in ("compute_time_seconds", "active_time_seconds", "data_transfer_bytes", "written_data_bytes"):
        first, last = before.get(name), after.get(name)
        if isinstance(first, (int, float)) and isinstance(last, (int, float)) and last >= first:
            result[name] = last - first
        else:
            result[name] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-service", required=True)
    parser.add_argument("--neon-project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if not 1 <= args.hours <= 168:
        parser.error("--hours must be between 1 and 168")
    for value in (args.render_service, args.neon_project):
        if not re.fullmatch(r"[a-z0-9-]+", value):
            parser.error("Provider IDs must contain only lowercase letters, digits, and hyphens")
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=args.hours)
    snapshot = {
        "captured_at": end.isoformat(), "render_window_start": start.isoformat(),
        "render_service": args.render_service, "neon_project": args.neon_project,
        "neon": neon_counters(args.neon_project), "render": {},
    }
    try:
        key = render_key()
    except (OSError, KeyError, ImportError):
        snapshot["render"] = {"unavailable": "Render credentials or PyYAML unavailable"}
    else:
        for metric in ("cpu", "memory", "http-requests", "bandwidth"):
            snapshot["render"][metric] = render_metric(key, args.render_service, metric, start, end)
    if args.compare:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        if baseline.get("neon_project") != args.neon_project:
            parser.error("Baseline belongs to a different Neon project")
        snapshot["neon_delta_since_baseline"] = counter_delta(baseline["neon"], snapshot["neon"])
        snapshot["baseline_captured_at"] = baseline["captured_at"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"Saved provider metrics to {args.output}")
    if "neon_delta_since_baseline" in snapshot:
        print(json.dumps(snapshot["neon_delta_since_baseline"]))


if __name__ == "__main__":
    main()
