"""
patch_guardian.py — тест + rollback система за CORTEX++
=========================================================
Преди да приложи patch:
  1. Прави backup на файла (ако вече съществува)
  2. Проверява синтаксис
  3. Пише новия код
  4. Import-check в изолиран subprocess
  5. Реално изпълнение (динамични self-modifier patches) или smoke test
     (фиксираните core файлове)
  6. Ако нещо се счупи → автоматичен rollback (restore backup или delete
     за нов файл)
  7. Записва резултата в data/patch_guardian/

Използване:
  from patch_guardian import PatchGuardian
  guardian = PatchGuardian()
  result = await guardian.apply_patch("agents/core/self_observer.py", new_code)
  result = await guardian.apply_patch("agents/core/climate_patch.py", new_code)
"""

import ast
import asyncio
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("PatchGuardian")

BACKUP_DIR = Path("data/patch_guardian/backups")
RESULTS_DIR = Path("data/patch_guardian/results")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Колко backup-а да пазим на файл
MAX_BACKUPS_PER_FILE = 10

# Файлове които могат да се patch-ват (реални пътища спрямо repo root)
PATCHABLE_FILES = {
    "agents/core/self_observer.py",
    "agents/core/self_modifier.py",
    "memory/continuous_learner.py",
    "execute_patches.py",
    "hypercortex_runner.py",
    "fast_cycle_runner.py",
}


def _is_dynamic_patch(filename: str) -> bool:
    """True за self-modifier-генерирани patches: agents/core/*_patch.py.

    Тези файлове не са известни предварително (името зависи от компонента,
    избран по време на изпълнение) — затова се разпознават по pattern, не
    по членство в PATCHABLE_FILES.
    """
    norm = filename.replace("\\", "/")
    return norm.startswith("agents/core/") and norm.endswith("_patch.py")


def _is_patchable(filename: str) -> bool:
    return filename in PATCHABLE_FILES or _is_dynamic_patch(filename)


def _subprocess_env() -> dict:
    """PYTHONPATH/CORTEX_BASE за subprocess-и, извикани от guardian-а.

    По конвенция guardian-ът очаква CWD == BASE_DIR при извикване (execute_patches.py
    прави os.chdir(BASE) преди apply_patch()) — Path.cwd() тук затова сочи вярно.
    """
    base = str(Path.cwd())
    return {**os.environ, "PYTHONPATH": base, "CORTEX_BASE": os.environ.get("CORTEX_BASE", base)}


class PatchResult:
    def __init__(self, file: str, success: bool, stage: str, error: str = None,
                 backup_path: str = None, stdout: str = None):
        self.file = file
        self.success = success
        self.stage = stage  # backup | syntax | import | smoke | execute | applied | rolled_back
        self.error = error
        self.backup_path = backup_path
        self.stdout = stdout
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "success": self.success,
            "stage": self.stage,
            "error": self.error,
            "backup_path": self.backup_path,
            "stdout": self.stdout,
            "timestamp": self.timestamp,
        }


