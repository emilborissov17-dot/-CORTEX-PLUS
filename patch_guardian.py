"""
patch_guardian.py — тест + rollback система за CORTEX++
=========================================================
Преди да приложи patch:
  1. Прави backup на файла
  2. Прилага patch-а
  3. Тества синтаксис + import
  4. Пуска smoke test (1 цикъл наблюдение)
  5. Ако нещо се счупи → автоматичен rollback
  6. Записва резултата в data/patch_guardian/

Използване:
  from patch_guardian import PatchGuardian
  guardian = PatchGuardian()
  result = await guardian.apply_patch("self_observer.py", new_code)
"""

import ast
import asyncio
import importlib.util
import json
import logging
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

# Файлове които могат да се patch-ват
PATCHABLE_FILES = {
    "self_observer.py",
    "self_modifier.py",
    "world_actor.py",
    "continuous_learner.py",
    "execute_patches.py",
    "hypercortex_runner.py",
    "fast_cycle_runner.py",
}


class PatchResult:
    def __init__(self, file: str, success: bool, stage: str, error: str = None, backup_path: str = None):
        self.file = file
        self.success = success
        self.stage = stage  # backup | syntax | import | smoke | applied | rolled_back
        self.error = error
        self.backup_path = backup_path
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "success": self.success,
            "stage": self.stage,
            "error": self.error,
            "backup_path": self.backup_path,
            "timestamp": self.timestamp,
        }


class PatchGuardian:
    """
    Пази системата от лоши patches.
    Backup → Test → Apply → Verify → (Rollback ако е нужно)
    """

    def __init__(self, smoke_test_timeout: int = 15):
        self.smoke_test_timeout = smoke_test_timeout

    # ─────────────────────────────────────────────────────────────
    # ГЛАВЕН МЕТОД
    # ─────────────────────────────────────────────────────────────

    async def apply_patch(self, filename: str, new_code: str) -> PatchResult:
        """
        Прилага patch безопасно.
        Връща PatchResult с детайли за успех/неуспех.
        """
        if filename not in PATCHABLE_FILES:
            return PatchResult(filename, False, "rejected",
                               f"Файлът '{filename}' не е в списъка с patchable файлове.")

        file_path = Path(filename)
        if not file_path.exists():
            return PatchResult(filename, False, "rejected", f"Файлът не съществува: {filename}")

        log.info(f"[PatchGuardian] Започвам patch на {filename}")

        # ── 1. BACKUP ──────────────────────────────────────────
        backup_path = self._make_backup(file_path)
        if not backup_path:
            return PatchResult(filename, False, "backup", "Backup неуспешен — patch отказан.")
        log.info(f"[PatchGuardian] Backup: {backup_path}")

        # ── 2. СИНТАКСИС ───────────────────────────────────────
        syntax_ok, syntax_error = self._check_syntax(new_code)
        if not syntax_ok:
            return PatchResult(filename, False, "syntax", syntax_error, str(backup_path))

        log.info(f"[PatchGuardian] Синтаксис OK")

        # ── 3. ПИШИ НОВИЯ КОД ──────────────────────────────────
        original_code = file_path.read_text(encoding="utf-8")
        file_path.write_text(new_code, encoding="utf-8")

        # ── 4. IMPORT TEST ─────────────────────────────────────
        import_ok, import_error = self._check_import(filename)
        if not import_ok:
            log.warning(f"[PatchGuardian] Import FAIL: {import_error} → rollback")
            self._rollback(file_path, backup_path)
            result = PatchResult(filename, False, "import", import_error, str(backup_path))
            result.stage = "rolled_back"
            self._save_result(result)
            return result

        log.info(f"[PatchGuardian] Import OK")

        # ── 5. SMOKE TEST ──────────────────────────────────────
        smoke_ok, smoke_error = await self._smoke_test(filename)
        if not smoke_ok:
            log.warning(f"[PatchGuardian] Smoke test FAIL: {smoke_error} → rollback")
            self._rollback(file_path, backup_path)
            result = PatchResult(filename, False, "smoke", smoke_error, str(backup_path))
            result.stage = "rolled_back"
            self._save_result(result)
            return result

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
        module_name = filename.replace(".py", "")
        try:
            result = subprocess.run(
                [sys.executable, "-c", f"import {module_name}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, None
            return False, result.stderr.strip()[:300]
        except subprocess.TimeoutExpired:
            return False, "Import timeout (>10s)"
        except Exception as e:
            return False, str(e)

    async def _smoke_test(self, filename: str) -> tuple[bool, str | None]:
        """
        Smoke test: ако е self_observer.py → опитва observe()
        За останалите файлове → само проверява import в subprocess
        """
        if filename == "self_observer.py":
            return await self._smoke_test_observer()
        elif filename == "hypercortex_runner.py":
            return await self._smoke_test_hypercortex()
        else:
            # За останалите — import е достатъчен
            return True, None

    async def _smoke_test_observer(self) -> tuple[bool, str | None]:
        """Пуска SelfObserver.observe() с timeout."""
        code = """
import asyncio, sys
sys.path.insert(0, '.')
async def test():
    from self_observer import SelfObserver
    obs = SelfObserver()
    signals = await obs.observe()
    print(f"OK:{len(signals)}")
asyncio.run(test())
"""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.smoke_test_timeout
            )
            output = stdout.decode().strip()
            if output.startswith("OK:"):
                count = int(output.split(":")[1])
                log.info(f"[smoke] SelfObserver → {count} сигнала")
                return True, None
            return False, stderr.decode().strip()[:300]
        except asyncio.TimeoutError:
            return False, f"Smoke test timeout (>{self.smoke_test_timeout}s)"
        except Exception as e:
            return False, str(e)

    async def _smoke_test_hypercortex(self) -> tuple[bool, str | None]:
        """Пуска HypercortexRunner с празни observations."""
        code = """
import asyncio, sys
sys.path.insert(0, '.')
async def test():
    from hypercortex_runner import HypercortexRunner
    h = HypercortexRunner()
    snaps = await h.run([])
    print(f"OK:{len(snaps)}")
asyncio.run(test())
"""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=10
            )
            output = stdout.decode().strip()
            if output.startswith("OK:"):
                return True, None
            return False, stderr.decode().strip()[:300]
        except asyncio.TimeoutError:
            return False, "Hypercortex smoke timeout"
        except Exception as e:
            return False, str(e)

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