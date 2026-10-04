"""Execution bridge to an OpenFOAM Foundation v14 installation.

Two runtimes are supported:

  wsl    - Windows host, OpenFOAM inside WSL2 (the reported runs' development
           environment). Commands are issued with
           ``wsl.exe -d <distro> -- bash -lc '...'``, which is exactly the probe
           pattern already used by scripts/check_environment.py.
  linux  - the host itself is Linux with Foundation v14 available.

Cases are always created inside the runtime filesystem (``$HOME/.cache`` by
default), never on a Windows drive mounted into WSL: OpenFOAM writes tens of
thousands of small ASCII monitor records per case and the 9p mount makes that
pathologically slow. This mirrors what validation/canonical_reference/Allrun
already does.

The pipeline code is copied into the runtime alongside the cases, again exactly
as Allrun does, so the code that ran is archived next to the evidence.
"""
from __future__ import annotations

import base64
import os
import platform
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import List, Optional


DEFAULT_DISTRO = os.getenv("OPENFOAM_WSL_DISTRO", "Ubuntu-24.04")
DEFAULT_BASHRC = os.getenv("OPENFOAM_BASHRC", "/opt/openfoam14/etc/bashrc")


class FoamRuntimeError(RuntimeError):
    pass


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class FoamRuntime:
    mode: str
    distro: str = DEFAULT_DISTRO
    bashrc: str = DEFAULT_BASHRC
    root: Optional[PurePosixPath] = None
    notes: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------

    @classmethod
    def detect(cls) -> "FoamRuntime":
        if platform.system() == "Windows":
            return cls(mode="wsl")
        return cls(mode="linux")

    # ------------------------------------------------------------------

    def _argv(self, script: str) -> List[str]:
        if self.mode == "wsl":
            # wsl.exe inherits the Windows caller's current directory.
            # OpenFOAM rejects Windows-mounted cwd paths containing spaces,
            # even when -case points to a native Linux directory.
            script = 'cd "$HOME" && ' + script
            # Passing a shell program directly through wsl.exe can cause
            # Windows-side argument processing to alter Bash $variables.
            # Encode the complete script so it reaches Bash byte-for-byte.
            payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
            transport = (
                f"printf '%s' {shlex.quote(payload)} | base64 -d | bash"
            )
            return [
                "wsl.exe",
                "-d",
                self.distro,
                "--",
                "bash",
                "-lc",
                transport,
            ]

        return ["bash", "-lc", script]

    def bash(
        self,
        script: str,
        *,
        timeout: Optional[float] = 600.0,
        foam: bool = True,
        stream_prefix: Optional[str] = None,
    ) -> CommandResult:
        """Run one bash script in the runtime.

        ``foam=True`` sources the Foundation v14 bashrc first.
        ``stream_prefix`` echoes stdout lines live (used for solver progress).
        """
        if foam:
            script = f'source {shlex.quote(self.bashrc)} >/dev/null 2>&1; {script}'

        argv = self._argv(script)

        if stream_prefix is None:
            try:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    stdin=subprocess.DEVNULL,
                )
            except FileNotFoundError as exc:
                raise FoamRuntimeError(
                    f"Cannot reach the {self.mode} runtime: {exc}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                return CommandResult(
                    124, exc.stdout or "", f"timeout after {timeout}s"
                )

            return CommandResult(proc.returncode, proc.stdout, proc.stderr)

        # Streaming mode: forward stdout as it arrives.
        lines: List[str] = []

        with subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            stdin=subprocess.DEVNULL,
        ) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line)
                text = line.rstrip()
                if text:
                    print(text if text.startswith("[") else f"{stream_prefix} {text}", flush=True)
            code = proc.wait()

        return CommandResult(code, "".join(lines), "")

    # ------------------------------------------------------------------

    def preflight(self) -> dict:
        """Verify Foundation v14, the required utilities, python3 and numpy."""
        script = (
            'echo "VERSION=$WM_PROJECT_VERSION"; '
            'for t in blockMesh checkMesh foamPostProcess foamRun; do '
            'command -v "$t" >/dev/null 2>&1 && echo "TOOL=$t" || echo "MISSING=$t"; '
            'done; '
            'python3 -c "import numpy;print(\'NUMPY=\'+numpy.__version__)" '
            '2>/dev/null || echo NUMPY=MISSING; '
            'echo "HOME=$HOME"'
        )

        result = self.bash(script, timeout=180)

        info = {
            "mode": self.mode,
            "distro": self.distro if self.mode == "wsl" else None,
            "bashrc": self.bashrc,
            "returncode": result.returncode,
            "raw": result.stdout.strip(),
        }

        parsed = dict(
            line.split("=", 1)
            for line in result.stdout.splitlines()
            if "=" in line
        )

        info["openfoam_version"] = parsed.get("VERSION", "")
        info["numpy"] = parsed.get("NUMPY", "MISSING")
        info["home"] = parsed.get("HOME", "")
        info["missing_tools"] = [
            line.split("=", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("MISSING=")
        ]

        info["ok"] = (
            result.ok
            and info["openfoam_version"] == "14"
            and not info["missing_tools"]
            and info["numpy"] != "MISSING"
        )

        if not info["ok"]:
            reasons = []
            if info["openfoam_version"] != "14":
                reasons.append(
                    "Foundation OpenFOAM 14 not found "
                    f"(WM_PROJECT_VERSION={info['openfoam_version']!r}); "
                    "OpenCFD releases are not interchangeable"
                )
            if info["missing_tools"]:
                reasons.append(
                    "missing utilities: " + ", ".join(info["missing_tools"])
                )
            if info["numpy"] == "MISSING":
                reasons.append("python3 numpy unavailable in the runtime")
            info["reason"] = "; ".join(reasons) or result.stderr.strip()

        return info

    # ------------------------------------------------------------------

    def to_runtime_path(self, local) -> str:
        """Translate a host path into a runtime path.

        On Windows, C:\\Users\\x\\repo becomes /mnt/c/Users/x/repo, which is how
        the WSL distribution sees the Windows drive.
        """
        if self.mode != "wsl":
            return str(Path(local).resolve())

        windows = PureWindowsPath(local)
        drive = windows.drive.rstrip(":").lower()

        if not drive:
            raise FoamRuntimeError(f"Cannot map path into WSL: {local}")

        rest = "/".join(windows.parts[1:])

        return f"/mnt/{drive}/{rest}"

    def make_root(self, stamp: str) -> PurePosixPath:
        # A login shell prints motd, conda banners and whatever else the user's
        # profile emits. The sentinel makes the answer unambiguous instead of
        # trusting the last line of stdout.
        script = (
            'root="${XDG_CACHE_HOME:-$HOME/.cache}/nozzle-e2e/' + stamp + '"; '
            'mkdir -p "$root/code" && printf "NOZZLE_ROOT=%s\\n" "$root"'
        )
        result = self.bash(script, foam=False, timeout=120)

        marked = [
            line.split("=", 1)[1].strip()
            for line in result.stdout.splitlines()
            if line.startswith("NOZZLE_ROOT=")
        ]

        if not result.ok or not marked:
            raise FoamRuntimeError(
                "Cannot create runtime root: "
                f"{result.stderr or result.stdout or 'no output'}"
            )

        self.root = PurePosixPath(marked[-1])
        return self.root

    def stage_code(self, local_code_dir: Path) -> PurePosixPath:
        """Copy the pipeline code into the runtime beside the cases."""
        if self.root is None:
            raise FoamRuntimeError("make_root must be called first")

        source = self.to_runtime_path(local_code_dir)
        target = self.root / "code"

        quoted_target = shlex.quote(str(target))

        # The sources sit on a Windows drive. Git on Windows can hand back CRLF
        # regardless of .gitattributes until the tree is renormalised, and a
        # lone trailing CR turns `blockMesh -case "$case"` into a command whose
        # argument ends in a carriage return. Strip CR from the staged copies;
        # the repository files are not touched.
        result = self.bash(
            f'cp -- {shlex.quote(source)}/*.py {shlex.quote(source)}/*.sh '
            f'{quoted_target}/ && '
            f"sed -i 's/\\r$//' {quoted_target}/*.sh {quoted_target}/*.py && "
            f'chmod +x {quoted_target}/*.sh && '
            f'ls {quoted_target}',
            foam=False,
            timeout=180,
        )

        if not result.ok:
            raise FoamRuntimeError(
                f"Cannot stage pipeline code: {result.stderr or result.stdout}"
            )

        return target

    def write_text(self, runtime_path: PurePosixPath, text: str) -> None:
        heredoc = f"cat > {shlex.quote(str(runtime_path))} <<'__NOZZLE_EOF__'\n{text}\n__NOZZLE_EOF__"
        result = self.bash(heredoc, foam=False, timeout=120)

        if not result.ok:
            raise FoamRuntimeError(
                f"Cannot write {runtime_path}: {result.stderr or result.stdout}"
            )

    def read_text(self, runtime_path: PurePosixPath) -> str:
        result = self.bash(
            f'cat -- {shlex.quote(str(runtime_path))}', foam=False, timeout=180
        )

        if not result.ok:
            raise FoamRuntimeError(
                f"Cannot read {runtime_path}: {result.stderr or result.stdout}"
            )

        return result.stdout

    def fetch_tail(
        self, runtime_path: PurePosixPath, local_path: Path, lines: int = 4000
    ) -> bool:
        """Copy the tail of a large runtime log to the host.

        Solver logs run to tens of megabytes over tens of thousands of
        timesteps; the full log stays in the runtime beside the case, which is
        where the complete evidence lives.
        """
        result = self.bash(
            f'test -f {shlex.quote(str(runtime_path))} && '
            f'tail -n {int(lines)} -- {shlex.quote(str(runtime_path))}',
            foam=False,
            timeout=300,
        )

        if not result.ok:
            return False

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(result.stdout, encoding="utf-8")
        return True

    def fetch_head(
        self, runtime_path: PurePosixPath, local_path: Path, lines: int = 400
    ) -> bool:
        """Copy the opening of a large runtime log to the host.

        The head carries the build banner, the case path, the signal-handler
        configuration and any dictionary error raised before the time loop
        starts. Fetching it alongside the tail means a returned run directory
        contains both ends of the solver log, which is what a later audit of a
        log-derived check needs.
        """
        result = self.bash(
            f'test -f {shlex.quote(str(runtime_path))} && '
            f'head -n {int(lines)} -- {shlex.quote(str(runtime_path))}',
            foam=False,
            timeout=300,
        )

        if not result.ok:
            return False

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(result.stdout, encoding="utf-8")
        return True

    def fetch(self, runtime_path: PurePosixPath, local_path: Path) -> bool:
        """Copy one runtime text file to the host. Returns False if absent."""
        result = self.bash(
            f'test -f {shlex.quote(str(runtime_path))} && '
            f'cat -- {shlex.quote(str(runtime_path))}',
            foam=False,
            timeout=300,
        )

        if not result.ok:
            return False

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(result.stdout, encoding="utf-8")
        return True
