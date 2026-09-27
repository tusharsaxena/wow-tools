"""Command-line front end. With no CLI-mode flags it opens the TUI instead."""
from __future__ import annotations

import argparse
import json
import sys

from wowtools.core.backup import BackupError
from wowtools.core.config import Config
from wowtools.core.events import get_event_log, log_event, log_exception
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_native
from wowtools.core.process import wow_check_for
from wowtools.core.updater import UpdateCheck
from wowtools.tools.wtf_cleaner.cleaner import CleanError, execute
from wowtools.tools.wtf_cleaner.report import (format_proposal_text, format_result_text, format_size,
                                               proposal_to_dict, result_to_dict)
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria, evaluate
from wowtools.tools.wtf_cleaner.safety import read_marker, recovery_message
from wowtools.tools.wtf_cleaner.scanner import ScanError, scan
from wowtools.tools.wtf_cleaner.settings import DEFAULT_BACKUP_SUBDIR, SECTION, load_settings, resolve_backup_dir

EXIT_OK, EXIT_USAGE, EXIT_SCAN, EXIT_PARTIAL, EXIT_BACKUP = 0, 1, 2, 3, 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m wowtools wtf-cleaner",
        description="Find and remove stale addon SavedVariables, backing them up to a zip first. "
                    "Without --flavor, --clean, --json or --dry-run the interactive TUI opens.")
    parser.add_argument("--flavor", help="retail, classic, classic_era, anniversary, ... (default: last used)")
    parser.add_argument("--account", metavar="NAME", help="scan only this account (default: all accounts)")
    parser.add_argument("--clean", action="store_true", help="back up and delete the proposal (asks first)")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--dry-run", action="store_true", help="write the backup zip but delete nothing")
    parser.add_argument("--no-backup", action="store_true", help="skip the zip backup (requires --yes)")
    parser.add_argument("--max-age", type=int, metavar="DAYS", help="override max_age_days")
    parser.add_argument("--criteria", metavar="LIST", help=f"comma list from: {', '.join(CRITERIA)}")
    parser.add_argument("--wow-path", metavar="PATH", help="override the configured WoW folder")
    parser.add_argument("--backup-dir", metavar="PATH", help="override the configured backup folder")
    parser.add_argument("--json", action="store_true", help="machine-readable output on stdout")
    parser.add_argument("--tui", action="store_true", help="open the TUI even if other flags are given")
    return parser


