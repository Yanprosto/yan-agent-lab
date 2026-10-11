"""Authored spatial studies using mcbuild DSL, merge, renderer and schematic export.
Run: PYTHONPATH=src python examples/sector_study/build.py
No LLM/API or Minecraft execution is claimed.
"""
from pathlib import Path
from collections import deque
import json, time, argparse
from mcbuild.dsl.sandbox import run_blueprint
from mcbuild.voxel import VoxelGrid
from mcbuild.export.schem import export_schem
from mcbuild.render.camera import render_isometric
from mcbuild.orchestrator.models import ProjectPlan
from mcbuild.orchestrator.merge import validate_and_merge_patch
from mcbuild.orchestrator.validator import validate_project_plan

OUT=Path(__file__).parent/'output'
C='light_gray_concrete'; D='deepslate_tiles'; M='polished_andesite'; R='cut_copper'; Y='yellow_concrete'; L='sea_lantern'
class Blueprint:
    def __init__(self): self.lines=[]
    def fill(self,a,b,mat=C): self.lines.append(f'fill({", ".join(map(str,(*a,*b)))}, {mat!r})')
    def clear(self,a,b): self.lines.append(f'clear({", ".join(map(str,(*a,*b)))})')
    def beam(self,a,b,mat=D): self.lines.append(f'line({", ".join(map(str,(*a,*b)))}, {mat!r})')
    def ring(self,y,outer=38,inner=28):
        for x in range(48-outer,49+outer):
            for z in range(48-outer,49+outer):
                r=(x-48)**2+(z-48)**2
                if inner**2<=r<=outer**2: self.fill((x,y,z),(x,y+1,z),M)
    def room(self,x,y,z,w,h,d):
        self.fill((x,y,z),(x+w,y+h,z+d),C)
        self.clear((x+2,y+1,z+2),(x+w-2,y+h-2,z+d-2))
        self.clear((x+3,y+1,z),(x+w-3,y+h-3,z+2))
        self.fill((x+3,y+h-2,z),(x+w-3,y+h-2,z),D)
        self.fill((x+3,y+h-3,z+2),(x+w-3,y+h-3,z+2),L)

