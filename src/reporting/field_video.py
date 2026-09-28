"""Automatic, verdict-independent field movies; renderer failures are artifact failures."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess


def locate_case(run):
    a = run.artifacts or {}
    candidates = [a.get('raw_case'), a.get('runtime_case'),
                  (a.get('case') or {}).get('case_dir'), a.get('evidence_root')]
    root = a.get('evidence_root')
    if root and Path(root).is_dir():
        for name in ('agent_result.json', 'validation.json'):
            for path in sorted(Path(root).rglob(name)):
                try:
                    data = json.loads(path.read_text(encoding='utf-8-sig'))
                    candidates.extend(data.get(k) for k in ('runtime_case', 'case_path', 'case'))
                except (OSError, ValueError):
                    pass
    for item in candidates:
        if not isinstance(item, str):
            continue
        path = Path(item)
        if (path / 'constant/polyMesh').is_dir():
            return str(path)
        if os.name == 'nt' and item.startswith('/home/'):
            # Native cases stay in WSL. The renderer performs the existence check.
            return item
    return None


def make_field_video(run, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    a = run.artifacts or {}
    meta = {'family': run.family, 'case': run.case,
            'verdict': run.decision.verdict if run.decision else 'NONE',
            'solver_invoked': bool(a.get('solver_invoked')),
            'source_kind': 'live' if run.mode == 'live' else 'archived_raw_fields'}
    status = {**meta, 'status': 'VISUALIZATION_INCOMPLETE', 'output_files': []}
    # A failed retry must never inherit an earlier successful manifest.
    (out / 'video_manifest.json').write_text(json.dumps(status), encoding='utf-8')
    source = locate_case(run)
    if not a.get('solver_invoked') and (run.family == 'airfoil' or run.mode != 'replay'):
        status.update(status='VIDEO_NOT_AVAILABLE_CFD_NOT_RUN', reason='CFD was not executed for this request.')
    elif not source:
        status['reason'] = 'No raw OpenFOAM case located; histories are not field movies.'
    else:
        renderer = os.environ.get('CFD_PVPYTHON') or shutil.which('pvpython') or shutil.which('pvbatch')
        script = Path(__file__).with_name('paraview_field_video.py').resolve()
        metadata = out / 'render_request.json'
        metadata.write_text(json.dumps(meta, indent=2), encoding='utf-8')
        args = ['--case', source, '--out', str(out.resolve()), '--metadata', str(metadata.resolve())]
        if os.environ.get('CFD_FFMPEG'):
            args += ['--ffmpeg', os.environ['CFD_FFMPEG']]
        if os.name == 'nt' and source.startswith('/'):
            def wsl_path(p):
                p = str(p).replace('\\', '/')
                return '/mnt/' + p[0].lower() + p[2:] if len(p) > 1 and p[1] == ':' else p
            command = ['wsl', '-d', os.environ.get('CFD_WSL_DISTRO', 'Ubuntu-24.04'), '--',
                       'xvfb-run', '-a', 'env', 'LIBGL_ALWAYS_SOFTWARE=1',
                       'pvpython', '--force-offscreen-rendering', wsl_path(script)]
            args = [wsl_path(x) for x in args]
        elif renderer:
            command = [renderer, '--force-offscreen-rendering', str(script)]
        else:
            command = None
            status['reason'] = 'ParaView pvpython/pvbatch is unavailable.'
        if command:
            try:
                result = subprocess.run(command + args, capture_output=True, text=True, timeout=3600)
                (out / 'renderer.log').write_text(result.stdout + result.stderr, encoding='utf-8')
                manifest = out / 'video_manifest.json'
                if manifest.exists():
                    status = json.loads(manifest.read_text())
                    if result.returncode or status.get('status') != 'RENDERED':
                        status.update(status='VISUALIZATION_INCOMPLETE',
                                      reason=status.get('reason', f'Renderer returned {result.returncode}; see renderer.log.'))
                else:
                    status['reason'] = f'Renderer returned {result.returncode}; see renderer.log.'
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                status['reason'] = f'Renderer could not finish: {type(exc).__name__}'
    (out / 'video_manifest.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    (out / 'visualization_status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    return status
