"""
Sentinel Aerial Inspections — Pipeline Status Reporter

Shared utility for all drone-pipeline scripts to report their execution status
back to the Supabase processing_jobs table.

Usage in each script:
    from pipeline_status import PipelineStatusReporter

    reporter = PipelineStatusReporter(
        processing_job_id=args.processing_job_id,
        step_name="video_color_grade",
    )
    reporter.start()
    try:
        # ... do work ...
        reporter.complete(output="12 videos graded")
    except Exception as e:
        reporter.fail(str(e))
        raise

The reporter is a no-op if --processing-job-id is not provided, so scripts
remain fully functional when run manually outside of n8n.
"""

import os
import logging
import json
from datetime import datetime, timezone
from typing import Optional

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_client():
    """Return a Supabase client or None if credentials are missing."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception as e:
        log.warning(f"Supabase client creation failed: {e}")
        return None


class PipelineStatusReporter:
    """Reports step-level status to processing_jobs.steps JSONB array.

    All methods are non-fatal: if Supabase is unreachable, errors are logged
    at WARNING level and the script continues normally.

    Args:
        processing_job_id: UUID of the processing_jobs row. None for manual runs.
        step_name: Name of the step this script handles (matches the JSONB step.name).
    """

    def __init__(self, processing_job_id: Optional[str], step_name: str):
        self.processing_job_id = processing_job_id
        self.step_name = step_name
        self._client = None
        self._active = bool(processing_job_id and SUPABASE_URL and SUPABASE_SERVICE_KEY)

        if self._active:
            self._client = _get_client()
            if not self._client:
                self._active = False
                log.warning(
                    "PipelineStatusReporter: Supabase client unavailable. "
                    "Status will not be reported."
                )

    def _fetch_job(self):
        """Fetch the current processing_jobs row."""
        if not self._active:
            return None
        try:
            result = self._client.table("processing_jobs") \
                .select("steps, status") \
                .eq("id", self.processing_job_id) \
                .single() \
                .execute()
            return result.data
        except Exception as e:
            log.warning(f"PipelineStatusReporter: fetch failed: {e}")
            return None

    def _update_step(self, patch: dict) -> bool:
        """Patch the matching step in the steps JSONB array."""
        if not self._active:
            return False

        job = self._fetch_job()
        if not job:
            return False

        steps = job.get("steps", [])
        if not isinstance(steps, list):
            steps = []

        step_idx = next(
            (i for i, s in enumerate(steps) if s.get("name") == self.step_name),
            None
        )

        if step_idx is None:
            log.warning(
                f"PipelineStatusReporter: step '{self.step_name}' not found in job "
                f"{self.processing_job_id}"
            )
            return False

        steps[step_idx] = {**steps[step_idx], **patch}

        # Determine job-level status from steps
        statuses = [s.get("status", "pending") for s in steps]
        if "failed" in statuses:
            job_status = "failed"
        elif "running" in statuses:
            job_status = "running"
        elif "awaiting_manual_edit" in statuses:
            job_status = "awaiting_manual_edit"
        elif all(s == "complete" for s in statuses):
            job_status = "complete"
        else:
            job_status = "running"

        update_data = {"steps": steps}
        if job_status == "complete":
            update_data["status"] = "complete"
            update_data["completed_at"] = _now_iso()
        elif job_status == "failed":
            update_data["status"] = "failed"
            # Set top-level error_message from the failed step
            failed_steps = [s for s in steps if s.get("status") == "failed"]
            if failed_steps:
                update_data["error_message"] = failed_steps[0].get("error", "Unknown error")
        elif job_status == "running":
            update_data["status"] = "running"
            update_data["current_step"] = self.step_name

        try:
            self._client.table("processing_jobs") \
                .update(update_data) \
                .eq("id", self.processing_job_id) \
                .execute()
            return True
        except Exception as e:
            log.warning(f"PipelineStatusReporter: update failed: {e}")
            return False

    def start(self) -> bool:
        """Mark step as running with started_at timestamp."""
        if not self._active:
            return False
        log.info(f"PipelineStatusReporter: step '{self.step_name}' starting")
        return self._update_step({
            "status": "running",
            "started_at": _now_iso(),
            "error": None,
        })

    def complete(self, output: Optional[str] = None) -> bool:
        """Mark step as complete with completed_at timestamp."""
        if not self._active:
            return False
        log.info(f"PipelineStatusReporter: step '{self.step_name}' complete")
        patch = {
            "status": "complete",
            "completed_at": _now_iso(),
        }
        if output is not None:
            patch["output"] = output
        return self._update_step(patch)

    def fail(self, error_message: str) -> bool:
        """Mark step as failed with error message."""
        if not self._active:
            return False
        log.warning(f"PipelineStatusReporter: step '{self.step_name}' failed: {error_message}")
        return self._update_step({
            "status": "failed",
            "completed_at": _now_iso(),
            "error": error_message[:2000],  # Truncate long stack traces
        })

    def await_manual_edit(self, message: Optional[str] = None) -> bool:
        """Mark step as awaiting_manual_edit (V5 pause point)."""
        if not self._active:
            return False
        log.info(f"PipelineStatusReporter: step '{self.step_name}' awaiting manual edit")
        patch = {
            "status": "awaiting_manual_edit",
        }
        if message:
            patch["output"] = message

        result = self._update_step(patch)

        # Also update job-level status
        if result and self._active:
            try:
                self._client.table("processing_jobs") \
                    .update({"status": "awaiting_manual_edit", "current_step": self.step_name}) \
                    .eq("id", self.processing_job_id) \
                    .execute()
            except Exception as e:
                log.warning(f"PipelineStatusReporter: awaiting_manual_edit job update failed: {e}")

        return result


def add_pipeline_args(parser) -> None:
    """Add --processing-job-id argument to any argparse parser.

    Call this in every script's argument setup to enable status reporting.

    Example:
        parser = argparse.ArgumentParser(...)
        add_pipeline_args(parser)
        args = parser.parse_args()
        reporter = PipelineStatusReporter(args.processing_job_id, "my_step")
    """
    parser.add_argument(
        "--processing-job-id",
        default=None,
        help="Supabase processing_jobs UUID (provided by n8n, optional for manual runs)",
    )
    parser.add_argument(
        "--step-name",
        default=None,
        help="Override the default step_name for PipelineStatusReporter (for scripts serving multiple paths)",
    )
