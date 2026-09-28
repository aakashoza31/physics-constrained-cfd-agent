#!/usr/bin/env python3
"""Decode and audit an existing field movie package (no CFD, no rendering)."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'video_manifest.json').read_text())
    assert manifest['status'] == 'RENDERED', 'Field rendering is not complete'
    times = manifest['rendered_solver_times']
    assert len(times) == manifest['frame_count'] >= 2
    assert times == sorted(set(times))
    records = manifest['per_frame_color_ranges']
    assert len(records) == len(times)*len(manifest['fields_rendered'])
    assert {(r['time'],r['field']) for r in records} == {
        (t,f) for t in times for f in manifest['fields_rendered']}
    for record in records:
        assert all(math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-12) for a,b in zip(
            record['range'],manifest['fixed_color_ranges'][record['field']]))
    outputs = []
    for name in manifest['output_files']:
        path = directory/name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == manifest['output_sha256'][name], 'Movie hash mismatch: '+name
        result = subprocess.run(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
            '-show_entries','stream=codec_name,nb_read_frames,width,height:format=duration',
            '-of','json',str(path)],check=True,capture_output=True,text=True)
        details = json.loads(result.stdout)
        assert int(details['streams'][0]['nb_read_frames']) == len(times), 'Frame count mismatch: '+name
        decoded = subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],
                                 check=True,capture_output=True,text=True)
        assert not decoded.stderr.strip(), 'Decode error: '+name
        outputs.append({'file':name,'sha256':digest,**details})
    assert (directory/'simulation.mp4').read_bytes() == (directory/'summary_evolution.mp4').read_bytes()
    result = {'status':'PASS','frame_count':len(times),'actual_time_range':[times[0],times[-1]],
              'fixed_ranges_verified':True,'all_movies_fully_decoded':True,
              'scientific_verdict':manifest['verdict'],'outputs':outputs}
    (directory/'video_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.directory),indent=2))
