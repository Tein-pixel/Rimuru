#!/usr/bin/env python3
# patch_apk.py — ML Tools Rimuru Firebase Premium Bypass
# Target: com.LbzToolss | Smali patch via apktool

import os
import re
import sys
import shutil
import subprocess
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
log = logging.getLogger("rimuru_patch")

INPUT_APK    = "original.apk"
DECODED_DIR  = "rimuru_decoded"
OUTPUT_APK   = "rimuru_patched.apk"

TARGET_STRINGS = [
    "Your account has been expired",
    "Redeem Now Premium",
    "Status : ",
    "banned_users",
    "checkPremiumStatus",
    "premium",
    "expired",
    "device_lock",
]

TARGET_ACTIVITIES = [
    "PreActivity.smali",
    "OuhActivity.smali",
    "MainActivity.smali",
]

def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    log.info(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        log.info(result.stdout.strip())
    if result.stderr.strip():
        log.warning(result.stderr.strip())
    if check and result.returncode != 0:
        log.error(f"Command failed: {' '.join(cmd)}")
        sys.exit(1)
    return result

def decompile():
    if Path(DECODED_DIR).exists():
        log.info(f"Removing existing decoded dir: {DECODED_DIR}")
        shutil.rmtree(DECODED_DIR)

    log.info(f"Decompiling {INPUT_APK} ...")
    run(["apktool", "d", INPUT_APK, "-o", DECODED_DIR, "--force"])
    log.info(f"Decompile complete → {DECODED_DIR}/")

def find_smali_dirs() -> list[Path]:
    base = Path(DECODED_DIR)
    dirs = sorted([d for d in base.iterdir() if d.is_dir() and d.name.startswith("smali")])
    log.info(f"Found smali dirs: {[d.name for d in dirs]}")
    return dirs

def score_file_for_target(filepath: Path) -> int:
    try:
        content = filepath.read_text(errors="replace")
    except Exception:
        return 0
    return sum(1 for s in TARGET_STRINGS if s.lower() in content.lower())

def find_target_smali_files(smali_dirs: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    all_smali: list[Path] = []

    for d in smali_dirs:
        all_smali.extend(d.rglob("*.smali"))

    for activity in TARGET_ACTIVITIES:
        base_name = activity.replace(".smali", "")
        candidates = [f for f in all_smali if f.stem.startswith(base_name)]
        if not candidates:
            log.warning(f"Not found: {activity}")
            continue

        scored = sorted(candidates, key=lambda f: score_file_for_target(f), reverse=True)
        best = scored[0]
        log.info(f"Target [{base_name}] → {best} (score={score_file_for_target(best)})")
        found[base_name] = best

        inner = [f for f in candidates if f != best]
        for ic in inner:
            key = ic.stem
            found[key] = ic
            log.info(f"  Inner class → {ic}")

    return found

def patch_smali_file(filepath: Path) -> int:
    content = filepath.read_text(errors="replace")
    lines   = content.splitlines(keepends=True)
    patches = 0
    new_lines = list(lines)

    i = 0
    while i < len(new_lines):
        line = new_lines[i]

        method_def = re.match(
            r'^\s*\.method\s+.*\s+(checkPremium\w*|isPremium\w*|checkStatus\w*|getStatus\w*|verifyPremium\w*)\s*\(\)Z',
            line
        )
        if method_def:
            method_name = method_def.group(1)
            log.info(f"  [PATCH] Found boolean method: {method_name} @ line {i+1} in {filepath.name}")
            j = i + 1
            while j < len(new_lines):
                if re.match(r'^\s*\.locals\s+\d+', new_lines[j]):
                    inject = "    const/4 v0, 0x1\n    return v0\n"
                    new_lines.insert(j + 1, inject)
                    log.info(f"    → Injected const/4 v0, 0x1 + return v0 after .locals @ line {j+1}")
                    patches += 1
                    break
                if re.match(r'^\s*\.end method', new_lines[j]):
                    break
                j += 1
            i = j + 1
            continue

        invoke_bool = re.match(
            r'^\s*invoke-(?:virtual|interface|direct)\s+.*\(\)Z',
            line
        )
        if invoke_bool:
            for lookahead in range(1, 4):
                if i + lookahead >= len(new_lines):
                    break
                next_line = new_lines[i + lookahead]
                move_match = re.match(r'^\s*move-result\s+(v\d+|p\d+)', next_line)
                if move_match:
                    reg = move_match.group(1)
                    for la2 in range(lookahead + 1, lookahead + 3):
                        if i + la2 >= len(new_lines):
                            break
                        cond_line = new_lines[i + la2]
                        cond_match = re.match(
                            r'^(\s*)(if-(?:eqz|nez))\s+(' + re.escape(reg) + r')\s*,\s*(:\w+)',
                            cond_line
                        )
                        if cond_match:
                            indent   = cond_match.group(1)
                            opcode   = cond_match.group(2)
                            label    = cond_match.group(4)
                            label_lower = label.lower()
                            is_fail_label = any(w in label_lower for w in [
                                "fail","expire","ban","lock","not","cond_1","cond_2","cond_3",
                                "cond_a","cond_b","cond_c","cond_d","cond_e"
                            ])
                            force_line = f"{indent}const/4 {reg}, 0x1\n"
                            if opcode == "if-eqz" and is_fail_label:
                                new_lines.insert(i + la2, force_line)
                                log.info(f"  [PATCH] Force {reg}=1 before if-eqz @ line {i+la2+1} → skips :fail in {filepath.name}")
                            elif opcode == "if-nez" and not is_fail_label:
                                new_lines.insert(i + la2, force_line)
                                log.info(f"  [PATCH] Force {reg}=1 before if-nez @ line {i+la2+1} → jumps to :success in {filepath.name}")
                            elif opcode == "if-nez" and is_fail_label:
                                force_zero = f"{indent}const/4 {reg}, 0x0\n"
                                new_lines.insert(i + la2, force_zero)
                                log.info(f"  [PATCH] Force {reg}=0 before if-nez @ line {i+la2+1} → skips :fail in {filepath.name}")
                            elif opcode == "if-eqz" and not is_fail_label:
                                force_zero = f"{indent}const/4 {reg}, 0x0\n"
                                new_lines.insert(i + la2, force_zero)
                                log.info(f"  [PATCH] Force {reg}=0 before if-eqz @ line {i+la2+1} → jumps to :success in {filepath.name}")
                            patches += 1
                            break
                    break

        const_premium = re.match(
            r'^\s*const-string\s+(v\d+|p\d+)\s*,\s*"(?:premium|active|true|1)"',
            line,
            re.IGNORECASE
        )
        if const_premium:
            cmp_reg = const_premium.group(1)
            for la in range(1, 6):
                if i + la >= len(new_lines):
                    break
                la_line = new_lines[i + la]
                if 'String;->equals' in la_line:
                    for la2 in range(la + 1, la + 3):
                        if i + la2 >= len(new_lines):
                            break
                        mr_line = new_lines[i + la2]
                        mr_match = re.match(r'^\s*move-result\s+(v\d+|p\d+)', mr_line)
                        if mr_match:
                            result_reg = mr_match.group(1)
                            indent = re.match(r'^(\s*)', mr_line).group(1)
                            force = f"{indent}const/4 {result_reg}, 0x1\n"
                            new_lines.insert(i + la2 + 1, force)
                            log.info(f"  [PATCH] Force String.equals result=1 @ line {i+la2+1} in {filepath.name}")
                            patches += 1
                            break
                    break

        if 'onDataChange' in line or 'getValue' in line:
            for la in range(1, 10):
                if i + la >= len(new_lines):
                    break
                la_line = new_lines[i + la]
                cond = re.match(r'^(\s*)(if-(?:eqz|nez))\s+(v\d+|p\d+)\s*,\s*(:\w+)', la_line)
                if cond:
                    indent = cond.group(1)
                    opcode = cond.group(2)
                    reg    = cond.group(3)
                    label  = cond.group(4)
                    label_lower = label.lower()
                    is_null_check = any(w in label_lower for w in ["null","none","cond_0","cond_1"])
                    if opcode == "if-eqz" and is_null_check:
                        force = f"{indent}const/4 {reg}, 0x1\n"
                        new_lines.insert(i + la, force)
                        log.info(f"  [PATCH] Force DataSnapshot null-check bypass @ line {i+la+1} in {filepath.name}")
                        patches += 1
                    break

        i += 1

    if patches > 0:
        filepath.write_text("".join(new_lines))
        log.info(f"  → {patches} patch(es) written to {filepath}")
    else:
        log.info(f"  → No patches needed in {filepath.name}")

    return patches

def inject_sharedprefs_premium(smali_dirs: list[Path]) -> int:
    target = None
    for d in smali_dirs:
        candidates = list(d.rglob("PreActivity.smali"))
        if candidates:
            target = max(candidates, key=lambda f: score_file_for_target(f))
            break

    if not target:
        log.warning("PreActivity.smali not found for SharedPrefs injection")
        return 0

    log.info(f"Injecting SharedPrefs premium into {target}")
    content = target.read_text(errors="replace")
    lines   = content.splitlines(keepends=True)

    in_oncreate = False
    locals_line  = -1
    inject_after = -1
    for i, line in enumerate(lines):
        if re.match(r'^\s*\.method.*\s+onCreate\s*\(Landroid/os/Bundle;\)V', line):
            in_oncreate = True
        if in_oncreate:
            if re.match(r'^\s*\.locals\s+\d+', line):
                cur_locals = int(re.search(r'\.locals\s+(\d+)', line).group(1))
                new_locals = max(cur_locals, 6)
                lines[i] = re.sub(r'\.locals\s+\d+', f'.locals {new_locals}', line)
                locals_line = i
            if locals_line >= 0 and re.match(r'^\s*invoke-super\s+', line):
                inject_after = i
                break
        if in_oncreate and re.match(r'^\s*\.end method', line):
            break

    if inject_after < 0:
        log.warning("Could not find inject point in onCreate")
        return 0

    inject_smali = (
        "\n"
        "    # [PATCH] Force premium via SharedPrefs\n"
        "    invoke-virtual {p0}, Landroid/app/Activity;->getApplicationContext()Landroid/content/Context;\n"
        "    move-result-object v0\n"
        "    const-string v1, \"com.LbzToolss_preferences\"\n"
        "    const/4 v2, 0x0\n"
        "    invoke-virtual {v0, v1, v2}, Landroid/content/Context;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;\n"
        "    move-result-object v3\n"
        "    invoke-interface {v3}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;\n"
        "    move-result-object v4\n"
        "    const-string v1, \"status\"\n"
        "    const-string v2, \"premium\"\n"
        "    invoke-interface {v4, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;\n"
        "    move-result-object v4\n"
        "    const-string v1, \"premium\"\n"
        "    const-string v2, \"true\"\n"
        "    invoke-interface {v4, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;\n"
        "    move-result-object v4\n"
        "    const-string v1, \"device_status\"\n"
        "    const-string v2, \"active\"\n"
        "    invoke-interface {v4, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;\n"
        "    move-result-object v4\n"
        "    const-string v1, \"isPremium\"\n"
        "    const/4 v2, 0x1\n"
        "    invoke-interface {v4, v1, v2}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;\n"
        "    move-result-object v4\n"
        "    const-string v1, \"token\"\n"
        "    const-string v2, \"cracked\"\n"
        "    invoke-interface {v4, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;\n"
        "    move-result-object v4\n"
        "    invoke-interface {v4}, Landroid/content/SharedPreferences$Editor;->apply()V\n"
        "    # [/PATCH]\n\n"
    )

    lines.insert(inject_after + 1, inject_smali)
    target.write_text("".join(lines))
    log.info(f"  → SharedPrefs premium injected after invoke-super @ line {inject_after + 2}")
    return 1

def clean_invalid_resources():
    """Hapus file resource yang namanya mengandung huruf kapital atau karakter aneh."""
    res_dir = Path(DECODED_DIR) / "res"
    if not res_dir.exists():
        return

    log.info("Cleaning invalid resource filenames...")
    count = 0
    # Hanya cek folder drawable, layout, mipmap, xml, anim
    target_dirs = ["drawable", "drawable-v21", "drawable-v24", "layout", "mipmap-hdpi", "mipmap-mdpi", "mipmap-xhdpi", "mipmap-xxhdpi", "mipmap-xxxhdpi", "xml", "anim"]
    
    for tdir in target_dirs:
        dir_path = res_dir / tdir
        if not dir_path.exists():
            continue
        for file in dir_path.rglob("*"):
            if file.is_file():
                if not re.match(r'^[a-z0-9_\.]+$', file.name):
                    log.warning(f"  Removing invalid resource: {file.name}")
                    file.unlink()
                    count += 1
    log.info(f"Removed {count} invalid resource files.")

def recompile():
    log.info(f"Recompiling {DECODED_DIR} → {OUTPUT_APK}")
    
    if Path(OUTPUT_APK).exists():
        Path(OUTPUT_APK).unlink()

    # Bersihkan resource yang namanya bikin error AAPT2 sebelum build
    clean_invalid_resources()

    # Menggunakan --use-aapt1 untuk menghindari validasi ketat AAPT2
    # yang menyebabkan error "Invalid file name: must contain only [a-z0-9_.]"
    cmd = ["apktool", "b", DECODED_DIR, "-o", OUTPUT_APK, "--force-all", "--use-aapt1"]
    run(cmd)
    log.info(f"Recompile complete → {OUTPUT_APK}")

def main():
    if not Path(INPUT_APK).exists():
        log.error(f"Input APK not found: {INPUT_APK}")
        sys.exit(1)

    total_patches = 0

    decompile()
    smali_dirs = find_smali_dirs()
    target_files = find_target_smali_files(smali_dirs)

    if not target_files:
        log.error("No target smali files found. Check APK structure.")
        sys.exit(1)

    for name, filepath in target_files.items():
        log.info(f"\n{'='*60}")
        log.info(f"Patching: {name} ({filepath})")
        log.info('='*60)
        n = patch_smali_file(filepath)
        total_patches += n

    log.info(f"\n{'='*60}")
    log.info("Injecting SharedPrefs premium bypass...")
    log.info('='*60)
    total_patches += inject_sharedprefs_premium(smali_dirs)

    log.info(f"\n{'='*60}")
    log.info(f"Total patches applied: {total_patches}")
    log.info('='*60)

    if total_patches == 0:
        log.warning("No patches were applied — smali structure may differ from expected.")
        log.warning("APK will still be recompiled but may not be cracked.")

    recompile()
    log.info(f"\nDone. Patched APK → {OUTPUT_APK}")

if __name__ == "__main__":
    main()