def design(kind):
    b=Blueprint(); b.fill((0,0,0),(95,1,95),D)
    # Loading apron and inset parallel freight channels.
    b.fill((4,2,8),(91,2,90),M)
    for x in (42,51): b.fill((x,3,9),(x+1,3,90),D)
    for z in range(10,90,5): b.fill((40,3,z),(54,3,z),R)
    if kind=='well':
        for x in (12,76):
            for z in (18,76):
                b.fill((x,3,z),(x+7,57,z+7),C)
                b.fill((x+2,5,z-1),(x+4,54,z-1),D)
                b.fill((x-2,3,z-2),(x+9,7,z+9),C)
        for y in (14,30,46):
            b.fill((12,y,18),(83,y+1,83),M); b.clear((24,y,30),(71,y+1,71))
            for z in (29,72):
                b.fill((24,y+2,z),(71,y+2,z),Y)
            for x in (12,76): b.room(x,y+2,78,7,9,12)
        b.fill((20,30,46),(75,31,51),D)
        b.fill((46,46,24),(51,47,76),D)
        for x in (17,78): b.fill((x,57,16),(x+2,59,86),R)
        b.fill((17,57,44),(80,60,48),Y)
        b.fill((47,35,46),(48,57,47),D)
        b.fill((42,34,42),(54,35,53),R)
        for z in (37,57): b.room(8,3,z,15,9,14)
    elif kind=='canyon':
        for x in (12,72):
            for z in (20,44,72):
                b.fill((x,3,z),(x+10,54,z+6),C)
                b.fill((x+3,8,z-1),(x+7,49,z-1),D)
                for yy in (14,30,46): b.fill((x-3,yy,z-2),(x+13,yy+2,z+9),C)
        for y in (14,30,46):
            for x in (10,66): b.fill((x,y,18),(x+20,y+1,86),M)
            b.fill((10,y,18),(86,y+1,25),M)
        for y,z in ((14,66),(30,43),(46,76)):
            b.fill((28,y,z),(68,y+1,z+6),D)
            for xx in range(28,68,6):
                b.beam((xx,y-5,z),(xx+6,y,z),R)
                b.fill((xx,y+2,z),(xx+2,y+2,z),Y)
        for y,z in ((3,30),(16,53),(32,28)): b.room(74,y,z,17,10,16)
        for z in (24,80):
            b.fill((16,55,z),(81,58,z+3),R)
            for x in range(19,78,8): b.beam((x,55,z),(x+6,59,z),D)
        b.fill((47,43,24),(48,55,25),D)
        b.fill((43,42,22),(54,43,29),Y)
    else:
        for y in (14,30,46): b.ring(y)
        for x,z in ((15,30),(15,64),(76,30),(76,64),(40,81),(56,81)):
            b.fill((x,3,z),(x+4,57,z+5),C)
            b.fill((x+1,8,z-1),(x+2,54,z-1),R)
        for y in (14,30,46): b.fill((10,y,18),(84,y+1,25),M)
        for y in (3,18,34): b.room(75,y,36,17,11,26)
        b.fill((44,3,43),(52,51,51),D)
        for y in (14,30,46):
            b.fill((18,y,45),(78,y+1,49),M)
            b.fill((46,y,48),(50,y+1,83),M)
        b.fill((13,58,44),(83,60,48),Y)
        b.fill((46,52,46),(49,58,49),R)
    # Shared circulation: broad full-block steps. Audit explicitly allows 1-block ascent.
    for i in range(46):
        x=6+i; y=2+i
        b.clear((x,y+1,3),(x,y+4,6))
        b.fill((x,y,3),(x,y,6),M)
        if i%8==0: b.fill((x,2,4),(x,y-1,5),D) if y>2 else None
    for y in (14,30,46):
        x=6+y-2
        b.clear((x,y+1,7),(x+3,y+3,25))
        b.fill((x,y,7),(x+3,y,25),M)
        b.fill((x+4,y,9),(x+4,y,17),Y)
        b.clear((x,y+2,18),(64,y+4,19))
        b.fill((x,y+1,18),(64,y+1,19),M)
    for x in (9,88):
        for z in (35,39,43):
            b.fill((x,3,z),(x,48,z),R)
            b.fill((x,48,z),(x+3,48,z),R)
        for y in (10,26,42): b.fill((x-1,y,34),(x+1,y,44),D)
    for z in (31,60):
        b.beam((13,17,z),(13,28,z+10),D)
        b.beam((81,33,z),(81,44,z+10),D)
    for y in (13,29,45):
        for x in range(28,70,12): b.fill((x,y,24),(x+2,y,24),L)
    # Loading clutter, vents and restrained warning marks.
    for x,z in ((27,79),(57,82),(29,33),(60,59)):
        b.fill((x,3,z),(x+5,6,z+7),R)
        b.fill((x,5,z),(x+5,5,z),D)
    for x in range(8,89,8): b.fill((x,3,10),(x+3,3,10),Y)
    return '\n'.join(b.lines)+'\n'

def routes(grid):
    solid=set(dict(grid.items()))
    def stand(p):
        x,y,z=p
        return (x,y-1,z) in solid and p not in solid and (x,y+1,z) not in solid
    start=(6,3,4); assert stand(start)
    dist={start:0}; q=deque([start])
    while q:
        x,y,z=q.popleft()
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            for dy in (0,1,-1):
                p=(x+dx,y+dy,z+dz)
                if p in dist or not stand(p): continue
                # Clearance above the lower endpoint during ascent/descent.
                high=max(y,p[1])
                if (x,high+1,z) in solid or (p[0],high+1,p[2]) in solid: continue
                dist[p]=dist[(x,y,z)]+1; q.append(p)
    targets={f'deck_{y}':(6+y+6,y+2,19) for y in (14,30,46)}
    result={k:{'foot_position':v,'reachable':v in dist,'steps':dist.get(v)} for k,v in targets.items()}
    assert all(v['reachable'] for v in result.values()), result
    return {'method':'full-cube support, two air blocks, cardinal moves, <=1 block ascent/descent; jump-capable, not Minecraft pathfinding','reachable_positions':len(dist),'targets':result}

