#!/usr/bin/env python3
"""Adversarial Stress Harness for M2: Patch Traversal, Rollback Security & Cache Invalidation.

Empirical verification suite for Challenger M2-1:
1. Adversarial Manifest Rollback Testing:
   - Path traversal payloads in orig_path (escaping REPO_ROOT & SITE_PACKAGES).
   - System root targets (C:\\Windows\\..., user profiles, etc.).
   - UNC paths (\\\\server\\share).
   - Prefix confusion attacks (repo_fake vs repo).
   - Path traversal payloads in bak_path (escaping backup_dir).
   - System files as bak_path.
   - Legitimate restore validation.
2. CLI --report Path Traversal Testing:
   - Upward relative traversals (../, ../../).
   - Absolute paths outside repo (C:\\Windows, C:\\temp).
   - UNC paths.
   - Prefix confusion paths.
   - Legitimate in-repo reports.
3. _get_tracked_targets() and Cache Invalidation Testing:
   - Completeness check across all PATCH_SPECS.
   - Specific verification of preferences.py and webadapter.py.
   - Dynamic tracking when PATCH_SPECS is mutated.
   - Cache invalidation when preferences.py or webadapter.py is modified.
   - Cache invalidation when new specs are added or files removed.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from typing import Any
from unittest import mock

if hasattr(sys.stdout, "reconfigure") and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure") and getattr(sys.stderr, "encoding", "").lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure tools directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import importlib.util

spec = importlib.util.spec_from_file_location("apply_patches", os.path.join(TOOLS_DIR, "apply-patches.py"))
if spec and spec.loader:
    apply_patches = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(apply_patches)
else:
    raise RuntimeError("Failed to load apply-patches.py")

# Mute standard logger during stress run to keep benchmark readable
apply_patches.logger.setLevel(logging.CRITICAL)


def run_m2_adversarial_stress():
    print("=" * 80)
    print("CHALLENGER M2-1: ADVERSARIAL STRESS HARNESS -- PATCH TRAVERSAL & ROLLBACK")
    print("=" * 80)

    summary: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "manifest_orig_path_tests": [],
        "manifest_bak_path_tests": [],
        "cli_report_tests": [],
        "tracked_targets_tests": [],
        "cache_invalidation_tests": [],
        "all_passed": True,
    }

    # =========================================================================
    # SUITE 1: Adversarial Manifest Rollback -- orig_path Traversal & Escapes
    # =========================================================================
    print("\n--- SUITE 1: Adversarial Manifest Rollback (orig_path Containment) ---")

    orig_traversal_payloads = [
        ("Relative upward escape (../outside.txt)", "../outside_file.txt"),
        ("Double relative upward escape (../../outside.txt)", "../../outside_file.txt"),
        ("Triple relative upward escape (../../../escape.txt)", "../../../escape.txt"),
        ("System root target (C:\\Windows\\System32\\cmd.exe)", r"C:\Windows\System32\cmd.exe"),
        ("System drivers hosts (C:\\Windows\\System32\\drivers\\etc\\hosts)", r"C:\Windows\System32\drivers\etc\hosts"),
        ("System Windows directory (C:\\Windows\\win.ini)", r"C:\Windows\win.ini"),
        (
            "User profile sensitive target",
            os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\Default"), ".ssh", "authorized_keys"),
        ),
        ("UNC server path (\\\\127.0.0.1\\c$\\exploit.txt)", r"\\127.0.0.1\c$\exploit.txt"),
        ("UNC remote share (\\\\attacker\\share\\payload.dll)", r"\\attacker\share\payload.dll"),
        ("Root relative path (\\Windows\\System32\\calc.exe)", r"\Windows\System32\calc.exe"),
        ("Drive root escape (D:\\outside\\evil.txt)", r"D:\outside\evil.txt"),
        (
            "Prefix collision escape (repo_fake\\file.txt)",
            os.path.abspath(apply_patches.REPO_ROOT) + "_fake" + os.sep + "file.txt",
        ),
        (
            "Subdirectory relative escape inside repo targeting root (tools\\..\\..\\outside.txt)",
            os.path.join(apply_patches.REPO_ROOT, "tools", "..", "..", "outside.txt"),
        ),
    ]

    for desc, orig_payload in orig_traversal_payloads:
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            bak_file = os.path.join(backup_dir, "test.bak")
            with open(bak_file, "w", encoding="utf-8") as f:
                f.write("malicious overwrite attempt")

            manifest = {orig_payload: bak_file}
            with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            tx = apply_patches.PatchTransaction(backup_dir=backup_dir)
            restored = tx.rollback()

            resolved_orig = os.path.abspath(orig_payload)
            target_overwritten = False
            if os.path.exists(resolved_orig):
                try:
                    with open(resolved_orig, "r", encoding="utf-8", errors="ignore") as f:
                        if f.read() == "malicious overwrite attempt":
                            target_overwritten = True
                except OSError:
                    pass

            is_rejected = (len(restored) == 0) and not target_overwritten

            if not is_rejected:
                summary["all_passed"] = False
                print(f"  [FAIL] {desc} -> NOT REJECTED! (restored={restored})")
            else:
                print(f"  [PASS] {desc} -> REJECTED (boundary enforced)")

            summary["manifest_orig_path_tests"].append(
                {
                    "payload": orig_payload,
                    "description": desc,
                    "passed": is_rejected,
                }
            )

    # =========================================================================
    # SUITE 2: Adversarial Manifest Rollback -- bak_path Traversal & Escapes
    # =========================================================================
    print("\n--- SUITE 2: Adversarial Manifest Rollback (bak_path Containment) ---")

    bak_traversal_payloads = [
        ("Relative upward escape (../outside.bak)", "../outside.bak"),
        ("Double relative upward escape (../../outside.bak)", "../../outside.bak"),
        ("Triple relative upward escape (../../../outside.bak)", "../../../outside.bak"),
        ("Targeting system file as backup (C:\\Windows\\win.ini)", r"C:\Windows\win.ini"),
        ("UNC path as backup (\\\\attacker\\share\\fake.bak)", r"\\attacker\share\fake.bak"),
        ("Backup dir prefix collision (backups_fake\\file.bak)", "fake_prefix"),
    ]

    for desc, bak_payload in bak_traversal_payloads:
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            if bak_payload == "fake_prefix":
                actual_bak = os.path.abspath(backup_dir) + "_fake" + os.sep + "file.bak"
                os.makedirs(os.path.dirname(actual_bak), exist_ok=True)
                with open(actual_bak, "w", encoding="utf-8") as f:
                    f.write("fake prefix content")
            else:
                actual_bak = bak_payload

            mock_repo = os.path.join(tmpdir, "mock_repo")
            os.makedirs(mock_repo, exist_ok=True)
            valid_target = os.path.join(mock_repo, "sub", "target.py")

            manifest = {valid_target: actual_bak}
            with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            tx = apply_patches.PatchTransaction(backup_dir=backup_dir)
            with mock.patch.object(apply_patches, "REPO_ROOT", mock_repo):
                restored = tx.rollback()

            is_rejected = (len(restored) == 0) and not os.path.exists(valid_target)

            if not is_rejected:
                summary["all_passed"] = False
                print(f"  [FAIL] {desc} -> NOT REJECTED! (restored={restored})")
            else:
                print(f"  [PASS] {desc} -> REJECTED (boundary enforced)")

            summary["manifest_bak_path_tests"].append(
                {
                    "payload": bak_payload,
                    "description": desc,
                    "passed": is_rejected,
                }
            )

    # Also test positive authorized rollback
    print("\n--- SUITE 2b: Authorized Rollback Functional Restoration ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        backup_dir = os.path.join(tmpdir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        mock_repo = os.path.join(tmpdir, "mock_repo")
        os.makedirs(mock_repo, exist_ok=True)

        target_file = os.path.join(mock_repo, "legit.py")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("corrupted/patched content")

        bak_file = os.path.join(backup_dir, "legit.bak")
        with open(bak_file, "w", encoding="utf-8") as f:
            f.write("original pristine content")

        manifest = {target_file: bak_file}
        with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        tx = apply_patches.PatchTransaction(backup_dir=backup_dir)
        with mock.patch.object(apply_patches, "REPO_ROOT", mock_repo):
            restored = tx.rollback()

        restored_content = ""
        if os.path.exists(target_file):
            with open(target_file, "r", encoding="utf-8") as f:
                restored_content = f.read()

        restored_ok = len(restored) == 1 and restored_content == "original pristine content"
        if restored_ok:
            print("  [PASS] Authorized rollback cleanly restored original content")
        else:
            print(f"  [FAIL] Authorized rollback failed! (restored={restored})")
            summary["all_passed"] = False

    # =========================================================================
    # SUITE 3: CLI --report Path Traversal & Escapes
    # =========================================================================
    print("\n--- SUITE 3: CLI --report Path Traversal Containment ---")

    report_payloads = [
        ("Relative upward escape (../report.json)", "../report.json", False),
        ("Double relative upward escape (../../report.json)", "../../report.json", False),
        ("Absolute path outside repo (C:\\temp\\report.json)", r"C:\temp\report.json", False),
        ("System root target (C:\\Windows\\report.json)", r"C:\Windows\report.json", False),
        ("Other drive target (D:\\report.json)", r"D:\report.json", False),
        ("UNC share target (\\\\attacker\\share\\report.json)", r"\\attacker\share\report.json", False),
        ("Prefix collision path", os.path.abspath(apply_patches.REPO_ROOT) + "_evil" + os.sep + "report.json", False),
        ("Valid repo root report (test_cli_rep.json)", "test_cli_rep.json", True),
        ("Valid subdirectory report (python/test_rep.json)", os.path.join("python", "test_rep.json"), True),
    ]

    for desc, r_payload, should_succeed in report_payloads:
        with mock.patch("sys.argv", ["apply-patches.py", "--check", "--report", r_payload]):
            raised_value_error = False
            try:
                apply_patches.main()
            except ValueError as ve:
                if "Report output must reside within repository directory" in str(ve):
                    raised_value_error = True
            except SystemExit:
                pass

            passed = False
            if not should_succeed and raised_value_error:
                passed = True
                print(f"  [PASS] {desc} -> REJECTED (ValueError raised as expected)")
            elif should_succeed and not raised_value_error:
                passed = True
                print(f"  [PASS] {desc} -> ACCEPTED (Valid path within REPO_ROOT)")
                abs_rep = os.path.abspath(r_payload)
                if os.path.exists(abs_rep):
                    try:
                        os.remove(abs_rep)
                    except OSError:
                        pass
            else:
                summary["all_passed"] = False
                print(
                    f"  [FAIL] {desc} -> UNEXPECTED (should_succeed={should_succeed}, raised_value_error={raised_value_error})"
                )

            summary["cli_report_tests"].append(
                {
                    "payload": r_payload,
                    "description": desc,
                    "passed": passed,
                }
            )

    # =========================================================================
    # SUITE 4: _get_tracked_targets() Completeness & Invalidation
    # =========================================================================
    print("\n--- SUITE 4: _get_tracked_targets() Coverage & Completeness ---")

    tracked_targets = apply_patches._get_tracked_targets()
    print(f"  Total tracked targets: {len(tracked_targets)}")

    missing_specs = []
    for spec_item in apply_patches.PATCH_SPECS:
        abs_target = os.path.abspath(spec_item.target_path)
        if abs_target not in tracked_targets:
            missing_specs.append(spec_item.name)

    if missing_specs:
        print(f"  [FAIL] Missing targets from PATCH_SPECS: {missing_specs}")
        summary["all_passed"] = False
    else:
        print(f"  [PASS] 100% of {len(apply_patches.PATCH_SPECS)} PATCH_SPECS are tracked")

    pref_path = os.path.abspath(os.path.join(apply_patches.SITE_PACKAGES, "searx", "preferences.py"))
    webadapter_path = os.path.abspath(os.path.join(apply_patches.SITE_PACKAGES, "searx", "webadapter.py"))

    if pref_path in tracked_targets:
        print("  [PASS] searx/preferences.py is explicitly tracked")
    else:
        print("  [FAIL] searx/preferences.py is NOT tracked")
        summary["all_passed"] = False

    if webadapter_path in tracked_targets:
        print("  [PASS] searx/webadapter.py is explicitly tracked")
    else:
        print("  [FAIL] searx/webadapter.py is NOT tracked")
        summary["all_passed"] = False

    mock_spec = apply_patches.PatchSpec(
        name="Mock Dynamic Patch",
        target_path=os.path.join(apply_patches.SITE_PACKAGES, "searx", "mock_target.py"),
        description="Dynamic test",
        patch_func=lambda c, f: c,
    )
    apply_patches.PATCH_SPECS.append(mock_spec)
    updated_tracked = apply_patches._get_tracked_targets()
    apply_patches.PATCH_SPECS.pop()

    dynamic_tracked_ok = os.path.abspath(mock_spec.target_path) in updated_tracked
    if dynamic_tracked_ok:
        print("  [PASS] _get_tracked_targets() dynamically tracks newly appended PATCH_SPECS")
    else:
        print("  [FAIL] _get_tracked_targets() failed to dynamically track appended spec")
        summary["all_passed"] = False

    # =========================================================================
    # SUITE 5: Cache Invalidation Mechanics
    # =========================================================================
    print("\n--- SUITE 5: Cache Invalidation Mechanics ---")

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_cache_file = os.path.join(tmpdir, "cache.json")
        mock_repo = os.path.join(tmpdir, "repo")
        os.makedirs(mock_repo, exist_ok=True)

        target1 = os.path.join(mock_repo, "preferences.py")
        target2 = os.path.join(mock_repo, "webadapter.py")
        with open(target1, "w", encoding="utf-8") as f:
            f.write("# preferences code")
        with open(target2, "w", encoding="utf-8") as f:
            f.write("# webadapter code")

        with (
            mock.patch.object(apply_patches, "CACHE_FILE", mock_cache_file),
            mock.patch.object(apply_patches, "REPO_ROOT", mock_repo),
            mock.patch.object(apply_patches, "_get_tracked_targets", return_value=[target1, target2]),
        ):
            apply_patches.save_patch_cache()
            self_valid = apply_patches.is_patch_cache_valid()
            if self_valid:
                print("  [PASS] Initial cache fingerprint is VALID")
            else:
                print("  [FAIL] Initial cache fingerprint is INVALID")
                summary["all_passed"] = False

            time.sleep(0.01)
            with open(target1, "a", encoding="utf-8") as f:
                f.write("\n# modified preferences")
            pref_invalidated = not apply_patches.is_patch_cache_valid()
            if pref_invalidated:
                print("  [PASS] Modifying preferences.py immediately INVALIDATES cache")
            else:
                print("  [FAIL] Modifying preferences.py did NOT invalidate cache")
                summary["all_passed"] = False

            apply_patches.save_patch_cache()

            time.sleep(0.01)
            with open(target2, "a", encoding="utf-8") as f:
                f.write("\n# modified webadapter")
            web_invalidated = not apply_patches.is_patch_cache_valid()
            if web_invalidated:
                print("  [PASS] Modifying webadapter.py immediately INVALIDATES cache")
            else:
                print("  [FAIL] Modifying webadapter.py did NOT invalidate cache")
                summary["all_passed"] = False

            apply_patches.save_patch_cache()

            target3 = os.path.join(mock_repo, "new_file.py")
            with open(target3, "w", encoding="utf-8") as f:
                f.write("# new file")
            with mock.patch.object(apply_patches, "_get_tracked_targets", return_value=[target1, target2, target3]):
                new_spec_invalidated = not apply_patches.is_patch_cache_valid()
                if new_spec_invalidated:
                    print("  [PASS] Adding new target to tracked list immediately INVALIDATES cache")
                else:
                    print("  [FAIL] Adding new target did NOT invalidate cache")
                    summary["all_passed"] = False

    print("\n" + "=" * 80)
    if summary["all_passed"]:
        print("ALL ADVERSARIAL STRESS SUITES PASSED (100% REJECTION OF TRAVERSALS)")
    else:
        print("SOME STRESS SUITES FAILED")
    print("=" * 80)

    return summary


if __name__ == "__main__":
    res = run_m2_adversarial_stress()
    sys.exit(0 if res["all_passed"] else 1)