def main(argv: list[str], *, cfg: Config | None = None, stdout=None, stderr=None, input_fn=input,
         wow_check=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    cfg = cfg if cfg is not None else Config().load()

    if args.tui or not any([args.flavor, args.clean, args.json, args.dry_run]):
        get_event_log().set_context(mode="tui")
        from wowtools.tools.wtf_cleaner.app import WtfCleanerApp

        WtfCleanerApp(cfg).run()
        return EXIT_OK

    get_event_log().set_context(mode="cli")
    checker = UpdateCheck(cfg).start() if cfg.check_for_updates and not args.json else None
    try:
        return _run(args, cfg, stdout, stderr, input_fn, wow_check)
    finally:
        notice = checker.notice() if checker else None
        if notice:
            print(notice, file=stderr)


def _override(section: str, key: str, old, new) -> None:
    log_event("config.changed", section=section, key=key, old=old, new=str(new), source="cli", persisted=False)


def _run(args, cfg: Config, stdout, stderr, input_fn, wow_check) -> int:
    def out(text: str) -> None:
        print(text, file=stdout)

    def err(text: str) -> None:
        print(text, file=stderr)

    if args.wow_path:
        wow_path = to_native(args.wow_path)
        _override("general", "wow_path", cfg.get("general", "wow_path"), args.wow_path)
    else:
        wow_path = cfg.wow_path
    if wow_path is None:
        err("No WoW folder is configured. Run the TUI once (python -m wowtools wtf-cleaner) or pass --wow-path.")
        return EXIT_USAGE
    install = WowInstall(wow_path)
    if not install.is_valid():
        err(f"No WoW flavor folders (_retail_, _classic_ ...) were found in {wow_path}.")
        return EXIT_USAGE
    flavor_name = args.flavor or cfg.last_flavor
    if not flavor_name:
        err("No flavor given. Pass --flavor (for example: --flavor retail).")
        return EXIT_USAGE
    flavor = install.flavor(flavor_name)
    if flavor is None:
        available = ", ".join(f.short_name for f in install.flavors())
        err(f"Unknown flavor {flavor_name!r}. Available: {available}")
        return EXIT_USAGE
    log_event("ui.selection", screen="cli", control="flavor", value=flavor.folder)
    account = None
    if args.account:
        names = sorted((a.name for a in flavor.accounts()), key=str.casefold)
        account = next((n for n in names if n.casefold() == args.account.strip().casefold()), None)
        if account is None:
            err(f"Unknown account {args.account!r} in {flavor.display_name}. "
                f"Available: {', '.join(names) or 'none'}")
            return EXIT_USAGE
        log_event("ui.selection", screen="cli", control="account", value=account)

    settings = load_settings(cfg)
    criteria = settings.criteria
    if args.criteria is not None or args.max_age is not None:
        names = ([n.strip() for n in args.criteria.split(",") if n.strip()]
                 if args.criteria is not None else criteria.enabled_names())
        max_age = args.max_age if args.max_age is not None else criteria.max_age_days
        if max_age < 1:
            err("--max-age must be at least 1 day.")
            return EXIT_USAGE
        try:
            criteria = Criteria.from_names(names, max_age)
        except ValueError as exc:
            err(str(exc))
            return EXIT_USAGE
        if args.criteria is not None:
            _override(SECTION, "criteria", settings.criteria.enabled_names(), ",".join(names))
        if args.max_age is not None:
            _override(SECTION, "max_age_days", settings.criteria.max_age_days, max_age)

    backup = settings.backup_before_delete and not args.no_backup
    override = None
    if args.backup_dir:
        override = to_native(args.backup_dir)
        _override(SECTION, "backup_dir", cfg.get(SECTION, "backup_dir"), args.backup_dir)
    elif args.wow_path and settings.backup_dir is None:
        override = wow_path / DEFAULT_BACKUP_SUBDIR  # the default follows a --wow-path override too
    backup_dir = resolve_backup_dir(cfg, settings, override)

    marker = read_marker(backup_dir)
    if marker is not None:  # never restored automatically; the TUI's Dismiss is what removes the marker
        log_event("recovery.incomplete_clean", flavor=marker.flavor, started=marker.started,
                  snapshot=str(marker.snapshot), files=len(marker.files))
        err(recovery_message(marker))

    try:
        result_scan = scan(flavor, account=account)
    except ScanError as exc:
        log_exception("scan", exc)
        err(str(exc))
        return EXIT_SCAN
    proposal = evaluate(result_scan, criteria)

    if not args.clean:
        out(json.dumps(proposal_to_dict(proposal, flavor, account=account), indent=2, ensure_ascii=False) if args.json
            else format_proposal_text(proposal, flavor, account=account))
        return EXIT_OK
    if args.no_backup and not args.yes:
        err("--no-backup is only allowed together with --yes.")
        return EXIT_USAGE
    if args.json and not (args.yes or args.dry_run):
        err("--json with --clean needs --yes or --dry-run (there is no prompt in JSON mode).")
        return EXIT_USAGE
    if not proposal.items:
        out(json.dumps({"proposal": proposal_to_dict(proposal, flavor, account=account), "result": None}, indent=2)
            if args.json else "Nothing to clean.")
        return EXIT_OK
    if not args.json:
        out(format_proposal_text(proposal, flavor, account=account))

    running = (wow_check or wow_check_for(flavor))()
    if running:
        log_event("wow.running_warning", executables=running)
        err(f"Warning: WoW appears to be running ({', '.join(running)}). Close it first: "
            "WoW rewrites SavedVariables when you log out.")

    if not args.yes and not args.dry_run:
        answer = input_fn(f"Back up and delete {proposal.total_files} files "
                          f"({format_size(proposal.total_size)})? [y/N] ")
        confirmed = answer.strip().lower() in ("y", "yes")
        log_event("ui.selection", screen="cli", control="confirm", value=confirmed)
        if not confirmed:
            out("Aborted. Nothing was changed.")
            return EXIT_OK

    stage_lines = {"snapshot": "Taking safety snapshot…", "backup": "Writing backup…"}
    if not args.dry_run:
        stage_lines["delete"] = "Deleting…"
    last_stage: list[str] = []

    def on_progress(stage: str, current: int, total: int, detail: str) -> None:
        if last_stage and last_stage[-1] == stage:
            return  # stage changes only, never one line per file
        last_stage.append(stage)
        if stage in stage_lines:
            out(stage_lines[stage])

    try:
        result = execute(proposal.items, flavor, dry_run=args.dry_run, backup=backup, backup_dir=backup_dir,
                         progress=None if args.json else on_progress)
    except BackupError as exc:
        err(f"Backup failed, nothing was deleted: {exc}")
        return EXIT_BACKUP
    except CleanError as exc:
        log_exception("clean", exc)
        err(str(exc))
        return EXIT_USAGE
    if args.json:
        out(json.dumps({"proposal": proposal_to_dict(proposal, flavor, account=account), "result": result_to_dict(result)},
                       indent=2, ensure_ascii=False))
    else:
        out("")
        out(format_result_text(result))
    return EXIT_PARTIAL if result.failed else EXIT_OK