def merge_checked(grid,title):
    # Reuse the existing plan schema; authored elevation partitions, not generated workers.
    p={'schema_version':1,'title':title,'project_summary':'Authored environment study; no planner/worker LLM run.',
       'site':{'min_x':0,'max_x':95,'min_z':0,'max_z':95,'base_y':0},
       'style_bible':{'architectural_style':'abandoned industrial freight node',
          'scale_and_massing':'96x96 plot, three elevated decks, dominant central void',
          'primary_palette':[C,D,M],'secondary_palette':[R],'accent_palette':[Y,L],
          'roof_language':'open gantries','opening_language':'deep service bays',
          'detail_language':'freight tracks and warning stripes','landscape_language':'loading apron',
          'global_constraints':['Keep central void open','Connect three main decks']},
       'interfaces':[],'work_packages':[]}
    template={'instances':[{'id':'main','anchor':[0,0,0],'rotation':0}],
              'requested_views':[{'yaw':0},{'mode':'top-down'}]}
    for i,(lo,hi) in enumerate(((0,13),(14,29),(30,45),(46,63))):
        import copy
        w=copy.deepcopy(template); w.update(id=f'layer_{i}',name=f'Elevation {lo}–{hi}',semantic_type='authored_elevation_partition',objective='Preserve authored geometry',depends_on=[],neighbor_context=[],worker_brief='No worker execution: partition of compiled authored DSL.',acceptance_criteria=['All voxels within bounds'])
        w['instances']=[{'id':'main','anchor':[0,lo,0],'rotation':0}]
        w['responsibility']={'boundary_kind':'hard','core':{'op':'shape','shape':{'kind':'axis_aligned_rectangle','min_x':0,'max_x':95,'min_z':0,'max_z':95}},'min_y':lo,'max_y':hi,'write_policy':'preserve_existing'}
        p['work_packages'].append(w)
    plan=ProjectPlan.from_dict(p); validation=validate_project_plan(plan,max_components=4)
    assert validation.valid, validation.to_dict()
    result=VoxelGrid(); reports=[]
    for w in plan.work_packages:
        patch=VoxelGrid()
        for (x,y,z),idx in grid.items():
            if w.responsibility.min_y<=y<=w.responsibility.max_y: patch.set(x,y,z,idx)
        merged=validate_and_merge_patch(result,patch,w,plan)
        assert merged.validation.accepted
        reports.append(merged.validation.to_dict()); result=merged.grid
    assert dict(result.items())==dict(grid.items())
    return result,p,reports

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--only',choices=['well','canyon','shaft']); parser.add_argument('--no-render',action='store_true'); args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    for kind in ([args.only] if args.only else ['well','canyon','shaft']):
        root=OUT/kind; root.mkdir(exist_ok=True); t=time.perf_counter()
        source=design(kind); (root/'blueprint.py').write_text(source)
        grid=VoxelGrid(); run_blueprint(source,grid,max_seconds=60,max_lines=5000000)
        assert not grid.palette_warnings, grid.palette_warnings
        grid,plan,reports=merge_checked(grid,kind)
        report={'provenance':'assistant_authored_DSL; no LLM worker run; no live placement','bounds':grid.bounds,'blocks':len(grid),'connectivity':routes(grid),'merge_reports':reports,'compile_validate_seconds':round(time.perf_counter()-t,3)}
        (root/'plan.json').write_text(json.dumps(plan,indent=2)); (root/'report.json').write_text(json.dumps(report,indent=2))
        export_schem(grid,str(root/'sector.schem'))
        print(kind,report['blocks'],report['compile_validate_seconds'],flush=True)
        if not args.no_render:
            for name,keep in [('overview',None),('cutaway',lambda p:p[2]>=46)]:
                t=time.perf_counter(); img=render_isometric(grid,yaw=0,keep=keep,width=1100,height=950,shadows=False)
                img.save(root/f'{name}.png'); print(kind,name,round(time.perf_counter()-t,1),flush=True)
if __name__=='__main__': main()
