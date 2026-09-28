import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.reporting import field_video, report_builder, visuals
from src.reporting.paraview_field_video import selected_times, time_directories, gas_constant
from src.agent.pipeline import run_pipeline, REPLAY


def run_object(family='cube', **artifacts):
    return SimpleNamespace(family=family, case='test', mode='replay', artifacts=artifacts,
                           decision=SimpleNamespace(verdict='REJECT'))


def raw_case(tmp_path):
    p = tmp_path/'case'
    (p/'constant/polyMesh').mkdir(parents=True)
    for t in ('0', '1e-3', '0.0137'):
        (p/t).mkdir()
        (p/t/'U').write_text('real-field-placeholder-for-discovery-test')
    return p


def test_actual_times_without_interpolation(tmp_path):
    times = time_directories(raw_case(tmp_path))
    assert [t for t,_ in times] == [0, .001, .0137]
    assert selected_times(times,2) == [times[0],times[-1]]


def test_no_cfd_does_not_render_even_with_raw_case(tmp_path, monkeypatch):
    monkeypatch.setattr(field_video.subprocess,'run',lambda *a,**k: pytest.fail('renderer invoked'))
    s = field_video.make_field_video(run_object('airfoil',raw_case=str(raw_case(tmp_path))),tmp_path/'out')
    assert s['status']=='VIDEO_NOT_AVAILABLE_CFD_NOT_RUN'
    assert s['output_files']==[]


def test_missing_raw_is_honest(tmp_path):
    s = field_video.make_field_video(run_object(),tmp_path)
    assert s['status']=='VISUALIZATION_INCOMPLETE'
    assert 'raw' in s['reason']


def test_missing_paraview_is_honest(tmp_path, monkeypatch):
    monkeypatch.delenv('CFD_PVPYTHON',raising=False)
    monkeypatch.setattr(field_video.shutil,'which',lambda x: None)
    s = field_video.make_field_video(run_object(raw_case=str(raw_case(tmp_path))),tmp_path/'out')
    assert s['status']=='VISUALIZATION_INCOMPLETE'
    assert 'ParaView' in s['reason']


def test_rejected_usable_run_renders_and_preserves_metadata(tmp_path,monkeypatch):
    monkeypatch.setattr(field_video.shutil,'which',lambda x:'pvpython')
    def renderer(cmd,**kwargs):
        out = Path(cmd[cmd.index('--out')+1])
        (out/'video_manifest.json').write_text(json.dumps({
            'status':'RENDERED','verdict':'REJECT','rendered_solver_times':[0,.001,.0137],
            'fixed_color_ranges':{'pressure':[1,3]},'output_files':['summary_evolution.mp4']}))
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(field_video.subprocess,'run',renderer)
    run = run_object(raw_case=str(raw_case(tmp_path)))
    s = field_video.make_field_video(run,tmp_path/'out')
    assert s['status']=='RENDERED'
    assert s['fixed_color_ranges']['pressure']==[1,3]
    assert s['rendered_solver_times']==[0,.001,.0137]
    assert run.decision.verdict=='REJECT'


def test_failed_retry_does_not_reuse_success(tmp_path,monkeypatch):
    case = raw_case(tmp_path)
    monkeypatch.setattr(field_video.shutil,'which',lambda x:'pvpython')
    monkeypatch.setattr(field_video.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr='failed'))
    (tmp_path/'video_manifest.json').write_text('{"status":"RENDERED"}')
    assert field_video.make_field_video(run_object(raw_case=str(case)),tmp_path)['status']=='VISUALIZATION_INCOMPLETE'


@pytest.mark.parametrize('status',['RENDERED','VISUALIZATION_INCOMPLETE'])
def test_report_stage_order_and_verdict_invariant(tmp_path,monkeypatch,status):
    run = run_pipeline('replay cube',mode=REPLAY,family='cube',case='drifting_wake')
    run.artifacts['solver_invoked']=True
    original = run.decision.to_dict()
    calls=[]
    def stage(name,value):
        def f(*args):
            calls.append(name)
            return value
        return f
    monkeypatch.setattr(visuals,'make_plots',stage('plots',[]))
    monkeypatch.setattr(visuals,'make_contours',stage('contours',[]))
    monkeypatch.setattr(field_video,'make_field_video',stage('field',{'status':status,'output_files':[]}))
    monkeypatch.setattr(visuals,'make_history_video',stage('history','history_evolution.mp4'))
    report_builder.build(run,tmp_path)
    assert calls==['plots','contours','field','history']
    assert json.loads((tmp_path/'final_decision.json').read_text())==original
    report=json.loads((tmp_path/'report/report.json').read_text())
    assert report['media']['history']=='history_evolution.mp4'
    assert report['media']['video'] != report['media']['history']
    assert (tmp_path/'video/visualization_status.json').exists()


