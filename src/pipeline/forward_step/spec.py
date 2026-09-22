"""Scope-checked specification for a uniform, periodic extrusion of a step."""
from dataclasses import dataclass, asdict, fields
from pathlib import Path
import json, math

@dataclass(frozen=True)
class ForwardStep3DSpec:
    length: float = 3.0
    height: float = 1.0
    step_x: float = 0.6
    step_height: float = 0.2
    span: float = 0.1
    nx: int = 240
    ny: int = 80
    nz: int = 8
    mach: float = 3.0
    pressure: float = 1.0
    temperature: float = 1.0
    end_time: float = 4.0
    max_co: float = 0.2
    write_interval: float = 0.1
    family: str = 'forward_step_3d'
    physics: str = 'inviscid_euler'
    span_bc: str = 'cyclic'

    def __post_init__(self):
        for key in ['length','height','step_x','step_height','span','mach',
                    'pressure','temperature','end_time','max_co','write_interval']:
            value = getattr(self,key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError(f'{key} must be finite and positive')
        for key in ['nx','ny','nz']:
            value=getattr(self,key)
            if type(value) is not int or value<2:
                raise ValueError(f'{key} must be an integer >= 2')
        if not (self.step_x<self.length and self.step_height<self.height):
            raise ValueError('Step must lie strictly inside the channel')
        if self.mach<=1: raise ValueError('This family supports supersonic inflow only')
        if self.max_co>0.2: raise ValueError('max_co above the trusted 0.2 recipe is not supported')
        if self.write_interval>self.end_time: raise ValueError('write_interval must not exceed end_time')
        if self.family!='forward_step_3d' or self.physics!='inviscid_euler' or self.span_bc!='cyclic':
            raise ValueError('Only periodic extruded forward-step inviscid Euler is supported')
        a,b=self.splits
        if not (1<=a<self.nx and 1<=b<self.ny):
            raise ValueError('Resolution must allocate at least one cell to every block')

    @property
    def splits(self):
        return round(self.nx*self.step_x/self.length),round(self.ny*self.step_height/self.height)

    @property
    def cells(self):
        a,b=self.splits
        return (a*self.ny+(self.nx-a)*(self.ny-b))*self.nz

    @property
    def velocity(self):
        # Preserve official U=3 exactly at canonical T=1 and nominal Mach=3.
        # The tutorial's rounded molecular weight makes actual M differ by ~3 ppm.
        return self.mach*math.sqrt(self.temperature)

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict): raise ValueError('Specification must be a mapping')
        unknown=set(data)-{f.name for f in fields(cls)}
        if unknown: raise ValueError('Unsupported specification keys: '+', '.join(sorted(unknown)))
        return cls(**data)

    @classmethod
    def load(cls,path):
        path=Path(path)
        if path.suffix.lower()=='.json': data=json.loads(path.read_text())
        else:
            import yaml
            data=yaml.safe_load(path.read_text())
        return cls.from_dict(data)
