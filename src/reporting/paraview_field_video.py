"""Run with pvpython. Two-pass fixed-range rendering of actual OpenFOAM fields.

Never writes to the source case. A temporary symlink view supplies a reader marker.
Decomposed histories can be read directly, without reconstructing frozen evidence.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def time_directories(root):
    found = []
    for p in root.iterdir():
        try:
            t = float(p.name)
        except ValueError:
            continue
        if math.isfinite(t) and p.is_dir() and ((p / 'U').is_file() or (p / 'U.gz').is_file()):
            found.append((t, p.name))
    return sorted(found)


def selected_times(times, limit):
    if limit < 2:
        raise ValueError('At least two frames are required')
    if len(times) <= limit:
        return times
    return [times[round(i * (len(times)-1)/(limit-1))] for i in range(limit)]


def color_limits(lo, hi):
    return [lo, hi if hi != lo else lo + max(abs(lo)*1e-6, 1e-12)]


def case_fingerprints(case):
    files = list((case/'system').glob('*')) + list((case/'constant').glob('*'))
    files += list((case/'constant/polyMesh').glob('*'))
    result = {}
    for path in sorted(files):
        if path.is_file():
            h = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024*1024), b''):
                    h.update(chunk)
            result[path.relative_to(case).as_posix()] = h.hexdigest()
    return result


def reader_shadow(case, shadow):
    """Read-only links, except equivalent numeric dimension syntax in private t=0 copies.

    ParaView 5.11 predates Foundation's named dimensions. Values and connectivity
    are untouched. Unknown named dimensions fail rather than being guessed.
    """
    edits = []
    dimensions = {'velocity':'0 1 -1 0 0 0 0', 'pressure':'1 -1 -2 0 0 0 0',
                  'temperature':'0 0 0 1 0 0 0'}
    for p in case.iterdir():
        if not p.is_dir():
            continue
        if p.name != '0':
            (shadow/p.name).symlink_to(p, target_is_directory=True)
            continue
        dest = shadow/p.name
        dest.mkdir()
        for field in p.iterdir():
            if field.name in ('U','p','T') and field.is_file():
                raw = field.read_bytes()
                text = raw.decode('utf-8', errors='surrogateescape')
                m = re.search(r'dimensions\s+\[([A-Za-z]+)\]\s*;', text)
                if m:
                    if m[1] not in dimensions:
                        raise ValueError('Unsupported named dimensions: '+m[1])
                    converted = text[:m.start()] + 'dimensions ['+dimensions[m[1]]+'];' + text[m.end():]
                    (dest/field.name).write_bytes(converted.encode('utf-8', errors='surrogateescape'))
                    edits.append({'file':'0/'+field.name,'from':m[1],'to':dimensions[m[1]],
                                  'source_sha256':hashlib.sha256(raw).hexdigest()})
                    continue
            (dest/field.name).symlink_to(field, target_is_directory=field.is_dir())
    return edits


def gas_constant(case):
    """Only derive Mach for explicitly supported calorically-perfect gas dictionaries."""
    for name in ('physicalProperties', 'thermophysicalProperties'):
        p = case / 'constant' / name
        if not p.exists():
            continue
        text = re.sub(r'//[^\n]*|/\*.*?\*/', '', p.read_text(), flags=re.S)
        if not re.search(r'equationOfState\s+perfectGas\s*;', text):
            continue
        if not re.search(r'\bthermo\s+(eConst|hConst)\s*;', text):
            continue
        def value(key):
            m = re.search(r'\b' + key + r'\s+([\deE.+-]+)\s*;', text)
            return float(m[1]) if m else None
        mw, cp, cv = value('molWeight'), value('Cp'), value('Cv')
        if not mw or not (cp or cv):
            continue
        R = 8314.46261815324 / mw
        cv = cv if cv is not None else cp-R
        if cv > 0:
            return (1+R/cv)*R
    return None


def render(args, manifest):
    import paraview.simple as pv
    case, out = Path(args.case).resolve(), Path(args.out).resolve()
    if not (case / 'constant/polyMesh').is_dir():
        raise ValueError('Raw mesh is unavailable')
    fingerprints = case_fingerprints(case)
    manifest['source_config_and_mesh_sha256'] = fingerprints
    roots = [case]
    processors = sorted(case.glob('processor[0-9]*'))
    if processors and len(time_directories(processors[0])) > len(time_directories(case)):
        roots = processors
    times = time_directories(roots[0])
    for root in roots[1:]:
        available = set(time_directories(root))
        times = [t for t in times if t in available]
    times = selected_times(times, args.max_frames)
    if len(times) < 2:
        raise ValueError('Fewer than two usable raw field times; no evolution movie can be made')
    # Read temporal semantics from the actual case, not the scientific goal of convergence.
    schemes = (case / 'system/fvSchemes').read_text()
    physical = not bool(re.search(r'\bsteadyState\b', schemes))
    control = (case / 'system/controlDict').read_text()
    def setting(key):
        m = re.search(r'\b' + key + r'\s+([^;]+);', control)
        return m[1].strip() if m else None
    manifest.update(source_case_directory='external-case://' + case.name,
                    source_case_id=hashlib.sha256(str(case).encode()).hexdigest(),
                    physical_solver_time=physical, solver=setting('solver') or setting('application'),
                    rendered_solver_times=[t for t, _ in times],
                    time_directory_names=[s for _, s in times], frame_count=len(times),
                    sampling='uniform index selection of actual available times; no temporal interpolation',
                    data_layout='decomposed' if len(roots)>1 else 'reconstructed',
                    output_cadence={k: setting(k) for k in ('writeControl','writeInterval','purgeWrite')},
                    paraview_version=str(pv.GetParaViewVersion()))
    ffmpeg = args.ffmpeg or os.environ.get('CFD_FFMPEG') or shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('FFmpeg is unavailable; set CFD_FFMPEG or --ffmpeg')
    version = subprocess.run([ffmpeg, '-version'], capture_output=True, text=True, check=True)
    manifest['ffmpeg_version'] = version.stdout.splitlines()[0]
    with tempfile.TemporaryDirectory(prefix='cfd-field-reader-') as temp:
        shadow = Path(temp)
        manifest['reader_only_dimension_translations'] = reader_shadow(case, shadow)
        marker = shadow / 'reader.foam'
        marker.touch()
        reader = pv.OpenFOAMReader(FileName=str(marker))
        reader.SkipZeroTime = 0
        reader.ListtimestepsaccordingtocontrolDict = 0
        if len(roots)>1:
            reader.CaseType = 'Decomposed Case'
        reader.MeshRegions = ['internalMesh']
        reader.SMProxy.InvokeCommand('Refresh')
        reader.UpdatePipelineInformation()
        reader_times = list(reader.TimestepValues)
        manifest['reader_time_values'] = reader_times
        # VTK 5.11 can expose times through single-precision information arrays.
        # Match existing directory times within float32 roundoff, never invent frames.
        if not all(any(abs(t-r) <= 2e-7 * max(1, abs(t)) for r in reader_times) for t,_ in times):
            raise ValueError('Selected on-disk times do not match ParaView reader times')
        available = set(reader.CellArrays.Available)
        fields = [('p','pressure'), ('U','velocity'), ('T','temperature'), ('rho','density'),
                  ('k','turbulence'), ('nut','turbulent_viscosity')]
        fields = [(f,n) for f,n in fields if f in available and
                  all((root / name / f).exists() or (root / name / (f+'.gz')).exists()
                      for root in roots for _,name in times)]
        reader.CellArrays = [f for f,_ in fields]
        source = reader
        for candidate in ('Ma', 'Mach', 'mach'):
            if candidate in available and all((r/n/candidate).exists() for r in roots for _,n in times):
                reader.CellArrays = list(reader.CellArrays) + [candidate]
                fields.append((candidate,'mach'))
                break
        else:
            gammaR = gas_constant(case)
            if gammaR and ('T','temperature') in fields and ('U','velocity') in fields:
                source = pv.Calculator(Input=source)
                source.AttributeType = 'Cell Data'
                source.ResultArrayName = 'derivedMach'
                source.Function = f'mag(U)/sqrt({gammaR:.16g}*T)'
                fields.append(('derivedMach','mach'))
                manifest['mach_derivation'] = {'formula':'mag(U)/sqrt(gamma*R*T)', 'gamma_R':gammaR}
        cube = manifest['family'] == 'cube'
        if cube:
            wake = pv.Calculator(Input=source)
            wake.AttributeType = 'Cell Data'
            wake.ResultArrayName = 'spanwiseVelocity'
            wake.Function = 'U_Z'
            source = wake
            fields.append(('spanwiseVelocity','wake'))
        required = {'pressure','velocity'} if cube else {'pressure','velocity','temperature','mach'}
        missing = required - {n for _,n in fields}
        if missing:
            raise ValueError('Required fields unavailable across selected times: '+', '.join(sorted(missing)))
        source.UpdatePipeline(times[0][0])
        bounds = source.GetDataInformation().GetBounds()
        if cube:
            source = pv.Slice(Input=source)
            source.SliceType = 'Plane'
            source.SliceType.Origin = [0, args.cube_slice_y, 0]
            source.SliceType.Normal = [0,1,0]
            camera = {'position':[3,args.cube_slice_y-50,0], 'focal_point':[3,args.cube_slice_y,0],
                      'view_up':[0,0,1], 'parallel_scale':4.2}
            manifest['slice'] = {'origin':[0,args.cube_slice_y,0], 'normal':[0,1,0],
                                 'meaning':'horizontal plane through cube mid-height; coordinates in case units'}
        else:
            x,y,z = [(bounds[i]+bounds[i+1])/2 for i in (0,2,4)]
            camera = {'position':[x,y,z+max(bounds[1]-bounds[0],1)], 'focal_point':[x,y,z],
                      'view_up':[0,1,0], 'parallel_scale':max((bounds[3]-bounds[2])*.7,(bounds[1]-bounds[0])*.36)}
            manifest['slice'] = None
        manifest['camera'] = camera
        manifest['rendering_method'] = 'ParaView OpenFOAMReader; cell coloring; offscreen rendering; two-pass fixed temporal ranges'
        ranges = {name:[float('inf'),-float('inf')] for _,name in fields}
        for time_index,(t,_) in enumerate(times):
            source.UpdatePipeline(t)
            for field,name in fields:
                info = source.GetCellDataInformation().GetArray(field)
                if info is None:
                    raise ValueError('Missing array at a selected time: '+field)
                lo,hi = info.GetComponentRange(-1 if field=='U' else 0)
                if not all(math.isfinite(v) for v in (lo,hi)):
                    raise ValueError('Non-finite field range: '+field)
                ranges[name] = [min(ranges[name][0],lo),max(ranges[name][1],hi)]
            (out/'render_progress.json').write_text(json.dumps({'pass':'range','completed':time_index+1,'total':len(times)}))
        manifest.update(fields_rendered=[n for _,n in fields], fixed_color_ranges=ranges,
                        range_scope='cell values on rendered dataset (slice for cube), across every selected time')
        manifest['field_data_ranges'] = {n:list(r) for n,r in ranges.items()}
        manifest['fixed_color_ranges'] = {n:color_limits(*r) for n,r in ranges.items()}
        manifest['per_frame_color_ranges'] = []
        view = pv.CreateView('RenderView')
        view.ViewSize = [args.width,args.height]
        view.OrientationAxesVisibility = 0
        view.Background = [0.08,0.10,0.14]
        view.UseColorPaletteForBackground = 0
        view.CameraParallelProjection = 1
        view.CameraPosition = camera['position']
        view.CameraFocalPoint = camera['focal_point']
        view.CameraViewUp = camera['view_up']
        view.CameraParallelScale = camera['parallel_scale']
        display = pv.Show(source,view)
        display.Representation = 'Surface'
        label = pv.Text()
        label_display = pv.Show(label,view)
        label_display.FontSize = 16
        label_display.WindowLocation = 'Upper Left Corner'
        outputs = []
        # Time outermost: parse each large native time directory once per pass.
        # The LUTs are configured once, then reused without autoscaling.
        for field,name in fields:
            lut = pv.GetColorTransferFunction(field)
            lut.ApplyPreset('Cool to Warm (Extended)',True)
            lo,hi = manifest['fixed_color_ranges'][name]
            lut.RescaleTransferFunction(lo,hi)
            lut.AutomaticRescaleRangeMode = 'Never'
            bar = pv.GetScalarBar(lut,view)
            bar.Title = name
            bar.ComponentTitle = ''
            bar.WindowLocation = 'Any Location'
            bar.Position = [.30,.07]
            bar.ScalarBarLength = .40
            bar.Visibility = 0
            bar.Orientation = 'Horizontal'
            (out/'frames'/name).mkdir(parents=True,exist_ok=True)
        for i,(t,_) in enumerate(times):
            view.ViewTime = t
            source.UpdatePipeline(t)
            for field,name in fields:
                pv.ColorBy(display,('CELLS',field,'Magnitude') if field=='U' else ('CELLS',field))
                for other,_ in fields:
                    pv.GetScalarBar(pv.GetColorTransferFunction(other),view).Visibility = 0
                # ColorBy itself may rescale even when the LUT's automatic mode is
                # Never. Reapply the SAME preread temporal range after every switch.
                lo,hi = manifest['fixed_color_ranges'][name]
                display.LookupTable.RescaleTransferFunction(lo,hi)
                display.LookupTable.AutomaticRescaleRangeMode = 'Never'
                display.SetScalarBarVisibility(view,True)
                label.Text = (f"{manifest['family']} | {name} | {manifest['verdict']}\n"
                              f"{'solver time' if physical else 'solver iteration'} = {t:.12g}")
                pv.SaveScreenshot(str(out/'frames'/name/f'{i:05d}.png'),view,ImageResolution=[args.width,args.height])
                points = list(display.LookupTable.RGBPoints)
                observed = [points[0],points[-4]]
                if not all(math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-12) for a,b in zip(observed,[lo,hi])):
                    raise ValueError('ParaView changed the fixed color range for '+name)
                manifest['per_frame_color_ranges'].append({'time':t,'field':name,'range':observed})
                display.SetScalarBarVisibility(view,False)
            (out/'render_progress.json').write_text(json.dumps({'pass':'frames','completed':i+1,'total':len(times)}))
        for field,name in fields:
            frames = out/'frames'/name
            target = name+'_evolution.mp4'
            subprocess.run([ffmpeg,'-y','-loglevel','error','-framerate',str(args.fps),
                            '-i',str(frames/'%05d.png'),'-frames:v',str(len(times)),
                            '-c:v','libx264','-threads','2','-crf','19',
                            '-pix_fmt','yuv420p',str(out/target)],check=True)
            outputs.append(target)
        preferred = ['velocity','wake','pressure','turbulence'] if cube else ['mach','pressure','velocity','temperature']
        chosen = [n for n in preferred if n in ranges][:4]
        if len(chosen)<2:
            raise ValueError('Not enough fields for a summary')
        inputs = []
        for n in chosen:
            inputs += ['-i',str(out/(n+'_evolution.mp4'))]
        layout = '|'.join(['0_0','w0_0','0_h0','w0_h0'][:len(chosen)])
        subprocess.run([ffmpeg,'-y','-loglevel','error',*inputs,'-filter_complex',
                        f'xstack=inputs={len(chosen)}:layout={layout}:fill=black',
                        '-c:v','libx264','-threads','2','-crf','20','-pix_fmt','yuv420p',str(out/'summary_evolution.mp4')],check=True)
        shutil.copyfile(out/'summary_evolution.mp4',out/'simulation.mp4')
        outputs += ['summary_evolution.mp4','simulation.mp4']
        # Decode the actual encoded movie, not a separately reconstructed mockup.
        select = f"select='eq(n,0)+eq(n,{len(times)//2})+eq(n,{len(times)-1})',scale=720:-1,tile=3x1"
        subprocess.run([ffmpeg,'-y','-loglevel','error','-i',str(out/'summary_evolution.mp4'),
                        '-vf',select,'-frames:v','1',str(out/'contact_sheet.png')],check=True)
        manifest['contact_sheet'] = 'contact_sheet.png'
        manifest['output_sha256'] = {n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in outputs}
        if case_fingerprints(case) != fingerprints:
            raise ValueError('Source case changed during rendering; outputs are not certified as a frozen snapshot')
        manifest['source_config_and_mesh_unchanged'] = True
        manifest.update(status='RENDERED', output_files=outputs, summary_fields=chosen,
                        is_flow_field_animation=True, fps=args.fps,
                        playback='one selected solver time per frame; frame spacing does not imply uniform physical time')
        # Release rendering resources while the X display and reader view exist.
        pv.Delete(label)
        pv.Delete(view)
        pv.Disconnect()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--metadata',required=True)
    p.add_argument('--ffmpeg')
    p.add_argument('--max-frames',type=int,default=100)
    p.add_argument('--fps',type=int,default=8)
    p.add_argument('--width',type=int,default=960)
    p.add_argument('--height',type=int,default=600)
    p.add_argument('--cube-slice-y',type=float,default=.5)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    manifest = json.loads(Path(args.metadata).read_text())
    manifest.update(status='VISUALIZATION_INCOMPLETE',output_files=[])
    try:
        render(args,manifest)
    except Exception as exc:
        manifest['reason'] = f'{type(exc).__name__}: {exc}'.replace(str(Path(args.case)), '<source-case>').replace(str(out),'<output>')
        import traceback
        traceback.print_exc()
    (out/'video_manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    return 0 if manifest['status']=='RENDERED' else 1


if __name__=='__main__':
    raise SystemExit(main())
