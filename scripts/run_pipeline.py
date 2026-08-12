from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence


# The project root is the parent folder of /scripts.
#
# Example:
#   script path:  SkillBridge/scripts/run_pipeline.py
#   project root: SkillBridge/
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PipelineStepError(RuntimeError):
    """Raised when one pipeline command fails."""


def run_command(
    step_name: str,
    command: Sequence[str],
) -> None:
    """
    Run one command and stop the pipeline if it fails.

    subprocess.run() returns a process exit code:
        0     -> success
        other -> failure

    We intentionally do not use shell=True. Passing commands as a list is
    safer and works more reliably across Windows and Linux.
    """

    print()
    print("=" * 72)
    print(f"STARTING: {step_name}")
    print("=" * 72)
    print("Command:", " ".join(command))
    print()

    started_at = time.perf_counter()

    try:
        result = subprocess.run(
            list(command),
            cwd=PROJECT_ROOT,
            check=False,
        )
    except FileNotFoundError as error:
        raise PipelineStepError(
            "Docker could not be found. Make sure Docker Desktop is "
            "installed, running, and available from your terminal."
        ) from error

    elapsed_seconds = time.perf_counter() - started_at

    if result.returncode != 0:
        raise PipelineStepError(
            f"Step '{step_name}' failed with exit code "
            f"{result.returncode}."
        )

    print()
    print(f"COMPLETED: {step_name} ({elapsed_seconds:.1f} seconds)")


def wait_for_postgres(
    max_attempts: int = 30,
    delay_seconds: float = 1.0,
) -> None:
    """
    Wait until PostgreSQL reports that it is ready.

    Starting a Docker container does not always mean PostgreSQL is
    immediately ready to accept connections.

    This command runs inside the PostgreSQL container:

        pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"

    We try once per second for up to 30 seconds.
    """

    print()
    print("Waiting for PostgreSQL to become ready...")

    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
    ]

    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        if result.returncode == 0:
            print("PostgreSQL is ready.")
            return

        print(
            f"PostgreSQL is not ready yet "
            f"({attempt}/{max_attempts})..."
        )
        time.sleep(delay_seconds)

    raise PipelineStepError(
        "PostgreSQL did not become ready within the expected time."
    )


def resolve_input_file(input_value: str) -> tuple[Path, str]:
    """
    Validate the input JSON path and return:

    1. The absolute host path used for validation.
    2. The project-relative container path.

    The pipeline container mounts:

        ./data -> /app/data

    Therefore, the input file must be inside the project's data directory.
    """

    provided_path = Path(input_value)

    if provided_path.is_absolute():
        host_path = provided_path.resolve()
    else:
        host_path = (PROJECT_ROOT / provided_path).resolve()

    data_directory = (PROJECT_ROOT / "data").resolve()

    try:
        host_path.relative_to(data_directory)
    except ValueError as error:
        raise PipelineStepError(
            "The input file must be inside the project's data directory "
            "because only that directory is mounted into the pipeline "
            "container."
        ) from error

    if not host_path.exists():
        raise PipelineStepError(
            f"Input file does not exist: {host_path}"
        )

    if not host_path.is_file():
        raise PipelineStepError(
            f"Input path is not a file: {host_path}"
        )

    # Convert the path into the format visible inside the container:
    # data/sample/real_raw_sample_jobs.json
    container_path = host_path.relative_to(PROJECT_ROOT).as_posix()

    return host_path, container_path


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line options supported by the runner."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the SkillBridge bronze, silver, enrichment, "
            "and dbt pipeline."
        )
    )

    parser.add_argument(
        "--input",
        default="data/sample/real_raw_sample_jobs.json",
        help=(
            "JSON input file relative to the project root. "
            "The file must be inside the data directory."
        ),
    )

    parser.add_argument(
        "--run-name",
        default="skillbridge_full_pipeline",
        help="Name stored in metadata.pipeline_runs for the bronze load.",
    )

    skill_options = parser.add_mutually_exclusive_group()

    skill_options.add_argument(
        "--skip-skills",
        action="store_true",
        help=(
            "Skip AI skill extraction. Useful when testing only "
            "bronze, silver, role analysis, or dbt."
        ),
    )

    skill_options.add_argument(
        "--force-skills",
        action="store_true",
        help=(
            "Pass --force to the AI skill extraction script. "
            "This can increase API usage."
        ),
    )

    parser.add_argument(
        "--restart-dashboard",
        action="store_true",
        help=(
            "Restart Streamlit after dbt finishes so the dashboard "
            "reloads the rebuilt gold marts."
        ),
    )

    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        host_input_path, container_input_path = resolve_input_file(
            args.input
        )

        print()
        print("SkillBridge pipeline")
        print("-" * 72)
        print(f"Project root : {PROJECT_ROOT}")
        print(f"Input file   : {host_input_path}")
        print(f"Run name     : {args.run_name}")
        print(
            "Skill step   : "
            + (
                "skipped"
                if args.skip_skills
                else "forced"
                if args.force_skills
                else "new jobs only"
            )
        )
        print("-" * 72)

        # ====================================================
        # Step 1: PostgreSQL
        # ====================================================
        run_command(
            "Start PostgreSQL",
            [
                "docker",
                "compose",
                "up",
                "-d",
                "postgres",
            ],
        )

        wait_for_postgres()

        # ====================================================
        # Step 2: Bronze
        # ====================================================
        run_command(
            "Load raw jobs into bronze",
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "pipeline",
                "python",
                "src/loaders/load_bronze_jobs.py",
                "--input",
                container_input_path,
                "--run-name",
                args.run_name,
            ],
        )

        # ====================================================
        # Step 3: Silver job postings
        # ====================================================
        run_command(
            "Transform bronze jobs into silver",
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "pipeline",
                "python",
                "src/transformations/bronze_to_silver_jobs.py",
            ],
        )

        # ====================================================
        # Step 4: Role analysis
        # ====================================================
        run_command(
            "Analyze job roles and exclusions",
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "pipeline",
                "python",
                "src/enrichment/analyze_jobs.py",
            ],
        )

        # ====================================================
        # Step 5: AI skill extraction
        # ====================================================
        if args.skip_skills:
            print()
            print("SKIPPED: AI skill extraction")
        else:
            skill_command = [
                "docker",
                "compose",
                "run",
                "--rm",
                "pipeline",
                "python",
                "src/enrichment/extract_skills_ai.py",
            ]

            if args.force_skills:
                skill_command.append("--force")

            run_command(
                "Extract and normalize job skills",
                skill_command,
            )

        # ====================================================
        # Step 6: dbt models and tests
        # ====================================================
        run_command(
            "Build and test dbt models",
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "dbt",
                "build",
                "--profiles-dir",
                ".",
            ],
        )

        # ====================================================
        # Step 7: Optional dashboard restart
        # ====================================================
        if args.restart_dashboard:
            run_command(
                "Restart Streamlit dashboard",
                [
                    "docker",
                    "compose",
                    "restart",
                    "streamlit",
                ],
            )
        else:
            print()
            print(
                "Dashboard not restarted. Use the Streamlit "
                "'Refresh data' button to clear cached query results."
            )

    except PipelineStepError as error:
        print()
        print("=" * 72)
        print("PIPELINE FAILED")
        print("=" * 72)
        print(error)
        return 1

    print()
    print("=" * 72)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 72)
    print(
        "Bronze, silver, enrichment, dbt models, and dbt tests "
        "completed successfully."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())