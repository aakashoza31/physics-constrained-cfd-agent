"""Evidence categories: hard failures, measurements and explicitly unresolved checks."""
from .spec import ForwardStep3DSpec
def validate(d):
    health={k:bool(d[k]) for k in ['solver_completed','mesh_ok','three_solution_directions','finite_all_saved','positive_all_saved','courant_finite_positive']}
    health['no_fatal_error']=not d['fatal_error']
    health['positive_every_step']=bool(all(v>0 for v in d['minima_every_step'].values()))
    health['fixed_recipe_unchanged']=d['fixed_recipe_unchanged']
    health['periodic_extrusion']=d['boundary']['no_empty_patches'] and d['boundary']['cyclic_patch_count']==2 and d['boundary']['translational_patch_count']==2 and d['boundary']['coupled_matching_ok']
    health['cell_count_matches_spec']=d['cells']==ForwardStep3DSpec.from_dict(d['spec']).cells
    jumps=d['shock'].get('jumps',{})
    shock={k+'_rises':jumps[k]>1 for k in ['p','rho','T'] if k in jumps}
    regime={'supersonic_inlet':bool(d['actual_inlet_Mach']>1)}
    failed=[k for k,v in {**health,**shock,**regime}.items() if not v]
    result={'status':'FAIL' if failed else 'NUMERICAL_HEALTH_PASS_SCIENTIFIC_REVIEW_REQUIRED',
            'failed_checks':failed,'numerical_health':health,'flow_regime':regime,'shock_compression':shock,
            'courant':{'status':'MEASURED','data':d['Co'],'note':'Controller target is not a strict stepwise cap. No post-hoc acceptance band imposed.'},
            'transient_conservation':{'status':'MEASURED','data':d['mass']},
            'baseline_comparison':{'status':'MEASURED' if 'comparison_2d' in d else 'NOT_APPLICABLE_CHANGED_PARAMETERS'},
            'spanwise_uniformity':{'status':'MEASURED','data':d['spanwise']},
            'transient_evolution':{'status':'MEASURED_NOT_REQUIRED_STEADY','data':d['recent_change']},
            'unresolved':['Mesh and time-step independence','Independent quantitative benchmark uncertainty',
                          'Exact numerical momentum and energy flux closure','Corner singularity sensitivity',
                          'Robustness to spanwise perturbations; uniform extrusion alone cannot establish this']}
    result['planar_velocity_invariant']={'status':'MEASURED_REQUIRES_REVIEW',
        'note':'A z-uniform field may still have nonzero Uz. Both spanwise variation and departure from zero Uz must be reviewed.',
        'max_abs_Uz':d['spanwise']['max_abs_Uz']}
    if d.get('scientific_review',{}).get('status')=='BLOCKED':
        result['status']='BLOCKED_PLANAR_INVARIANCE'
        result['scientific_review']=d['scientific_review']
    return result