def test_mach_derivation_requires_supported_thermodynamics(tmp_path):
    (tmp_path/'constant').mkdir()
    path=tmp_path/'constant/physicalProperties'
    path.write_text('thermo eConst; equationOfState perfectGas; molWeight 28.9702542045296; Cv 717.5;')
    assert gas_constant(tmp_path)==pytest.approx(401.8,rel=1e-5)
    path.write_text('equationOfState incompressiblePerfectGas;')
    assert gas_constant(tmp_path) is None


@pytest.mark.parametrize('runner_record', [
    {'status':'ACCEPTED','failed_checks':[]},
    {'status':'STOPPED_FAIL_SAFELY','failed_checks':['stationarity']},
    {},
])
def test_future_live_pipeline_automatically_hands_raw_case_to_reporting(tmp_path,monkeypatch,runner_record):
    from src.agent.pipeline import LIVE
    from src.orchestration import live
    from tests.consolidated.test_live_dispatch import RecordingDispatch
    raw = str(raw_case(tmp_path))
    runner_record = {**runner_record, 'runtime_case':raw}
    monkeypatch.setattr(live,'runtime_status',lambda:{'available':True})
    run = run_pipeline('run the nozzle',mode=LIVE,family='nozzle',case='canonical_reference',
                       allow_cfd=True,live_kwargs={'out_dir':tmp_path/'live',
                       'dispatch':RecordingDispatch(runner_record)})
    before = run.decision.to_dict()
    seen=[]
    def fake_video(run,out):
        seen.append((run.mode,field_video.locate_case(run)))
        return {'status':'VISUALIZATION_INCOMPLETE','reason':'mocked missing renderer'}
    monkeypatch.setattr(field_video,'make_field_video',fake_video)
    monkeypatch.setattr(visuals,'make_plots',lambda *a:[])
    monkeypatch.setattr(visuals,'make_contours',lambda *a:[])
    monkeypatch.setattr(visuals,'make_history_video',lambda *a:None)
    report_builder.build(run,tmp_path/'report')
    assert seen==[(LIVE,raw)]
    assert json.loads((tmp_path/'report/final_decision.json').read_text())==before


def test_plot_failure_cannot_prevent_video_status_or_scientific_decision(tmp_path,monkeypatch):
    run=run_pipeline('replay cube',mode=REPLAY,family='cube',case='drifting_wake')
    def failed(*a):
        raise RuntimeError('test plot failure')
    monkeypatch.setattr(visuals,'make_plots',failed)
    monkeypatch.setattr(visuals,'make_contours',lambda *a:[])
    monkeypatch.setattr(visuals,'make_history_video',lambda *a:None)
    report_builder.build(run,tmp_path)
    assert json.loads((tmp_path/'final_decision.json').read_text())['verdict']=='REJECT'
    status=json.loads((tmp_path/'video/visualization_status.json').read_text())
    assert status['status']=='VISUALIZATION_INCOMPLETE'
    assert status['stage_errors'][0]['stage']=='plots'


def test_reader_translation_is_equivalent_and_leaves_source_untouched(tmp_path):
    from src.reporting.paraview_field_video import reader_shadow
    import os
    if os.name=='nt':
        pytest.skip('Symlink shadow is exercised by WSL rendering; Windows needs symlink privileges')
    case=tmp_path/'source'; (case/'0').mkdir(parents=True)
    source='dimensions [velocity]; internalField uniform (2 0 0);'
    (case/'0/U').write_text(source)
    shadow=tmp_path/'view';shadow.mkdir()
    edits=reader_shadow(case,shadow)
    assert (case/'0/U').read_text()==source
    assert (shadow/'0/U').read_text()=='dimensions [0 1 -1 0 0 0 0]; internalField uniform (2 0 0);'
    assert edits[0]['file']=='0/U'


def test_constant_color_range_is_recorded_without_zero_width():
    from src.reporting.paraview_field_video import color_limits
    assert color_limits(1,1)==[1,1.000001]
    assert color_limits(-3,4)==[-3,4]
