import json
import unittest
from live_preview import place_preview, checked_rows, load_models

class Bridge:
    def __init__(self, occupied=False, drop=False, y=180):
        self.world={}; self.messages=[]; self.reply=None; self.occupied=occupied; self.drop=drop; self.y=y
    async def send(self,raw):
        m=json.loads(raw); self.messages.append(m)
        if m['type']=='blocks' and not self.drop:
            for p in m['changes']: self.world[(p['x'],p['y'],p['z'])]=p['block']
        if m['type']=='action':
            rows=[]
            for p in m['args']['positions']:
                block=self.world.get((p['x'],p['y'],p['z']),'minecraft:air')
                if self.occupied and m['id'].startswith('pre-shaft'): block='minecraft:stone'
                rows.append({**p,'block':block,'is_air':block=='minecraft:air','world_x':p['x'],'world_y':p['y']+self.y,'world_z':p['z']})
            self.reply=json.dumps({'type':'observation','id':m['id'],'ok':True,'result':{'blocks':rows}})
    async def recv(self): return self.reply

class LiveTests(unittest.IsolatedAsyncioTestCase):
    def report(self): return {'sent_blocks':0,'verified_blocks':0,'completed_models':[]}
    def models(self): return [(k,[{'x':i,'y':0,'z':16,'block':'minecraft:stone'}]) for i,k in enumerate(('well','canyon','shaft'))]
    async def test_success(self):
        b=Bridge(); r=self.report(); await place_preview(b,self.models(),r)
        self.assertEqual(r['verified_blocks'],3); self.assertEqual(r['status'],'placed_and_verified')
    async def test_last_site_occupied_means_zero_writes(self):
        b=Bridge(occupied=True)
        with self.assertRaisesRegex(RuntimeError,'occupied'): await place_preview(b,self.models(),self.report())
        self.assertFalse(any(m['type']=='blocks' for m in b.messages))
    async def test_missing_placement_is_not_success(self):
        b=Bridge(drop=True)
        with self.assertRaisesRegex(RuntimeError,'mismatch'): await place_preview(b,self.models(),self.report())
        self.assertFalse(any(m['type']=='finish' for m in b.messages))
    async def test_wrong_height_zero_writes(self):
        b=Bridge(y=250)
        with self.assertRaisesRegex(RuntimeError,'Y=180'): await place_preview(b,self.models(),self.report())
        self.assertFalse(b.world)
    def test_incomplete_observation(self):
        with self.assertRaises(RuntimeError): checked_rows({'blocks':[]},[{'x':0,'y':0,'z':0}])
    def test_actual_models_disjoint_and_state_free(self):
        models=load_models(); seen=set()
        self.assertEqual(sum(len(c) for _,c in models),214822)
        for _,cells in models:
            for p in cells:
                coord=(p['x'],p['y'],p['z']); self.assertNotIn(coord,seen); seen.add(coord)
                self.assertNotIn('[',p['block'])
                self.assertLessEqual(p['y']+180,240)
if __name__=='__main__': unittest.main()