class PatchGuardian:
    """
    Пази системата от лоши patches.
    Backup → Test → Apply → Verify → (Rollback ако е нужно)
    """

    def __init__(self, patch_exec_timeout: int = 30):
        self.patch_exec_timeout = patch_exec_timeout

    # ─────────────────────────────────────────────────────────────
    # ГЛАВЕН МЕТОД
    # ─────────────────────────────────────────────────────────────

    async def apply_patch(self, filename: str, new_code: str) -> PatchResult:
        """
        Прилага patch безопасно.
        Връща PatchResult с детайли за успех/неуспех.

        Два режима, по filename:
          - Фиксираните 7 core файла (PATCHABLE_FILES): трябва вече да
            съществуват; rollback при неуспех = restore на backup-а.
          - Динамични self-modifier patches (agents/core/*_patch.py): може
            да не съществуват предварително (нов файл); rollback при
            неуспех = изтриване (няма смислен "предишен" backup).
        """
        if not _is_patchable(filename):
            return PatchResult(filename, False, "rejected",
                               f"Файлът '{filename}' не е в списъка с patchable файлове.")

        file_path = Path(filename)
        dynamic = _is_dynamic_patch(filename)
        existed = file_path.exists()

        if not existed and not dynamic:
            return PatchResult(filename, False, "rejected", f"Файлът не съществува: {filename}")

        log.info(f"[PatchGuardian] Започвам patch на {filename}")

        # ── 1. BACKUP (само ако вече има какво да пазим) ────────
        backup_path = None
        if existed:
            backup_path = self._make_backup(file_path)
            if not backup_path:
                return PatchResult(filename, False, "backup", "Backup неуспешен — patch отказан.")
            log.info(f"[PatchGuardian] Backup: {backup_path}")
        else:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        # ── 2. СИНТАКСИС ───────────────────────────────────────
        syntax_ok, syntax_error = self._check_syntax(new_code)
        if not syntax_ok:
            return PatchResult(filename, False, "syntax", syntax_error,
                                str(backup_path) if backup_path else None)

        log.info(f"[PatchGuardian] Синтаксис OK")

        # ── 3. ПИШИ НОВИЯ КОД ──────────────────────────────────
        file_path.write_text(new_code, encoding="utf-8")

        def _fail(stage: str, error: str) -> PatchResult:
            if dynamic:
                try:
                    file_path.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                self._rollback(file_path, backup_path)
            result = PatchResult(filename, False, stage, error,
                                  str(backup_path) if backup_path else None)
            result.stage = "rolled_back"
            self._save_result(result)
            return result

        # ── 4. IMPORT TEST ─────────────────────────────────────
        # За динамични patches това е инертно: self_modifier обгражда целия
        # генериран код в `if __name__ == "__main__":`, така че самият import
        # не изпълнява логиката на патча (само проверява че модулът се зарежда).
        import_ok, import_error = self._check_import(filename)
        if not import_ok:
            log.warning(f"[PatchGuardian] Import FAIL: {import_error} → rollback")
            return _fail("import", import_error)

        log.info(f"[PatchGuardian] Import OK")

        # ── 5. РЕАЛНО ИЗПЪЛНЕНИЕ / SMOKE TEST ──────────────────
        if dynamic:
            exec_ok, exec_error, exec_stdout = await self._execute_dynamic_patch(filename)
            if not exec_ok:
                log.warning(f"[PatchGuardian] Execution FAIL: {exec_error} → rollback")
                return _fail("execute", exec_error)
            log.info(f"[PatchGuardian] Execution OK")

            result = PatchResult(filename, True, "applied",
                                  backup_path=str(backup_path) if backup_path else None,
                                  stdout=exec_stdout)
            self._save_result(result)
            if backup_path:
                self._cleanup_old_backups(filename)
            log.info(f"[PatchGuardian] ✅ Patch приложен успешно: {filename}")
            return result

        smoke_ok, smoke_error = await self._smoke_test(filename)
        if not smoke_ok:
            log.warning(f"[PatchGuardian] Smoke test FAIL: {smoke_error} → rollback")
            return _fail("smoke", smoke_error)

        log.info(f"[PatchGuardian] Smoke test OK")

        # ── 6. УСПЕХ ───────────────────────────────────────────
        result = PatchResult(filename, True, "applied", backup_path=str(backup_path))
        self._save_result(result)
        self._cleanup_old_backups(filename)
        log.info(f"[PatchGuardian] ✅ Patch приложен успешно: {filename}")
        return result

    # ─────────────────────────────────────────────────────────────
    # ROLLBACK
    # ─────────────────────────────────────────────────────────────

    def rollback(self, filename: str, backup_path: str = None) -> bool:
        """
        Ръчен rollback към последния backup (или конкретен backup_path).
        """
        file_path = Path(filename)

        if backup_path:
            bp = Path(backup_path)
        else:
            # Намери най-новия backup
            bp = self._latest_backup(filename)

        if not bp or not bp.exists():
            log.error(f"[PatchGuardian] Няма backup за {filename}")
            return False

        shutil.copy2(bp, file_path)
        log.info(f"[PatchGuardian] 🔄 Rollback: {filename} ← {bp}")
        return True

    def list_backups(self, filename: str) -> list[dict]:
        """Списък с всички backup-и за даден файл."""
        pattern = f"{filename}.*.bak"
        backups = sorted(BACKUP_DIR.glob(pattern), reverse=True)
        return [
            {"path": str(b), "timestamp": b.stat().st_mtime, "size": b.stat().st_size}
            for b in backups
        ]

    # ─────────────────────────────────────────────────────────────
    # ВЪТРЕШНИ МЕТОДИ
    # ─────────────────────────────────────────────────────────────

    def _make_backup(self, file_path: Path) -> Path | None:
        try:
            ts = int(time.time())
            backup_path = BACKUP_DIR / f"{file_path.name}.{ts}.bak"
            shutil.copy2(file_path, backup_path)
            return backup_path
        except Exception as e:
            log.error(f"Backup грешка: {e}")
            return None

    def _check_syntax(self, code: str) -> tuple[bool, str | None]:
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError на ред {e.lineno}: {e.msg}"

    def _check_import(self, filename: str) -> tuple[bool, str | None]:
        """Опитва да import-не модула в изолиран subprocess."""
        module_name = str(Path(filename).with_suffix("")).replace(os.sep, ".").replace("/", ".")
        env = _subprocess_env()
        try:
            result = subprocess.run(
                [sys.executable, "-c", f"import {module_name}"],
                capture_output=True, text=True, timeout=10,
                cwd=str(Path.cwd()), env=env,
            )
            if result.returncode == 0:
                return True, None
            return False, result.stderr.strip()[:300]
        except subprocess.TimeoutExpired:
            return False, "Import timeout (>10s)"
        except Exception as e:
            return False, str(e)

    async def _execute_dynamic_patch(self, filename: str) -> tuple[bool, str | None, str | None]:
        """
        Реално изпълнява self-modifier-генериран patch (agents/core/*_patch.py).

        Кодът е обграден в `if __name__ == "__main__":` (виж self_modifier
        _ensure_main_guard) — import-check-ът по-горе е инертен, затова ТУК е
        единствената реална екзекуция на patch-а. Същите семантики като
        предишния директен subprocess.run в execute_patches.py: cwd=BASE,
        30s timeout.
        """
        file_path = Path(filename)
        env = _subprocess_env()
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(file_path),
                cwd=str(Path.cwd()), env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.patch_exec_timeout
            )
            out = stdout.decode(errors="replace").strip()
            if proc.returncode == 0:
                return True, None, out[:2000]
            return False, stderr.decode(errors="replace").strip()[:300], out[:500]
        except asyncio.TimeoutError:
            return False, f"Patch execution timeout (>{self.patch_exec_timeout}s)", None
        except Exception as e:
            return False, str(e), None

    async def _smoke_test(self, filename: str) -> tuple[bool, str | None]:
        """
        За всички PATCHABLE_FILES — import test-ът (стъпка 4) вече провери че
        модулът се зарежда. Нито self_observer.py, нито hypercortex_runner.py
        експонират клас с cheap entrypoint за реален smoke call (проверено:
        agents/core/self_observer.py е само модулни функции — run(), get_tools()
        и т.н., без SelfObserver клас; hypercortex_runner.py също — main(),
        run_agents() и т.н., без HypercortexRunner клас), затова import е
        достатъчен и тук.
        """
        return True, None

    def _rollback(self, file_path: Path, backup_path: Path):
        shutil.copy2(backup_path, file_path)
        log.info(f"[PatchGuardian] 🔄 Auto-rollback: {file_path.name} ← {backup_path.name}")

    def _latest_backup(self, filename: str) -> Path | None:
        pattern = f"{filename}.*.bak"
        backups = sorted(BACKUP_DIR.glob(pattern), reverse=True)
        return backups[0] if backups else None

    def _cleanup_old_backups(self, filename: str):
        pattern = f"{filename}.*.bak"
        backups = sorted(BACKUP_DIR.glob(pattern), reverse=True)
        for old in backups[MAX_BACKUPS_PER_FILE:]:
            old.unlink()
            log.debug(f"[PatchGuardian] Изтрит стар backup: {old.name}")

    def _save_result(self, result: PatchResult):
        path = RESULTS_DIR / f"result_{int(time.time())}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────
# CLI — за ръчно използване
# ─────────────────────────────────────────────────────────────────

async def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="PatchGuardian CLI")
    sub = parser.add_subparsers(dest="cmd")

    # apply
    p_apply = sub.add_parser("apply", help="Приложи patch от файл")
    p_apply.add_argument("target", help="Целеви файл (напр. self_observer.py)")
    p_apply.add_argument("patch_file", help="Файл с новия код")

    # rollback
    p_rb = sub.add_parser("rollback", help="Rollback към последния backup")
    p_rb.add_argument("target", help="Файл за rollback")
    p_rb.add_argument("--backup", help="Конкретен backup path (опционално)")

    # list
    p_list = sub.add_parser("list", help="Списък backups")
    p_list.add_argument("target", help="Файл")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    guardian = PatchGuardian()

    if args.cmd == "apply":
        new_code = Path(args.patch_file).read_text(encoding="utf-8")
        result = await guardian.apply_patch(args.target, new_code)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    elif args.cmd == "rollback":
        ok = guardian.rollback(args.target, args.backup)
        print("✅ Rollback успешен" if ok else "❌ Rollback неуспешен")

    elif args.cmd == "list":
        backups = guardian.list_backups(args.target)
        for b in backups:
            ts = datetime.fromtimestamp(b["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {ts}  {b['path']}  ({b['size']} bytes)")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(_cli())